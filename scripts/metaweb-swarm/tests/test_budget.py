import copy
import json
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor

from metaweb_swarm.budget import conservative_input_tokens, held_totals, mark_unknown, reconcile, recover_unsettled, reserve, settle


def state(tokens=1000, usd=None, prices=(1, 2, 0.01)):
    return {"config": {"max_total_tokens": tokens, "estimated_budget_usd": usd,
                       "input_price_per_million": prices[0], "output_price_per_million": prices[1],
                       "web_search_price_per_call": prices[2], "model": "mock"},
            "usage": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "web_search_calls": 0, "unknown_steps": 0}}


def usage(input_tokens=100, output_tokens=50, searches=0):
    return {"input_tokens": input_tokens, "output_tokens": output_tokens, "total_tokens": input_tokens + output_tokens,
            "web_search_calls": searches}


class BudgetTests(unittest.TestCase):
    def test_preflight_reserves_full_request_before_execution(self):
        s = state(tokens=1000)
        a = reserve(s, "AGENT-001", 600, 200, 0)
        self.assertIsInstance(a, dict)
        self.assertEqual(held_totals(s)["tokens"], 800)
        self.assertTrue(reserve(s, "AGENT-002", 200, 100, 0).startswith("MAX_TOTAL_TOKENS"))
        self.assertEqual(len(s["budget_reservations"]), 1)

    def test_concurrent_requests_share_host_lock_and_cannot_oversubscribe(self):
        s, lock = state(tokens=1000), threading.Lock()

        def attempt(agent):
            with lock:
                return reserve(s, agent, 600, 100, 0)

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(attempt, ("AGENT-001", "AGENT-002")))
        self.assertEqual(sum(isinstance(r, dict) for r in results), 1)
        self.assertEqual(held_totals(s)["tokens"], 700)

    def test_spent_tokens_are_included_with_other_request_holds(self):
        s = state(tokens=1000)
        s["usage"].update(usage(400, 100))
        self.assertIsInstance(reserve(s, "AGENT-001", 200, 100, 0), dict)
        self.assertTrue(reserve(s, "AGENT-002", 150, 100, 0).startswith("MAX_TOTAL_TOKENS"))

    def test_exact_token_and_usd_boundary_is_allowed_without_float_drift(self):
        s = state(tokens=3, usd=0.000004)
        a = reserve(s, "AGENT-001", 2, 1, 0)
        self.assertIsInstance(a, dict)
        self.assertEqual(a["usd_upper"], "0.000004")

    def test_usd_reserves_search_calls_and_all_token_prices(self):
        s = state(tokens=10000, usd=0.02)
        self.assertIsInstance(reserve(s, "AGENT-001", 100, 100, 1), dict)
        self.assertTrue(reserve(s, "AGENT-002", 100, 100, 1).startswith("ESTIMATED_DOLLAR_BUDGET"))

    def test_missing_prices_fail_closed_only_when_dollars_are_enforced(self):
        s = state(usd=1, prices=(1, None, 0.01))
        self.assertEqual(reserve(s, "AGENT-001", 100, 50, 0), "USD_PRICE_CEILINGS_REQUIRED")
        self.assertNotIn("budget_reservations", s)
        s["config"]["estimated_budget_usd"] = None
        a = reserve(s, "AGENT-001", 100, 50, 0)
        self.assertIsNone(a["usd_upper"])

    def test_failed_request_retains_unknown_hold_and_blocks_all_agents(self):
        s = state(tokens=10000)
        a = reserve(s, "AGENT-001", 100, 50, 1)
        mark_unknown(s, a["id"], "Connection lost after request dispatch")
        self.assertEqual(held_totals(s)["tokens"], 150)
        self.assertIn("HUMAN_BUDGET_RECONCILIATION_REQUIRED", reserve(s, "AGENT-002", 1, 1, 0))
        self.assertEqual(settle(s, "AGENT-001", usage()), "HUMAN_BUDGET_RECONCILIATION_REQUIRED")
        self.assertEqual(held_totals(s)["reservations"], 1)

    def test_process_resume_marks_orphan_reserved_requests_unknown(self):
        s = state()
        reserve(s, "AGENT-001", 100, 50, 0)
        resumed = json.loads(json.dumps(s))
        records = recover_unsettled(resumed)
        self.assertEqual(records[0]["status"], "UNKNOWN")
        self.assertEqual(held_totals(resumed)["tokens"], 150)
        self.assertEqual(recover_unsettled(resumed), [])

    def test_known_settlement_releases_hold_but_does_not_double_account_usage(self):
        s = state()
        a = reserve(s, "AGENT-001", 300, 100, 2)
        original_usage = copy.deepcopy(s["usage"])
        result = settle(s, "AGENT-001", usage(100, 50, 1))
        self.assertEqual(result["status"], "SETTLED")
        self.assertEqual(s["usage"], original_usage)
        self.assertEqual(held_totals(s)["tokens"], 0)
        self.assertIn(a["id"], s["budget_settlements"])
        s["usage"].update(usage(100, 50, 1))  # Response hook's atomic accounting.
        b = reserve(s, "AGENT-001", 200, 100, 0)
        self.assertEqual(b["request_seq"], 2)

    def test_unknown_usage_missing_fields_keeps_reservation(self):
        s = state()
        reserve(s, "AGENT-001", 300, 100, 0)
        self.assertIn("RECONCILIATION", settle(s, "AGENT-001", {"input_tokens": 100}))
        self.assertEqual(held_totals(s)["unknown"], 1)

    def test_explicit_incomplete_usage_keeps_reservation(self):
        s = state()
        reserve(s, "AGENT-001", 300, 100, 0)
        self.assertIn("RECONCILIATION", settle(s, "AGENT-001", usage() | {"usage_complete": False}))
        self.assertEqual(held_totals(s)["tokens"], 400)

    def test_usage_bound_breach_is_audited_and_fail_closed(self):
        s = state()
        reserve(s, "AGENT-001", 100, 50, 1)
        reason = settle(s, "AGENT-001", usage(101, 50, 1))
        self.assertIn("RESERVATION_BOUND_EXCEEDED", reason)
        self.assertEqual(s["budget_breaches"][0]["usage"]["input_tokens"], 101)
        self.assertEqual(held_totals(s)["unknown"], 1)

    def test_search_count_exceeding_bound_is_not_silently_released(self):
        s = state()
        reserve(s, "AGENT-001", 100, 50, 0)
        self.assertIn("BOUND_EXCEEDED", settle(s, "AGENT-001", usage(100, 50, 1)))

    def test_operator_reconciliation_retains_note_and_original_unknown_hold(self):
        s = state()
        a = reserve(s, "AGENT-001", 100, 50, 1)
        mark_unknown(s, a["id"], "Interrupted request")
        with self.assertRaises(ValueError):
            reconcile(s, a["id"], usage(0, 0, 0), "")
        closed = reconcile(s, a["id"], usage(0, 0, 0), "Operator checked request never reached provider")
        self.assertEqual(closed["status"], "RECONCILED")
        self.assertEqual(closed["total_upper_tokens"], 150)
        self.assertEqual(held_totals(s)["tokens"], 0)
        self.assertIsInstance(reserve(s, "AGENT-001", 1, 1, 0), dict)

    def test_legacy_unknown_usage_needs_explicit_reconciliation(self):
        s = state()
        s["usage"]["unknown_steps"] = 1
        self.assertIn("legacy unknown", reserve(s, "AGENT-001", 1, 1, 0))

    def test_one_active_request_per_agent_and_durable_sequence(self):
        s = state()
        reserve(s, "AGENT-001", 100, 50, 0)
        self.assertEqual(reserve(s, "AGENT-001", 1, 1, 0), "ACTIVE_REQUEST_ALREADY_RESERVED")
        settle(s, "AGENT-001", usage())
        resumed = json.loads(json.dumps(s))
        self.assertEqual(reserve(resumed, "AGENT-001", 1, 1, 0)["id"], "AGENT-001:2")

    def test_text_bound_includes_utf8_tools_output_schema_and_framing(self):
        a = conservative_input_tokens("A", [{"role": "user", "content": "🙂"}], [])
        b = conservative_input_tokens("A", [{"role": "user", "content": "🙂"}], [{"name": "lookup", "parameters": {"type": "object"}}], {"type": "object", "properties": {"summary": {"type": "string"}}})
        self.assertGreater(a, 4096 + 4)
        self.assertGreater(b, a)
        self.assertGreater(conservative_input_tokens("A", [{"role": "user", "content": "🙂" * 100}], []), a + 390)

    def test_media_inputs_need_explicit_model_specific_bound(self):
        with self.assertRaisesRegex(ValueError, "Multimodal"):
            conservative_input_tokens("A", [{"content": [{"type": "input_image", "image_url": "https://host/a.png"}]}], [])

    def test_bad_bounds_prices_and_usage_are_rejected_or_retained(self):
        for bounds in ((True, 1, 0), (-1, 1, 0), (1, 1.2, 0), (1, 1, -1)):
            with self.subTest(bounds=bounds), self.assertRaises(ValueError):
                reserve(state(), "AGENT-001", *bounds)
        for price in (-1, float("nan"), float("inf"), True):
            with self.subTest(price=price), self.assertRaises(ValueError):
                reserve(state(usd=1, prices=(price, 1, 0.01)), "AGENT-001", 1, 1, 0)
        s = state()
        reserve(s, "AGENT-001", 100, 50, 0)
        self.assertIn("RECONCILIATION", settle(s, "AGENT-001", usage() | {"total_tokens": 151}))


if __name__ == "__main__":
    unittest.main()
