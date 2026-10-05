#!/usr/bin/env python3
"""Create a text-only MoM-like PDF from the existing ALL_POSTS.json.

The compact serializer is shared with filter-all-posts.py; the ultra PDF
exporter is neither imported nor modified. PDF lines flow through three
columns on square 210 x 210 mm pages with equal margins.
Source line breaks become wide spaces. The adjacent UTF-8 TXT retains the
compact source's line breaks and code indentation; it is not raw JSON.
The DullGPT example output log is shortened to the same preview limits as
ALL_POSTS.txt; --full-dullgpt-log keeps it complete. Executable code is kept.

Examples (from the repository root):
    python scripts/export-site-mom-like.py
    python scripts/export-site-mom-like.py --lang en --section volna-tvorba
    python scripts/export-site-mom-like.py --lang both --page-numbers
    python scripts/export-site-mom-like.py --page-width-mm 210 --page-height-mm 210

Install dependencies: python -m pip install -r requirements-mom-like-export.txt
No browser, media files, network access, or site rebuild is needed.
"""

from __future__ import annotations

from export_naming import add_arguments, stamped_path, timestamp_for

import argparse
from collections import Counter
import datetime as dt
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import sys
import tempfile


SCRIPT_VERSION = "1.0.3"
DEFAULT_OUTPUT = "exports/vojtamaur-web-export-mom-like.pdf"
MM = 72 / 25.4
# Match the preview limits in generate-all-posts.mjs, applied only to the
# DullGPT example output log here. Executable code remains complete.
DULLGPT_MAX_LINES = 120
DULLGPT_MAX_CHARS = 12000


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--version", action="version", version=SCRIPT_VERSION)
    parser.add_argument("--project-root", type=Path,
                        default=Path(__file__).resolve().parent.parent)
    parser.add_argument("--input", default="dist/ALL_POSTS.json",
                        help="JSON-LD snapshot, or an explicit legacy structured TXT.")
    parser.add_argument("--output", default=None,
                        help="PDF path; adjacent .txt and .manifest.json are also written.")
    parser.add_argument("--lang", "--language", choices=("cs", "en", "both"), default="cs")
    parser.add_argument("--section", action="append",
                        help="Section(s), repeat or comma-separate; default: volna-tvorba. Use all for every section.")
    parser.add_argument("--from-date", metavar="YYYY-MM-DD")
    parser.add_argument("--to-date", metavar="YYYY-MM-DD")
    parser.add_argument("--full-dullgpt-log", action="store_true",
                        help="Keep the full DullGPT output log instead of its TXT-style preview.")
    parser.add_argument("--page-width-mm", type=float, default=210.0)
    parser.add_argument("--page-height-mm", type=float, default=210.0)
    parser.add_argument("--columns", type=int, default=3)
    parser.add_argument("--font-size", type=float, default=4.0, help="Points; default: 4.")
    parser.add_argument("--char-spacing", type=float, default=-0.2,
                        help="Tracking in points; default: -0.2, as in the MoM reference.")
    parser.add_argument("--line-height", type=float, default=0.875,
                        help="Multiplier; default: 0.875 (3.5 pt at 4 pt).")
    parser.add_argument("--line-gap-spaces", type=int, default=7,
                        help="Spaces replacing a source line break; default: 7.")
    parser.add_argument("--margin-mm", type=float, default=7.0,
                        help="Left, right and bottom margin; default: 7 mm.")
    parser.add_argument("--top-margin-mm", type=float, default=None,
                        help="Override top margin; default: same as --margin-mm.")
    parser.add_argument("--column-gap-mm", type=float, default=1.0)
    parser.add_argument("--font", type=Path, help="Primary TrueType font, normally Arial.")
    parser.add_argument("--fallback-font", type=Path, action="append", default=[],
                        help="Additional TrueType font, repeat for Unicode coverage.")
    parser.add_argument("--page-numbers", action="store_true",
                        help="Print page numbers in the bottom margin (default: off).")
    add_arguments(parser)
    args = parser.parse_args(argv)
    if args.section is None:
        args.section = ["volna-tvorba"]
    if args.top_margin_mm is None:
        args.top_margin_mm = args.margin_mm
    return args


def validate_args(args):
    limits = {
        "page_width_mm": (50, 1000), "page_height_mm": (50, 1000),
        "font_size": (2, 24), "line_height": (0.8, 3),
        "margin_mm": (2, 100), "top_margin_mm": (2, 100),
        "column_gap_mm": (0.1, 30),
    }
    for name, (low, high) in limits.items():
        value = getattr(args, name)
        if not math.isfinite(value) or not low <= value <= high:
            raise ValueError(f"--{name.replace('_', '-')} must be between {low} and {high}.")
    if not 1 <= args.columns <= 12:
        raise ValueError("--columns must be between 1 and 12.")
    if not 1 <= args.line_gap_spaces <= 40:
        raise ValueError("--line-gap-spaces must be between 1 and 40.")
    if not math.isfinite(args.char_spacing) or not -0.1 * args.font_size <= args.char_spacing <= args.font_size:
        raise ValueError("--char-spacing must be between -10% and 100% of --font-size.")
    width = (args.page_width_mm - 2 * args.margin_mm
             - (args.columns - 1) * args.column_gap_mm) / args.columns
    height = args.page_height_mm - args.top_margin_mm - args.margin_mm
    if width * MM < 10 * args.font_size or height * MM < 3 * args.font_size:
        raise ValueError("Page margins/columns leave too little room for text.")


def resolve_path(root, value):
    path = Path(value).expanduser()
    return (path if path.is_absolute() else root / path).resolve()


def load_filter(root):
    path = root / "scripts" / "filter-all-posts.py"
    if not path.is_file():
        raise ValueError(f"Shared compact serializer not found: {path}")
    name = "mom_like_filter_all_posts"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def select_entries(parsed, filters, args):
    languages = None if args.lang == "both" else {args.lang}
    sections = filters.split_values(args.section)
    filters.validate_requested_values(languages,
        filters.available_values(parsed.entries, "LANGUAGE"), "language")
    filters.validate_requested_values(sections,
        filters.available_values(parsed.entries, "SECTION"), "section")
    start = filters.parse_iso_date(args.from_date, "--from-date") if args.from_date else None
    end = filters.parse_iso_date(args.to_date, "--to-date") if args.to_date else None
    if start and end and start > end:
        raise ValueError("--from-date must not be later than --to-date.")
    selected = filters.filtered_entries(parsed.entries, languages, sections, start, end)
    if not selected:
        raise ValueError("The filters selected no articles.")
    filters.validate_compact_image_names(selected)
    return selected


def preview_dullgpt_log(compact, metadata, truncations):
    if metadata.get("SLUG") != "dullgpt":
        return compact

    def shorten(match):
        raw = match.group(1).rstrip()
        # Recognize the output log by its content. Do not truncate the Python
        # program or assume that the log is always the second code block.
        if not re.match(r"Input: .*?, Output:", raw):
            return match.group(0)
        if "[TRUNCATED:" in raw:
            return match.group(0)  # Legacy TXT already contains its preview.
        lines = raw.split("\n")
        if len(lines) <= DULLGPT_MAX_LINES and len(raw) <= DULLGPT_MAX_CHARS:
            return match.group(0)
        visible = "\n".join(lines[:DULLGPT_MAX_LINES]).rstrip()
        shown_lines = min(len(lines), DULLGPT_MAX_LINES)
        if len(visible) > DULLGPT_MAX_CHARS:
            visible = visible[:DULLGPT_MAX_CHARS].rstrip()
            shown_lines = len(visible.split("\n")) if visible else 0
        omitted_lines = max(0, len(lines) - shown_lines)
        omitted_chars = len(raw) - len(visible)
        truncations.append({"slug": metadata["SLUG"], "language": metadata.get("LANGUAGE"),
                            "original_lines": len(lines), "original_characters": len(raw),
                            "shown_lines": shown_lines, "shown_characters": len(visible),
                            "omitted_lines": omitted_lines, "omitted_characters": omitted_chars})
        note = (f"[TRUNCATED: original code/output block had {len(lines)} lines and {len(raw)} characters; "
                f"showing first {shown_lines} lines. Omitted {omitted_lines} lines and {omitted_chars} characters.]")
        return "\n".join(["[CODE BLOCK]", visible, "", note,
                          "See the full website source or rendered post for the complete version.",
                          "[/CODE BLOCK]"])

    return re.sub(r"^\[CODE BLOCK\]\n(.*?)^\[/CODE BLOCK\]", shorten, compact, flags=re.M | re.S)


def compact_document(parsed, entries, filters, args, truncations=None, heading_ranges=None):
    if truncations is None:
        truncations = []
    sections = sorted({entry.metadata["SECTION"] for entry in entries})
    languages = sorted({entry.metadata["LANGUAGE"] for entry in entries})
    header = [
        "ALL_POSTS",
        "Source: https://vojtamaur.cz/ | Author: Vojta Maur",
        f"Derived from: {parsed.source_name}",
        f"Selection: {len(entries)} articles | Languages: {', '.join(languages)}"
        f" | Sections: {', '.join(sections)}",
    ]
    generated = filters.extract_source_generated(parsed.preamble)
    if generated:
        header.append(f"Source generated: {generated}")
    if args.from_date or args.to_date:
        header.append(f"Dates: {args.from_date or 'unbounded'} to {args.to_date or 'unbounded'}")
    header.extend([
        "Format: [title|YYYY-MM]; media: [img:filename|ALT: ...|CAPTION: ...]"
        " or [video/pdf/interactive|SOURCE: ...]. Media files are not included.",
        "PDF line breaks are shown as wide gaps, including in code. The adjacent UTF-8 TXT"
        " preserves compact-source line breaks and code indentation."
        " Unsupported font characters appear as [U+XXXX] in the PDF only.",
    ])
    blocks = ["\n".join(header)]
    for entry in entries:
        compact = filters.serialize_compact_entry(entry)
        if not args.full_dullgpt_log:
            compact = preview_dullgpt_log(compact, entry.metadata, truncations)
        # Bilingual selections need an explicit language marker in the reading layer.
        if len(languages) > 1:
            compact = f"[LANG: {entry.metadata['LANGUAGE']}]\n" + compact
        blocks.append(compact)
    if truncations:
        header.append("DullGPT output log shortened to the same preview limits as ALL_POSTS.txt"
                      " (120 lines / 12000 characters); the full log remains in the source JSON.")
        blocks[0] = "\n".join(header)
    if heading_ranges is not None:
        offset = len(blocks[0]) + 2
        for block in blocks[1:]:
            # Only the actual article heading is emphasized. Lookalike date
            # records in prose, code and media descriptions remain ordinary.
            start = block.index("\n") + 1 if len(languages) > 1 else 0
            end = block.find("\n", start)
            if end < 0:
                end = len(block)
            heading_ranges.append((offset + start, offset + end))
            offset += len(block) + 2
    return "\n\n".join(blocks) + "\n"


def font_paths(args):
    win = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
    candidates = [win / "arial.ttf",
        Path("/usr/share/fonts/truetype/msttcorefonts/Arial.ttf"),
        Path("/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf"),
        Path("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"),
        Path("/System/Library/Fonts/Supplemental/Arial.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")]
    primary = args.font.expanduser().resolve() if args.font else next(
        (path for path in candidates if path.is_file()), None)
    if primary is None or not primary.is_file():
        raise ValueError("No suitable primary font found. Supply --font path/to/font.ttf.")
    explicit = [path.expanduser().resolve() for path in args.fallback_font]
    for path in explicit:
        if not path.is_file():
            raise ValueError(f"Fallback font not found: {path}")
    automatic = [win / "seguisym.ttf", win / "msyh.ttc", win / "seguiemj.ttf",
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")]
    paths = [primary, *explicit, *(path for path in automatic if path.is_file())]
    return list(dict.fromkeys(paths))


class Fonts:
    """Embedded fonts with measured fallback, never silent missing-glyph boxes."""

    def __init__(self, paths, source, size, char_spacing=-0.2):
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        self.size = size
        self.char_spacing = char_spacing
        self.by_char = {}
        self.paths = []
        self.names = []
        needed = {char for char in source if not char.isspace()} | set("[U+0123456789ABCDEF] ")
        for index, path in enumerate(paths):
            name = f"MoMFont{index}"
            font = TTFont(name, str(path))
            # ReportLab versions in use can emit invalid ToUnicode mappings for
            # supplementary-plane glyphs. Preserve those as explicit code points
            # rather than producing a PDF whose text cannot be recovered.
            covered = {char for char in needed if ord(char) <= 0xFFFF
                       and ord(char) in font.face.charToGlyph}
            if index == 0 or covered:
                pdfmetrics.registerFont(font)
                self.paths.append(path)
                self.names.append(name)
                for char in covered:
                    self.by_char[char] = name
                needed -= covered
            if not needed:
                break
        primary = self.names[0]
        if any(char not in self.by_char for char in "[U+0123456789ABCDEF] "):
            raise ValueError("The selected fonts must contain basic Latin letters, digits and spaces.")
        self.widths = {char: pdfmetrics.stringWidth(char, name, size)
                       for char, name in self.by_char.items()}
        self.primary = primary
        self.escaped = Counter(char for char in source
                               if not char.isspace() and char not in self.by_char)

    def prepare(self, source):
        return "".join(f"[U+{ord(char):04X}]" if char in self.escaped else char
                       for char in source)

    def width(self, text):
        return self.advance(text) - self.char_spacing if text else 0.0

    def advance(self, text):
        # PDF Tc advances after every glyph, but the last tracking interval is
        # outside the visible width of a completed line.
        return sum(self.widths[char] + self.char_spacing for char in text)

    def runs(self, text):
        name, run = None, []
        for char in text:
            current = self.by_char[char]
            if current != name and run:
                yield name, "".join(run)
                run = []
            name = current
            run.append(char)
        if run:
            yield name, "".join(run)


def flow_lines(source, fonts, column_width, gap_spaces):
    """Greedy wrapping, preserving every non-whitespace character, including URLs.

    Logical line breaks become seven spaces; ordinary spaces stay ordinary.
    A separator at a physical line/column/page boundary is consumed as a break.
    Media records and URLs may also wrap after punctuation, as in the reference.
    Oversize words are split without inserting a hyphen or dropping characters.
    """
    line = ""
    advance = 0.0
    pending = ""
    for token in re.findall(r"\s+|\S+", source):
        if token.isspace():
            token = token.replace("\r\n", "\n").replace("\r", "\n")
            pending = (" " * gap_spaces if "\n" in token else
                       " " * len(token.expandtabs(4)))
            continue
        # Treat URL/path and compact-record punctuation as break opportunities.
        # Keeping an entire long filename indivisible previously left large
        # empty portions of columns, even when it contained many legal breaks.
        pieces = re.findall(r"[^/\-_|?&=#]*[/\-_|?&=#]|[^/\-_|?&=#]+$", token)
        for index, piece in enumerate(pieces):
            separator = pending if line and index == 0 else ""
            addition = fonts.advance(separator + piece)
            if line and advance + addition - fonts.char_spacing > column_width + 1e-8:
                yield line, advance - fonts.char_spacing, True
                line, advance, separator = "", 0.0, ""
            if fonts.width(piece) > column_width + 1e-8:
                for char in piece:
                    step = fonts.widths[char] + fonts.char_spacing
                    if fonts.widths[char] > column_width or step <= 0:
                        raise ValueError("Font size or character spacing does not fit the column.")
                    if line and advance + step - fonts.char_spacing > column_width + 1e-8:
                        yield line, advance - fonts.char_spacing, True
                        line, advance = "", 0.0
                    line += char
                    advance += step
            else:
                line += separator + piece
                advance += fonts.advance(separator + piece)
        pending = ""
    if line:
        yield line, advance - fonts.char_spacing, False


def heading_positions(source, ranges, fonts):
    """Map article headings to non-whitespace positions after glyph escaping.

    Physical wrapping and expanded newline gaps do not change these positions,
    so emphasis survives a line, column or page boundary without guessing from
    title/date patterns in the body text.
    """
    positions = set()
    cursor = offset = 0
    for start, end in ranges:
        offset += len(re.sub(r"\s+", "", fonts.prepare(source[cursor:start])))
        count = len(re.sub(r"\s+", "", fonts.prepare(source[start:end])))
        positions.update(range(offset, offset + count))
        offset += count
        cursor = end
    return positions


def styled_runs(text, fonts, bold_positions, position):
    key, run = None, []
    for char in text:
        current = (fonts.by_char[char], position in bold_positions)
        if current != key and run:
            yield *key, "".join(run)
            run = []
        key = current
        run.append(char)
        if not char.isspace():
            position += 1
    if run:
        yield *key, "".join(run)


def render_pdf(path, source, fonts, args, bold_positions=None):
    from reportlab.pdfgen.canvas import Canvas
    from reportlab.pdfbase.pdfmetrics import getAscentDescent
    width, height = args.page_width_mm * MM, args.page_height_mm * MM
    margin, top, gap = args.margin_mm * MM, args.top_margin_mm * MM, args.column_gap_mm * MM
    column_width = (width - 2 * margin - (args.columns - 1) * gap) / args.columns
    leading = args.font_size * args.line_height
    # Leave a full font-size cell at each frame boundary for ascenders/descenders.
    rows = math.floor((height - top - margin - args.font_size) / leading) + 1
    grid_height = (rows - 1) * leading + args.font_size
    grid_inset = (height - top - margin - grid_height) / 2
    _, descent = getAscentDescent(fonts.primary, args.font_size)
    first_baseline = height - top - grid_inset - (args.font_size + descent)
    canvas = Canvas(str(path), pagesize=(width, height), pageCompression=1)
    canvas.setTitle("vojtamaur.cz - ALL_POSTS")
    canvas.setAuthor("Vojta Maur")
    canvas.setCreator(f"export-site-mom-like.py {SCRIPT_VERSION}")
    canvas.setSubject("Text-only compact archive; source line breaks rendered as wide gaps.")
    # Fill-and-stroke produces heavier headings using the same embedded glyphs
    # and advances. This preserves the calibrated density and page count.
    canvas.setLineWidth(args.font_size * 0.02)
    bold_positions = bold_positions or set()
    position = 0
    page_number, column, row, count = 1, 0, 0, 0

    def footer():
        if args.page_numbers:
            from reportlab.pdfbase.pdfmetrics import stringWidth
            label = str(page_number)
            x = (width - stringWidth(label, fonts.primary, args.font_size)) / 2
            obj = canvas.beginText(x, max(1, (margin - args.font_size) / 2))
            obj.setWordSpace(0)
            obj.setCharSpace(0)
            obj.setTextRenderMode(0)
            obj.setFont(fonts.primary, args.font_size)
            obj.textOut(label)
            canvas.drawText(obj)

    for text, text_width, justify in flow_lines(source, fonts, column_width, args.line_gap_spaces):
        if row == rows:
            row, column = 0, column + 1
        if column == args.columns:
            footer()
            canvas.showPage()
            canvas.setLineWidth(args.font_size * 0.02)
            page_number, column = page_number + 1, 0
        x = margin + column * (column_width + gap)
        y = first_baseline - row * leading
        extra_space = max(0, (column_width - text_width) / text.count(" ")) if justify and " " in text else 0
        for name, bold, run in styled_runs(text, fonts, bold_positions, position):
            # PDF text mode survives BT/ET, while ReportLab initializes each
            # text object as ordinary. Isolate runs so bold cannot leak into
            # subsequent prose, and position them using the measured advances.
            canvas.saveState()
            obj = canvas.beginText(x, y)
            obj.setCharSpace(fonts.char_spacing)
            obj.setWordSpace(extra_space)
            obj.setFont(name, args.font_size)
            obj.setTextRenderMode(2 if bold else 0)
            obj.textOut(run)
            canvas.drawText(obj)
            canvas.restoreState()
            x += fonts.advance(run) + extra_space * run.count(" ")
        position += len(re.sub(r"\s+", "", text))
        row += 1
        count += 1
    footer()
    canvas.save()
    return {"pages": page_number, "lines": count, "lines_per_column": rows,
            "column_width_mm": column_width / MM,
            "text_frame_width_mm": (width - 2 * margin) / MM,
            "text_frame_height_mm": (height - top - margin) / MM,
            "vertical_grid_inset_mm": grid_inset / MM}


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def verify_pdf(path, expected, args, pages):
    from pypdf import PdfReader
    reader = PdfReader(path)
    if len(reader.pages) != pages:
        raise ValueError("PDF verification failed: page count mismatch.")
    extracted = []
    for page in reader.pages:
        if abs(float(page.mediabox.width) - args.page_width_mm * MM) > 0.02 or abs(
                float(page.mediabox.height) - args.page_height_mm * MM) > 0.02:
            raise ValueError("PDF verification failed: page dimensions mismatch.")
        if page.images:
            raise ValueError("PDF verification failed: unexpected embedded images.")
        text = page.extract_text()
        if args.page_numbers:
            text = text.rstrip()
            number = str(len(extracted) + 1)
            if not text.endswith("\n" + number):
                raise ValueError("PDF verification failed: missing page number.")
            text = text[:-(len(number) + 1)]
        extracted.append(text)
    normalize = lambda text: re.sub(r"\s+", "", text)
    if normalize("".join(extracted)) != normalize(expected):
        raise ValueError("PDF verification failed: extracted characters differ from the source.")


def export(args):
    validate_args(args)
    root = args.project_root.expanduser().resolve()
    filters = load_filter(root)
    input_path = resolve_path(root, args.input)
    default_output = Path(DEFAULT_OUTPUT)
    if args.lang != "cs":
        language = "cs-en" if args.lang == "both" else args.lang
        default_output = default_output.with_name(f"{default_output.stem}-{language}.pdf")
    output_path = (resolve_path(root, args.output) if args.output is not None
                   else stamped_path(root / default_output, timestamp_for(args)))
    if output_path.suffix.lower() != ".pdf":
        raise ValueError("--output must end in .pdf.")
    text_path = output_path.with_suffix(".txt")
    manifest_path = output_path.with_suffix(".manifest.json")
    if input_path in (output_path, text_path, manifest_path):
        raise ValueError("Output files must not overwrite the input snapshot.")
    input_bytes = input_path.read_bytes()
    parsed = filters.parse_export(input_path)
    if input_path.read_bytes() != input_bytes:
        raise ValueError("The input changed while it was being read. Please retry.")
    entries = select_entries(parsed, filters, args)
    truncations = []
    headings = []
    source = compact_document(parsed, entries, filters, args, truncations, headings)
    fonts = Fonts(font_paths(args), source, args.font_size, args.char_spacing)
    prepared = fonts.prepare(source)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".mom-like-", dir=output_path.parent) as temporary:
        folder = Path(temporary)
        pdf = folder / output_path.name
        layout = render_pdf(pdf, prepared, fonts, args, heading_positions(source, headings, fonts))
        verify_pdf(pdf, prepared, args, layout["pages"])
        text_bytes = source.encode("utf-8")
        txt = folder / text_path.name
        txt.write_bytes(text_bytes)
        data = {
            "generator": f"export-site-mom-like.py {SCRIPT_VERSION}",
            "generated_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
            "input": {"path": str(input_path), "bytes": len(input_bytes), "sha256": sha256(input_bytes),
                      "articles_total": len(parsed.entries), "articles_selected": len(entries)},
            "selection": {"language": args.lang, "sections": filters.split_values(args.section) and
                          sorted(filters.split_values(args.section)) or ["all"],
                          "from_date": args.from_date, "to_date": args.to_date},
            "articles": [{key: entry.metadata[key] for key in ("LANGUAGE", "SECTION", "SLUG", "DATE", "URL")
                          if key in entry.metadata} for entry in entries],
            "layout": {**{key: getattr(args, key) for key in ("page_width_mm", "page_height_mm", "columns",
                        "font_size", "char_spacing", "line_height", "line_gap_spaces", "margin_mm", "top_margin_mm",
                        "column_gap_mm", "page_numbers")}, **layout, "alignment": "justified",
                       "article_headings": "bold title and date (fill-and-stroke)",
                       "headings_emphasized": len(headings),
                       "fonts": [{"path": str(path), "sha256": sha256(path.read_bytes())} for path in fonts.paths]},
            "content": {"text_only": True, "source_characters": len(source),
                        "embedded_images": 0, "code_layout": "flow; original indentation and lines in TXT",
                        "dullgpt_log": {"full": args.full_dullgpt_log,
                            "max_lines": DULLGPT_MAX_LINES, "max_characters": DULLGPT_MAX_CHARS,
                            "truncated_blocks": truncations},
                        "unsupported_characters": {f"U+{ord(char):04X}": count
                                                   for char, count in sorted(fonts.escaped.items())}},
            "verification": {"all_non_whitespace_characters_match": True},
            "output": {"path": str(output_path), "pages": layout["pages"],
                       "bytes": pdf.stat().st_size, "sha256": sha256(pdf.read_bytes())},
            "text_output": {"path": str(text_path), "encoding": "UTF-8", "bytes": len(text_bytes),
                            "sha256": sha256(text_bytes)},
        }
        manifest = folder / manifest_path.name
        manifest.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        # Only publish outputs after the complete PDF has passed verification.
        pdf.replace(output_path)
        txt.replace(text_path)
        manifest.replace(manifest_path)
    print(f"[done] {len(entries)} articles, {layout['pages']} pages, {output_path.stat().st_size:,} bytes")
    print(f"[pdf] {output_path}\n[text] {text_path}\n[manifest] {manifest_path}")
    if truncations:
        print(f"[compact] Shortened {len(truncations)} DullGPT output log(s); "
              f"omitted {sum(record['omitted_characters'] for record in truncations):,} log characters.")
    if fonts.escaped:
        print("[note] Unsupported font characters are written as Unicode code points in the PDF: "
              + ", ".join(f"U+{ord(char):04X} ({count})" for char, count in fonts.escaped.items())
              + ". The TXT retains the source characters.", file=sys.stderr)
    return data


def main(argv=None):
    args = parse_args(argv)
    try:
        export(args)
    except ImportError as exc:
        raise SystemExit("Missing dependency. Run: python -m pip install -r requirements-mom-like-export.txt"
                         f"\nDetails: {exc}") from exc
    except (ValueError, OSError) as exc:
        raise SystemExit(str(exc)) from exc
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
