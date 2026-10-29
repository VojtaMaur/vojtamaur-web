"""Language selection follows article metadata, including the TXT fallback."""
import json
from pathlib import Path
import tempfile
import unittest

from content import build_catalog
from generate import arguments


class ContentLanguageTests(unittest.TestCase):
    def setUp(self):
        from PIL import Image
        self.temporary = tempfile.TemporaryDirectory(prefix="meme-language-")
        self.root = Path(self.temporary.name)
        (self.root / "dist").mkdir()
        (self.root / "public/images").mkdir(parents=True)
        Image.new("RGB", (32, 32), "white").save(self.root / "public/images/example.png")
        self.articles = [
            {"inLanguage": "en", "url": "https://example.test/en/example/",
             "headline": "English title only", "vm:articleHtml": "<h2>English heading only</h2><p>English paragraph only.</p>"},
            {"inLanguage": "cs", "url": "https://example.test/example/",
             "headline": "Výhradně český titulek", "vm:articleHtml": "<h2>Výhradně český nadpis</h2><p>Výhradně český odstavec.</p>"},
        ]
        self.write_json(self.articles)

    def write_json(self, articles):
        (self.root / "dist/ALL_POSTS.json").write_text(json.dumps({"hasPart": articles}), encoding="utf-8")

    def tearDown(self):
        self.temporary.cleanup()

    def test_default_en_and_explicit_cs_or_both(self):
        for language, selected in (("en", {"en"}), ("cs", {"cs"}), ("en+cs", {"en", "cs"})):
            catalog = build_catalog(self.root, language=language)
            self.assertEqual({record["language"] for record in catalog["texts"]}, selected)
            self.assertEqual(len(catalog["texts"]), 3 * len(selected))
        self.assertEqual(build_catalog(self.root)["language"], "en")
        self.assertEqual(arguments([]).language, "en")
        self.assertEqual(arguments(["--language", "EN+CS"]).language, "en+cs")
        self.assertEqual(arguments(["--lang", "CS"]).language, "cs")

    def test_txt_language_headers_are_read_before_titles_and_body(self):
        (self.root / "dist/ALL_POSTS.json").unlink()
        text = "Global export notes must never become a caption.\n"
        for article in self.articles:
            text += ("=" * 60 + "\nTITLE: " + article["headline"] + "\nURL: " + article["url"]
                     + "\nLANGUAGE: " + article["inLanguage"] + "\n" + "=" * 60
                     + "\n" + ("English body only." if article["inLanguage"] == "en" else "Výhradně české tělo.") + "\n")
        (self.root / "dist/ALL_POSTS.txt").write_text(text, encoding="utf-8")
        for language in ("en", "cs"):
            catalog = build_catalog(self.root, language=language)
            self.assertEqual({record["language"] for record in catalog["texts"]}, {language})
            self.assertEqual(len(catalog["texts"]), 2)
            self.assertTrue(all("Global" not in record["text"] for record in catalog["texts"]))
            self.assertEqual(next(r["text"] for r in catalog["texts"] if r["kind"] == "title"),
                             self.articles[0 if language == "en" else 1]["headline"])

    def test_missing_or_unlabelled_language_does_not_fall_back_to_other_languages(self):
        self.write_json(self.articles[1:])
        with self.assertRaisesRegex(ValueError, "language en"):
            build_catalog(self.root)
        with self.assertRaisesRegex(ValueError, "language en"):
            build_catalog(self.root, language="en+cs")
        self.articles[0].pop("inLanguage")
        self.write_json(self.articles)
        with self.assertRaisesRegex(ValueError, "language en"):
            build_catalog(self.root)

    def test_english_captions_exclude_protected_original_and_explicit_foreign_blocks(self):
        self.articles[0]["vm:articleHtml"] += (
            '<span translate="no"><p>Netraňslatovaná česká báseň.</p></span>'
            '<div class="notranslate"><p>Další původní český text.</p></div>'
            '<section lang="cs"><p>Explicitně český odstavec.</p></section>'
            '<p>An English paragraph after the protected blocks.</p>')
        self.write_json(self.articles)
        texts = [record["text"] for record in build_catalog(self.root)["texts"]]
        self.assertIn("An English paragraph after the protected blocks.", texts)
        self.assertFalse(any("česk" in text for text in texts))
        # Suppressing all HTML paragraphs must not bring them back via articleBody.
        self.articles[0]["vm:articleHtml"] = '<div translate="no"><p>Výhradně české tělo.</p></div>'
        self.articles[0]["articleBody"] = "Výhradně české tělo."
        self.write_json(self.articles)
        self.assertEqual([record["kind"] for record in build_catalog(self.root)["texts"]], ["title"])


if __name__ == "__main__":
    unittest.main()
