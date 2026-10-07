from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from metaweb_swarm.workspace import (
    DockerExecutor, SecurityError, SnapshotLimitError, Workspace,
    _linked, create_snapshot, export_patch,
)


class WorkspaceFixture:
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary.name)
        self.project = self.base / "project"
        self.project.mkdir()
        (self.project / "index.html").write_text("old content\n", encoding="utf-8")
        self.snapshot = self.base / "snapshot"

    def tearDown(self):
        self.temporary.cleanup()

    def workspace(self):
        create_snapshot(self.project, self.snapshot)
        return Workspace(self.snapshot, self.base / "agent")


class WorkspaceTests(WorkspaceFixture, unittest.TestCase):
    def test_snapshot_excludes_secrets_caches_archives_and_bundle(self):
        for name in (".env", ".env.production", "private.pem", "credentials.json", "source-bundle.zip", "backup.tar"):
            (self.project / name).write_text("sensitive", encoding="utf-8")
        for directory in ("node_modules", ".aws", "dist-prod", "exports", ".source-bundle-staging"):
            (self.project / directory).mkdir()
            (self.project / directory / "file.txt").write_text("excluded", encoding="utf-8")
        result = create_snapshot(self.project, self.snapshot)
        self.assertEqual(set(result["files"]), {"index.html"})
        self.assertEqual(result["hash"], result["sha256"])
        self.assertGreaterEqual(len(result["skipped"]), 11)
        self.assertEqual((self.snapshot / "index.html").read_text(), "old content\n")

    def test_credential_content_is_excluded_without_exposing_its_value(self):
        examples = {
            "plain.txt": "sk-" + "a" * 30,
            "github.txt": "ghp_" + "b" * 30,
            "aws.txt": "AKIA" + "A" * 16,
            "rsa.txt": "-----BEGIN RSA PRIVATE KEY-----",
        }
        for name, value in examples.items():
            (self.project / name).write_text(value, encoding="utf-8")
        (self.project / "source-bundle").mkdir()
        (self.project / "source-bundle" / "reconstruct.py").write_text("print('helper')", encoding="utf-8")
        result = create_snapshot(self.project, self.snapshot)
        self.assertEqual(set(result["files"]), {"index.html", "source-bundle/reconstruct.py"})
        encoded = json.dumps(result)
        self.assertTrue(all(value not in encoded for value in examples.values()))
        self.assertTrue(all("content" in entry["reason"] for entry in result["skipped"]))

    def test_configured_large_file_survives_workspace_and_patch_export(self):
        payload = b"\x00" + b"a" * 20_000_001
        (self.project / "large.bin").write_bytes(payload)
        create_snapshot(self.project, self.snapshot, max_file_bytes=64_000_000)
        workspace = Workspace(self.snapshot, self.base / "agent")
        self.assertEqual((workspace.source / "large.bin").stat().st_size, len(payload))
        result = export_patch(self.snapshot, workspace.source, self.base / "patch")
        self.assertEqual(result["changed"], 0)

    def test_read_file_rejects_binary_content_with_clear_error(self):
        workspace = self.workspace()
        workspace.write_file("work/file.bin", b"\x00binary")
        with self.assertRaisesRegex(ValueError, "UTF-8 text"):
            workspace.read_file("work/file.bin")
        info = workspace.file_info("work/file.bin")
        self.assertTrue(info["binary"])
        self.assertEqual(info["bytes"], 7)

    def test_size_limits_leave_no_partial_snapshot(self):
        (self.project / "large.txt").write_text("123456", encoding="utf-8")
        with self.assertRaises(SnapshotLimitError):
            create_snapshot(self.project, self.snapshot, max_file_bytes=5)
        self.assertFalse(self.snapshot.exists())
        self.assertFalse(list(self.base.glob(".swarm-snapshot-*")))
        with self.assertRaises(SnapshotLimitError):
            create_snapshot(self.project, self.snapshot, max_file_bytes=100, max_total_bytes=15)
        self.assertFalse(self.snapshot.exists())

    def test_manifest_hashes_copied_bytes_if_source_changes_after_read(self):
        import hashlib
        from metaweb_swarm import workspace as module
        original_read = module._read_bytes
        original_bytes = (self.project / "index.html").read_bytes()

        def changing_source(root, relative, limit=64_000_000):
            data = original_read(root, relative, limit)
            (self.project / "index.html").write_text("later change\n", encoding="utf-8")
            return data

        with patch.object(module, "_read_bytes", side_effect=changing_source):
            result = create_snapshot(self.project, self.snapshot)
        copied = (self.snapshot / "index.html").read_bytes()
        self.assertEqual(result["files"]["index.html"]["sha256"], hashlib.sha256(copied).hexdigest())
        self.assertEqual(copied, original_bytes)
        self.assertEqual((self.project / "index.html").read_text(), "later change\n")

    def test_snapshot_cannot_be_inside_project(self):
        with self.assertRaises(SecurityError):
            create_snapshot(self.project, self.project / "copy")
        self.assertFalse((self.project / "copy").exists())

    @unittest.skipUnless(shutil.which("git"), "Git unavailable")
    def test_git_snapshot_preserves_uncommitted_content_and_omits_untracked(self):
        subprocess.run(["git", "init", str(self.project)], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(self.project), "add", "index.html"], check=True, capture_output=True)
        (self.project / "index.html").write_text("working change\n", encoding="utf-8")
        (self.project / "untracked.txt").write_text("not tracked", encoding="utf-8")
        result = create_snapshot(self.project, self.snapshot)
        self.assertEqual(result["mode"], "git-tracked")
        self.assertEqual((self.snapshot / "index.html").read_text(), "working change\n")
        self.assertFalse((self.snapshot / "untracked.txt").exists())
        self.assertFalse((self.snapshot / ".git").exists())

    def test_workspace_copy_is_independent_and_resume_preserves_changes(self):
        workspace = self.workspace()
        workspace.write_file("source/vojtamaur-web/index.html", "changed")
        self.assertEqual((self.snapshot / "index.html").read_text(), "old content\n")
        self.assertEqual((self.project / "index.html").read_text(), "old content\n")
        source_info = (self.project / "index.html").stat()
        copy_info = (workspace.source / "index.html").stat()
        self.assertNotEqual((source_info.st_dev, source_info.st_ino), (copy_info.st_dev, copy_info.st_ino))
        resumed = Workspace(self.snapshot, workspace.root)
        self.assertEqual(resumed.read_file("source/vojtamaur-web/index.html"), "changed")
        self.assertIn("source/vojtamaur-web/index.html", resumed.list_files("source"))

    def test_workspace_rejects_path_traversal_and_windows_aliases(self):
        workspace = self.workspace()
        for name in ("../escape", "work/../../escape", "/tmp/escape", "C:\\escape", "\\\\server\\share", "work/file:stream", "work/CON", "work/thing.", "work/thing ", "work//bad"):
            with self.subTest(name=name):
                with self.assertRaises(SecurityError):
                    workspace.write_file(name, "escape")
                with self.assertRaises(SecurityError):
                    workspace.read_file(name)
        with self.assertRaises(SecurityError):
            workspace.write_file(".metaweb-workspace.json", "{}")
        self.assertFalse((self.base / "escape").exists())

    def test_symlinks_are_excluded_from_snapshot_and_blocked_in_file_tools(self):
        outside = self.base / "outside.txt"
        outside.write_text("private", encoding="utf-8")
        try:
            (self.project / "link.txt").symlink_to(outside)
        except OSError as exc:
            self.skipTest(f"Symlink creation unavailable: {exc}")
        result = create_snapshot(self.project, self.snapshot)
        self.assertFalse((self.snapshot / "link.txt").exists())
        self.assertTrue(any(item["path"] == "link.txt" for item in result["skipped"]))
        workspace = Workspace(self.snapshot, self.base / "agent")
        (workspace.work / "linked").symlink_to(self.base, target_is_directory=True)
        with self.assertRaises(SecurityError):
            workspace.read_file("work/linked/outside.txt")
        with self.assertRaises(SecurityError):
            workspace.write_file("work/linked/outside.txt", "overwritten")
        with self.assertRaises(SecurityError):
            workspace.list_files()
        self.assertEqual(outside.read_text(), "private")

    def test_windows_reparse_attribute_is_detected(self):
        self.assertTrue(_linked(SimpleNamespace(st_mode=0o100644, st_file_attributes=0x400)))
        self.assertFalse(_linked(SimpleNamespace(st_mode=0o100644, st_file_attributes=0)))

    @unittest.skipUnless(os.name == "nt", "Windows junction test")
    def test_windows_junction_cannot_escape_or_enter_snapshot(self):
        outside = self.base / "outside"
        outside.mkdir()
        (outside / "secret.txt").write_text("private", encoding="utf-8")
        junction = self.project / "junction"
        created = subprocess.run(["cmd", "/c", "mklink", "/J", str(junction), str(outside)], capture_output=True)
        if created.returncode:
            self.skipTest("Windows junction creation unavailable")
        try:
            result = create_snapshot(self.project, self.snapshot)
            self.assertFalse((self.snapshot / "junction").exists())
            self.assertTrue(any(entry["path"] == "junction" for entry in result["skipped"]))
            workspace = Workspace(self.snapshot, self.base / "agent")
            link = workspace.work / "junction"
            created = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(outside)], capture_output=True)
            self.assertEqual(created.returncode, 0)
            try:
                with self.assertRaises(SecurityError):
                    workspace.read_file("work/junction/secret.txt")
                with self.assertRaises(SecurityError):
                    workspace.write_file("work/junction/secret.txt", "overwritten")
                with self.assertRaises(SecurityError):
                    DockerExecutor().run(workspace.root, ["true"])
                self.assertEqual((outside / "secret.txt").read_text(), "private")
            finally:
                link.rmdir()
        finally:
            junction.rmdir()

    @unittest.skipUnless(shutil.which("git"), "Git unavailable")
    def test_text_patch_applies_to_a_separate_review_copy(self):
        (self.project / "remove.txt").write_text("remove me\n", encoding="utf-8")
        (self.project / "ž space.txt").write_text("before without newline", encoding="utf-8")
        workspace = self.workspace()
        workspace.write_file("source/vojtamaur-web/index.html", "new content\n")
        workspace.write_file("source/vojtamaur-web/new.txt", "new file\n")
        workspace.write_file("source/vojtamaur-web/ž space.txt", "after without newline")
        (workspace.source / "remove.txt").unlink()
        result = export_patch(self.snapshot, workspace.source, self.base / "patch")
        self.assertEqual(result["changed"], 4)
        content = Path(result["patch"]).read_text(encoding="utf-8")
        self.assertIn("-old content", content)
        self.assertIn("+new content", content)
        self.assertIn("\\ No newline at end of file", content)
        review = self.base / "review"
        shutil.copytree(self.snapshot, review)
        checked = subprocess.run(["git", "apply", "--check", result["patch"]], cwd=review, capture_output=True)
        self.assertEqual(checked.returncode, 0, checked.stderr.decode(errors="replace"))
        applied = subprocess.run(["git", "apply", result["patch"]], cwd=review, capture_output=True)
        self.assertEqual(applied.returncode, 0, applied.stderr.decode(errors="replace"))
        self.assertEqual((review / "ž space.txt").read_text(encoding="utf-8"), "after without newline")
        self.assertFalse((review / "remove.txt").exists())
        self.assertEqual((self.project / "index.html").read_text(), "old content\n")

    def test_binary_manifest_has_exact_added_deleted_and_changed_content(self):
        (self.project / "old.bin").write_bytes(b"\x00old")
        (self.project / "changed.bin").write_bytes(b"\x00before")
        workspace = self.workspace()
        (workspace.source / "old.bin").unlink()
        workspace.write_file("source/vojtamaur-web/changed.bin", b"\x00after")
        workspace.write_file("source/vojtamaur-web/new.bin", b"\x00new")
        workspace.write_file("source/vojtamaur-web/.env", "do not export")
        result = export_patch(self.snapshot, workspace.source, self.base / "patch")
        manifest = json.loads(Path(result["binary_manifest"]).read_text(encoding="utf-8"))
        records = {record["path"]: record for record in manifest["files"]}
        self.assertEqual(records["new.bin"]["operation"], "added")
        self.assertEqual(records["old.bin"]["operation"], "deleted")
        self.assertEqual((self.base / "patch" / records["old.bin"]["before_artifact"]).read_bytes(), b"\x00old")
        self.assertEqual((self.base / "patch" / records["changed.bin"]["after_artifact"]).read_bytes(), b"\x00after")
        self.assertFalse(any(item["path"] == ".env" for item in result["files"]))
        self.assertTrue(any(item["path"] == ".env" for item in result["skipped"]))

    def test_export_cannot_write_inside_snapshot_or_source(self):
        workspace = self.workspace()
        with self.assertRaises(SecurityError):
            export_patch(self.snapshot, workspace.source, workspace.source / "patch")
        with self.assertRaises(SecurityError):
            export_patch(self.snapshot, workspace.source, self.snapshot / "patch")


class DockerTests(WorkspaceFixture, unittest.TestCase):
    def test_docker_has_only_workspace_mount_and_no_host_secrets(self):
        workspace = self.workspace()
        executor = DockerExecutor(timeout_seconds=3)
        calls = []

        def fake_call(argv, environment, timeout):
            calls.append((argv, environment, timeout))
            output = "linux\n" if "info" in argv else json.dumps({"Running": False, "ExitCode": 0}) if "{{json .State}}" in argv else ""
            return {"returncode": 0, "output": output, "timed_out": False, "output_truncated": False}

        with patch.object(executor, "_call", side_effect=fake_call), patch.dict(os.environ, {"OPENAI_API_KEY": "secret", "DOCKER_HOST": "tcp://bad", "MY_SECRET": "private"}):
            result = executor.run(workspace.root, ["python", "-c", "print('ok')"])
        self.assertEqual(result["status"], "COMPLETED")
        self.assertTrue(result["cleanup_ok"])
        created = next(args for args, _, _ in calls if "create" in args)
        self.assertEqual(created.count("--mount"), 1)
        self.assertIn(f"type=bind,src={workspace.root},dst=/workspace", created)
        self.assertNotIn(str(self.project), " ".join(created))
        self.assertNotIn(str(self.snapshot), " ".join(created))
        for option in ("--pull=never", "--read-only", "--cap-drop", "--security-opt", "--pids-limit", "--memory", "--cpus"):
            self.assertIn(option, created)
        self.assertEqual(created[created.index("--network") + 1], "none")
        self.assertEqual(created[created.index("--entrypoint") + 1], "/usr/bin/timeout")
        self.assertEqual(created[-7:], ["--signal=TERM", "--kill-after=5", "--", "3s", "python", "-c", "print('ok')"])
        for _, environment, _ in calls:
            self.assertNotIn("OPENAI_API_KEY", environment)
            self.assertNotIn("DOCKER_HOST", environment)
            self.assertNotIn("MY_SECRET", environment)
        self.assertTrue(any("kill" in args for args, _, _ in calls))
        self.assertTrue(any("rm" in args and "--force" in args for args, _, _ in calls))

    def test_timeout_kills_and_removes_named_container(self):
        workspace = self.workspace()
        executor = DockerExecutor(timeout_seconds=1)
        calls = []

        def fake_call(argv, environment, timeout):
            calls.append(argv)
            attached = "start" in argv
            return {"returncode": -1 if attached else 0, "output": "linux" if "info" in argv else "", "timed_out": attached, "output_truncated": False}

        with patch.object(executor, "_call", side_effect=fake_call):
            result = executor.run(workspace.root, ["sleep", "30"])
        self.assertEqual(result["status"], "LIMIT_REACHED")
        self.assertTrue(result["cleanup_ok"])
        self.assertIn(["docker", "kill", result["container"]], calls)
        self.assertIn(["docker", "rm", "--force", result["container"]], calls)

    def test_attach_client_failure_still_cleans_container(self):
        workspace = self.workspace()
        executor = DockerExecutor()
        calls = []

        def fake_call(argv, environment, timeout):
            calls.append(argv)
            if "start" in argv:
                raise OSError("attach client disappeared")
            return {"returncode": 0, "output": "linux" if "info" in argv else "", "timed_out": False, "output_truncated": False}

        with patch.object(executor, "_call", side_effect=fake_call):
            result = executor.run(workspace.root, ["true"])
        self.assertEqual(result["status"], "BLOCKED")
        self.assertTrue(result["cleanup_ok"])
        self.assertTrue(any("kill" in args for args in calls))

    def test_docker_rejects_ordinary_project_directory(self):
        with self.assertRaises((SecurityError, FileNotFoundError)):
            DockerExecutor().run(self.project, ["true"])

    def test_independent_watchdog_exit_is_limit_reached(self):
        workspace = self.workspace()
        executor = DockerExecutor(timeout_seconds=3)

        def fake_call(argv, environment, timeout):
            output = "linux" if "info" in argv else json.dumps({"Running": False, "ExitCode": 124}) if "{{json .State}}" in argv else ""
            return {"returncode": 0, "output": output, "timed_out": False, "output_truncated": False}

        with patch.object(executor, "_call", side_effect=fake_call):
            result = executor.run(workspace.root, ["sleep", "30"])
        self.assertEqual(result["status"], "LIMIT_REACHED")
        self.assertEqual(result["returncode"], 124)
        self.assertTrue(result["timed_out"])
        self.assertTrue(result["cleanup_ok"])

    def test_output_collection_is_bounded(self):
        executor = DockerExecutor()
        executor.output_limit = 1000
        result = executor._call([sys.executable, "-c", "print('x'*1000000)"], dict(os.environ), 5)
        self.assertEqual(result["returncode"], 0)
        self.assertEqual(len(result["output"]), 1000)
        self.assertTrue(result["output_truncated"])


if __name__ == "__main__":
    unittest.main()
