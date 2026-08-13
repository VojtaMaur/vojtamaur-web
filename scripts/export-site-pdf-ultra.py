#!/usr/bin/env python3
"""Export vojtamaur.cz as an ultra-compact PDF with real media thumbnails.

This exporter reuses the MoM-style compact serialization implemented by
``scripts/filter-all-posts.py``. Text flows continuously at 4 pt in four
columns. Image records are replaced with aggressively downsampled, clickable
thumbnails; video, PDF, and interactive embeds become compact text links.

When both languages are exported, identical media is embedded only once by
default. The Czech and English pages use the same files, so repeating every
thumbnail would consume space without adding archival information.

Typical workflow from the project root:

    npm run build:web:strict
    python scripts/export-site-pdf-ultra.py
"""

from __future__ import annotations

import argparse
import base64
import datetime as dt
import hashlib
import html
import importlib.util
import io
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any, Sequence
from urllib.parse import unquote, urljoin, urlsplit


SCRIPT_VERSION = "3.3.2"
DEFAULT_SITE_URL = "https://vojtamaur.cz/"
DEFAULT_INPUT = "dist/ALL_POSTS.txt"
DEFAULT_FILTER_SCRIPT = "scripts/filter-all-posts.py"
DEFAULT_OUTPUT = "exports/vojtamaur-web-export-ultra.pdf"
DEFAULT_SEPARATE_DIR = "exports/ultra-media-separate"
DEFAULT_TITLE = "vojtamaur.cz - ultra-compact media archive"

CSS_LENGTH_RE = re.compile(r"^(?:\d+(?:\.\d+)?|\.\d+)(?:mm|cm|in|pt|px)$")
URL_RE = re.compile(r"https?://[^\s<>\[\]\"']+", flags=re.IGNORECASE)


@dataclass(frozen=True)
class Thumbnail:
    data_url: str
    encoded_bytes: int
    width_mm: float
    height_mm: float


@dataclass
class MediaStats:
    image_occurrences: int = 0
    images_embedded: int = 0
    duplicate_images_omitted: int = 0
    missing_images: int = 0
    unreadable_images: int = 0
    embed_occurrences: int = 0
    embed_cards: int = 0
    duplicate_embeds_omitted: int = 0
    thumbnail_bytes: int = 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Create a MoM-density, four-column PDF containing compact text, "
            "real image thumbnails, and compact media links."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Examples:
  python scripts/export-site-pdf-ultra.py --lang cs
  python scripts/export-site-pdf-ultra.py --lang en
  python scripts/export-site-pdf-ultra.py --lang both
  python scripts/export-site-pdf-ultra.py --section cestovani
  python scripts/export-site-pdf-ultra.py --section volna-tvorba,vystavy
  python scripts/export-site-pdf-ultra.py --lang cs --section cestovani
  python scripts/export-site-pdf-ultra.py --separate
  python scripts/export-site-pdf-ultra.py --image-dpi 70
""",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {SCRIPT_VERSION}",
    )
    parser.add_argument(
        "--project-root",
        default=None,
        help="Project root. Default: detected from this script's location.",
    )
    parser.add_argument(
        "--input",
        default=DEFAULT_INPUT,
        help=f"Structured ALL_POSTS export. Default: {DEFAULT_INPUT}",
    )
    parser.add_argument(
        "--filter-script",
        default=DEFAULT_FILTER_SCRIPT,
        help=(
            "Compact serializer to reuse, relative to project root. "
            f"Default: {DEFAULT_FILTER_SCRIPT}"
        ),
    )
    parser.add_argument(
        "--output",
        default=DEFAULT_OUTPUT,
        help=f"Output PDF, relative to project root. Default: {DEFAULT_OUTPUT}",
    )
    parser.add_argument(
        "--site-url",
        default=DEFAULT_SITE_URL,
        help=f"Public root used by PDF links. Default: {DEFAULT_SITE_URL}",
    )
    parser.add_argument("--title", default=DEFAULT_TITLE, help="PDF title metadata.")
    parser.add_argument(
        "--lang",
        "--language",
        dest="lang",
        choices=["cs", "en", "both"],
        default="both",
        help="Language export: cs, en, or both. Default: both.",
    )
    parser.add_argument(
        "--section",
        action="append",
        metavar="SECTION",
        help="Section(s), repeat or comma-separate. Omitted means all.",
    )
    parser.add_argument("--from-date", metavar="YYYY-MM-DD")
    parser.add_argument("--to-date", metavar="YYYY-MM-DD")
    parser.add_argument(
        "--separate",
        action="store_true",
        help="Export every selected article/language as a separate compact PDF.",
    )
    parser.add_argument(
        "--output-dir",
        default=DEFAULT_SEPARATE_DIR,
        help=(
            "Output directory used by --separate, relative to project root. "
            f"Default: {DEFAULT_SEPARATE_DIR}"
        ),
    )
    parser.add_argument(
        "--paper",
        choices=["A3", "A4", "A5", "Legal", "Letter"],
        default="A4",
        help="Page format. Default: A4.",
    )
    parser.add_argument(
        "--columns", type=int, default=4, help="Text columns. Default: 4."
    )
    parser.add_argument(
        "--font-size",
        type=float,
        default=4.0,
        help="Body size in points. Default: 4.0.",
    )
    parser.add_argument(
        "--line-height",
        type=float,
        default=0.9,
        help="Unitless text line-height. Default: 0.9.",
    )
    parser.add_argument(
        "--margin", default="6mm", help="Margin on all sides. Default: 6mm."
    )
    parser.add_argument(
        "--column-gap", default="1.2mm", help="Column gap. Default: 1.2mm."
    )
    parser.add_argument(
        "--thumbnail-width-mm",
        type=float,
        default=14.5,
        help="Thumbnail box width. Default: 14.5 mm (three fit per column).",
    )
    parser.add_argument(
        "--thumbnail-height-mm",
        type=float,
        default=10.0,
        help="Thumbnail box height. Default: 10 mm.",
    )
    parser.add_argument(
        "--image-dpi",
        type=int,
        default=240,
        help="Thumbnail raster resolution. Default: 240 dpi.",
    )
    parser.add_argument(
        "--jpeg-quality",
        type=int,
        default=70,
        help="Thumbnail JPEG quality from 1 to 95. Default: 70.",
    )
    parser.add_argument(
        "--repeat-media",
        action="store_true",
        help="Repeat identical media in both language versions instead of embedding once.",
    )
    parser.add_argument(
        "--no-links",
        action="store_true",
        help="Remove clickable links from text, thumbnails, and media URLs.",
    )
    parser.add_argument(
        "--no-page-numbers",
        action="store_true",
        help="Do not print the tiny page-number footer.",
    )
    parser.add_argument(
        "--no-manifest",
        action="store_true",
        help="Do not write the adjacent JSON manifest.",
    )
    return parser.parse_args()


def resolve_path(project_root: Path, value: str) -> Path:
    path = Path(value).expanduser()
    return path.resolve() if path.is_absolute() else (project_root / path).resolve()


def normalize_site_url(value: str) -> str:
    value = value.strip()
    parsed = urlsplit(value)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        raise SystemExit("--site-url must be an absolute HTTP(S) URL.")
    return value.rstrip("/") + "/"


def validate_args(args: argparse.Namespace) -> None:
    if not 1 <= args.columns <= 12:
        raise SystemExit("--columns must be between 1 and 12.")
    if not 2.0 <= args.font_size <= 24.0:
        raise SystemExit("--font-size must be between 2 and 24 points.")
    if not 0.75 <= args.line_height <= 3.0:
        raise SystemExit("--line-height must be between 0.75 and 3.0.")
    if not 3.0 <= args.thumbnail_width_mm <= 80.0:
        raise SystemExit("--thumbnail-width-mm must be between 3 and 80.")
    if not 3.0 <= args.thumbnail_height_mm <= 80.0:
        raise SystemExit("--thumbnail-height-mm must be between 3 and 80.")
    if not 36 <= args.image_dpi <= 600:
        raise SystemExit("--image-dpi must be between 36 and 600.")
    if not 1 <= args.jpeg_quality <= 95:
        raise SystemExit("--jpeg-quality must be between 1 and 95.")
    for name in ("margin", "column_gap"):
        value = getattr(args, name).strip().lower()
        if not CSS_LENGTH_RE.fullmatch(value):
            option = "--" + name.replace("_", "-")
            raise SystemExit(f"{option} must be a CSS length such as 6mm or 4pt.")
        setattr(args, name, value)


def ensure_dependencies() -> None:
    missing: list[str] = []
    try:
        import playwright.sync_api  # noqa: F401
    except ImportError:
        missing.append("playwright")
    try:
        import pypdf  # noqa: F401
    except ImportError:
        missing.append("pypdf")
    try:
        import PIL  # noqa: F401
    except ImportError:
        missing.append("Pillow")
    if missing:
        packages = " ".join(missing)
        raise SystemExit(
            f"Missing Python package(s): {', '.join(missing)}.\n"
            f"Install with: python -m pip install {packages}\n"
            "Playwright also needs Chromium: python -m playwright install chromium"
        )


def load_filter_module(path: Path) -> ModuleType:
    if not path.is_file():
        raise SystemExit(f"Compact serializer not found: {path}")
    module_name = "vojtamaur_filter_all_posts"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"Could not load compact serializer: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def split_url_trailer(value: str) -> tuple[str, str]:
    trailer = ""
    while value and value[-1] in ".,;:!?":
        trailer = value[-1] + trailer
        value = value[:-1]
    while value.endswith(")") and value.count("(") < value.count(")"):
        trailer = ")" + trailer
        value = value[:-1]
    return value, trailer


def linkify_text(value: str, enabled: bool) -> str:
    if not enabled:
        return html.escape(value)
    output: list[str] = []
    cursor = 0
    for match in URL_RE.finditer(value):
        output.append(html.escape(value[cursor : match.start()]))
        url, trailer = split_url_trailer(match.group(0))
        if url:
            escaped = html.escape(url, quote=True)
            output.append(f'<a href="{escaped}">{html.escape(url)}</a>')
        output.append(html.escape(trailer))
        cursor = match.end()
    output.append(html.escape(value[cursor:]))
    return "".join(output)


def split_compact_fields(record: str) -> list[str]:
    if len(record) < 2 or record[0] != "[" or record[-1] != "]":
        return [record]
    fields: list[str] = []
    current: list[str] = []
    escaped = False
    for character in record[1:-1]:
        if escaped:
            current.append(character)
            escaped = False
        elif character == "\\":
            escaped = True
        elif character == "|":
            fields.append("".join(current))
            current = []
        else:
            current.append(character)
    if escaped:
        current.append("\\")
    fields.append("".join(current))
    return fields


def compact_details(fields: Sequence[str]) -> dict[str, str]:
    details: dict[str, str] = {}
    for field in fields:
        if ": " in field:
            key, value = field.split(": ", 1)
            details.setdefault(key.upper(), value)
    return details


def normalize_repeated_link(value: str) -> str:
    """Collapse ``/path/file.jpg [/path/file.jpg]`` to the actual file path."""
    match = re.fullmatch(r"(.+?)\s+\[(.+)\]", value.strip())
    if match and match.group(1) == match.group(2):
        return match.group(1)
    return value.strip()


def build_image_map(entries: Sequence[Any], filter_module: ModuleType) -> dict[str, str]:
    paths: dict[str, str] = {}
    for entry in entries:
        lines = entry.body.splitlines()
        for index, line in enumerate(lines):
            if line.strip() != "[MEDIA: image]":
                continue
            details, _ = filter_module.compact_detail_lines(lines, index + 1)
            file_value = next(
                (
                    item.removeprefix("FILE: ")
                    for item in details
                    if item.startswith("FILE: ")
                ),
                None,
            )
            if not file_value:
                continue
            # Match the basename emitted by filter-all-posts.py, then point it
            # to the cleaned source path. Some rendered links repeat their URL
            # in brackets, and the current compact serializer preserves that
            # suffix in the basename.
            serialized_value = file_value.replace("\\", "/")
            compact_name = serialized_value.rsplit("/", 1)[-1]
            cleaned_path = normalize_repeated_link(file_value).replace("\\", "/")
            paths[compact_name] = cleaned_path
    return paths


def local_media_path(dist_dir: Path, raw_path: str) -> Path | None:
    parsed = urlsplit(raw_path)
    path_text = parsed.path if parsed.scheme in {"http", "https"} else raw_path
    path_text = unquote(path_text.split("?", 1)[0].split("#", 1)[0])
    path_text = path_text.replace("\\", "/").lstrip("/")
    if path_text.lower().startswith("dist/"):
        path_text = path_text[5:]
    candidate = (dist_dir / Path(path_text)).resolve()
    try:
        candidate.relative_to(dist_dir.resolve())
    except ValueError:
        return None
    return candidate if candidate.is_file() else None


def public_media_url(site_url: str, raw_path: str) -> str:
    parsed = urlsplit(raw_path)
    if parsed.scheme in {"http", "https"}:
        return raw_path
    return urljoin(site_url, raw_path.lstrip("/"))


def fitted_box_mm(
    aspect_ratio: float,
    max_width_mm: float,
    max_height_mm: float,
) -> tuple[float, float]:
    if aspect_ratio <= 0:
        return max_width_mm, max_height_mm
    if aspect_ratio >= max_width_mm / max_height_mm:
        return max_width_mm, max_width_mm / aspect_ratio
    return max_height_mm * aspect_ratio, max_height_mm


def raster_thumbnail(
    source: Path,
    width_px: int,
    height_px: int,
    jpeg_quality: int,
    image_dpi: int,
) -> Thumbnail:
    from PIL import Image, ImageOps

    with Image.open(source) as opened:
        with ImageOps.exif_transpose(opened) as oriented:
            frame = oriented.convert("RGBA")
            source_width, source_height = frame.size
            scale = min(width_px / source_width, height_px / source_height)
            target_width = max(1, round(source_width * scale))
            target_height = max(1, round(source_height * scale))
            frame = frame.resize(
                (target_width, target_height), Image.Resampling.LANCZOS
            )
            background = Image.new("RGB", frame.size, "white")
            background.paste(frame, mask=frame.getchannel("A"))
            stream = io.BytesIO()
            background.save(
                stream,
                format="JPEG",
                quality=jpeg_quality,
                optimize=True,
                progressive=True,
                subsampling="4:2:0",
            )
    payload = stream.getvalue()
    encoded = base64.b64encode(payload).decode("ascii")
    return Thumbnail(
        f"data:image/jpeg;base64,{encoded}",
        len(payload),
        target_width / image_dpi * 25.4,
        target_height / image_dpi * 25.4,
    )


def svg_thumbnail(
    source: Path,
    max_width_mm: float,
    max_height_mm: float,
) -> Thumbnail:
    import xml.etree.ElementTree as ET

    payload = source.read_bytes()
    encoded = base64.b64encode(payload).decode("ascii")
    aspect_ratio = 1.0
    try:
        root = ET.fromstring(payload)
        view_box = root.attrib.get("viewBox", "").replace(",", " ").split()
        if len(view_box) == 4 and float(view_box[3]) != 0:
            aspect_ratio = float(view_box[2]) / float(view_box[3])
    except (ET.ParseError, ValueError):
        pass
    width_mm, height_mm = fitted_box_mm(
        aspect_ratio, max_width_mm, max_height_mm
    )
    return Thumbnail(
        f"data:image/svg+xml;base64,{encoded}", len(payload), width_mm, height_mm
    )


def make_thumbnail(
    source: Path,
    width_px: int,
    height_px: int,
    jpeg_quality: int,
    image_dpi: int,
    max_width_mm: float,
    max_height_mm: float,
) -> Thumbnail:
    if source.suffix.lower() == ".svg":
        return svg_thumbnail(source, max_width_mm, max_height_mm)
    return raster_thumbnail(
        source, width_px, height_px, jpeg_quality, image_dpi
    )


def linked_wrapper(
    tag: str,
    css_class: str,
    href: str,
    title: str,
    content: str,
    links_enabled: bool,
    style: str = "",
) -> str:
    escaped_title = html.escape(title, quote=True)
    style_attribute = f' style="{html.escape(style, quote=True)}"' if style else ""
    if links_enabled and href:
        escaped_href = html.escape(href, quote=True)
        return (
            f'<a class="{css_class}"{style_attribute} href="{escaped_href}" '
            f'title="{escaped_title}">{content}</a>'
        )
    return (
        f'<{tag} class="{css_class}"{style_attribute} '
        f'title="{escaped_title}">{content}</{tag}>'
    )


def render_compact_body(
    entries: Sequence[Any],
    filter_module: ModuleType,
    image_map: dict[str, str],
    dist_dir: Path,
    args: argparse.Namespace,
    thumbnail_cache: dict[Path, Thumbnail] | None = None,
) -> tuple[str, MediaStats, int]:
    fragments: list[str] = []
    stats = MediaStats()
    seen_images: set[str] = set()
    seen_embeds: set[str] = set()
    if thumbnail_cache is None:
        thumbnail_cache = {}
    compact_characters = 0
    width_px = max(1, round(args.thumbnail_width_mm / 25.4 * args.image_dpi))
    height_px = max(1, round(args.thumbnail_height_mm / 25.4 * args.image_dpi))

    def is_image_line(value: str) -> bool:
        return value.startswith("[img:") and value.endswith("]")

    def render_image_record(value: str) -> str | None:
        stats.image_occurrences += 1
        fields = split_compact_fields(value)
        filename = fields[0].removeprefix("img:")
        details = compact_details(fields[1:])
        raw_path = image_map.get(filename)
        media_key = (raw_path or filename).casefold()
        if not args.repeat_media and media_key in seen_images:
            stats.duplicate_images_omitted += 1
            return None
        seen_images.add(media_key)

        if not raw_path:
            stats.missing_images += 1
            return None
        source = local_media_path(dist_dir, raw_path)
        if source is None:
            stats.missing_images += 1
            return None

        label = details.get("CAPTION") or details.get("ALT") or filename
        try:
            thumbnail = thumbnail_cache.get(source)
            if thumbnail is None:
                thumbnail = make_thumbnail(
                    source,
                    width_px,
                    height_px,
                    args.jpeg_quality,
                    args.image_dpi,
                    args.thumbnail_width_mm,
                    args.thumbnail_height_mm,
                )
                thumbnail_cache[source] = thumbnail
                stats.thumbnail_bytes += thumbnail.encoded_bytes
            image = (
                f'<img src="{thumbnail.data_url}" '
                f'alt="{html.escape(label, quote=True)}">'
            )
            stats.images_embedded += 1
            return linked_wrapper(
                "span",
                "media-thumb",
                public_media_url(args.site_url, raw_path),
                label,
                image,
                not args.no_links,
                (
                    f"width:{thumbnail.width_mm:.3f}mm;"
                    f"height:{thumbnail.height_mm:.3f}mm"
                ),
            )
        except Exception:
            stats.unreadable_images += 1
            return None

    def render_image_run(values: Sequence[str]) -> list[str]:
        rendered = [
            markup
            for value in values
            if (markup := render_image_record(value)) is not None
        ]
        if not rendered:
            return []
        if len(rendered) == 1:
            return [
                rendered[0].replace(
                    'class="media-thumb"',
                    'class="media-thumb media-thumb-single"',
                    1,
                )
            ]

        rows: list[str] = []
        for start in range(0, len(rendered), 3):
            row_items = rendered[start : start + 3]
            cells = "".join(
                f'<span class="media-grid-cell">{markup}</span>'
                for markup in row_items
            )
            rows.append(
                '<span class="media-grid-row" '
                f'style="grid-template-columns:repeat({len(row_items)}, '
                f'{args.thumbnail_width_mm:g}mm)">{cells}</span>'
            )
        return rows

    fragments.append(
        '<span class="document-mark">[vojtamaur.cz|compact media archive|'
        f'{len(entries)} articles]</span> '
    )

    for entry in entries:
        compact = filter_module.serialize_compact_entry(entry)
        compact_characters += len(compact)
        lines = compact.splitlines()
        if not lines:
            continue

        title_fields = split_compact_fields(lines[0])
        title_text = " | ".join(title_fields)
        article_url = entry.metadata.get("URL", "")
        fragments.append('<span class="article-break"></span>')
        fragments.append(
            linked_wrapper(
                "span",
                "article-title",
                article_url,
                title_text,
                html.escape(title_text),
                not args.no_links,
            )
            + " "
        )

        in_code = False
        content_lines = lines[1:]
        line_index = 0
        while line_index < len(content_lines):
            stripped = content_lines[line_index].strip()
            if not stripped:
                line_index += 1
                continue
            if stripped == "[CODE BLOCK]":
                in_code = True
                fragments.append('<span class="code-marker">[code]</span> ')
                line_index += 1
                continue
            if stripped == "[/CODE BLOCK]":
                in_code = False
                fragments.append('<span class="code-marker">[/code]</span> ')
                line_index += 1
                continue

            # A short caption ending in a colon followed by multiple images is
            # the compact representation of a site MediaRow. Keep its first
            # three-image row with the caption so neither can become orphaned.
            if (
                not in_code
                and stripped.endswith(":")
                and len(stripped) <= 160
                and line_index + 1 < len(content_lines)
                and is_image_line(content_lines[line_index + 1].strip())
            ):
                run_end = line_index + 1
                while (
                    run_end < len(content_lines)
                    and is_image_line(content_lines[run_end].strip())
                ):
                    run_end += 1
                image_values = [
                    value.strip()
                    for value in content_lines[line_index + 1 : run_end]
                ]
                if image_values:
                    groups = render_image_run(image_values)
                    nonbreaking_label = stripped.replace(" ", "\u00a0")
                    label_markup = (
                        '<div class="media-label">'
                        + linkify_text(nonbreaking_label, enabled=not args.no_links)
                        + "</div>"
                    )
                    if groups:
                        fragments.append(
                            '<div class="media-labelled-group">'
                            + label_markup
                            + groups[0]
                            + "</div> "
                        )
                        fragments.extend(group + " " for group in groups[1:])
                    else:
                        fragments.append(label_markup + " ")
                    line_index = run_end
                    continue

            if not in_code and is_image_line(stripped):
                run_end = line_index
                while (
                    run_end < len(content_lines)
                    and is_image_line(content_lines[run_end].strip())
                ):
                    run_end += 1
                groups = render_image_run(
                    [value.strip() for value in content_lines[line_index:run_end]]
                )
                next_text = (
                    content_lines[run_end].strip()
                    if run_end < len(content_lines)
                    else ""
                )
                next_is_plain_text = bool(next_text) and not next_text.startswith("[")
                if groups and len(groups) == 1 and next_is_plain_text:
                    # Let the following paragraph use the horizontal space next
                    # to a short image row, but keep that paragraph intact so a
                    # lone fragment cannot be stranded beside the images.
                    paragraph_markup = (
                        '<span class="text media-side-text">'
                        + linkify_text(next_text, enabled=not args.no_links)
                        + "</span>"
                    )
                    fragments.append(
                        '<span class="media-with-text">'
                        + groups[0]
                        + paragraph_markup
                        + "</span> "
                    )
                    line_index = run_end + 1
                    continue
                fragments.extend(group + " " for group in groups)
                line_index = run_end
                continue

            if not in_code and stripped.startswith(
                ("[video", "[pdf", "[interactive")
            ) and stripped.endswith("]"):
                stats.embed_occurrences += 1
                fields = split_compact_fields(stripped)
                kind = fields[0].lower()
                details = compact_details(fields[1:])
                source = details.get("SOURCE", "")
                key = f"{kind}|{source}".casefold()
                if not args.repeat_media and key in seen_embeds:
                    stats.duplicate_embeds_omitted += 1
                    line_index += 1
                    continue
                seen_embeds.add(key)
                public_url = public_media_url(args.site_url, source) if source else ""
                displayed_url = public_url or source or f"[{kind}]"
                fragments.append(
                    linked_wrapper(
                        "span",
                        "embed-link",
                        public_url,
                        details.get("TITLE") or source or kind,
                        html.escape(displayed_url),
                        not args.no_links,
                    )
                    + " "
                )
                stats.embed_cards += 1
                line_index += 1
                continue

            css_class = "code-text" if in_code else "text"
            fragments.append(
                f'<span class="{css_class}">'
                + linkify_text(stripped, enabled=not args.no_links)
                + "</span> "
            )
            line_index += 1

    return "".join(fragments), stats, compact_characters


def document_html(body: str, args: argparse.Namespace) -> str:
    title = html.escape(args.title)
    thumb_width = f"{args.thumbnail_width_mm:g}mm"
    thumb_height = f"{args.thumbnail_height_mm:g}mm"
    return f"""<!doctype html>
<html lang="cs">
<head>
<meta charset="utf-8">
<title>{title}</title>
<style>
  @page {{ size: {args.paper} portrait; margin: {args.margin}; }}
  html, body {{ margin: 0; padding: 0; background: #fff; }}
  body {{
    color: #000;
    font-family: Arial, "Liberation Sans", sans-serif;
    font-size: {args.font_size:g}pt;
    font-kerning: normal;
    line-height: {args.line_height:g};
    text-rendering: optimizeLegibility;
  }}
  .content {{
    column-count: {args.columns};
    column-gap: {args.column_gap};
    column-fill: balance;
    hyphens: auto;
    margin: 0;
    overflow-wrap: anywhere;
    padding: 0;
    widows: 1;
    orphans: 1;
  }}
  a, a:visited {{ color: inherit; text-decoration: none; }}
  .article-break {{
    break-after: avoid;
    clear: both;
    display: block;
    height: 0;
    line-height: 0;
  }}
  .document-mark, .article-title {{
    background: #000;
    color: #fff;
    display: inline;
    font-weight: 700;
    line-height: 1.05;
    padding: 0 0.35mm;
  }}
  .document-mark {{ background: #555; }}
  .code-marker {{ color: #555; font-size: 0.9em; font-weight: 400; }}
  .code-text {{ font-family: "Arial Narrow", Arial, sans-serif; }}
  .media-thumb {{
    align-items: center;
    background: #fff;
    box-sizing: border-box;
    display: inline-flex;
    justify-content: center;
    margin: 0;
    overflow: hidden;
    vertical-align: top;
    break-inside: avoid;
  }}
  .media-thumb img {{
    border: 0.05pt solid #aaa;
    box-sizing: border-box;
    display: block;
    height: 100%;
    object-fit: contain;
    width: 100%;
  }}
  .media-thumb-single {{
    float: left;
    margin: 0.12mm 0.45mm 0.12mm 0;
  }}
  .media-grid-row {{
    break-inside: avoid;
    display: inline-grid;
    gap: 0.18mm;
    grid-auto-rows: {thumb_height};
    grid-template-columns: repeat(3, {thumb_width});
    line-height: 0;
    margin: 0.12mm 0;
    vertical-align: top;
  }}
  .media-grid-cell {{
    align-items: center;
    display: flex;
    height: {thumb_height};
    justify-content: center;
    width: {thumb_width};
  }}
  .media-labelled-group {{
    break-inside: avoid;
    clear: both;
    display: block;
    max-width: 100%;
  }}
  .media-label {{
    display: block;
    line-height: {args.line_height:g};
    overflow-wrap: normal;
    white-space: nowrap;
    word-break: keep-all;
  }}
  .media-labelled-group .media-thumb-single {{
    display: flex;
    float: none;
    margin: 0.12mm 0;
  }}
  .media-labelled-group .media-grid-row {{ display: grid; }}
  .media-with-text {{
    break-inside: avoid;
    display: inline-block;
    max-width: 100%;
    vertical-align: top;
  }}
  .media-with-text .media-grid-row {{
    float: left;
    margin: 0.12mm 0.45mm 0.12mm 0;
  }}
  .media-with-text::after {{ clear: both; content: ""; display: table; }}
  .embed-link {{
    color: #333 !important;
    font-size: 3.6pt;
    overflow-wrap: anywhere;
    text-decoration: none;
  }}
</style>
</head>
<body><div class="content">{body}</div></body>
</html>"""


def render_pdf_with_browser(
    browser: Any,
    html_source: str,
    output_path: Path,
    args: argparse.Namespace,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_output = output_path.with_name(output_path.name + ".rendering.pdf")
    temporary_output.unlink(missing_ok=True)
    page = browser.new_page()
    try:
        page.set_content(
            html_source,
            wait_until="domcontentloaded",
            timeout=120_000,
        )
        page.evaluate(
            """async () => {
              await document.fonts.ready;
              await Promise.all(
                Array.from(document.images, (image) =>
                  image.decode().catch(() => undefined)
                )
              );
            }"""
        )
        page.pdf(
            path=str(temporary_output),
            format=args.paper,
            landscape=False,
            print_background=True,
            prefer_css_page_size=True,
            margin={
                "top": args.margin,
                "right": args.margin,
                "bottom": args.margin,
                "left": args.margin,
            },
            display_header_footer=not args.no_page_numbers,
            header_template="<span></span>",
            footer_template=(
                '<div style="box-sizing:border-box;color:#555;'
                'font-family:Arial,sans-serif;font-size:4pt;'
                'padding:0 6mm;text-align:center;width:100%">'
                '<span class="pageNumber"></span>/<span class="totalPages"></span>'
                "</div>"
            ),
        )
        temporary_output.replace(output_path)
    except Exception:
        temporary_output.unlink(missing_ok=True)
        raise
    finally:
        page.close()


def render_pdf(html_source: str, output_path: Path, args: argparse.Namespace) -> None:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            render_pdf_with_browser(browser, html_source, output_path, args)
        finally:
            browser.close()


def inspect_pdf(path: Path) -> tuple[int, float, float, int]:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    if not reader.pages:
        raise SystemExit("The generated PDF has no pages.")
    first = reader.pages[0].mediabox
    links = 0
    for page in reader.pages:
        for annotation_ref in page.get("/Annots", []):
            if annotation_ref.get_object().get("/Subtype") == "/Link":
                links += 1
    return len(reader.pages), float(first.width), float(first.height), links


def write_manifest(
    manifest_path: Path,
    input_path: Path,
    input_bytes: bytes,
    output_path: Path,
    page_count: int,
    link_count: int,
    compact_characters: int,
    selected_count: int,
    total_count: int,
    stats: MediaStats,
    args: argparse.Namespace,
) -> None:
    data = {
        "generated_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "generator": f"export-site-pdf-ultra.py {SCRIPT_VERSION}",
        "title": args.title,
        "input": {
            "path": str(input_path),
            "bytes": len(input_bytes),
            "sha256": sha256_bytes(input_bytes),
            "articles_selected": selected_count,
            "articles_total": total_count,
            "compact_characters": compact_characters,
        },
        "selection": {
            "language": args.lang,
            "sections": args.section or ["all"],
            "from_date": args.from_date,
            "to_date": args.to_date,
        },
        "layout": {
            "paper": args.paper,
            "columns": args.columns,
            "font_size_pt": args.font_size,
            "line_height": args.line_height,
            "margin": args.margin,
            "column_gap": args.column_gap,
            "thumbnail_width_mm": args.thumbnail_width_mm,
            "thumbnail_height_mm": args.thumbnail_height_mm,
            "image_dpi": args.image_dpi,
            "jpeg_quality": args.jpeg_quality,
            "repeat_media": args.repeat_media,
            "clickable_links": not args.no_links,
            "page_numbers": not args.no_page_numbers,
        },
        "media": vars(stats),
        "output": {
            "path": str(output_path),
            "pages": page_count,
            "links": link_count,
            "bytes": output_path.stat().st_size,
            "sha256": sha256_file(output_path),
        },
    }
    manifest_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def selected_entries(
    parsed: Any,
    filter_module: ModuleType,
    args: argparse.Namespace,
) -> list[Any]:
    languages = None if args.lang == "both" else {args.lang}
    sections = filter_module.split_values(args.section)
    filter_module.validate_requested_values(
        languages,
        filter_module.available_values(parsed.entries, "LANGUAGE"),
        "language",
    )
    filter_module.validate_requested_values(
        sections,
        filter_module.available_values(parsed.entries, "SECTION"),
        "section",
    )
    date_from = (
        filter_module.parse_iso_date(args.from_date, "--from-date")
        if args.from_date
        else None
    )
    date_to = (
        filter_module.parse_iso_date(args.to_date, "--to-date")
        if args.to_date
        else None
    )
    if date_from and date_to and date_from > date_to:
        raise filter_module.ExportError("--from-date must not be later than --to-date.")
    selected = filter_module.filtered_entries(
        parsed.entries, languages, sections, date_from, date_to
    )
    if not selected:
        raise filter_module.ExportError("The filters selected no articles.")
    filter_module.validate_compact_image_names(selected)
    return selected


def safe_filename(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "-", value).strip("-._")
    return cleaned or "untitled"


def add_media_stats(total: MediaStats, current: MediaStats) -> None:
    for field in vars(total):
        setattr(total, field, getattr(total, field) + getattr(current, field))


def render_separate_exports(
    entries: Sequence[Any],
    filter_module: ModuleType,
    image_map: dict[str, str],
    dist_dir: Path,
    output_dir: Path,
    args: argparse.Namespace,
) -> tuple[list[dict[str, Any]], MediaStats, int]:
    from playwright.sync_api import sync_playwright

    output_dir.mkdir(parents=True, exist_ok=True)
    thumbnail_cache: dict[Path, Thumbnail] = {}
    records: list[dict[str, Any]] = []
    total_stats = MediaStats()
    total_characters = 0

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            for index, entry in enumerate(entries, start=1):
                language = entry.metadata.get("LANGUAGE", "unknown")
                section = entry.metadata.get("SECTION", "unknown")
                slug = entry.metadata.get("SLUG", f"article-{index}")
                output_path = (
                    output_dir
                    / safe_filename(language)
                    / safe_filename(section)
                    / f"{safe_filename(slug)}.pdf"
                )
                print(f"[{index}/{len(entries)}] {language.upper()} {section}/{slug}")
                body, stats, characters = render_compact_body(
                    [entry],
                    filter_module,
                    image_map,
                    dist_dir,
                    args,
                    thumbnail_cache,
                )
                render_pdf_with_browser(
                    browser, document_html(body, args), output_path, args
                )
                pages, _, _, links = inspect_pdf(output_path)
                add_media_stats(total_stats, stats)
                total_characters += characters
                records.append(
                    {
                        "path": str(output_path),
                        "language": language,
                        "section": section,
                        "slug": slug,
                        "pages": pages,
                        "links": links,
                        "bytes": output_path.stat().st_size,
                        "sha256": sha256_file(output_path),
                    }
                )
        finally:
            browser.close()
    return records, total_stats, total_characters


def write_separate_manifest(
    manifest_path: Path,
    input_path: Path,
    input_bytes: bytes,
    records: Sequence[dict[str, Any]],
    stats: MediaStats,
    compact_characters: int,
    selected_count: int,
    total_count: int,
    args: argparse.Namespace,
) -> None:
    data = {
        "generated_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "generator": f"export-site-pdf-ultra.py {SCRIPT_VERSION}",
        "mode": "separate",
        "input": {
            "path": str(input_path),
            "bytes": len(input_bytes),
            "sha256": sha256_bytes(input_bytes),
            "articles_selected": selected_count,
            "articles_total": total_count,
            "compact_characters": compact_characters,
        },
        "selection": {
            "language": args.lang,
            "sections": args.section or ["all"],
            "from_date": args.from_date,
            "to_date": args.to_date,
        },
        "layout": {
            "paper": args.paper,
            "columns": args.columns,
            "font_size_pt": args.font_size,
            "line_height": args.line_height,
            "margin": args.margin,
            "column_gap": args.column_gap,
            "thumbnail_width_mm": args.thumbnail_width_mm,
            "thumbnail_height_mm": args.thumbnail_height_mm,
            "image_dpi": args.image_dpi,
            "jpeg_quality": args.jpeg_quality,
            "clickable_links": not args.no_links,
            "page_numbers": not args.no_page_numbers,
        },
        "media": vars(stats),
        "summary": {
            "pdfs": len(records),
            "pages": sum(record["pages"] for record in records),
            "bytes": sum(record["bytes"] for record in records),
        },
        "outputs": list(records),
    }
    manifest_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    args = parse_args()
    validate_args(args)
    ensure_dependencies()
    args.site_url = normalize_site_url(args.site_url)

    project_root = (
        Path(args.project_root).expanduser().resolve()
        if args.project_root
        else Path(__file__).resolve().parent.parent
    )
    input_path = resolve_path(project_root, args.input)
    filter_path = resolve_path(project_root, args.filter_script)
    output_path = resolve_path(project_root, args.output)
    dist_dir = project_root / "dist"

    if not input_path.is_file():
        raise SystemExit(
            f"Input archive not found: {input_path}\n"
            "Run a site build first so dist/ALL_POSTS.txt exists."
        )
    if not dist_dir.is_dir():
        raise SystemExit(f"Built media directory not found: {dist_dir}")

    filter_module = load_filter_module(filter_path)
    try:
        parsed = filter_module.parse_export(input_path)
        selected = selected_entries(parsed, filter_module, args)
    except filter_module.ExportError as exc:
        raise SystemExit(str(exc)) from exc

    image_map = build_image_map(selected, filter_module)
    print(f"[input] {input_path}")
    print(f"[compact] {len(selected)} of {len(parsed.entries)} articles")
    print(
        f"[layout] {args.paper}, {args.columns} columns, {args.font_size:g} pt; "
        f"thumbnails {args.thumbnail_width_mm:g} x {args.thumbnail_height_mm:g} mm"
    )
    print(f"[media] resolving {len(image_map)} unique image name(s)")

    input_bytes = input_path.read_bytes()
    if args.separate:
        output_dir = resolve_path(project_root, args.output_dir)
        print(f"[separate] {output_dir}")
        records, stats, compact_characters = render_separate_exports(
            selected,
            filter_module,
            image_map,
            dist_dir,
            output_dir,
            args,
        )
        if stats.missing_images or stats.unreadable_images:
            print(
                f"[warn] {stats.missing_images} missing and "
                f"{stats.unreadable_images} unreadable image occurrence(s) "
                "were omitted from the PDF.",
                file=sys.stderr,
            )
        if not args.no_manifest:
            manifest_path = output_dir / "pdf-export-manifest.json"
            write_separate_manifest(
                manifest_path,
                input_path,
                input_bytes,
                records,
                stats,
                compact_characters,
                len(selected),
                len(parsed.entries),
                args,
            )
            print(f"[manifest] {manifest_path}")
        print(
            f"[done] {len(records)} PDF(s), "
            f"{sum(record['pages'] for record in records)} total page(s), "
            f"{sum(record['bytes'] for record in records):,} bytes"
        )
        return 0

    body, stats, compact_characters = render_compact_body(
        selected, filter_module, image_map, dist_dir, args
    )
    print(
        f"[media] embedded {stats.images_embedded} image(s), "
        f"{stats.embed_cards} media link(s); omitted "
        f"{stats.duplicate_images_omitted + stats.duplicate_embeds_omitted} "
        "duplicate media occurrence(s)"
    )
    if stats.missing_images or stats.unreadable_images:
        print(
            f"[warn] {stats.missing_images} missing and "
            f"{stats.unreadable_images} unreadable image(s) were omitted from the PDF.",
            file=sys.stderr,
        )

    print(f"[render] {output_path}")
    render_pdf(document_html(body, args), output_path, args)
    page_count, width_pt, height_pt, link_count = inspect_pdf(output_path)

    manifest_path = output_path.with_suffix(".manifest.json")
    if not args.no_manifest:
        write_manifest(
            manifest_path,
            input_path,
            input_bytes,
            output_path,
            page_count,
            link_count,
            compact_characters,
            len(selected),
            len(parsed.entries),
            stats,
            args,
        )

    print(
        f"[done] {page_count} page(s), {width_pt:.1f} x {height_pt:.1f} pt, "
        f"{output_path.stat().st_size:,} bytes, {link_count} link(s)"
    )
    if not args.no_manifest:
        print(f"[manifest] {manifest_path}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("Interrupted.", file=sys.stderr)
        raise SystemExit(130)
