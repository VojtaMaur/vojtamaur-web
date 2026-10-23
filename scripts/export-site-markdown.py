#!/usr/bin/env python3
"""Manually export the built JSON-LD article archive as one readable Markdown file.

Uses rendered HTML from the snapshot, never raw MDX or the truncated TXT body.
Media become ordinary public links; no build, translation or network access.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from urllib.parse import quote, unquote, urljoin, urlsplit, urlunsplit

from export_naming import add_arguments, stamped_path, timestamp_for

ROOT = Path(__file__).resolve().parent.parent
SITE = "https://vojtamaur.cz/"
SECTION_LABELS = {
    "cs": {"volna-tvorba": "Volná tvorba", "vystavy": "Výstavy", "cestovani": "Cestování"},
    "en": {"volna-tvorba": "Personal Work", "vystavy": "Exhibitions", "cestovani": "Travel"},
}
SKIP = {"script", "style", "noscript", "template", "nav", "button"}
BLOCK = {"div", "section", "article", "main", "header", "footer", "p", "figure", "figcaption", "address"}


def load_filter_module():
    name = "vojtamaur_markdown_filters"
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name("filter-all-posts.py"))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def inline_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def escape_text(value: str) -> str:
    value = value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    value = re.sub(r"([\\`*_[\]!#~])", r"\\\1", value)
    value = re.sub(r"^(\s*\d+)([.)])(?=\s)", r"\1\\\2", value)
    return re.sub(r"^(\s*[+-])(?=\s)", r"\\\1", value)


def link(label: str, url: str) -> str:
    # Parentheses, whitespace and angle brackets must not terminate a Markdown link.
    destination = quote(url, safe=":/?#@!$&'*+,;=%~.-_")
    return f"[{label} unlinked]" if not url else f"[{label}]({destination})"


def anchor(article: dict) -> str:
    key = f"{article['inLanguage']}-{article['vm:slug']}"
    if re.fullmatch(r"[a-zA-Z0-9_-]+", key):
        return "post-" + key
    # Keep unusual/nested slugs distinct without relying on a viewer's slugger.
    readable = re.sub(r"[^a-zA-Z0-9_-]", "-", key)
    return f"post-{readable}-{hashlib.sha256(key.encode('utf-8')).hexdigest()[:12]}"


class MarkdownRenderer:
    def __init__(self, article: dict, routes: dict[str, str]):
        self.article = article
        self.routes = routes
        self.base = urljoin(SITE, article["vm:builtHtmlPath"])
        self.protected: list[str] = []

    def protect(self, text: str) -> str:
        self.protected.append(text)
        return f"\x00MD{len(self.protected) - 1}\x00"

    def restore(self, text: str) -> str:
        while re.search(r"\x00MD(\d+)\x00", text):
            text = re.sub(r"\x00MD(\d+)\x00", lambda m: self.protected[int(m[1])], text)
        return text

    def url(self, raw: str | None) -> str:
        if not raw or not raw.strip():
            return ""
        url = urlsplit(urljoin(self.base, raw.strip()))
        if url.scheme.lower() not in {"http", "https", "mailto", "tel", "gemini", "gopher", "ftp", "ipfs", "ipns"}:
            return ""
        if url.netloc == urlsplit(SITE).netloc and url.path in self.routes:
            canonical = urlsplit(self.routes[url.path])
            url = url._replace(path=canonical.path)
        return urlunsplit(url)

    def children(self, node) -> str:
        return "".join(self.render(child) for child in node.children)

    def clean(self, text: str) -> str:
        # Code has been replaced by tokens, so prose cleanup cannot alter it.
        text = re.sub(r"[ \t]+\n", "\n", text)
        text = re.sub(r"\n[ \t]+(?=\n)", "\n", text)
        return re.sub(r"\n{3,}", "\n\n", text).strip()

    def image(self, node) -> str:
        url = self.url(node.get("src"))
        filename = unquote(urlsplit(url).path.rsplit("/", 1)[-1]) if url else ""
        alt = inline_text(node.get("alt", ""))
        label = "Image: " + (alt or filename or "source unavailable")
        if alt and filename and filename != alt:
            label += f" ({filename})"
        return link(escape_text(label), url)

    def media(self, node) -> str:
        sources = [node.get("src") or node.get("data")]
        sources += [item.get("src") for item in node.find_all("source")]
        urls = list(dict.fromkeys(url for raw in sources if (url := self.url(raw))))
        references = []
        for url in urls:
            kind = "PDF" if urlsplit(url).path.lower().endswith(".pdf") else (
                "Audio" if node.name == "audio" else "Video" if node.name == "video" or
                re.search(r"(?:youtube(?:-nocookie)?\.com|youtu\.be|vimeo\.com)$", urlsplit(url).hostname or "")
                else "Embedded content"
            )
            title = inline_text(node.get("title", ""))
            name = unquote(urlsplit(url).path.rsplit("/", 1)[-1])
            references.append(link(escape_text(f"{kind}: {title or name or url}"), url))
        if not references:
            references.append(link("Embedded content: view original article", self.article["url"]))
        return "\n\n" + "\n\n".join(references) + "\n\n"

    def table(self, node) -> str:
        rows = []
        for row in node.find_all("tr"):
            if row.find_parent("table") is not node:
                continue
            cells = []
            for cell in row.find_all(["td", "th"], recursive=False):
                text = self.restore(self.clean(self.children(cell)))
                text = text.replace("|", "\\|").replace("\n", "<br>")
                cells.append(text)
            if cells:
                rows.append((row, cells))
        if not rows:
            return ""
        # Complex merged/nested tables are linearized explicitly instead of
        # inventing a rectangular association between headings and cells.
        if node.select("[rowspan], [colspan], table"):
            content = "\n".join(f"- {' / '.join(cells)}" for _, cells in rows)
        else:
            width = max(len(cells) for _, cells in rows)
            header = rows[0][1] if rows[0][0].find("th") else [f"Column {i + 1}" for i in range(width)]
            body = rows[1:] if rows[0][0].find("th") else rows
            def line(cells):
                return "| " + " | ".join(cells + [""] * (width - len(cells))) + " |"
            content = "\n".join([line(header), line(["---"] * width)] + [line(cells) for _, cells in body])
        caption = node.find("caption", recursive=False)
        if caption:
            content = self.clean(self.children(caption)) + "\n\n" + content
        return "\n\n" + self.protect(content) + "\n\n"

    def render(self, node) -> str:
        from bs4 import Comment, NavigableString
        if isinstance(node, Comment):
            return ""
        if isinstance(node, NavigableString):
            return escape_text(re.sub(r"\s+", " ", str(node)))
        tag = node.name
        if tag in SKIP or node.has_attr("hidden") or node.get("aria-hidden", "").lower() == "true":
            return ""
        if tag == "pre":
            text = node.get_text().replace("\r\n", "\n").replace("\r", "\n")
            runs = [len(m[0]) for m in re.finditer(r"`+", text)]
            fence = "`" * max(3, max(runs, default=0) + 1)
            code = node.find("code")
            classes = (code.get("class", []) if code else []) + node.get("class", [])
            language = next((c.removeprefix("language-") for c in classes if re.fullmatch(r"language-[\w+-]+", c)), "")
            block = f"{fence}{language}\n{text}{'' if text.endswith(chr(10)) else chr(10)}{fence}"
            return "\n\n" + self.protect(block) + "\n\n"
        if tag in {"code", "kbd", "samp"}:
            text = node.get_text().replace("\n", " ")
            fence = "`" * (max((len(m[0]) for m in re.finditer(r"`+", text)), default=0) + 1)
            pad = " " if text.startswith(("`", " ")) or text.endswith(("`", " ")) else ""
            return self.protect(f"{fence}{pad}{text}{pad}{fence}")
        if tag == "img":
            return self.image(node)
        if tag in {"iframe", "object", "embed", "video", "audio"}:
            return self.media(node)
        if tag in {"source", "track"}:
            return ""
        if tag in {"svg", "canvas"}:
            title = node.find(["title", "desc"])
            label = f"{tag.upper()}: {inline_text(title.get_text()) if title else 'view original article'}"
            return "\n\n" + link(escape_text(label), self.article["url"]) + "\n\n"
        if tag == "table":
            return self.table(node)
        if tag in {"ul", "ol"}:
            items = []
            start = int(node.get("start", "1")) if str(node.get("start", "1")).isdigit() else 1
            for index, item in enumerate(node.find_all("li", recursive=False), start):
                marker = f"{index}. " if tag == "ol" else "- "
                body = self.restore(self.clean(self.children(item)))
                lines = body.split("\n")
                items.append(marker + lines[0] + "".join("\n" + " " * len(marker) + line for line in lines[1:]))
            return "\n\n" + self.protect("\n".join(items)) + "\n\n"
        content = self.children(node)
        if tag == "a":
            url = self.url(node.get("href"))
            if not url:
                return content
            if node.find(["img", "video", "audio", "iframe"]):
                # ImageFigure normally links to the image itself. Avoid nested
                # Markdown links; retain a distinct full-size destination too.
                image = node.find("img")
                return content if image and self.url(image.get("src")) == url else content + " · " + link("Open link", url)
            return link(content.strip() or escape_text(url), url)
        if re.fullmatch(r"h[1-6]", tag or ""):
            level = min(6, max(3, int(tag[1]) + 1))
            return "\n\n" + "#" * level + " " + self.clean(content) + "\n\n"
        if tag in {"strong", "b", "em", "i", "del", "s"}:
            marker = "**" if tag in {"strong", "b"} else "~~" if tag in {"del", "s"} else "*"
            if not content.strip():
                return content
            leading = " " if content.startswith(" ") else ""
            trailing = " " if content.endswith(" ") else ""
            return leading + marker + content.strip() + marker + trailing
        if tag == "blockquote":
            quoted = "\n".join("> " + line for line in self.restore(self.clean(content)).split("\n"))
            return "\n\n" + self.protect(quoted) + "\n\n"
        if tag == "br":
            return self.protect("  \n")
        if tag == "hr":
            return "\n\n---\n\n"
        if tag == "summary":
            return "\n\n**" + self.clean(content) + "**\n\n"
        if tag in BLOCK or tag in {"dl", "dt", "dd", "details"}:
            return "\n\n" + self.clean(content) + "\n\n" if content.strip() else ""
        # NoTranslate and layout/span wrappers are transparent. Their text stays.
        return content

    def convert(self, html: str) -> str:
        from bs4 import BeautifulSoup
        if "\x00" in html:
            raise ValueError("Article HTML contains a reserved NUL character.")
        soup = BeautifulSoup(html, "html.parser")
        body = soup.select_one(".post-body")
        if body is None:
            raise ValueError(f"Article content container missing: {self.article['url']}")
        text = self.clean(self.children(body))
        return self.restore(text)


def atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_name = None
    try:
        with tempfile.NamedTemporaryFile(mode="wb", dir=path.parent, prefix=f".{path.name}.", delete=False) as temporary:
            temporary_name = temporary.name
            temporary.write(payload)
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_name, path)
    finally:
        if temporary_name:
            Path(temporary_name).unlink(missing_ok=True)


def serialize(document, selected, source_hash, filters, edition):
    routes = {}
    for article in document["hasPart"]:
        routes[urlsplit(article["url"]).path] = article["url"]
        routes[urlsplit(urljoin(SITE, article["vm:builtHtmlPath"])).path] = article["url"]
    parts = ["# ALL_POSTS", "Vojta Maur — article archive", "\n".join([
        f"- Articles (language versions): {len(selected)}",
        f"- Selection: {escape_text(filters)}",
        f"- Source snapshot: {escape_text(document.get('vm:sourceGeneratedAt') or document.get('vm:generatedAt', 'unknown'))}",
        f"- Source JSON SHA-256: `{source_hash}`",
    ] + ([f"- Export edition (local time): `{edition}`"] if edition else [])),
        "Images, downloads and embedded media are ordinary links; their contents are not bundled. "
        "English routes may retain protected or untranslated text. Dates preserve the source metadata, including approximate legacy dates.",
        "## Contents", "\n".join(
            f"- {link(escape_text(a['headline']), '#' + anchor(a))} — {a['inLanguage'].upper()}, {a['datePublished']}"
            for a in selected
        ) or "No articles selected."]
    for article in selected:
        title = escape_text(article["headline"])
        lang, section = article["inLanguage"], article["articleSection"]
        label = SECTION_LABELS.get(lang, {}).get(section, section)
        header = [f'<a id="{anchor(article)}"></a>', f"## {title}",
                  f"**Language:** {lang.upper()} · **Section:** {escape_text(label)} · **Date:** {article['datePublished']}",
                  link("Original article", article["url"])]
        rendered = article.get("vm:renderedMetadata", [])
        if rendered:
            header.append(" · ".join(escape_text(inline_text(value)) for value in rendered))
        if article.get("vm:languageStatus") == "incomplete-czech-fallback":
            header.append("> English translation is incomplete; this snapshot contains Czech fallback text.")
        header.append(MarkdownRenderer(article, routes).convert(article["vm:articleHtml"]))
        parts += ["---", "\n\n".join(header)]
    return "\n\n".join(parts) + "\n"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", nargs="?", type=Path, help="JSON-LD snapshot (default: dist/ALL_POSTS.json)")
    parser.add_argument("--input", dest="input_path", type=Path, help="alternative to the positional input")
    parser.add_argument("--project-root", type=Path, default=ROOT)
    parser.add_argument("-o", "--output", type=Path, help="exact .md destination under exports/; no timestamp is added")
    parser.add_argument("--language", "--lang", action="append", help="repeat or comma-separate; cs, en, both or all (default: all)")
    parser.add_argument("--section", action="append", help="repeat or comma-separate section slugs; default: all")
    parser.add_argument("--from-date", metavar="YYYY-MM-DD")
    parser.add_argument("--to-date", metavar="YYYY-MM-DD")
    parser.add_argument("--list-values", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--allow-empty", action="store_true")
    add_arguments(parser)
    args = parser.parse_args(argv)
    try:
        try:
            import bs4  # noqa: F401; same dependency as the EPUB exporters
        except ImportError as exc:
            raise ValueError("Markdown export requires Beautiful Soup: python -m pip install beautifulsoup4") from exc
        if args.input is not None and args.input_path is not None:
            raise ValueError("Choose either positional input or --input, not both.")
        root = args.project_root.resolve()
        source = (root / (args.input_path or args.input or Path("dist/ALL_POSTS.json"))).resolve()
        payload = source.read_bytes()
        raw = payload.decode("utf-8-sig")
        filters = load_filter_module()
        parsed = filters.parse_json_export(raw)
        document = json.loads(raw)
        for article in document["hasPart"]:
            for field in ("headline", "vm:builtHtmlPath", "vm:articleHtml"):
                if not isinstance(article.get(field), str) or not article[field].strip():
                    raise ValueError(f"Missing article {field}: {article.get('url')}")
            rendered = article.get("vm:renderedMetadata", [])
            if not isinstance(rendered, list) or any(not isinstance(item, str) for item in rendered):
                raise ValueError("vm:renderedMetadata must be an array of strings.")
        if args.list_values:
            filters.list_values(parsed)
            return 0
        languages = filters.split_values(args.language)
        if languages == {"both"}:
            languages = {"cs", "en"}
        sections = filters.split_values(args.section)
        for requested, field in ((languages, "LANGUAGE"), (sections, "SECTION")):
            filters.validate_requested_values(requested, filters.available_values(parsed.entries, field), field.lower())
        date_from = filters.parse_iso_date(args.from_date, "--from-date") if args.from_date else None
        date_to = filters.parse_iso_date(args.to_date, "--to-date") if args.to_date else None
        if date_from and date_to and date_from > date_to:
            raise ValueError("--from-date must not be later than --to-date.")
        entries = filters.filtered_entries(parsed.entries, languages, sections, date_from, date_to)
        if not entries and not args.allow_empty:
            raise ValueError("The filters selected no articles. Use --allow-empty for an intentional empty export.")
        by_key = {(a["inLanguage"], a["vm:slug"]): a for a in document["hasPart"]}
        selected = [by_key[(e.metadata["LANGUAGE"], e.metadata["SLUG"])] for e in entries]
        language_name = "+".join(sorted(languages)) if languages else "all"
        section_name = "+".join(sorted(sections)) if sections else "all"
        parts = ["ALL_POSTS", f"lang-{filters.safe_filename_part(language_name)}", f"section-{filters.safe_filename_part(section_name)}"]
        if date_from:
            parts.append(f"from-{date_from.isoformat()}")
        if date_to:
            parts.append(f"to-{date_to.isoformat()}")
        edition = timestamp_for(args)
        output = ((root / args.output) if args.output else stamped_path(root / "exports" / ("__".join(parts) + ".md"), edition)).resolve()
        if output == source or not output.is_relative_to((root / "exports").resolve()) or output.suffix.lower() != ".md":
            raise ValueError("Output must be a .md file under exports/ and must not overwrite the input.")
        description = f"language={language_name}; section={section_name}; from={args.from_date or 'any'}; to={args.to_date or 'any'}"
        result = serialize(document, selected, hashlib.sha256(payload).hexdigest(), description, edition)
        encoded = result.encode("utf-8")  # No BOM: # remains the first Markdown character.
        if not args.dry_run:
            atomic_write(output, encoded)
        print(f"Selected articles: {len(selected)} of {len(parsed.entries)}")
        print(f"Selection: {description}")
        print(f"Output: {output}")
        print(f"Encoding: UTF-8, LF, no BOM; {len(encoded)} bytes")
        print(f"SHA-256: {hashlib.sha256(encoded).hexdigest()}")
        if args.dry_run:
            print("Dry run: no file was written.")
        return 0
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
