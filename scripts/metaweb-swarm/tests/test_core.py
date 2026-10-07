import asyncio
import json
import io
import tempfile
import time
import unittest
from unittest.mock import patch
from contextlib import redirect_stdout
from pathlib import Path

from metaweb_swarm.config import load_config
from metaweb_swarm.demo import DemoBackend
from metaweb_swarm.engine import Engine, ToolAPI, ensure_external, initialize, decide, unblock
from metaweb_swarm.policy import normalize_idea, normalize_output, spawn_verdict
from metaweb_swarm.roles import seed_agents
from metaweb_swarm.storage import Store, run_lock
from metaweb_swarm.workspace import Workspace


class PolicyTests(unittest.TestCase):
    def test_recurring_rejects_provider_not_mechanism(self):
        idea = normalize_idea(DemoBackend.idea("Example", "Optical encoding", "RECURRING", "DISCOVERED"))
        self.assertEqual(idea["status"], "REJECTED")
        self.assertEqual(idea["mechanism"], "Optical encoding")
        self.assertIn("one-time", " ".join(idea["policy_notes"]))

    def test_piql_is_known(self):
        idea = normalize_idea(DemoBackend.idea("PiqlFilm in Arctic World Archive", "Piql", "ONE_TIME", "DISCOVERED"))
        self.assertEqual(idea["status"], "REJECTED")
        self.assertIn("DUPLICATE_KNOWN", idea["rejection_reason"])

    def test_blocked_and_false_completion(self):
        with self.assertRaises(ValueError):
            normalize_idea(DemoBackend.idea("Example", "New channel", "FREE", "BLOCKED"))
        idea = normalize_idea(DemoBackend.idea("Example", "New channel", "FREE", "COMPLETED"))
        self.assertEqual(idea["status"], "BLOCKED")

    def test_stopping_with_leads_requires_continuation(self):
        output = normalize_output({"status": "COMPLETED", "reason_for_stopping": "done", "unexplored_leads": ["Try FEC"], "blind_spots": []})
        self.assertEqual(output["status"], "CONTINUE")

    def test_completed_report_preserves_leads_without_reopening_assignment(self):
        lead = 'No actionable unexplored leads remain for this reporting role.'
        result = normalize_output({'status':'COMPLETED', 'reason_for_stopping':'Report done', 'unexplored_leads':[lead], 'blind_spots':[]}, synthesis=True)
        self.assertEqual(result['status'], 'COMPLETED')
        self.assertEqual(result['unexplored_leads'], [])
        self.assertEqual(result['handoff_leads'], [lead])
        result = normalize_output({'status':'CONTINUE', 'reason_for_stopping':'Read missing receipt', 'unexplored_leads':['Inspect Docker output'], 'blind_spots':[]}, synthesis=True)
        self.assertEqual(result['status'], 'CONTINUE')

    def test_spawn_overlap_and_hard_limits(self):
        config = load_config()
        agents = seed_agents(config)
        request = {"role": agents[1]["role"], "mission": "New precise question", "reason": "Coverage", "unique_expertise": "Radio", "question": "How to decode?", "expected_output": "Protocol evidence"}
        _, denial = spawn_verdict(request, agents[0], agents, config)
        self.assertIn("OVERLAP", denial)
        config["max_agents"] = len(agents)
        request["role"] = "Specialist ABC"
        _, denial = spawn_verdict(request, agents[0], agents, config)
        self.assertEqual(denial, "MAX_AGENTS")

    def test_runtime_cannot_be_inside_or_contain_production(self):
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / "project"
            with self.assertRaises(ValueError):
                ensure_external(project, project / "runs")
            with self.assertRaises(ValueError):
                ensure_external(project, temp)

    def test_doctor_rejects_incompatible_sdk_even_with_key_and_package(self):
        from metaweb_swarm.cli import doctor
        with patch.dict("os.environ", {"OPENAI_API_KEY": "fixture-key"}), patch("importlib.metadata.version", return_value="0.0.0"), patch("metaweb_swarm.backend.check_sdk", side_effect=ValueError("incompatible interface")), redirect_stdout(io.StringIO()):
            self.assertEqual(doctor("openai"), 2)


class SchedulerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.project = root / "project"
        (self.project / "scripts").mkdir(parents=True)
        (self.project / "src").mkdir()
        (self.project / "src" / "original.txt").write_text("unchanged", encoding="utf-8")
        self.config = load_config()
        self.config["run_mode"] = "autonomous"  # Exercise all scheduler roles; supervised selection is tested separately.
        self.run = initialize(self.project, root / "runs", self.config)

    def tearDown(self):
        self.temp.cleanup()

    def execute(self, backend=None):
        engine = Engine(self.run, backend or DemoBackend(), "demo")
        try:
            return asyncio.run(engine.run())
        finally:
            engine.close()

    def test_full_demo_emergence_audit_approvals_reports_origin_unchanged(self):
        state = self.execute()
        self.assertEqual(state["status"], "BLOCKED")
        self.assertEqual(len(state["agents"]), 13)
        self.assertEqual(state["usage"]["requests"], 0)
        self.assertEqual(len(state["ideas"]), 5)
        self.assertEqual(len(state["approvals"]), 2)
        self.assertTrue(all(not a["executed"] for a in state["approvals"]))
        self.assertEqual((self.project / "src" / "original.txt").read_text(), "unchanged")
        self.assertFalse((self.project / "scripts" / "swarm-demo-example.txt").exists())
        for name in ("SWARM_REPORT.md", "TIMELINE.md", "ideas.jsonl", "manifest.json", "checkpoint.json"):
            self.assertTrue((self.run / name).is_file(), name)
        patch = self.run / "patches" / "AGENT-013" / "changes.patch"
        self.assertIn("swarm-demo-example", patch.read_text())
        store = Store(self.run)
        try:
            self.assertGreater(store.verify()["events"], 20)
            # Portable checkpoint can be missing/stale; SQLite is the committed truth.
            (self.run / "checkpoint.json").write_text("not JSON")
            self.assertEqual(store.load()["steps"], 13)
        finally:
            store.close()

    def test_pause_and_resume_dont_repeat_finished_roles(self):
        (self.run / "PAUSE.flag").write_text("pause")
        state = self.execute()
        self.assertEqual(state["status"], "PAUSED")
        self.assertEqual(state["steps"], 0)
        (self.run / "PAUSE.flag").unlink()
        self.execute()
        state = self.execute()
        self.assertEqual(state["steps"], 13)

    def test_cli_resume_extends_token_budget_durably(self):
        from metaweb_swarm.cli import main
        store = Store(self.run)
        state = store.load()
        original = state["config"]["max_total_tokens"]
        state["config"]["max_steps"] = 1
        state["steps"] = 1
        store.commit(state, "test_limit", {})
        store.close()
        with redirect_stdout(io.StringIO()):
            self.assertEqual(main(["resume", str(self.run), "--backend", "demo", "--extend-tokens", "100000"]), 3)
        store = Store(self.run)
        try:
            self.assertEqual(store.load()["config"]["max_total_tokens"], original + 100000)
            store.verify()
        finally:
            store.close()

    def test_global_limit_is_distinct_and_count_reserved(self):
        store = Store(self.run)
        state = store.load()
        state["config"]["max_steps"] = 2
        store.commit(state, "test_limit", {})
        store.close()
        state = self.execute()
        self.assertEqual(state["status"], "LIMIT_REACHED")
        self.assertEqual(state["steps"], 2)
        self.assertTrue(any(a["status"] == "PENDING" for a in state["agents"]))

    def test_human_gate_payload_binding_and_unblock(self):
        self.execute()
        store = Store(self.run)
        try:
            state = store.load()
            gate = state["approvals"][0]
            gate["action"]["target"] = "https://example.org/changed"
            with self.assertRaises(ValueError):
                decide(store, state, gate["id"], "approve", "Approved exact intent")
            state = store.load()
            gate = state["approvals"][0]
            with self.assertRaises(ValueError):
                unblock(store, state, gate["agent_id"], "Account ready")
            decide(store, state, gate["id"], "approve", "Approved fixture intent only")
            self.assertFalse(gate["executed"])
            self.assertEqual(gate["status"], "APPROVED")
            previous_rounds = next(a for a in state["agents"] if a["id"] == gate["agent_id"])["rounds"]
            unblock(store, state, gate["agent_id"], "Fixture manual completion recorded")
            agent = next(a for a in state["agents"] if a["id"] == gate["agent_id"])
            self.assertEqual(agent["rounds"], previous_rounds)
            self.assertEqual(agent["status"], "PENDING")
        finally:
            store.close()

    def test_model_leads_exhaust_round_limit(self):
        class Continuing:
            async def step(self, agent, prompt, history, api, config):
                return {"output": {"status": "COMPLETED", "reason_for_stopping": "claimed done", "summary": "", "unexplored_leads": ["specific lead"], "blind_spots": []}, "history": [], "usage": {}, "raw": {}}
        state = self.execute(Continuing())
        self.assertEqual(state["status"], "LIMIT_REACHED")
        research = [a for a in state['agents'] if a.get('work_kind') != 'SYNTHESIS']
        reporters = [a for a in state['agents'] if a.get('work_kind') == 'SYNTHESIS']
        self.assertTrue(all(a['status'] == 'LIMIT_REACHED' and a['unexplored_leads'] for a in research))
        self.assertTrue(reporters)
        self.assertTrue(all(a['status'] == 'COMPLETED' and a['handoff_leads'] == ['specific lead'] for a in reporters))

    def test_smoke_cannot_complete_from_success_claim_without_test_receipt(self):
        class ClaimsSuccess:
            async def step(self, agent, prompt, history, api, config):
                return {'output': {'status':'COMPLETED', 'reason_for_stopping':'Docker worked', 'summary':'Done', 'unexplored_leads':[], 'blind_spots':[]}, 'history':[], 'usage':{}, 'raw':{}}
        engine = Engine(self.run, ClaimsSuccess(), 'demo')
        try:
            engine.state['config']['sandbox_smoke_test'] = True
            engine.state['agents'] = [a for a in engine.state['agents'] if a['role'] in {'Prototyper','Synthesizer / Reporter'}]
            engine.store.commit(engine.state, 'smoke_fixture', {})
            state = asyncio.run(engine.run())
            prototype = next(a for a in state['agents'] if a['role'] == 'Prototyper')
            self.assertEqual(prototype['status'], 'LIMIT_REACHED')
            self.assertIn('record_test', prototype['unexplored_leads'][0])
            self.assertEqual(state['status'], 'LIMIT_REACHED')
            self.assertFalse(state.get('tests'))
        finally:
            engine.close()

    def test_lock_prevents_two_writers(self):
        with run_lock(self.run):
            with self.assertRaises(ValueError):
                with run_lock(self.run):
                    pass

    def test_turn_quantum_continues_without_repeating_completed_tools(self):
        from metaweb_swarm.backend import BackendYield
        class YieldOnce:
            async def step(self, agent, prompt, history, api, config):
                if agent["rounds"] == 1:
                    api.note("first quantum observation")
                    raise BackendYield("Max turns (6) exceeded", history=[
                        {"type": "function_call", "name": "note", "call_id": "observed", "arguments": "{}"},
                        {"type": "function_call_output", "call_id": "observed", "output": '{"recorded":true}'}])
                assert any(i.get("call_id") == "observed" for i in history)
                return {"output": {"status": "COMPLETED", "reason_for_stopping": "done", "summary": "observation retained", "unexplored_leads": [], "blind_spots": []}, "history": history, "usage": {}, "raw": {}}
        state = self.execute(YieldOnce())
        self.assertEqual(state["status"], "COMPLETED")
        self.assertTrue(all(a["rounds"] == 2 for a in state["agents"]))

    def test_owner_only_completion_is_requeued_for_external_discovery(self):
        class OwnerOnly:
            async def step(self, agent, prompt, history, api, config):
                api.record_sdk_event("web_search_call", {"action": {"sources": [{"url": "https://vojtamaur.cz/"}]}})
                return {"output": {"status": "COMPLETED", "reason_for_stopping": "done", "summary": "owner audit", "unexplored_leads": [], "blind_spots": []}, "history": [], "usage": {}, "raw": {}}
        engine = Engine(self.run, OwnerOnly(), "openai")
        try:
            agent = engine.state["agents"][1]
            asyncio.run(engine.step(agent))
            self.assertEqual(agent["status"], "PENDING")
            self.assertFalse(agent["external_sources"])
            self.assertIn("external primary", agent["unexplored_leads"][0])
        finally:
            engine.close()

    def test_durable_usage_reconciles_without_double_counting(self):
        class UsageBackend:
            async def step(self, agent, prompt, history, api, config):
                api.record_sdk_event("history_checkpoint", {"history": [{"role": "user", "content": "checkpoint"}]})
                api.record_sdk_event("model_request_started", {"attempt": 1})
                api.record_sdk_event("web_search_call", {"type": "web_search_call"})
                api.record_sdk_event("model_response", {"usage": {"input_tokens": 100, "output_tokens": 50, "total_tokens": 150}})
                return {"output": {"status": "COMPLETED", "reason_for_stopping": "finished", "summary": "", "unexplored_leads": [], "blind_spots": []}, "history": [],
                        "usage": {"requests": 1, "web_search_calls": 1, "input_tokens": 100, "output_tokens": 50, "total_tokens": 150}, "raw": {"usage_complete": True}}
        store = Store(self.run)
        state = store.load()
        state["config"]["max_steps"] = 1
        store.commit(state, "test_limit")
        store.close()
        state = self.execute(UsageBackend())
        self.assertEqual(state["usage"]["total_tokens"], 150)
        self.assertEqual(state["usage"]["requests"], 1)
        self.assertEqual(state["usage"]["web_search_calls"], 1)
        self.assertEqual(state["usage"]["unknown_steps"], 0)

    def test_crash_recovery_retains_usage_and_charges_uncertain_request(self):
        store = Store(self.run)
        state = store.load()
        state["backend"] = "demo"
        state["steps"] = state["config"]["max_steps"]
        state["agents"][0].update(status="RUNNING", rounds=1, round_usage={"requests": 2, "responses_received": 1})
        state["usage"]["total_tokens"] = 150
        state["active_batch_started_at"] = state["created_at"]
        store.commit(state, "test_crash")
        store.close()
        state = self.execute()
        self.assertEqual(state["status"], "BLOCKED")
        self.assertIn('HUMAN_BUDGET_RECONCILIATION_REQUIRED', state['stop_reason'])
        self.assertEqual(state["usage"]["total_tokens"], 150)
        self.assertEqual(state["usage"]["unknown_steps"], 1)
        self.assertGreaterEqual(state["active_seconds"], 0)
        self.assertIsNone(state["active_batch_started_at"])

    def test_binary_artifact_uses_exact_bytes_and_keeps_proto_unverified(self):
        engine = Engine(self.run, DemoBackend(), "demo")
        try:
            agent = engine.state["agents"][0]
            workspace = Workspace(self.run / "snapshot", self.run / "agents" / agent["id"] / "workspace")
            workspace.write_file("work/example.bin", b"\x00\x01\xff")
            api = ToolAPI(engine, agent, workspace)
            idea = DemoBackend.idea("Binary prototype", "Encoding", "FREE", "PROTOTYPED")
            idea["artifacts"] = ["work/example.bin"]
            result = api.submit_idea(idea)
            self.assertEqual(result["status"], "INVESTIGATING")
            self.assertTrue(result["artifact_checks"][0]["binary"])
            self.assertFalse(result["prototype_tested"])
        finally:
            engine.close()

    def test_missing_response_usage_is_durable_before_crash(self):
        engine = Engine(self.run, DemoBackend(), "demo")
        try:
            agent = engine.state["agents"][0]
            agent.update(status="RUNNING", rounds=1, round_usage={})
            engine.state["steps"] = engine.state["config"]["max_steps"]
            workspace = Workspace(self.run / "snapshot", self.run / "agents" / agent["id"] / "workspace")
            api = ToolAPI(engine, agent, workspace)
            api.record_sdk_event("model_request_started", {"attempt": 1})
            api.record_sdk_event("model_response", {"usage": {"total_tokens": 0}})
            self.assertTrue(engine.store.load()["agents"][0]["round_usage"]["usage_incomplete"])
        finally:
            engine.close()
        state = self.execute()
        self.assertEqual(state["usage"]["unknown_steps"], 1)

    def test_cancelled_experiment_finishes_cleanup_before_returning(self):
        engine = Engine(self.run, DemoBackend(), "demo")
        engine.state["config"]["experiments"] = "docker"
        agent = engine.state["agents"][0]
        workspace = Workspace(self.run / "snapshot", self.run / "agents" / agent["id"] / "workspace")
        api = ToolAPI(engine, agent, workspace)
        finished = []
        class FakeDocker:
            def __init__(self, *args):
                pass
            def run(self, root, argv):
                time.sleep(0.05)
                finished.append(True)
                return {"status": "COMPLETED", "exit_code": 0}
        async def cancellation():
            task = asyncio.create_task(api.run_experiment(["python", "example.py"]))
            await asyncio.sleep(0.01)
            task.cancel()
            await asyncio.sleep(0.01)
            task.cancel()  # Repeated operator interruption must not abandon cleanup.
            with self.assertRaises(asyncio.CancelledError):
                await task
            self.assertEqual(finished, [True])
        try:
            with patch("metaweb_swarm.engine.DockerExecutor", FakeDocker):
                asyncio.run(cancellation())
        finally:
            engine.close()

    def test_workspace_setup_failure_is_blocked_and_reports_settled(self):
        with patch("metaweb_swarm.engine.Workspace", side_effect=OSError("fixture disk unavailable")):
            state = self.execute()
        self.assertEqual(state["status"], "BLOCKED")
        self.assertTrue(all(a["status"] == "BLOCKED" for a in state["agents"]))
        self.assertFalse(any(a["status"] == "RUNNING" for a in state["agents"]))
        self.assertEqual(state["usage"]["unknown_steps"], 0)
        manifest = json.loads((self.run / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["agent_statuses"], {"BLOCKED": 12})

    def test_cancelled_last_round_cannot_exceed_agent_limit(self):
        from metaweb_swarm.engine import Engine
        class CancelledBackend:
            async def step(self, *args):
                raise asyncio.CancelledError()
        engine = Engine(self.run, CancelledBackend(), "demo")
        engine.state["config"]["max_agent_rounds"] = 1
        try:
            with self.assertRaises(asyncio.CancelledError):
                asyncio.run(engine.run())
            self.assertEqual(engine.state["agents"][0]["status"], "LIMIT_REACHED")
            self.assertEqual(engine.state["agents"][0]["rounds"], 1)
        finally:
            engine.close()


if __name__ == "__main__":
    unittest.main()
