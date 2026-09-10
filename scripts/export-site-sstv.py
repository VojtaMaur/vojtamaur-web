#!/usr/bin/env python3
"""Manually render finished article HTML to native SSTV PNG frames.

Run after an existing web build: npm run export:sstv
Preview: npm run export:sstv -- --slug koncepty --max-pages 10
Higher resolution: npm run export:sstv -- --mode pd290 --lang en

No build, encoder, audio, calibration image, or network access is invoked.
Each successful run creates a new directory under exports/sstv/<mode>/.
Selection comes from ALL_POSTS.txt; full text and images come from built HTML.
"""

from __future__ import annotations

import argparse
import base64
import datetime as dt
import io
import json
import os
import re
import sys
import tempfile
from functools import lru_cache
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urljoin, urlsplit, urlunsplit

from export_common import (
    find_built_article_html, normalize_site_url, parse_all_posts_index,
    resolve_path, sha256_file, sorted_built_posts,
)


VERSION = "1.0.0"
# Native dimensions independently agree in these implementations. Do not crop
# the historical extra scan lines or substitute a square image.
MODE_SOURCES = [
    "https://github.com/dnet/pySSTV/blob/master/pysstv/color.py",
    "https://github.com/n5ac/mmsstv/blob/master/EMMSSTV.TXT",
    "https://www.classicsstv.com/pdmodes.php",
]
MODES = {"pd120": (640, 496), "pd180": (640, 496),
         "pd240": (640, 496), "pd290": (800, 616)}
BLOCK_TAGS = set("article section div p h1 h2 h3 h4 h5 h6 ul ol li dl dt dd "
                 "blockquote pre figure figcaption table details summary header".split())
MEDIA_TAGS = {"img", "svg", "iframe", "video", "audio", "object", "embed", "canvas"}
SKIP_TAGS = {"script", "style", "noscript", "nav", "button", "template"}


@dataclass
class Block:
    kind: str
    text: str = ""
    source: str = ""


class PreviewComplete(Exception):
    """Stop at a whole-frame boundary, with an explicitly partial manifest."""


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--version", action="version", version=VERSION)
    parser.add_argument("--project-root", default=str(Path(__file__).resolve().parent.parent))
    parser.add_argument("--dist", default="dist", help="Existing finished build; never rebuilt.")
    parser.add_argument("--mode", type=str.lower, choices=MODES, default="pd120")
    parser.add_argument("--lang", choices=("cs", "en", "both"), default="cs")
    parser.add_argument("--section", action="append", default=[], help="Repeat or comma-separate.")
    parser.add_argument("--slug", action="append", default=[], help="Exact article slug(s), repeat or comma-separate.")
    parser.add_argument("--output-dir", help="Parent for a NEW run directory. Default: exports/sstv/<mode>.")
    parser.add_argument("--max-pages", type=int, help="Preview: stop after this many PNGs, mark export partial.")
    parser.add_argument("--font-size", type=int, help="Body size in native pixels. Default: 24 (PD290: 30).")
    parser.add_argument("--font", help="Regular TrueType/OpenType font, e.g. a local Unicode sans serif.")
    parser.add_argument("--bold-font", help="Matching bold font. With --font alone use that font for headings too.")
    parser.add_argument("--site-url", default="https://vojtamaur.cz")
    args = parser.parse_args()
    if args.max_pages is not None and args.max_pages < 1:
        parser.error("--max-pages must be positive")
    if args.font_size is not None and not 16 <= args.font_size <= 48:
        parser.error("--font-size must be between 16 and 48 native pixels")
    return args


def csv_values(values):
    return {item.strip() for value in values for item in value.split(",") if item.strip()}


def clean_text(value):
    return re.sub(r"[^\S\n]+", " ", value.replace("\r", "")).strip()


def public_url(value, page_url):
    value = value.strip()
    if not value or value.startswith(("data:", "javascript:")):
        return ""
    return urljoin(page_url, value)


def normalize_built_urls(soup, html_file, dist_dir, site_url, posts):
    """Resolve relative links against the real built file, including USB routes."""
    base = urljoin(site_url, html_file.relative_to(dist_dir).as_posix())
    routes = {"/index.html": "/", "/en.html": "/en/", "/en/index.html": "/en/"}
    for post in posts:
        path = "/" + ("en/" if post.lang == "en" else "") + post.slug.strip("/")
        routes[path + ".html"] = path + "/"
        routes[path + "/index.html"] = path + "/"
    for node in soup.find_all(True):
        for attr in ("href", "src", "data-src", "data", "poster"):
            value = node.get(attr)
            if not value:
                continue
            target = public_url(value, base)
            if not target:
                continue
            parsed = urlsplit(target)
            if parsed.netloc.lower() == urlsplit(site_url).netloc.lower():
                target = urlunsplit((parsed.scheme, parsed.netloc,
                                    routes.get(unquote(parsed.path), parsed.path),
                                    parsed.query, parsed.fragment))
            node[attr] = target


def inline_text(node, page_url):
    from bs4 import Comment, NavigableString
    if isinstance(node, Comment):
        return ""
    if isinstance(node, NavigableString):
        return re.sub(r"\s+", " ", str(node))
    if node.name in SKIP_TAGS:
        return ""
    if node.name == "br":
        return "\n"
    text = "".join(inline_text(child, page_url) for child in node.children)
    if node.name == "a":
        target = public_url(node.get("href", ""), page_url)
        if target and target.rstrip("/") != text.strip().rstrip("/"):
            text += f" [{target}]"
    return text


def extract_blocks(node, page_url):
    """Flatten layout, retaining reading order, URLs, captions and full code.

    Narrow SSTV frames cannot use web galleries or wide tables. Images get their
    own frames and table cells become labelled records, with no text truncation.
    """
    from bs4 import Comment, NavigableString
    if isinstance(node, Comment):
        return
    if isinstance(node, NavigableString):
        text = clean_text(str(node))
        if text:
            yield Block("text", text)
        return
    name = node.name
    if name in SKIP_TAGS or node.get("aria-hidden") == "true":
        return
    if name == "img":
        # Do not serialize a gallery as a thumbnail-sized web screenshot.
        yield Block("image", node.get("alt", ""), node.get("src") or node.get("data-src", ""))
        return
    if name in MEDIA_TAGS:
        source = node.get("src") or node.get("data", "")
        if not source and node.find("source"):
            source = node.find("source").get("src", "")
        label = {"iframe": "Embedded media", "svg": "Vector image", "canvas": "Interactive canvas"}.get(name, name.title())
        yield Block("reference", f"[{label}]\n{public_url(source, page_url) or page_url}")
        return
    if name == "pre":
        yield Block("code", node.get_text().replace("\r\n", "\n").expandtabs(4))
        return
    if name == "table":
        if node.caption:
            yield Block("heading", clean_text(inline_text(node.caption, page_url)))
        rows = [row for row in node.find_all("tr") if row.find_parent("table") is node]
        labels = []
        for number, row in enumerate(rows, 1):
            cells = row.find_all(["th", "td"], recursive=False)
            if cells and all(cell.name == "th" for cell in cells):
                labels = [clean_text(inline_text(cell, page_url)) for cell in cells]
                yield Block("heading", " | ".join(labels))
                continue
            yield Block("heading", f"[Table / {number}]")
            for index, cell in enumerate(cells):
                label = labels[index] if index < len(labels) else str(index + 1)
                yield Block("heading", label)
                yield from extract_blocks(cell, page_url)
        return
    if name in {"ul", "ol"}:
        try:
            start = int(node.get("start", 1))
        except ValueError:
            start = 1
        for number, item in enumerate(node.find_all("li", recursive=False), start):
            parts = list(extract_blocks(item, page_url))
            prefix = f"{number}. " if name == "ol" else "• "
            if parts and parts[0].kind in {"text", "heading"}:
                parts[0].text = prefix + parts[0].text
            else:
                yield Block("text", prefix)
            yield from parts
        return
    if name and re.fullmatch(r"h[1-6]|summary", name):
        yield Block("heading", clean_text(inline_text(node, page_url)))
        return

    buffer = []
    for child in node.children:
        if isinstance(child, Comment):
            continue
        if isinstance(child, NavigableString):
            buffer.append(re.sub(r"\s+", " ", str(child)))
        elif child.name in SKIP_TAGS or child.get("aria-hidden") == "true":
            continue
        elif (child.name in BLOCK_TAGS | MEDIA_TAGS
              or child.find(list(BLOCK_TAGS | MEDIA_TAGS)) is not None):
            text = clean_text("".join(buffer))
            if text:
                yield Block("text", text)
            buffer = []
            yield from extract_blocks(child, page_url)
        else:
            buffer.append(inline_text(child, page_url))
    text = clean_text("".join(buffer))
    if text:
        yield Block("text", text)


def local_image_path(source, html_file, dist_dir, page_url, site_url):
    """Resolve web and USB-relative assets only inside the selected build."""
    parsed = urlsplit(source)
    if not source or parsed.scheme not in {"", "http", "https"}:
        return None
    if parsed.netloc:
        if parsed.netloc.lower() != urlsplit(site_url).netloc.lower():
            return None
        candidate = dist_dir / unquote(parsed.path).lstrip("/")
    elif parsed.path.startswith("/"):
        candidate = dist_dir / unquote(parsed.path).lstrip("/")
    else:
        candidate = html_file.parent / unquote(parsed.path)
    resolved = candidate.resolve()
    if not resolved.is_relative_to(dist_dir):
        return None
    return resolved if resolved.is_file() else None


def font_paths(args):
    if args.font:
        regular = Path(args.font).expanduser().resolve()
        bold = Path(args.bold_font).expanduser().resolve() if args.bold_font else regular
        if not regular.is_file() or not bold.is_file():
            raise ValueError("The specified font file does not exist")
        return regular, bold
    windows = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
    candidates = [
        (windows / "arial.ttf", windows / "arialbd.ttf"),
        (Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
         Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")),
        (Path("/System/Library/Fonts/Supplemental/Arial.ttf"),
         Path("/System/Library/Fonts/Supplemental/Arial Bold.ttf")),
    ]
    for regular, bold in candidates:
        if regular.is_file() and bold.is_file():
            return regular, Path(args.bold_font).resolve() if args.bold_font else bold
    raise ValueError("No Unicode font found. Pass --font and optionally --bold-font.")


class FontFamily:
    """Measured font fallback: unsupported Unicode must not become blank boxes."""
    def __init__(self, primary, size):
        from PIL import ImageFont
        self.size = size
        windows = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
        candidates = [primary, windows / "seguisym.ttf", windows / "seguiemj.ttf",
                      windows / "msjh.ttc", windows / "simsun.ttc",
                      Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
                      Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc")]
        self.paths = list(dict.fromkeys(path for path in candidates if path.is_file()))
        self.fonts = [ImageFont.truetype(str(path), size) for path in self.paths]
        self.missing_masks = [self.mask(font, "\U0010ffff") for font in self.fonts]
        self.missing, self.used = set(), {0}

    @staticmethod
    def mask(font, character):
        mask = font.getmask(character)
        return mask.size, bytes(mask)

    @lru_cache(maxsize=4096)
    def choose(self, character):
        if character.isspace():
            return 0
        for index, font in enumerate(self.fonts):
            if self.mask(font, character) != self.missing_masks[index]:
                return index
        return -1

    def runs(self, text):
        current, buffer = 0, []
        for character in text:
            index = self.choose(character)
            if index < 0:
                self.missing.add(character)
                index, character = 0, f"[U+{ord(character):04X}]"
            if index != current and buffer:
                yield self.fonts[current], "".join(buffer)
                buffer = []
            current = index
            self.used.add(index)
            buffer.append(character)
        if buffer:
            yield self.fonts[current], "".join(buffer)

    def getlength(self, text):
        return sum(font.getlength(run) for font, run in self.runs(text))

    def getmetrics(self):
        metrics = [font.getmetrics() for font in self.fonts]
        return max(item[0] for item in metrics), max(item[1] for item in metrics)

    def draw(self, draw, position, text):
        x, top = position
        baseline = top + self.getmetrics()[0]
        for font, run in self.runs(text):
            draw.text((x, baseline), run, font=font, fill="black", anchor="ls")
            x += font.getlength(run)


def wrap_text(text, font, width, preserve=False):
    """Wrap by measured pixel width, including URLs longer than one line."""
    lines = []
    for paragraph in text.split("\n"):
        if not paragraph:
            lines.append("")
            continue
        remaining = paragraph if preserve else re.sub(r"\s+", " ", paragraph).strip()
        while remaining:
            low, high = 1, len(remaining)
            if font.getlength(remaining[0]) > width:
                raise ValueError("Font contains a glyph wider than the content area")
            while low < high:
                mid = (low + high + 1) // 2
                if font.getlength(remaining[:mid]) <= width:
                    low = mid
                else:
                    high = mid - 1
            end = low
            if end < len(remaining) and not preserve:
                space = remaining.rfind(" ", 0, end + 1)
                if space > 0:
                    end = space
            lines.append(remaining[:end])
            remaining = remaining[end:]
            if not preserve:
                remaining = remaining.lstrip(" ")
    return lines


def rasterize_svg(source, max_width, max_height):
    """Use the same optional Chromium runtime as the existing PDF exporter.

    SVG is loaded as an inert image, with no website scripts or remote requests.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise ValueError("SVG needs Playwright: install requirements-sstv-export.txt, then python -m playwright install chromium") from None
    from PIL import Image
    data_url = "data:image/svg+xml;base64," + base64.b64encode(source.read_bytes()).decode("ascii")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            context = browser.new_context(java_script_enabled=False, device_scale_factor=1)
            context.route("**/*", lambda route: route.abort())
            page = context.new_page()
            page.set_content(f'<html><body style="margin:0;background:white"><img src="{data_url}" style="display:block"></body></html>')
            dimensions = page.locator("img").evaluate("img => ({width: img.naturalWidth, height: img.naturalHeight, complete: img.complete})")
            if not dimensions["complete"] or not dimensions["width"] or not dimensions["height"]:
                raise ValueError(f"SVG did not load: {source}")
            width, height = dimensions["width"], dimensions["height"]
            ratio = min(max_width / width, max_height / height)
            fitted = (max(1, round(width * ratio)), max(1, round(height * ratio)))
            page.set_viewport_size({"width": fitted[0], "height": fitted[1]})
            page.locator("img").evaluate("(img, size) => {img.style.width=size[0]+'px'; img.style.height=size[1]+'px';}", fitted)
            payload = page.screenshot(type="png", animations="disabled")
            return Image.open(io.BytesIO(payload)).convert("RGBA"), (width, height)
        finally:
            browser.close()


class Renderer:
    def __init__(self, args, folder, regular_path, bold_path):
        self.args, self.folder = args, folder
        self.width, self.height = MODES[args.mode]
        scale = self.width / 640
        self.margin = round(24 * scale)
        size = args.font_size or round(24 * scale)
        self.font = FontFamily(regular_path, size)
        self.heading = FontFamily(bold_path, round(size * 1.2))
        self.small = FontFamily(bold_path, round(18 * scale))
        self.top = round(66 * scale)
        self.bottom = self.height - round(56 * scale)
        self.content_width = self.width - 2 * self.margin
        self.pages, self.warnings = [], []
        self.canvas = None
        self.job = None

    def start_page(self):
        from PIL import Image, ImageDraw
        if self.args.max_pages is not None and len(self.pages) >= self.args.max_pages:
            raise PreviewComplete()
        self.canvas = Image.new("RGB", (self.width, self.height), "white")
        self.draw = ImageDraw.Draw(self.canvas)
        header = f"vojtamaur.cz   |   {self.job['lang'].upper()}   |   {self.args.mode.upper()}"
        self.small.draw(self.draw, (self.margin, self.margin), header)
        self.draw.line((self.margin, self.top - 12, self.width - self.margin, self.top - 12), fill="black", width=2)
        self.y, self.items = self.top, []

    def finish_page(self):
        if self.canvas is None:
            return
        if not self.items:
            self.canvas = None
            return
        number = len(self.pages) + 1
        label = f"{number:06d}  |  {self.job['title']}"
        while self.small.getlength(label) > self.content_width:
            label = label[:-2].rstrip("…") + "…"
        footer_y = self.height - self.margin - sum(self.small.getmetrics())
        self.small.draw(self.draw, (self.margin, footer_y), label)
        filename = f"{number:06d}.png"
        path = self.folder / filename
        self.canvas.save(path, format="PNG", optimize=True)
        self.pages.append({"file": filename, "sha256": sha256_file(path),
                           "slug": self.job["slug"], "lang": self.job["lang"],
                           "items": self.items})
        self.canvas = None

    def add_text(self, text, kind="text"):
        font = self.heading if kind == "heading" else self.font
        lines = wrap_text(text, font, self.content_width, preserve=(kind == "code"))
        ascent, descent = font.getmetrics()
        line_height = max(round(font.size * 1.3), ascent + descent + 2)
        for index, line in enumerate(lines):
            if self.canvas is None:
                self.start_page()
            # Avoid a one-line heading at the bottom when it can fit with text.
            reserve = line_height
            if kind == "heading" and index == 0 and len(lines) <= 2:
                reserve += len(lines) * line_height
            if self.y + reserve > self.bottom and self.items:
                self.finish_page()
                self.start_page()
            if self.y + line_height > self.bottom:
                self.finish_page()
                self.start_page()
            font.draw(self.draw, (self.margin, self.y), line)
            self.items.append({"kind": kind, "text": line})
            self.y += line_height
        if self.canvas is not None:
            self.y += round(self.font.size * 0.4)

    def add_image(self, block, html_file, dist_dir, page_url, site_url):
        from PIL import Image, ImageOps
        target = public_url(block.source, page_url)
        source = local_image_path(block.source, html_file, dist_dir, page_url, site_url)
        if source is None:
            self.warnings.append({"source": target, "reason": "Missing, remote or unsupported image source"})
            self.add_text(f"[Image unavailable]\n{block.text}\n{target or page_url}", "reference")
            return
        try:
            image_height = self.bottom - self.top
            if source.suffix.lower() == ".svg":
                animated = False
                fitted, original_size = rasterize_svg(source, self.content_width, image_height)
            else:
                with Image.open(source) as opened:
                    animated = getattr(opened, "n_frames", 1) > 1
                    frame = ImageOps.exif_transpose(opened).convert("RGBA")
                    original_size = frame.size
                    ratio = min(self.content_width / frame.width, image_height / frame.height)
                    fitted = frame.resize((max(1, round(frame.width * ratio)), max(1, round(frame.height * ratio))),
                                          Image.Resampling.LANCZOS)
        except (OSError, ValueError, Image.DecompressionBombError) as exc:
            self.warnings.append({"source": target, "reason": f"Cannot render image: {exc}"})
            self.add_text(f"[Image unavailable]\n{block.text}\n{target}", "reference")
            return
        self.finish_page()
        self.start_page()
        left = (self.width - fitted.width) // 2
        top = self.top + (image_height - fitted.height) // 2
        self.canvas.paste(fitted, (left, top), fitted.getchannel("A"))
        self.items.append({"kind": "image", "source": target, "alt": block.text,
                           "source_sha256": sha256_file(source), "source_size": original_size,
                           "rendered_box": [left, top, fitted.width, fitted.height],
                           "frame": "first" if animated else "still"})
        self.finish_page()
        # Captions and long alt text use normal pagination, never microscopic type.
        if block.text.strip():
            self.add_text(block.text, "caption")


def run(args):
    try:
        from bs4 import BeautifulSoup
        from PIL import Image  # noqa: F401
    except ImportError:
        raise ValueError("Install dependencies: python -m pip install -r requirements-sstv-export.txt") from None
    project_root = Path(args.project_root).resolve()
    dist_dir = resolve_path(project_root, args.dist)
    site_url = normalize_site_url(args.site_url)
    index_path = dist_dir / "ALL_POSTS.txt"
    if not index_path.is_file():
        raise ValueError(f"Finished build index missing: {index_path}. Run a web build first.")
    posts = parse_all_posts_index(index_path)
    sections, slugs = csv_values(args.section), csv_values(args.slug)
    for label, requested, available in (
        ("section", sections, {post.section for post in posts}),
        ("slug", slugs, {post.slug for post in posts}),
    ):
        if requested - available:
            raise ValueError(f"Unknown {label}: {', '.join(sorted(requested - available))}")
    selected = sorted_built_posts(post for post in posts
                                 if (args.lang == "both" or post.lang == args.lang)
                                 and (not sections or post.section in sections)
                                 and (not slugs or post.slug in slugs))
    if not selected:
        raise ValueError("No articles match the requested filters")
    jobs = []
    for post in selected:
        source = find_built_article_html(dist_dir, post.slug, post.lang)
        if source is None or not source.resolve().is_relative_to(dist_dir):
            raise ValueError(f"Built article missing or outside build: {post.lang}/{post.slug}")
        jobs.append((post, source))
    regular, bold = font_paths(args)
    output_parent = resolve_path(project_root, args.output_dir or f"exports/sstv/{args.mode}")
    if output_parent.is_relative_to(dist_dir) or output_parent == project_root or project_root.is_relative_to(output_parent):
        raise ValueError("Output must be a dedicated export directory outside dist/ and outside project ancestors")
    output_parent.mkdir(parents=True, exist_ok=True)
    # Work in a fresh owned directory. A failed export never overwrites older PNGs.
    with tempfile.TemporaryDirectory(prefix=".sstv-", dir=output_parent) as temporary:
        folder = Path(temporary)
        renderer = Renderer(args, folder, regular, bold)
        articles, partial = [], False
        try:
            for post, source in jobs:
                soup = BeautifulSoup(source.read_bytes(), "html.parser")
                normalize_built_urls(soup, source, dist_dir, site_url, posts)
                article = soup.select_one("main article") or soup.find("article")
                body = article.select_one(".post-body") if article else None
                if body is None:
                    raise ValueError(f"Article body missing: {source}")
                heading = article.find("h1")
                title = heading.get_text(" ", strip=True) if heading else post.title
                robots = " ".join(tag.get("content", "") for tag in soup.find_all("meta")
                                  if tag.get("name", "").lower() == "robots").lower()
                status = "source" if post.lang == "cs" else "incomplete" if "noindex" in robots else "translated"
                prefix = "en/" if post.lang == "en" else ""
                page_url = urljoin(site_url, f"{prefix}{post.slug}/")
                record = {"slug": post.slug, "lang": post.lang, "title": title,
                          "section": post.section, "date": post.date, "url": page_url,
                          "translation_status": status, "html": source.relative_to(dist_dir).as_posix(),
                          "html_sha256": sha256_file(source), "first_page": len(renderer.pages) + 1,
                          "complete": False}
                articles.append(record)
                renderer.job = record
                print(f"[sstv] {post.lang.upper()} {post.slug}", flush=True)
                renderer.add_text(title, "heading")
                renderer.add_text(f"{post.section} | {post.date}\n{page_url}")
                if status == "incomplete":
                    renderer.add_text("[EN incomplete / Czech fallback]", "reference")
                for meta in article.select(".post-header .post-meta"):
                    renderer.add_text(clean_text(meta.get_text(" ", strip=True)))
                for block in extract_blocks(body, page_url):
                    if block.kind == "image":
                        renderer.add_image(block, source, dist_dir, page_url, site_url)
                    else:
                        renderer.add_text(block.text, block.kind)
                renderer.finish_page()
                record["complete"] = True
                record["last_page"] = len(renderer.pages)
        except PreviewComplete:
            partial = True
            articles[-1]["last_page"] = len(renderer.pages)
            # The next article may not yet have produced a frame.
            if articles[-1]["first_page"] > len(renderer.pages):
                articles.pop()
        if not renderer.pages:
            raise ValueError("Export produced no pages")
        width, height = MODES[args.mode]
        families = (renderer.font, renderer.heading, renderer.small)
        missing_characters = set().union(*(family.missing for family in families))
        if missing_characters:
            renderer.warnings.append({"reason": "Missing font glyphs rendered as explicit Unicode code points",
                                      "characters": [f"U+{ord(char):04X}" for char in sorted(missing_characters)]})
        used_font_paths = set().union(*({family.paths[i] for i in family.used} for family in families))
        manifest = {
            "version": VERSION, "created_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
            "mode": args.mode, "width": width, "height": height, "pixel_format": "RGB",
            "mode_sources": MODE_SOURCES, "source_index_sha256": sha256_file(index_path),
            "body_font_size": renderer.font.size,
            "fonts": {"regular": regular.name, "bold": bold.name,
                      "regular_sha256": sha256_file(regular), "bold_sha256": sha256_file(bold),
                      "used": [{"name": path.name, "sha256": sha256_file(path)}
                               for path in sorted(used_font_paths)]},
            "selection": {"lang": args.lang, "sections": sorted(sections), "slugs": sorted(slugs)},
            "partial": partial, "selected_articles": len(jobs), "page_count": len(renderer.pages),
            "articles": articles, "pages": renderer.pages, "warnings": renderer.warnings,
            "limitations": ["No audio encoding or calibration frames; radio round-trip testing is pending.",
                            "Interactive media and unavailable/unsupported images are visible text references.",
                            "Animated images use their first frame. Image detail is limited by the native raster.",
                            "HTML styling is simplified; tables are linearized and code is wrapped.",
                            "Only indexed articles are exported; homepage and linked file payloads are not appended."],
        }
        (folder / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        (folder / "README.txt").write_text(
            f"vojtamaur.cz SSTV PNG export\nMode: {args.mode.upper()}\n"
            f"Native RGB raster: {width} x {height} px\nPages: {len(renderer.pages)}\n"
            f"Partial preview: {'YES' if partial else 'NO'}\n\n"
            "Import numbered PNGs in filename order into an SSTV encoder using the mode above.\n"
            "Keep native dimensions; disable cropping, stretching, templates and added overlays.\n"
            "Each PNG is one complete frame. No audio is generated here.\n"
            "Calibration and receive/decode testing remain a separate next step.\n"
            "manifest.json records reading order, source articles, image references and warnings.\n",
            encoding="utf-8")
        stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        destination = output_parent / f"{stamp}-{args.lang}{'-preview' if partial else ''}"
        folder.rename(destination)
    print(f"[sstv] {len(renderer.pages)} PNGs, {width} x {height}, {args.mode.upper()}")
    print(f"[sstv] Output: {destination}")
    print(f"[sstv] Warnings: {len(renderer.warnings)}; partial: {partial}")
    return 0


def main():
    try:
        return run(parse_args())
    except (ValueError, OSError) as exc:
        print(f"[sstv] ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
