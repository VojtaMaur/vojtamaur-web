"""Integration checks for real PNG/RaptorQ editions; no web build is invoked.

Run after installing requirements and building/providing the shipped WASM codec:
python -B -m unittest discover -s scripts/meme-archive -p test_workflow.py -v
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import random
import shutil
import subprocess
import sys
import tempfile
import unittest


HERE = Path(__file__).resolve().parent


class WorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PIL import Image  # noqa: F401
        import segno  # noqa: F401
        import zxingcpp  # noqa: F401
        from render import find_font
        cls.font_source = Path(find_font())
        cls.naming_source = HERE.parent / "export_naming.py"
        if not cls.naming_source.is_file() and os.environ.get("MEME_TEST_PROJECT_ROOT"):
            cls.naming_source = Path(os.environ["MEME_TEST_PROJECT_ROOT"]) / "scripts" / "export_naming.py"
        if not cls.naming_source.is_file():
            raise RuntimeError("Cannot find export_naming.py; set MEME_TEST_PROJECT_ROOT for a staged checkout.")

    def setUp(self):
        from PIL import Image, ImageDraw
        self.temporary = tempfile.TemporaryDirectory(prefix="meme-archive-test-")
        self.root = Path(self.temporary.name)
        for directory in ("dist", "scripts", "public/images", "exports"):
            (self.root / directory).mkdir(parents=True, exist_ok=True)
        shutil.copy2(self.naming_source, self.root / "scripts" / "export_naming.py")
        self.font = self.root / "font.ttf"
        shutil.copy2(self.font_source, self.font)
        rng = random.Random(27)
        self.raw = ("ALL_POSTS / Příliš žluťoučký kůň\r\n" + "".join(rng.choice(
            "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 ") for _ in range(640))).encode("utf-8")
        (self.root / "dist" / "ALL_POSTS.txt").write_bytes(self.raw)
        (self.root / "dist" / "ALL_POSTS.json").write_text(json.dumps({"hasPart": [
            {"url": "https://example.test/one/", "inLanguage": "cs", "headline": "Příliš žluťoučký kůň", "articleBody": "První věta patří k jinému obrázku. Druhá věta zkouší české háčky."},
            {"url": "https://example.test/two/", "inLanguage": "cs", "headline": "Náhodný úvod a nezávislý závěr", "articleBody": "Nadpis nemusí souviset s fotografií. Archiv se obnoví z kódů."},
            {"url": "https://example.test/en/one/", "inLanguage": "en", "headline": "A very independent introduction", "articleBody": "The caption belongs to another picture. The archive can be recovered from codes."},
            {"url": "https://example.test/en/two/", "inLanguage": "en", "headline": "The independent conclusion", "articleBody": "Collect enough memes to recover the archive. Chance selects the next caption."},
        ]}, ensure_ascii=False), encoding="utf-8")
        for name, color in (("picture.png", "#457789"), ("kurt-godel-rat.jpg", "#a65968")):
            image = Image.new("RGB", (360, 240), color)
            draw = ImageDraw.Draw(image)
            draw.ellipse((90, 30, 280, 220), fill="#dfbe72")
            draw.rectangle((10, 180, 350, 220), fill="#293242")
            image.save(self.root / "public" / "images" / name)
        self.environment = dict(os.environ, PYTHONIOENCODING="utf-8")
        self.environment.pop("VOJTAMAUR_EXPORT_TIMESTAMP", None)

    def tearDown(self):
        self.temporary.cleanup()

    def run_generate(self, *arguments, expected=0):
        result = subprocess.run([sys.executable, "-B", str(HERE / "generate.py"),
                                 "--project-root", str(self.root), *map(str, arguments)],
                                capture_output=True, text=True, encoding="utf-8", env=self.environment, timeout=90)
        self.assertEqual(result.returncode, expected, result.stdout + "\n" + result.stderr)
        return result

    def new(self, stamp="000001", count=2, seed="repeatable", extra=()):
        arguments = ["--timestamp", f"2026-10-29_10-00-00-{stamp}", "--seed", seed,
                     "--font", self.font, "--symbol-size", "64", "--width", "512",
                     "--image-height", "320", "--max-text-chars", "60", "--verify-qr"]
        if count is not None:
            arguments.extend(("--count", str(count)))
        self.run_generate(*arguments, *extra)
        return self.root / "exports" / f"vojtamaur-web-export-meme-archive-2026-10-29_10-00-00-{stamp}"

    def run_decode(self, inputs, output, expected=0, extra=()):
        result = subprocess.run([sys.executable, "-B", str(HERE / "decode.py"),
                                 *map(str, inputs), "--output", str(output), *map(str, extra)],
                                capture_output=True, text=True, encoding="utf-8", env=self.environment, timeout=90)
        self.assertEqual(result.returncode, expected, result.stdout + "\n" + result.stderr)
        return result

    @staticmethod
    def hashes(folder):
        return [hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted((folder / "memes").glob("*.png"))]

    def test_reproducible_editions_and_resume_match_uninterrupted_pngs(self):
        first = self.new(count=2)
        before = self.hashes(first)
        self.run_generate("--resume", first, "--count", "2", "--verify-qr")
        second = self.new(stamp="000002", count=4)
        self.assertEqual(self.hashes(first)[:2], before)
        self.assertEqual(self.hashes(first), self.hashes(second))
        a = json.loads((first / "manifest.json").read_text())
        b = json.loads((second / "manifest.json").read_text())
        self.assertEqual(a["edition"], b["edition"])
        self.assertEqual((first / "memes.jsonl").read_bytes(), (second / "memes.jsonl").read_bytes())
        self.assertEqual((self.root / "dist" / "ALL_POSTS.txt").read_bytes(), self.raw)

    def test_interrupted_tail_and_orphan_png_regenerate_exactly(self):
        first = self.new(count=2)
        reference = self.new(stamp="000002", count=3)
        with (first / "memes.jsonl").open("ab") as stream:
            stream.write(b'{"index":2,"file":')
        (first / "memes" / "00000003.png").write_bytes(b"interrupted raster")
        self.run_generate("--resume", first, "--count", "1", "--verify-qr")
        self.assertEqual(self.hashes(first), self.hashes(reference))
        self.assertTrue((first / "memes.interrupted.jsonl").is_file())
        records = [json.loads(line) for line in (first / "memes.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual([record["index"] for record in records], [0, 1, 2])

    def test_changed_selected_image_rejects_resume(self):
        from content import choose_meme
        first = self.new(count=2)
        manifest = json.loads((first / "manifest.json").read_text(encoding="utf-8"))
        catalog = json.loads((first / "catalog.json").read_text(encoding="utf-8"))
        choice = choose_meme(catalog, manifest["recipe"]["seed"], 2, manifest["recipe"]["rat_weight"])
        image = self.root / choice["image"]["path"]
        image.write_bytes(image.read_bytes() + b"changed")
        result = self.run_generate("--resume", first, "--count", "1", expected=1)
        self.assertIn("Source image changed", result.stderr)
        self.assertEqual(len(self.hashes(first)), 2)

    def test_changed_font_committed_png_and_duplicate_lock_reject(self):
        from generate import edition_lock
        first = self.new(count=1)
        with edition_lock(first):
            result = self.run_generate("--resume", first, "--count", "1", expected=1)
        self.assertIn("another process", result.stderr)
        original_font = self.font.read_bytes()
        self.font.write_bytes(original_font + b"modified font bytes")
        result = self.run_generate("--resume", first, "--count", "1", expected=1)
        self.assertIn("same font bytes", result.stderr)
        self.font.write_bytes(original_font)
        png = first / "memes" / "00000001.png"
        png.write_bytes(png.read_bytes() + b"modified raster bytes")
        result = self.run_generate("--resume", first, "--count", "1", expected=1)
        self.assertIn("Committed meme missing or changed", result.stderr)

    def test_existing_edition_is_not_replaced(self):
        first = self.new(count=1)
        before = self.hashes(first)
        self.run_generate("--timestamp", "2026-10-29_10-00-00-000001", "--count", "1", expected=1)
        self.assertEqual(self.hashes(first), before)

    def test_language_choices_filter_captions_and_localize_the_footer(self):
        from render import FOUNTAIN_COPY
        for position, language in enumerate((None, "EN", "CS", "EN+CS"), 21):
            with self.subTest(language=language):
                folder = self.new(stamp=f"{position:06d}", count=3,
                                  extra=() if language is None else ("--language", language))
                expected = (language or "en").lower()
                manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
                self.assertEqual(manifest["recipe"]["settings"]["language"], expected)
                self.assertEqual(manifest["input_sha256"], hashlib.sha256(self.raw).hexdigest())
                catalog = json.loads((folder / "catalog.json").read_text(encoding="utf-8"))
                selected = {"en", "cs"} if expected == "en+cs" else {expected}
                self.assertEqual({record["language"] for record in catalog["texts"]}, selected)
                for line in (folder / "memes.jsonl").read_text(encoding="utf-8").splitlines():
                    record = json.loads(line)
                    for key in ("top", "bottom"):
                        if record["choice"][key]:
                            self.assertIn(record["choice"][key]["language"], selected)
                    render = record["render"]
                    self.assertTrue(record["qr_verified"])
                    self.assertEqual(render["footer_language"], expected)
                    for lang in selected:
                        self.assertIn(FOUNTAIN_COPY[lang].splitlines()[0], render["footer_explanation"])
                    self.assertIn(f"minimum {sum(manifest['source_counts'])}", render["footer_explanation"])
                    self.assertLessEqual(render["footer_text_box"][3], render["height"] - 16)
        self.run_generate("--resume", folder, "--language", "CS", "--count", "1", expected=2)

    def test_narrow_bilingual_footer_stays_readable_below_qr(self):
        folder = self.new(stamp="000025", count=1,
                          extra=("--language", "EN+CS", "--symbol-size", "512"))
        record = json.loads((folder / "memes.jsonl").read_text(encoding="utf-8"))
        geometry = record["render"]
        self.assertTrue(record["qr_verified"])
        self.assertGreater(geometry["footer_text_box"][1], geometry["qr_box"][3])
        self.assertLess(geometry["footer_text_box"][3], geometry["height"])

    def test_reconstruction_estimate_changes_with_symbol_size_and_archive_bytes(self):
        minima = []
        for stamp, symbol_size in (("000031", 64), ("000032", 128), ("000033", 128)):
            if stamp == "000033":
                rng = random.Random(6330)
                raw = "".join(rng.choice("abcdefghijklmnopqrstuvwxyz0123456789 ") for _ in range(6000))
                (self.root / "dist/ALL_POSTS.txt").write_text(raw, encoding="utf-8")
            folder = self.new(stamp=stamp, count=1, extra=("--symbol-size", str(symbol_size)))
            manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
            record = json.loads((folder / "memes.jsonl").read_text(encoding="utf-8"))
            minimum = ((folder / "archive.rq").stat().st_size + symbol_size - 1) // symbol_size
            self.assertEqual(minimum, sum(manifest["source_counts"]))
            self.assertEqual(record["render"]["footer_recovery"]["minimum"], minimum)
            self.assertEqual(record["render"]["footer_recovery"]["recommended"], minimum + 2 * manifest["block_count"])
            self.assertIn(f"minimum {minimum}", record["render"]["footer_explanation"])
            self.assertIn(f"~{minimum + 2 * manifest['block_count']}+", record["render"]["footer_explanation"])
            self.assertTrue(record["qr_verified"])
            minima.append(minimum)
        self.assertEqual(len(set(minima)), 3)

    def test_default_real_repair_only_reconstruction_and_mixed_editions(self):
        first = self.new(count=None)
        manifest = json.loads((first / "manifest.json").read_text(encoding="utf-8"))
        source_count = sum(manifest["source_counts"])
        images = sorted((first / "memes").glob("*.png"))
        self.assertGreater(len(images), source_count)
        # Discard every systematic/source symbol. Decode only repair QR pixels,
        # relocated away from archive.rq, manifests and all other edition files.
        received = self.root / "received-repairs"
        received.mkdir()
        for path in images[source_count:]:
            shutil.copy2(path, received / path.name)
        recovered = self.root / "exports" / "from-repairs.txt"
        self.run_decode([received], recovered)
        self.assertEqual(recovered.read_bytes(), self.raw)
        refused = self.root / "exports" / "incomplete.txt"
        self.run_decode([images[0]], refused, expected=2)
        self.assertFalse(refused.exists())
        second = self.new(stamp="000002", count=1, seed="another-edition")
        mixed = [*images, second / "memes" / "00000001.png"]
        result = self.run_decode(mixed, self.root / "exports" / "mixed.txt", expected=1)
        self.assertIn("Mixed editions", result.stderr)
        self.assertFalse((self.root / "exports" / "mixed.txt").exists())
        selected = self.root / "exports" / "selected.txt"
        self.run_decode(mixed, selected, extra=("--edition", manifest["edition"]))
        self.assertEqual(selected.read_bytes(), self.raw)
        self.run_decode([received], recovered, expected=1)
        self.assertEqual(recovered.read_bytes(), self.raw)


if __name__ == "__main__":
    unittest.main()
