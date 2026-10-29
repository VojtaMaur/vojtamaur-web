"""Frozen, provenance-bearing meme inputs, independent of archive packet order."""
from __future__ import annotations

import hashlib
import html
from html.parser import HTMLParser
import json
import math
from pathlib import Path
import random
import re


RASTER_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tif", ".tiff", ".avif"}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


class _TextBlocks(HTMLParser):
    def __init__(self, language=None):
        super().__init__(convert_charrefs=True)
        self.blocks = []
        self.capture = None
        self.fragments = []
        self.suppressed = 0
        self.language = language
        self.stack = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag in {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}:
            if tag == "br" and self.capture and not self.suppressed:
                self.fragments.append(" ")
            return
        declared = (attrs.get("lang") or "").lower().split("-")[0]
        protected = (self.language == "en" and (
            attrs.get("translate") == "no" or attrs.get("data-i18n") == "protect"
            or "notranslate" in (attrs.get("class") or "").split()))
        blocked = (tag in {"script", "style", "pre", "code"} or protected
                   or bool(declared and self.language and declared != self.language))
        self.stack.append((tag, blocked))
        if blocked:
            self.suppressed += 1
        if not self.suppressed and tag in {"p", "h1", "h2", "h3", "h4", "h5", "h6"}:
            self.capture, self.fragments = tag, []

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_endtag(self, tag):
        if self.capture == tag:
            self.blocks.append((tag, "".join(self.fragments)))
            self.capture, self.fragments = None, []
        for offset in range(len(self.stack) - 1, -1, -1):
            if self.stack[offset][0] == tag:
                self.suppressed -= sum(blocked for _, blocked in self.stack[offset:])
                del self.stack[offset:]
                break

    def handle_data(self, data):
        if self.capture and not self.suppressed:
            self.fragments.append(data)


def _excerpts(text: str, max_chars: int):
    clean = re.sub(r"\s+", " ", html.unescape(text)).strip()
    if len(clean) < 8 or not re.search(r"[^\W\d_]", clean, re.UNICODE):
        return
    if re.search(r"https?://|\[/|\.(?:jpg|png|webp|pdf)(?:\s|$)", clean, re.I):
        return
    # Keep actual sentences when possible; long sentences become word-boundary excerpts.
    for sentence in re.split(r"(?<=[.!?])\s+", clean):
        if len(sentence) < 8:
            continue
        if len(sentence) > max_chars:
            sentence = sentence[:max_chars - 1].rsplit(" ", 1)[0].rstrip(" ,;:") + "…"
        yield sentence


def build_catalog(root, max_chars=120, language="en"):
    """Snapshot article captions and every readable local raster, including unused images.

    The caller saves this catalogue in its edition; later source edits cannot reorder
    the random choices. Image hashes let resume reject changed source pictures.
    """
    from PIL import Image

    root = Path(root).resolve()
    if max_chars < 20:
        raise ValueError("max_chars must be at least 20")
    language = language.lower()
    if language not in {"en", "cs", "en+cs"}:
        raise ValueError("Caption language must be EN, CS or EN+CS")
    selected_languages = {"en", "cs"} if language == "en+cs" else {language}
    text_records = []
    seen = set()

    def add(text, source, kind, source_language):
        for excerpt in _excerpts(text, max_chars):
            key = (source_language, excerpt)
            if key in seen:
                continue
            seen.add(key)
            text_records.append({"text": excerpt, "source": source, "kind": kind,
                                 "language": source_language})

    json_path = root / "dist" / "ALL_POSTS.json"
    if json_path.is_file():
        data = json.loads(json_path.read_text(encoding="utf-8-sig"))
        for article in data.get("hasPart", []):
            source_language = str(article.get("inLanguage", "")).lower().split("-")[0]
            if source_language not in selected_languages:
                continue
            source = article.get("url") or article.get("vm:sourcePath") or "dist/ALL_POSTS.json"
            add(article.get("headline", ""), source, "title", source_language)
            parser = _TextBlocks(source_language)
            article_html = article.get("vm:articleHtml", "")
            parser.feed(article_html)
            blocks = parser.blocks if article_html.strip() else [("p", p) for p in article.get("articleBody", "").splitlines()]
            for tag, text in blocks:
                add(text, source, tag, source_language)
    else:
        text_path = root / "dist" / "ALL_POSTS.txt"
        parts = re.split(r"(?m)^={10,}\r?$", text_path.read_text(encoding="utf-8-sig"))
        for offset in range(1, len(parts) - 1, 2):
            fields = dict(re.findall(r"(?m)^([A-Z_]+):[ \t]*(.*?)\r?$", parts[offset]))
            source_language = fields.get("LANGUAGE", "").lower().split("-")[0]
            if source_language not in selected_languages:
                continue
            source = fields.get("URL", "dist/ALL_POSTS.txt")
            add(fields.get("TITLE", ""), source, "title", source_language)
            for line in parts[offset + 1].splitlines():
                add(line, source, "text", source_language)
    available = {record["language"] for record in text_records}
    missing = selected_languages - available
    if missing:
        raise ValueError("No caption candidates for language " + ", ".join(sorted(missing))
                         + " in dist/ALL_POSTS.json or dist/ALL_POSTS.txt")
    images = []
    skipped = []
    candidates = sorted((root / "public" / "images").rglob("*"), key=lambda p: p.as_posix())
    for path in candidates:
        if not path.is_file() or path.suffix.lower() not in RASTER_EXTENSIONS:
            continue
        relative = path.relative_to(root).as_posix()
        if not path.resolve().is_relative_to(root):
            skipped.append({"path": relative, "reason": "outside project root"})
            continue
        try:
            with Image.open(path) as image:
                width, height = image.size
                image.verify()
            if width < 16 or height < 16:
                raise ValueError("image is smaller than 16 pixels")
            images.append({"path": relative, "sha256": sha256_file(path), "width": width, "height": height})
        except (OSError, ValueError, Image.DecompressionBombError) as exc:
            skipped.append({"path": relative, "reason": str(exc)})
    if not images:
        raise ValueError("No readable raster images in public/images")
    return {"version": 2, "language": language, "max_chars": max_chars,
            "texts": text_records, "images": images, "skipped_images": skipped}


def choose_meme(catalog, seed, index, rat_weight=1.25):
    """Stable per-index selection, without requiring earlier memes to be generated."""
    if index < 0 or not math.isfinite(rat_weight) or rat_weight <= 0:
        raise ValueError("index must be nonnegative and rat_weight finite and positive")
    digest = hashlib.sha256((str(seed) + "\0" + str(index)).encode("utf-8")).digest()
    rng = random.Random(int.from_bytes(digest, "big"))
    weights = [rat_weight if Path(image["path"]).name.casefold() == "kurt-godel-rat.jpg" else 1.0
               for image in catalog["images"]]
    image = rng.choices(catalog["images"], weights=weights, k=1)[0]
    top, bottom = rng.choice(catalog["texts"]), rng.choice(catalog["texts"])
    layout = rng.choice(("top", "bottom", "both"))
    return {"index": index, "image": image, "top": top if layout != "bottom" else None,
            "bottom": bottom if layout != "top" else None, "layout": layout}
