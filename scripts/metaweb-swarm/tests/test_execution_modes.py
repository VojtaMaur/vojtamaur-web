"""End-to-end host policy checks; fake model/Docker, real local deposit receipts."""
import asyncio
import hashlib
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from metaweb_swarm.backend import OpenAIBackend
from metaweb_swarm.config import load_config
from metaweb_swarm.demo import DemoBackend
from metaweb_swarm.engine import Engine, ToolAPI, decide, initialize
from metaweb_swarm.workspace import Workspace
from tests.test_backend import SDK_AVAILABLE

if SDK_AVAILABLE:
    from tests.test_backend import FakeProvider, final_response


class FinishResearch:
    async def step(self, agent, prompt, history, api, config):
        data = DemoBackend.idea("Useful unimplemented candidate", "Independent public archive mechanism", "FREE", "INVESTIGATING")
        api.submit_idea(data)
        return {"output": {"status": "COMPLETED", "reason_for_stopping": "Assigned research complete; implementation left for operator selection",
                           "summary": "Useful hypothesis saved", "unexplored_leads": [], "handoff_leads": ["Prototype later"], "blind_spots": []},
                "history": history, "usage": {"requests": 0, "input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "web_search_calls": 0}, "raw": {"usage_complete": True}}


class ExecutionModesTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.project = self.root / "project"
        (self.project / "public").mkdir(parents=True)
        (self.project / "public" / "ARCHIVE.txt").write_text("Existing archive index\n", encoding="utf-8")
        (self.project / "exports").mkdir()
        (self.project / "exports" / "build.zip").write_bytes(b"Opaque owner-prepared ZIP fixture")
        self.destination = self.root / "deposit"
        self.config = load_config()
        self.config.update(run_mode="autonomous", external_scope="external", approval_required=False,
                           experiments="docker", model="fixture-model", max_total_tokens=1_000_000,
                           external_resources=[{"id": "public-deposit", "kind": "local_directory", "directory": str(self.destination), "max_bytes": 64_000_000, "cost_usd": 0}])
        self.open_run()

    def open_run(self):
        self.run = initialize(self.project, self.root / "runs", self.config)
        self.engine = Engine(self.run, DemoBackend(), "demo")
        self.agent = self.engine.state["agents"][0]
        self.workspace = Workspace(self.run / "snapshot", self.run / "agents" / self.agent["id"] / "workspace", self.config["max_file_bytes"], self.config["max_snapshot_bytes"])
        self.api = ToolAPI(self.engine, self.agent, self.workspace)

    def tearDown(self):
        self.engine.close()
        self.temp.cleanup()

    def candidate(self, **changes):
        data = DemoBackend.idea("Public recovery package", "Deposit independently reconstructable build bytes", "FREE", "INVESTIGATING")
        data.update(changes)
        return self.api.submit_idea(data)

    async def prepare_tested_candidate(self):
        self.api.write_file("artifacts/recovery.txt", "recoverable public build bytes\n")
        idea = self.candidate(status="PROTOTYPED", artifacts=["artifacts/recovery.txt"])
        self.api.record_critique(idea["id"], "PASS", "Payload is a public build and this free destination is within granted scope")
        with patch("metaweb_swarm.engine.DockerExecutor") as executor:
            executor.return_value.run.return_value = {"status": "COMPLETED", "returncode": 0, "stdout": "Assertions passed", "stderr": ""}
            result = await self.api.run_experiment(["python", "check.py"], idea["id"])
        self.assertEqual(result["status"], "COMPLETED")
        receipt = self.api.record_test(idea["id"], result["experiment_id"], "Assert recovery bytes match a known hash and are reconstructable")
        self.assertTrue(receipt["host_execution_verified"])
        return self.api.idea(idea["id"]), receipt

    async def test_supervised_research_can_finish_without_rejecting_good_ideas(self):
        self.engine.state["config"]["run_mode"] = "supervised"
        self.engine.backend = FinishResearch()
        self.engine.state["agents"] = [a for a in self.engine.state["agents"] if a["role"] in {"Prototyper", "Synthesizer / Reporter"}]
        with redirect_stdout(io.StringIO()):
            result = await self.engine.run()
        self.assertEqual(result["status"], "COMPLETED")
        prototyper = next(a for a in result["agents"] if a["role"] == "Prototyper")
        self.assertEqual(prototyper["rounds"], 0)
        self.assertEqual(len(result["ideas"]), 1)
        self.assertEqual(result["ideas"][0]["status"], "INVESTIGATING")
        self.assertEqual(result["experiments"], [])
        self.assertEqual(result["external_actions"], [])
        self.assertTrue((self.run / "SWARM_REPORT.md").is_file())

    async def test_supervised_waits_for_selection_then_runs_without_rejecting_candidate(self):
        self.engine.state["config"]["run_mode"] = "supervised"
        idea = self.candidate()
        deferred = await self.api.run_experiment(["python", "check.py"], idea["id"])
        self.assertEqual(deferred["status"], "DEFERRED")
        self.assertTrue(deferred["research_may_finish"])
        self.assertNotEqual(idea["status"], "REJECTED")
        self.engine.state["implementation_choices"][idea["id"]] = {"decision": "implement"}
        with patch("metaweb_swarm.engine.DockerExecutor") as executor:
            executor.return_value.run.return_value = {"status": "COMPLETED", "returncode": 0}
            result = await self.api.run_experiment(["python", "check.py"], idea["id"])
        self.assertEqual(result["status"], "COMPLETED")

    async def test_autonomous_sandbox_executes_local_code_but_deposit_is_blocked(self):
        self.engine.state["config"]["external_scope"] = "sandbox-only"
        idea, receipt = await self.prepare_tested_candidate()
        result = await self.api.deposit_file(idea["id"], "public-deposit", "artifacts/recovery.txt")
        self.assertEqual(result["reason"], "EXTERNAL_SCOPE_DISABLED")
        self.assertTrue(idea["prototype_tested"])
        self.assertFalse(self.destination.exists())
        self.assertEqual(self.engine.state["approvals"], [])

    async def test_exit_zero_without_bound_artifact_cannot_certify_prototype(self):
        idea = self.candidate()
        with patch("metaweb_swarm.engine.DockerExecutor") as executor:
            executor.return_value.run.return_value = {"status": "COMPLETED", "returncode": 0}
            result = await self.api.run_experiment(["python", "check.py"], idea["id"])
        with self.assertRaisesRegex(ValueError, "declared prototype artifacts"):
            self.api.record_test(idea["id"], result["experiment_id"], "The process exited zero")
        self.assertEqual(self.engine.state['tests'], [])
        self.assertFalse(idea['prototype_tested'])

    async def test_approval_disabled_deposit_has_exact_readback_and_no_hidden_gate(self):
        idea, receipt = await self.prepare_tested_candidate()
        result = await self.api.deposit_file(idea["id"], "public-deposit", "artifacts/recovery.txt", object_name="recovery.txt")
        self.assertEqual(result["status"], "VERIFIED")
        self.assertTrue(result["receipt"]["host_verified"])
        expected = self.workspace.root.joinpath("artifacts/recovery.txt").read_bytes()
        self.assertEqual((self.destination / "recovery.txt").read_bytes(), expected)
        self.assertEqual(result["receipt"]["sha256"], hashlib.sha256(expected).hexdigest())
        self.assertEqual(self.engine.state["approvals"], [])
        self.assertEqual(idea["status"], "COMPLETED")
        self.assertTrue(idea["completion_receipts"])
        repeated = await self.api.deposit_file(idea["id"], "public-deposit", "artifacts/recovery.txt", object_name="recovery.txt")
        self.assertEqual(repeated["id"], result["id"])
        self.assertEqual(len(self.engine.state["external_actions"]), 1)
        self.assertGreater(self.engine.store.verify()["events"], 0)

    async def test_approval_required_queues_then_exact_decision_allows_execution(self):
        self.engine.state["config"]["approval_required"] = True
        idea, _ = await self.prepare_tested_candidate()
        first = await self.api.deposit_file(idea["id"], "public-deposit", "artifacts/recovery.txt", object_name="recovery.txt")
        self.assertEqual(first["status"], "DEFERRED")
        self.assertEqual(self.engine.state["approvals"][0]["status"], "PENDING")
        self.assertFalse(self.destination.exists())
        decide(self.engine.store, self.engine.state, first["approval_id"], "approve", "Publish this exact public test fixture")
        result = await self.api.deposit_file(idea["id"], "public-deposit", "artifacts/recovery.txt", object_name="recovery.txt")
        self.assertEqual(result["status"], "VERIFIED")
        self.assertTrue(self.engine.state["approvals"][0]["executed"])
        self.assertEqual(len(self.engine.state["approvals"]), 1)

    async def test_external_action_limit_prevents_second_write(self):
        self.engine.state["config"]["max_external_actions"] = 1
        idea, _ = await self.prepare_tested_candidate()
        first = await self.api.deposit_file(idea["id"], "public-deposit", "artifacts/recovery.txt", object_name="first.txt")
        self.assertEqual(first["status"], "VERIFIED")
        second = await self.api.deposit_file(idea["id"], "public-deposit", "artifacts/recovery.txt", object_name="second.txt")
        self.assertEqual(second["reason"], "MAX_EXTERNAL_ACTIONS")
        self.assertFalse((self.destination / "second.txt").exists())

    async def test_external_byte_limit_prevents_any_write(self):
        self.engine.state["config"]["max_external_bytes"] = 1
        idea, _ = await self.prepare_tested_candidate()
        result = await self.api.deposit_file(idea["id"], "public-deposit", "artifacts/recovery.txt")
        self.assertEqual(result["reason"], "MAX_EXTERNAL_BYTES")
        self.assertFalse(self.destination.exists())
        self.assertEqual(self.engine.state["external_actions"], [])

    async def test_changed_artifact_after_successful_test_cannot_publish(self):
        idea, _ = await self.prepare_tested_candidate()
        self.api.write_file("artifacts/recovery.txt", "different untested build bytes\n")
        result = await self.api.deposit_file(idea["id"], "public-deposit", "artifacts/recovery.txt")
        self.assertEqual(result["reason"], "ARTIFACT_BYTES_NOT_IN_EXECUTED_TEST")
        self.assertFalse(self.destination.exists())

    async def test_failed_docker_exit_cannot_be_recorded_as_successful_test(self):
        self.api.write_file("artifacts/recovery.txt", "build bytes\n")
        idea = self.candidate(status="PROTOTYPED", artifacts=["artifacts/recovery.txt"])
        with patch("metaweb_swarm.engine.DockerExecutor") as executor:
            executor.return_value.run.return_value = {"status": "COMPLETED", "returncode": 1}
            result = await self.api.run_experiment(["python", "check.py"], idea["id"])
        with self.assertRaisesRegex(ValueError, "successful Docker"):
            self.api.record_test(idea["id"], result["experiment_id"], "Assertions failed")
        self.assertFalse(idea.get("prototype_tested"))

    async def test_other_agent_cannot_claim_experiment_as_its_test(self):
        idea, receipt = await self.prepare_tested_candidate()
        other = self.engine.state["agents"][1]
        other_workspace = Workspace(self.run / "snapshot", self.run / "agents" / other["id"] / "workspace")
        other_api = ToolAPI(self.engine, other, other_workspace)
        with self.assertRaisesRegex(ValueError, "this agent"):
            other_api.record_test(idea["id"], receipt["experiment_id"], "Claim someone else's execution")

    def test_submit_deduplicates_paraphrases_and_retains_agent_provenance(self):
        a = self.candidate(provider="ORCID", title="Public ORCID recovery pointer", mechanism="Public ORCID record links to preserved artifact packages", mechanism_kind="REGISTRATION")
        other = self.engine.state["agents"][1]
        other_api = ToolAPI(self.engine, other, Workspace(self.run / "snapshot", self.run / "agents" / other["id"] / "workspace"))
        data = DemoBackend.idea("ORCID reconstruction anchor", "Use ORCID public pointers to preserved ZIPs", "FREE", "INVESTIGATING")
        data.update(provider="ORCID", mechanism_kind="OTHER")
        b = other_api.submit_idea(data)
        self.assertEqual(a["id"], b["id"])
        self.assertEqual(len(self.engine.state["ideas"]), 1)
        self.assertEqual(b["contributors"], [self.agent["id"], other["id"]])
        self.assertEqual(len(b["submissions"]), 2)

    def test_materialized_export_is_independent_and_hash_bound(self):
        original = self.project.joinpath("exports/build.zip").read_bytes()
        result = self.api.materialize_export("build.zip", "artifacts/public-build.zip")
        self.assertEqual(result["sha256"], hashlib.sha256(original).hexdigest())
        self.workspace.write_file("artifacts/public-build.zip", b"changed private bytes")
        self.assertEqual(self.project.joinpath("exports/build.zip").read_bytes(), original)
        self.assertEqual(self.run.joinpath("input_exports/build.zip").read_bytes(), original)

    def test_materialize_export_above_old_20mb_limit(self):
        self.engine.close()
        self.project.joinpath("exports/large.zip").write_bytes(b"x" * 20_000_001)
        self.open_run()
        result = self.api.materialize_export("large.zip", "artifacts/large.zip")
        self.assertEqual(result["bytes"], 20_000_001)
        self.assertEqual(self.workspace.root.joinpath("artifacts/large.zip").stat().st_size, 20_000_001)

    @unittest.skipUnless(SDK_AVAILABLE, "Install optional SDK for local fake-model integration")
    async def test_fake_sdk_uses_real_engine_budget_reservation_and_settlement(self):
        provider = FakeProvider([final_response()])
        result = await OpenAIBackend(provider).step(self.agent, "Review saved ideas", [], self.api, self.engine.state["config"])
        self.assertEqual(result["usage"]["total_tokens"], 15)
        self.assertEqual(self.engine.state["usage"]["total_tokens"], 15)
        self.assertEqual(self.engine.state["budget_reservations"], {})
        self.assertEqual(len(self.engine.state["budget_settlements"]), 1)
        settlement = next(iter(self.engine.state["budget_settlements"].values()))
        self.assertEqual(settlement["status"], "SETTLED")
        self.assertEqual(provider.model.calls[0][1]["model_settings"].extra_args["max_tool_calls"], self.config["max_web_search_calls_per_request"])
        self.assertGreater(self.engine.store.verify()["events"], 0)

    async def test_untested_export_cannot_bypass_test_with_another_artifact(self):
        idea, _ = await self.prepare_tested_candidate()
        result = await self.api.deposit_file(idea["id"], "public-deposit", "build.zip", source="export")
        self.assertEqual(result["status"], "BLOCKED")
        self.assertFalse(self.destination.exists())

    async def test_materialized_export_captured_by_test_can_deposit_exact_original(self):
        original = self.project.joinpath("exports/build.zip").read_bytes()
        self.api.materialize_export("build.zip", "artifacts/public-build.zip")
        idea, receipt = await self.prepare_tested_candidate()
        self.assertEqual(receipt["exports"][0]["export"], "build.zip")
        result = await self.api.deposit_file(idea["id"], "public-deposit", "build.zip", source="export", object_name="build.zip")
        self.assertEqual(result["status"], "VERIFIED")
        self.assertEqual(self.destination.joinpath("build.zip").read_bytes(), original)

    async def test_unknown_resource_and_disabled_experiments_are_bounded(self):
        idea, _ = await self.prepare_tested_candidate()
        unknown = await self.api.deposit_file(idea["id"], "never-granted", "artifacts/recovery.txt")
        self.assertEqual(unknown["reason"], "RESOURCE_NOT_GRANTED")
        self.engine.state["config"]["experiments"] = "disabled"
        result = await self.api.run_experiment(["python", "check.py"], idea["id"])
        self.assertEqual(result["status"], "BLOCKED")
        self.assertFalse(self.destination.exists())

    async def test_pause_resume_preserves_research_and_audit_chain(self):
        self.engine.backend = FinishResearch()
        self.engine.state["agents"] = [a for a in self.engine.state["agents"] if a["role"] == "Synthesizer / Reporter"]
        pause = self.run / "PAUSE.flag"
        pause.write_text("Operator pause", encoding="utf-8")
        with redirect_stdout(io.StringIO()):
            paused = await self.engine.run()
        self.assertEqual(paused["status"], "PAUSED")
        self.assertEqual(self.engine.store.load()["steps"], 0)
        before = self.engine.store.verify()
        pause.unlink()
        with redirect_stdout(io.StringIO()):
            finished = await self.engine.run()
        self.assertEqual(finished["status"], "COMPLETED")
        self.assertEqual(finished["steps"], 1)
        self.assertEqual(len(finished["ideas"]), 1)
        after = self.engine.store.verify()
        self.assertGreater(after["events"], before["events"])
        self.assertNotEqual(after["head_hash"], before["head_hash"])

    @unittest.skipUnless(SDK_AVAILABLE, "Install optional SDK for local fake-model integration")
    async def test_fake_sdk_timeout_retains_unknown_budget_across_reopen(self):
        self.engine.backend = OpenAIBackend(FakeProvider(["wait"]))
        self.engine.state["config"]["step_timeout_seconds"] = 1
        with redirect_stdout(io.StringIO()):
            await self.engine.step(self.agent)
        hold = next(iter(self.engine.state["budget_reservations"].values()))
        self.assertEqual(hold["status"], "UNKNOWN")
        self.assertEqual(self.engine.state["usage"]["requests"], 1)
        self.assertEqual(self.engine.state["usage"]["unknown_steps"], 1)
        self.engine.close()
        self.engine = Engine(self.run, DemoBackend(), "demo")
        self.agent = self.engine.state["agents"][0]
        self.api = ToolAPI(self.engine, self.agent, self.workspace)
        retained = next(iter(self.engine.state["budget_reservations"].values()))
        self.assertEqual(retained["id"], hold["id"])
        reason = self.api.begin_model_request("Continue", [{"role": "user", "content": "Continue"}], [], None)
        self.assertIn("RECONCILIATION_REQUIRED", reason)
        self.assertGreater(self.engine.store.verify()["events"], 0)


if __name__ == "__main__":
    unittest.main()
