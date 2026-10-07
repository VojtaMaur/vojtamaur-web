"""Offline regression tests for evidence attribution, reports and context boundaries."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from metaweb_swarm.context import _fetch_public, capture_context, redact_text
from metaweb_swarm.reporting import generate_reports


class ContextTests(unittest.TestCase):
    def test_missing_sources_are_explicit_and_user_piql_is_retained(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / "snapshot"
            project.mkdir()
            output = Path(directory) / "context"
            metadata = capture_context(project, output)
            local = [entry for entry in metadata["sources"] if entry["kind"] == "local_snapshot"]
            self.assertEqual(len(local), 4)
            self.assertTrue(all(entry["status"] == "ERROR" for entry in local))
            self.assertFalse(metadata["live_requested"])
            self.assertIn("IN PROGRESS", (output / "CURRENT_STATE.md").read_text(encoding="utf-8"))
            self.assertEqual(metadata, json.loads((output / "provenance.json").read_text(encoding="utf-8")))

    def test_live_error_is_not_fabricated_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch("metaweb_swarm.context._fetch_public", side_effect=OSError("offline")):
                metadata = capture_context(Path(directory), Path(directory) / "context", fetch_live=True)
            live = [entry for entry in metadata["sources"] if entry["kind"] == "live_public_get"]
            self.assertEqual(len(live), 4)
            self.assertTrue(all(entry["status"] == "ERROR" and entry["error"] == "offline" for entry in live))

    def test_public_dns_cannot_resolve_to_private_network(self):
        with patch("metaweb_swarm.context.socket.getaddrinfo", return_value=[(2, 1, 6, "", ("127.0.0.1", 443))]):
            with self.assertRaisesRegex(ValueError, "non-public"):
                _fetch_public("https://vojtamaur.cz/")
        with self.assertRaisesRegex(ValueError, "allowlist"):
            _fetch_public("http://127.0.0.1/private")

    def test_capture_excludes_credentials_from_allowed_text(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            (project / "README.md").write_text("OPENAI_API_KEY=sk-" + "a" * 30 + "\nOrdinary context", encoding="utf-8")
            output = project / "context"
            metadata = capture_context(project, output)
            self.assertNotIn("sk-", (output / "local-project-README.md").read_text(encoding="utf-8"))
            entry = next(item for item in metadata["sources"] if item.get("source") == "README.md")
            self.assertTrue(entry["redacted"])
            self.assertNotEqual(entry["sha256"], entry["source_sha256"])

    def test_private_key_redaction_preserves_public_key(self):
        text = "-----BEGIN PRIVATE KEY-----\nsecret\n-----END PRIVATE KEY-----\n-----BEGIN PUBLIC KEY-----\npublic\n-----END PUBLIC KEY-----"
        redacted = redact_text(text)
        self.assertNotIn("secret", redacted)
        self.assertIn("BEGIN PUBLIC KEY", redacted)


class ReportingTests(unittest.TestCase):
    def test_report_preserves_blockers_and_does_not_invent_completion(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "raw").mkdir()
            events = [{"seq": 1, "time": "2026-10-06T09:00:00Z", "kind": "agent_step", "agent_id": "AGENT-001", "data": {"backend": "demo"}, "hash": "abc", "prev_hash": ""}]
            (root / "raw/events.jsonl").write_text("\n".join(json.dumps(item) for item in events) + "\n", encoding="utf-8")
            state = {"run_id": "fixture", "status": "BLOCKED", "backend": "demo", "config": {},
                     "agents": [{"id": "AGENT-001", "role": "Scout", "status": "BLOCKED", "rounds": 1,
                                 "summary": "No publication happened", "reason_for_stopping": "Human registration needed"}],
                     "ideas": [{"id": "IDEA-001", "agent_id": "AGENT-001", "title": "One time payment", "status": "BLOCKED", "payment_model": "one_time"}],
                     "approvals": [{"id": "APPROVAL-001", "status": "PENDING", "action": {"type": "payment"}}]}
            generate_reports(root, state)
            report = (root / "SWARM_REPORT.md").read_text(encoding="utf-8")
            self.assertIn("DEMO / OFFLINE FIXTURE", report)
            self.assertIn("Human registration needed", report)
            self.assertIn("No publication happened", report)
            self.assertIn("APPROVAL-001", report)
            manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
            self.assertTrue(manifest["demo_fixture"])
            self.assertEqual(manifest["event_count"], 1)
            self.assertEqual(manifest["idea_statuses"], {"BLOCKED": 1})
            self.assertEqual(json.loads((root / "ideas.jsonl").read_text(encoding="utf-8"))["payment_model"], "one_time")
            before = {name: (root / name).read_bytes() for name in ("SWARM_REPORT.md", "TIMELINE.md", "ideas.jsonl", "manifest.json")}
            generate_reports(root, state)
            self.assertEqual(before, {name: (root / name).read_bytes() for name in before})

    def test_json_reports_remain_valid_after_secret_redaction(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = {"run_id": "redaction", "status": "PAUSED", "config": {"note": "OPENAI_API_KEY=secret"},
                     "ideas": [{"id": "IDEA-001", "summary": "api_key=secret"}], "agents": []}
            generate_reports(root, state)
            manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
            ideas = json.loads((root / "ideas.jsonl").read_text(encoding="utf-8"))
            self.assertIn("[REDACTED]", manifest["config"]["note"])
            self.assertIn("[REDACTED]", ideas["summary"])

    def test_truncated_audit_is_reported(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "raw").mkdir()
            (root / "raw/events.jsonl").write_text('{"seq":', encoding="utf-8")
            generate_reports(root, {"run_id": "corrupt", "status": "BLOCKED"})
            manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["event_count"], 0)
            self.assertEqual(len(manifest["event_read_errors"]), 1)

    def test_timeline_summarizes_model_payloads_but_keeps_usage_and_raw_link(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "raw").mkdir()
            event = {"seq": 1, "time": "2026-10-06T09:00:00Z", "kind": "sdk_model_response", "agent_id": "AGENT-001",
                     "data": {"usage": {"total_tokens": 42}, "output": [{"type": "message", "content": "large payload " * 5000}]}}
            (root / "raw/events.jsonl").write_text(json.dumps(event) + "\n", encoding="utf-8")
            generate_reports(root, {"run_id": "summary", "status": "PAUSED", "software_version": "0.1.0", "prompt_hashes": {"CORE.md": "123"}})
            timeline = (root / "TIMELINE.md").read_text(encoding="utf-8")
            self.assertLess(len(timeline), 2000)
            self.assertIn('"total_tokens": 42', timeline)
            self.assertIn("raw/events.jsonl#L1", timeline)
            self.assertNotIn("large payload", timeline)
            manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["prompt_hashes"]["CORE.md"], "123")


if __name__ == "__main__":
    unittest.main()
