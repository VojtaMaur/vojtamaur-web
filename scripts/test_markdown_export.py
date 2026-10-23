#!/usr/bin/env python3
"""Offline regression checks for the manual Markdown exporter."""
import contextlib
import copy
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
spec = importlib.util.spec_from_file_location("markdown_export", Path(__file__).with_name("export-site-markdown.py"))
exporter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(exporter)


def article(slug="example", language="cs", section="volna-tvorba", position=1):
    url = f"https://vojtamaur.cz/{'en/' if language == 'en' else ''}{slug}/"
    metadata = {"TITLE": "Source title", "SLUG": slug, "URL": url, "LANGUAGE": language,
                "SECTION": section, "DATE": "2026-04-01", "SOURCE": f"src/content/posts/{slug}.mdx"}
    return {"@type": "BlogPosting", "url": url, "headline": "Rendered title", "inLanguage": language,
            "articleSection": section, "datePublished": metadata["DATE"], "vm:slug": slug,
            "vm:position": position, "vm:sourceMetadata": metadata, "articleBody": "Full body",
            "vm:builtHtmlPath": f"{'en/' if language == 'en' else ''}{slug}/index.html",
            "vm:articleHtml": '<div class="post-body"><p>Full body</p></div>',
            "vm:renderedMetadata": ["April 2026"], "vm:languageStatus": "original"}


def document(articles=None):
    articles = articles or [article()]
    return {"@type": "Collection", "vm:articleCount": len(articles), "hasPart": articles,
            "vm:generatedAt": "2026-10-23T07:00:00Z"}


class ConversionTests(unittest.TestCase):
    def convert(self, body, record=None):
        record = record or article()
        routes = {"/example.html": "https://vojtamaur.cz/example/",
                  '/' + record['vm:builtHtmlPath']: record['url']}
        return exporter.MarkdownRenderer(record, routes).convert(
            '<div class="post-body">' + body + '</div>')

    def test_protected_text_and_wrappers(self):
        result = self.convert('<p>A <span class="notranslate" translate="no">anti_language</span> B<br>C</p>'
                              '<script>discard()</script><div aria-hidden="true">hidden</div>')
        self.assertEqual(result, 'A anti\\_language B  \nC')

    def test_images_are_links_without_nested_links(self):
        result = self.convert('<figure><a href="/images/a.jpg"><img src="/images/a.jpg" alt="A [photo]"></a>'
                              '<figcaption>Caption <em>text</em></figcaption></figure>')
        self.assertNotIn('![', result)
        self.assertEqual(result.count('https://vojtamaur.cz/images/a.jpg'), 1)
        self.assertIn('A \\[photo\\]', result)
        self.assertIn('Caption *text*', result)

    def test_image_full_size_link_and_other_files(self):
        result = self.convert('<a href="/images/full.jpg"><img src="/images/thumb.jpg"></a>'
                              '<iframe src="/files/a(b).pdf" title="Document"></iframe>'
                              '<a href="/files/archive.zip">Archive</a>')
        for reference in ('/images/full.jpg', '/images/thumb.jpg', '/files/a%28b%29.pdf', '/files/archive.zip'):
            self.assertIn('https://vojtamaur.cz' + reference, result)
        self.assertIn('[PDF: Document]', result)

    def test_flat_usb_relative_urls_and_fragments(self):
        record = article(language="en")
        record['vm:builtHtmlPath'] = 'en/example.html'
        result = self.convert('<a href="../example.html#part">Czech</a><img src="../images/a.jpg">'
                              '<a href="#details">Details</a>', record)
        self.assertIn('(https://vojtamaur.cz/example/#part)', result)
        self.assertIn('(https://vojtamaur.cz/images/a.jpg)', result)
        self.assertIn('(https://vojtamaur.cz/en/example/#details)', result)

    def test_complete_code_and_safe_fences(self):
        code = '  first\n\n' + '  value = "```"  \n' * 150 + 'last'
        result = self.convert('<pre><code class="language-python">' + code + '</code></pre>')
        self.assertEqual(result, '````python\n' + code + '\n````')

    def test_inline_code_and_literal_markup(self):
        result = self.convert('<p>&lt;NoTranslate&gt; [x] *y* <code>`a`</code></p>')
        self.assertEqual(result, '&lt;NoTranslate&gt; \\[x\\] \\*y\\* `` `a` ``')

    def test_lists_quotes_and_nested_code(self):
        result = self.convert('<ol start="3"><li><p>One</p><ul><li>Nested</li></ul>'
                              '<pre><code>  x\n\n  y</code></pre></li><li>Two</li></ol>'
                              '<blockquote><p>Quote</p><pre>x\n\ny</pre></blockquote>')
        self.assertIn('3. One\n   \n   - Nested', result)
        self.assertIn('   ```\n     x\n   \n     y\n   ```', result)
        self.assertIn('4. Two', result)
        self.assertIn('> ```\n> x\n> \n> y\n> ```', result)

    def test_tables_preserve_header_links_code_and_breaks(self):
        result = self.convert('<table><tr><th>Name</th><th>Value</th></tr><tr><td>A | B</td>'
                              '<td><a href="/files/a.pdf">PDF</a><br><code>x|y</code></td></tr></table>')
        self.assertIn('| Name | Value |\n| --- | --- |', result)
        self.assertIn('A \\| B', result)
        self.assertIn('[PDF](https://vojtamaur.cz/files/a.pdf)', result)
        self.assertIn('<br>`x\\|y`', result)

    def test_missing_body_fails_and_unsupported_media_is_explicit(self):
        with self.assertRaisesRegex(ValueError, 'container missing'):
            exporter.MarkdownRenderer(article(), {}).convert('<p>Wrong container</p>')
        result = self.convert('<canvas></canvas><iframe src="javascript:bad()"></iframe>')
        self.assertIn('[CANVAS: view original article]', result)
        self.assertIn('[Embedded content: view original article]', result)
        self.assertNotIn('javascript:', result)


class CommandTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        (self.root / 'dist').mkdir()
        # Deliberately reverse array order: vm:position remains authoritative.
        self.data = document([article('english', 'en', 'vystavy', 2), article(position=1)])
        self.source = self.root / 'dist' / 'ALL_POSTS.json'
        self.source.write_text(json.dumps(self.data), encoding='utf-8')
        self.original = self.source.read_bytes()

    def tearDown(self):
        self.temporary.cleanup()

    def run_export(self, *args):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return exporter.main(['--project-root', str(self.root), *args])

    def test_full_archive_order_toc_and_timestamp(self):
        self.assertEqual(self.run_export('--timestamp', '2026-10-23_09-00-00-123456'), 0)
        output = next((self.root / 'exports').glob('*.md'))
        self.assertEqual(output.name, 'ALL_POSTS__lang-all__section-all-2026-10-23_09-00-00-123456.md')
        payload = output.read_bytes()
        self.assertTrue(payload.startswith(b'# ALL_POSTS\n'))
        self.assertNotIn(b'\r', payload)
        result = payload.decode('utf-8')
        self.assertLess(result.index('<a id="post-cs-example">'), result.index('<a id="post-en-english">'))
        self.assertIn('](#post-cs-example)', result)
        self.assertEqual(self.source.read_bytes(), self.original)

    def test_filter_and_explicit_name(self):
        self.assertEqual(self.run_export('--lang', 'en', '--section', 'vystavy', '--from-date', '2026-04-01',
                                         '--to-date', '2026-04-01', '-o', 'exports/chosen.md'), 0)
        text = (self.root / 'exports' / 'chosen.md').read_text(encoding='utf-8')
        self.assertIn('<a id="post-en-english">', text)
        self.assertNotIn('post-cs-example', text)

    def test_invalid_filters_and_output_are_rejected(self):
        for args in [('--section', 'typo'), ('--lang', 'de'), ('--from-date', '2027-01-01'),
                     ('--from-date', '2026-12-31', '--to-date', '2026-01-01'),
                     ('--output', 'dist/ALL_POSTS.md'), ('--output', 'exports/a.txt')]:
            with self.subTest(args=args), self.assertRaises(SystemExit) as result:
                self.run_export(*args)
            self.assertEqual(result.exception.code, 2)
        self.assertFalse((self.root / 'exports').exists())

    def test_dry_run_and_lists_write_nothing(self):
        for args in [('--dry-run',), ('--list-values',), ('--lang', 'cs,en', '--dry-run'),
                     ('--lang', 'both', '--dry-run'), ('--language', 'cs', '--language', 'en', '--dry-run')]:
            self.assertEqual(self.run_export(*args), 0)
        self.assertFalse((self.root / 'exports').exists())

    def test_missing_rich_html_is_not_silently_downgraded(self):
        broken = copy.deepcopy(self.data)
        del broken['hasPart'][0]['vm:articleHtml']
        self.source.write_text(json.dumps(broken), encoding='utf-8')
        with self.assertRaises(SystemExit):
            self.run_export()
        self.assertFalse((self.root / 'exports').exists())


if __name__ == '__main__':
    unittest.main()
