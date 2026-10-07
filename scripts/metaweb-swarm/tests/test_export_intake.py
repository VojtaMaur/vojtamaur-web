import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from metaweb_swarm.export_intake import intake_exports
from metaweb_swarm.workspace import SecurityError, SnapshotLimitError


class ExportIntakeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.project = self.base / "project"
        self.project.mkdir()
        self.exports = self.project / "exports"
        self.exports.mkdir()
        self.run = self.base / "run"
        self.run.mkdir()

    def tearDown(self):
        self.temp.cleanup()

    def test_only_allowlisted_public_payloads_are_copied_and_hashed(self):
        names = ["web.zip", "book.epub", "book.pdf", "ALL_POSTS.txt", "web.manifest.json"]
        for name in names:
            (self.exports / name).write_bytes(b"public bytes " + name.encode())
        (self.exports / "credentials.json").write_text("private", encoding="utf-8")
        (self.exports / "irrelevant.7z").write_bytes(b"backup")
        (self.exports / "not-a-manifest.json").write_bytes(b"private")
        original = {name: (self.exports / name).read_bytes() for name in names}
        result = intake_exports(self.project, self.run)
        self.assertEqual({item["path"] for item in result["files"]}, set(names))
        self.assertEqual(result["total_bytes"], sum(map(len, original.values())))
        for item in result["files"]:
            copied = self.run / "input_exports" / item["path"]
            self.assertEqual(copied.read_bytes(), original[item["path"]])
            self.assertEqual(item["sha256"], hashlib.sha256(copied.read_bytes()).hexdigest())
            self.assertNotEqual(copied.stat().st_ino, (self.exports / item["path"]).stat().st_ino)
        self.assertEqual(json.loads((self.run / "input_exports/manifest.json").read_text(encoding="utf-8")), result)
        self.assertTrue(all((self.exports / name).read_bytes() == data for name, data in original.items()))

    def test_explicit_selection_is_relative_and_not_recursive(self):
        (self.exports / "nested").mkdir()
        (self.exports / "nested/book.pdf").write_bytes(b"PDF")
        (self.exports / "book.epub").write_bytes(b"EPUB")
        result = intake_exports(self.project, self.run, ["nested/book.pdf"])
        self.assertEqual([item["path"] for item in result["files"]], ["nested/book.pdf"])
        self.assertFalse((self.run / "input_exports/book.epub").exists())
        for selection in (["../secret.txt"], ["C:\\secret.txt"], ["credentials.json"]):
            other_run = self.base / ("run-" + str(len(list(self.base.iterdir()))))
            other_run.mkdir()
            with self.assertRaises(ValueError):
                intake_exports(self.project, other_run, selection)
            self.assertFalse((other_run / "input_exports").exists())

    def test_size_limits_abort_without_partial_intake_or_source_mutation(self):
        source = self.exports / "too-big.pdf"
        source.write_bytes(b"a" * 20)
        for limits in ({"max_file_bytes": 10}, {"max_total_bytes": 10}):
            with self.assertRaises(SnapshotLimitError):
                intake_exports(self.project, self.run, **limits)
            self.assertFalse((self.run / "input_exports").exists())
            self.assertFalse(list(self.run.glob(".swarm-exports-*")))
            self.assertEqual(source.read_bytes(), b"a" * 20)

    def test_resume_never_overwrites_original_payloads(self):
        (self.exports / "book.pdf").write_bytes(b"original")
        intake_exports(self.project, self.run)
        (self.exports / "book.pdf").write_bytes(b"later")
        with self.assertRaises(FileExistsError):
            intake_exports(self.project, self.run)
        self.assertEqual((self.run / "input_exports/book.pdf").read_bytes(), b"original")

    def test_text_credentials_rejected_but_opaque_owner_zip_is_not_extracted(self):
        secret = b"sk-" + b"a" * 30
        (self.exports / "accidental.txt").write_bytes(secret)
        with self.assertRaisesRegex(SecurityError, "Potential credential") as raised:
            intake_exports(self.project, self.run)
        self.assertNotIn(secret.decode(), str(raised.exception))
        self.assertFalse((self.run / "input_exports").exists())
        (self.exports / "owner.zip").write_bytes(secret)
        result = intake_exports(self.project, self.run, ["owner.zip"])
        self.assertEqual(result["files"][0]["credential_screening"], "opaque_owner_public_export")
        self.assertIn("opaque", result["scope"])

    def test_missing_exports_retains_empty_manifest_and_rejects_explicit_selection(self):
        self.exports.rmdir()
        result = intake_exports(self.project, self.run)
        self.assertFalse(result["files"])
        self.assertIn("missing", result["skipped"][0]["reason"])
        other = self.base / "other"
        other.mkdir()
        with self.assertRaises(FileNotFoundError):
            intake_exports(self.project, other, ["book.pdf"])

    def test_production_and_export_intake_cannot_overlap(self):
        inside = self.project / "run"
        inside.mkdir()
        with self.assertRaises(SecurityError):
            intake_exports(self.project, inside)
        self.assertFalse((inside / "input_exports").exists())

    @unittest.skipUnless(os.name == "nt", "Windows junction test")
    def test_junction_export_root_and_explicit_nested_path_are_refused(self):
        outside = self.base / "outside"
        outside.mkdir()
        (outside / "secret.pdf").write_bytes(b"private")
        link = self.exports / "junction"
        created = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(outside)], capture_output=True)
        if created.returncode:
            self.skipTest("Junction unavailable")
        try:
            result = intake_exports(self.project, self.run)
            self.assertFalse(result["files"])
            self.assertEqual(result["skipped"][0]["reason"], "symlink or reparse point")
            other = self.base / "other"
            other.mkdir()
            with self.assertRaises(SecurityError):
                intake_exports(self.project, other, ["junction/secret.pdf"])
            self.assertEqual((outside / "secret.pdf").read_bytes(), b"private")
        finally:
            link.rmdir()

