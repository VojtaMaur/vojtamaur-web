import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import tempfile
import unittest

from metaweb_swarm.run_memory import build_run_memory, memory_markdown, write_run_memory


class RunMemoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def state(self, status="COMPLETED", **extra):
        return {"schema_version": 1, "status": status, "ideas": [], "agents": [],
                "updated_at": "2026-10-07T10:00:00Z", **extra}

    def checkpoint(self, name, state):
        run = self.root / name
        run.mkdir()
        (run / "checkpoint.json").write_text(json.dumps(state), encoding="utf-8")
        return run

    def test_readonly_sqlite_is_authoritative_over_stale_projection(self):
        run = self.checkpoint("20261006-a", self.state("REJECTED"))
        with sqlite3.connect(run / "state.sqlite3") as connection:
            connection.execute("CREATE TABLE state (id INTEGER PRIMARY KEY, body TEXT)")
            connection.execute("INSERT INTO state VALUES (1,?)", (json.dumps(self.state("COMPLETED")),))
        connection.close()
        before = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in run.iterdir()}
        memory = build_run_memory(self.root)
        self.assertEqual(memory["entries"][0]["status"], "COMPLETED")
        self.assertEqual(memory["entries"][0]["source"], "sqlite_read_only")
        after = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in run.iterdir()}
        self.assertEqual(before, after)

    def test_terminal_limits_and_blockers_retained_but_active_runs_omitted(self):
        for number, status in enumerate(("COMPLETED", "BLOCKED", "LIMIT_REACHED", "RUNNING", "PAUSED")):
            self.checkpoint(f"run-{number}", self.state(status))
        self.checkpoint("unfinished", self.state("LIMIT_REACHED", active_batch_started_at="in flight"))
        memory = build_run_memory(self.root, "run-0")
        self.assertEqual({entry["status"] for entry in memory["entries"]}, {"BLOCKED", "LIMIT_REACHED"})
        self.assertIn("NOT IMPLEMENTED METAWEB BASELINE", memory["notice"])

    def test_demo_runs_are_not_real_research_memory_by_default(self):
        self.checkpoint("demo", self.state(backend="demo"))
        self.assertFalse(build_run_memory(self.root)["entries"])
        self.assertEqual(len(build_run_memory(self.root, include_demo=True)["entries"]), 1)

    def test_artifacts_rejections_failures_and_receipts_are_distinct(self):
        ideas = [{"title": "Rejected QR", "status": "REJECTED"},
                 {"title": "Claimed implementation", "status": "COMPLETED"},
                 {"title": "Untested sample", "status": "PROTOTYPED", "artifact_checks": [{"path": "x"}]},
                 {"title": "Tested sample", "status": "PROTOTYPED", "artifact_checks": [{"path": "y"}], "prototype_tested": True}]
        actions = [{"status": "COMPLETED", "result": {"verified": True}}, {"status": "COMPLETED"}]
        self.checkpoint("run", self.state(ideas=ideas, agents=[{"status": "BLOCKED"}], external_actions=actions))
        entry = build_run_memory(self.root)["entries"][0]
        self.assertEqual(entry["counts"]["rejected"], 1)
        self.assertEqual(entry["counts"]["checked_artifacts"], 2)
        self.assertEqual(entry["counts"]["tested_artifacts"], 1)
        self.assertEqual(entry["counts"]["untested_artifacts"], 1)
        self.assertEqual(entry["counts"]["verified_external_receipts"], 1)
        self.assertIn("1 blocked/failed agents", entry["summary"])
        self.assertIn("Rejected QR [REJECTED]", entry["summary"])

    def test_external_receipt_uses_current_host_verified_action_contract(self):
        actions = [{"status": "VERIFIED", "receipt": {"host_verified": True}},
                   {"status": "VERIFIED", "receipt": {"host_verified": False}},
                   {"status": "UNKNOWN", "receipt": {"host_verified": True}}]
        self.checkpoint("run", self.state(external_actions=actions))
        self.assertEqual(build_run_memory(self.root)["entries"][0]["counts"]["verified_external_receipts"], 1)

    def test_checkpoint_fallback_and_oversize_corruption_are_bounded(self):
        good = self.checkpoint("good", self.state())
        (good / "state.sqlite3").write_bytes(b"corrupt SQLite")
        self.checkpoint("oversized", self.state(summary="x" * 1000))
        self.checkpoint("bad", {"schema_version": 99, "status": "COMPLETED"})
        memory = build_run_memory(self.root, max_state_bytes=500)
        self.assertEqual(len(memory["entries"]), 1)
        self.assertEqual(memory["entries"][0]["source"], "checkpoint_projection_not_authoritative")
        self.assertEqual(len(memory["skipped"]), 2)

    def test_wal_bearing_snapshot_uses_labelled_projection_without_sqlite_side_effects(self):
        run = self.checkpoint("wal-run", self.state("LIMIT_REACHED"))
        connection = sqlite3.connect(run / "state.sqlite3")
        try:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("CREATE TABLE state (id INTEGER PRIMARY KEY, body TEXT)")
            connection.execute("INSERT INTO state VALUES (1,?)", (json.dumps(self.state("COMPLETED")),))
            connection.commit()
            before = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in run.iterdir()}
            memory = build_run_memory(self.root)
            self.assertEqual(memory["entries"][0]["source"], "checkpoint_projection_not_authoritative")
            self.assertEqual(memory["entries"][0]["status"], "LIMIT_REACHED")
            after = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in run.iterdir()}
            self.assertEqual(before, after)
        finally:
            connection.close()

    def test_memory_is_short_redacted_and_latest_first(self):
        for number in range(6):
            self.checkpoint(f"2026100{number}-run", self.state(ideas=[{"title": "sk-" + "a" * 30, "status": "DISCOVERED"}]))
        memory = build_run_memory(self.root, max_runs=2, max_chars=1000)
        self.assertEqual(len(memory["entries"]), 2)
        self.assertEqual(memory["entries"][0]["run_id"], "20261005-run")
        self.assertNotIn("sk-" + "a" * 30, memory_markdown(memory))
        self.assertTrue(memory["truncated"])

    def test_atomic_derived_index_and_current_state_never_change_old_runs(self):
        previous = self.checkpoint("previous", self.state())
        current = self.checkpoint("current", self.state("PAUSED"))
        original = (previous / "checkpoint.json").read_bytes()
        returned = write_run_memory(current, current_state=self.state("LIMIT_REACHED"))
        self.assertEqual([entry["run_id"] for entry in returned["entries"]], ["previous"])
        index = json.loads((self.root / "RUN_MEMORY.json").read_text(encoding="utf-8"))
        self.assertEqual(index["entries"][0]["run_id"], "current")
        self.assertEqual(index["entries"][0]["source"], "caller_committed_state")
        self.assertEqual((previous / "checkpoint.json").read_bytes(), original)
        self.assertFalse(list(self.root.rglob(".swarm-*.tmp")))

    @unittest.skipUnless(os.name == "nt", "Windows junction test")
    def test_linked_prior_run_and_linked_output_are_refused(self):
        outside = self.root.parent / (self.root.name + "-outside")
        outside.mkdir()
        try:
            (outside / "checkpoint.json").write_text(json.dumps(self.state()), encoding="utf-8")
            linked = self.root / "linked"
            created = subprocess.run(["cmd", "/c", "mklink", "/J", str(linked), str(outside)], capture_output=True)
            if created.returncode:
                self.skipTest("Junction unavailable")
            try:
                self.assertFalse(build_run_memory(self.root)["entries"])
                with self.assertRaises(ValueError):
                    write_run_memory(linked)
                self.assertEqual(set(path.name for path in outside.iterdir()), {"checkpoint.json"})
            finally:
                linked.rmdir()
        finally:
            (outside / "checkpoint.json").unlink(missing_ok=True)
            outside.rmdir()
