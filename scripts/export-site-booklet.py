#!/usr/bin/env python3
"""Export ALL_POSTS as a compact A5 reader and duplex A4 booklet.

Print the imposed A4 files in landscape at actual size, one PDF page per
side, flipping on the short edge. Keep booklet mode off. Fold and stitch
each print file's stack separately. Use --print-test for a two-sheet proof.
"""

from __future__ import annotations

import argparse
from datetime import datetime
from importlib import import_module
from io import BytesIO
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from export_naming import TIMESTAMP_FORMAT, new_timestamp, stamped_path, validate_timestamp


TITLE = "ALL POSTS"
COVER_LABELS = {
    "cs": ("EDICE A5", "Jazyk: čeština", "Sekce", "Datum"),
    "en": ("A5 EDITION", "Language: English", "Sections", "Date"),
}
# Match the public section names and order in src/lib/i18n.ts.
SECTION_LABELS = {
    "cs": {"volna-tvorba": "Volná tvorba", "vystavy": "Výstavy", "cestovani": "Cestování"},
    "en": {"volna-tvorba": "Personal Work", "vystavy": "Exhibitions", "cestovani": "Travel"},
}
MM = 72 / 25.4
A5 = (148 * MM, 210 * MM)
A4_LANDSCAPE = (297 * MM, 210 * MM)
DEFAULT_FONT_SIZE = 5.5
DEFAULT_MAX_SHEETS = 10
MARGIN_MM = 7
COLUMN_GAP_MM = 2.5
TRACKING = -0.1
LINE_HEIGHT = 1.04


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--input", default="dist/ALL_POSTS.json",
                        help="JSON-LD snapshot. Relative paths use the project root (default: %(default)s).")
    parser.add_argument("--lang", "--language", choices=("cs", "en"), default="cs",
                        help="Article language (default: %(default)s).")
    parser.add_argument("--section", action="append",
                        help="Repeat or comma-separate section slugs (volna-tvorba, vystavy, cestovani). "
                             "Default: volna-tvorba (Volna tvorba). Use all for every section.")
    parser.add_argument("--full-dullgpt-log", action="store_true",
                        help="Keep the full DullGPT output log instead of the MoM-like preview.")
    parser.add_argument("--font-size", type=float, default=DEFAULT_FONT_SIZE, metavar="PT",
                        help="Body size in points, 4 to 12 (default: %(default)s).")
    parser.add_argument("--max-sheets", type=int, default=DEFAULT_MAX_SHEETS, metavar="N",
                        help="Maximum A4 sheets per foldable stack (default: %(default)s). "
                             "Use 0 to force a single stack.")
    parser.add_argument("--print-test", action="store_true",
                        help="Export only a numbered, two-sheet A4 proof for checking your printer.")
    parser.add_argument("--timestamp", type=validate_timestamp, metavar="YYYY-MM-DD_HH-MM-SS-ffffff",
                        help="Override the shared export timestamp (default: local export start time).")
    args = parser.parse_args(argv)
    if not 4 <= args.font_size <= 12:
        parser.error("--font-size must be between 4 and 12.")
    if args.max_sheets < 0:
        parser.error("--max-sheets must be non-negative.")
    return args


def compact_source(entries, filters, mom, *, full_dullgpt_log):
    blocks = []
    headings = []
    truncations = []
    offset = 0
    for entry in entries:
        block = filters.serialize_compact_entry(entry)
        if not full_dullgpt_log:
            block = mom.preview_dullgpt_log(block, entry.metadata, truncations)
        headings.append((offset, offset + len(block.split("\n", 1)[0])))
        blocks.append(block)
        offset += len(block) + 2
    return "\n\n".join(blocks), headings, truncations


def cover_lines(lang, sections, stamp):
    subtitle, language, section_label, date_label = COVER_LABELS[lang]
    labels = SECTION_LABELS[lang]
    section_names = [label for slug, label in labels.items() if slug in sections]
    section_names.extend(sorted(sections - labels.keys()))
    date = datetime.strptime(stamp, TIMESTAMP_FORMAT).date()
    date_text = f"{date.day}. {date.month}. {date.year}" if lang == "cs" else date.isoformat()
    return [TITLE, subtitle, language, f"{section_label}: {', '.join(section_names)}", f"{date_label}: {date_text}"]


def render_reader(path, body_path, source, heading_ranges, font_size, mom, cover):
    from pypdf import PdfReader, PdfWriter
    from reportlab.pdfgen.canvas import Canvas

    layout = SimpleNamespace(
        page_width_mm=148, page_height_mm=210, columns=2,
        margin_mm=MARGIN_MM, top_margin_mm=MARGIN_MM, column_gap_mm=COLUMN_GAP_MM,
        font_size=font_size, line_height=LINE_HEIGHT, char_spacing=TRACKING, line_gap_spaces=5,
        font=None, fallback_font=[], page_numbers=False,
    )
    fonts = mom.Fonts(mom.font_paths(layout), source, font_size, layout.char_spacing)
    bold = mom.heading_positions(source, heading_ranges, fonts)
    prepared = fonts.prepare(source)
    body_pages = mom.render_pdf(body_path, prepared, fonts, layout, bold, heading_stroke=0.045)["pages"]

    overlays = BytesIO()
    canvas = Canvas(overlays, pagesize=A5, pageCompression=1)
    width, height = A5
    canvas.setFont("Helvetica-Bold", 22)
    canvas.drawCentredString(width / 2, height / 2 + 31, cover[0])
    canvas.setFont("Helvetica", 10)
    canvas.drawCentredString(width / 2, height / 2 + 12, cover[1])
    canvas.setFont(fonts.primary, 9)
    for row, line in enumerate(cover[2:]):
        canvas.drawCentredString(width / 2, height / 2 - 10 - 14 * row, line)
    canvas.showPage()
    for number in range(2, body_pages + 2):
        canvas.setFont("Helvetica", 6)
        canvas.drawCentredString(width / 2, 4 * MM, str(number))
        canvas.showPage()
    canvas.save()

    writer = PdfWriter()
    writer.add_metadata({"/Title": f"{cover[0]} / {cover[1]}", "/Creator": "export-site-booklet.py"})
    overlay_pages = PdfReader(overlays).pages
    writer.add_page(overlay_pages[0])
    for index, body_page in enumerate(PdfReader(body_path).pages, start=1):
        numbered = writer.add_page(body_page)
        numbered.merge_page(overlay_pages[index])
        numbered.compress_content_streams()
    writer.write(path)

    # Verify the final reader, including the number added to each body page.
    pages = PdfReader(path).pages
    if len(pages) != body_pages + 1 or pages[0].extract_text().split() != " ".join(cover).split():
        raise ValueError("Reader verification failed: cover or page count mismatch.")
    content = []
    for number, page in enumerate(pages[1:], start=2):
        body, _, footer = page.extract_text().rstrip().rpartition("\n")
        if footer != str(number):
            raise ValueError(f"Reader verification failed: missing page number {number}.")
        content.append("".join(body.split()))
    if "".join(content) != "".join(prepared.split()):
        raise ValueError("Reader verification failed: PDF text differs from the compact source.")
    if fonts.escaped:
        print("[note] Unsupported glyphs printed as explicit Unicode code points: "
              + ", ".join(f"U+{ord(char):04X} ({count})" for char, count in sorted(fonts.escaped.items())),
              file=sys.stderr)


def impose(pages, path, *, title=f"{TITLE} / A5 EDITION - A4 print"):
    """Write one nested stack, outer sheet first, front then back."""
    from pypdf import PdfWriter
    from pypdf.generic import DictionaryObject, NameObject

    writer = PdfWriter()
    writer.pdf_header = "%PDF-1.7"
    writer.add_metadata({"/Title": title, "/Creator": "export-site-booklet.py"})
    writer.root_object[NameObject("/ViewerPreferences")] = DictionaryObject({
        NameObject("/Duplex"): NameObject("/DuplexFlipShortEdge"),
        NameObject("/PrintScaling"): NameObject("/None"),
    })
    half_width = A4_LANDSCAPE[0] / 2
    inset = (half_width - A5[0]) / 2  # A4's half-sheet is 0.5 mm wider than ISO A5.
    padded = list(pages) + [None] * (-len(pages) % 4)
    last = len(padded) - 1
    for offset in range(0, len(padded) // 2, 2):
        for left, right in ((last - offset, offset), (offset + 1, last - offset - 1)):
            side = writer.add_blank_page(*A4_LANDSCAPE)
            for index, x in ((left, inset), (right, half_width + inset)):
                if padded[index] is not None:
                    side.merge_translated_page(padded[index], x, 0)
            side.compress_content_streams()
    writer.write(path)


def print_test(path, font_size, mom):
    from pypdf import PdfReader
    from reportlab.pdfgen.canvas import Canvas

    sample = ("Příliš žluťoučký kůň úpěl ďábelské ódy. The quick brown fox jumps over the lazy dog. "
              "Při skutečné velikosti by měl být tento text ostrý, včetně háčků a čárek. "
              "At actual size, this paragraph uses the same type size and line spacing as the booklet.")
    fonts = mom.Fonts(mom.font_paths(SimpleNamespace(font=None, fallback_font=[])),
                      sample, font_size, TRACKING)
    stream = BytesIO()
    canvas = Canvas(stream, pagesize=A5, pageCompression=1)
    width, height = A5
    column_width = (width - (2 * MARGIN_MM + COLUMN_GAP_MM) * MM) / 2
    lines = list(mom.flow_lines(fonts.prepare(sample), fonts, column_width, 5))
    for number in range(1, 9):
        canvas.setFont("Helvetica-Bold", 12)
        canvas.drawCentredString(width / 2, height - 13 * MM, "TOP EDGE")
        canvas.setFont("Helvetica-Bold", 52)
        canvas.drawCentredString(width / 2, height / 2, str(number))
        canvas.setFont("Helvetica", 8)
        canvas.drawCentredString(width / 2, 68 * MM, f"Print sample at {font_size:g} pt")
        for row, (line, _, _) in enumerate(lines):
            x = (width - column_width) / 2
            y = 62 * MM - row * font_size * LINE_HEIGHT
            for name, run in fonts.runs(line):
                obj = canvas.beginText(x, y)
                obj.setFont(name, font_size)
                obj.setCharSpace(TRACKING)
                obj.textOut(run)
                canvas.drawText(obj)
                x += fonts.advance(run)
        canvas.showPage()
    canvas.save()
    impose(PdfReader(stream).pages, path)


def export(args, root, stamp, mom):
    from pypdf import PdfReader

    exports = root / "exports"
    basename = f"ALL_POSTS-A5-{args.lang}"
    edition = stamped_path(exports / basename, stamp)
    if edition.exists():
        raise ValueError(f"This edition already exists: {edition}. Use a new timestamp.")
    filters = mom.load_filter(root)
    input_path = mom.resolve_path(root, args.input)
    parsed = filters.parse_json_export(input_path.read_text(encoding="utf-8-sig"))
    sections = filters.split_values(args.section or ["volna-tvorba"])
    filters.validate_requested_values(sections, filters.available_values(parsed.entries, "SECTION"), "section")
    filters.validate_requested_values({args.lang}, filters.available_values(parsed.entries, "LANGUAGE"), "language")
    entries = filters.filtered_entries(parsed.entries, {args.lang}, sections, None, None)
    if not entries:
        raise ValueError("The filters selected no articles.")
    filters.validate_compact_image_names(entries)
    source, headings, truncations = compact_source(entries, filters, mom, full_dullgpt_log=args.full_dullgpt_log)
    selected_sections = {entry.metadata["SECTION"] for entry in entries}
    cover = cover_lines(args.lang, selected_sections, stamp)
    print_label = "tisk A4" if args.lang == "cs" else "A4 print"

    exports.mkdir(exist_ok=True)
    with TemporaryDirectory(prefix=".booklet-", dir=exports) as temp:
        staging = Path(temp) / "edition"
        staging.mkdir()
        reader = stamped_path(staging / f"{basename}-read.pdf", stamp)
        render_reader(reader, Path(temp) / "body.pdf", source, headings, args.font_size, mom, cover)
        pages = PdfReader(reader).pages
        pages_per_stack = args.max_sheets * 4 or len(pages)
        starts = range(0, len(pages), pages_per_stack)
        stack_reports = []
        for part, start in enumerate(starts, start=1):
            stack = pages[start:start + pages_per_stack]
            name = f"{basename}-print-a4-{part:02d}-of-{len(starts):02d}.pdf"
            print_path = stamped_path(staging / name, stamp)
            impose(stack, print_path, title=f"{cover[0]} / {cover[1]} - {print_label}")
            sheets = (len(stack) + 3) // 4
            stack_reports.append(f"[print] {print_path.name}: {sheets} A4 sheets, "
                                 f"A5 pages {start + 1}-{start + len(stack)}")
        staging.rename(edition)

    print(f"[done] {len(entries)} articles ({args.lang}: {', '.join(sorted(selected_sections))}), {len(pages)} A5 pages")
    print(f"[read] {edition / reader.name}")
    print("\n".join(stack_reports))
    if truncations:
        omitted = sum(record["omitted_characters"] for record in truncations)
        print(f"[compact] DullGPT output log shortened by {omitted:,} characters. "
              "Use --full-dullgpt-log to keep it complete.")
    if args.max_sheets == 0 and len(pages) > DEFAULT_MAX_SHEETS * 4:
        print(f"[note] Single stack exceeds {DEFAULT_MAX_SHEETS} sheets. Check fold and stitch on your paper.")


def main(argv=None):
    args = parse_args(argv)
    root = Path(__file__).resolve().parent.parent
    try:
        stamp = args.timestamp or new_timestamp()
        mom = import_module("export-site-mom-like")
        if args.print_test:
            exports = root / "exports"
            exports.mkdir(exist_ok=True)
            path = stamped_path(exports / "ALL_POSTS-A5-test-print-a4.pdf", stamp)
            if path.exists():
                raise ValueError(f"This print test already exists: {path}. Use a new timestamp.")
            with TemporaryDirectory(prefix=".booklet-", dir=exports) as temp:
                proof = Path(temp) / path.name
                print_test(proof, args.font_size, mom)
                proof.rename(path)
            print(f"[print test] {path} (2 A4 sheets, duplex short edge)")
        else:
            export(args, root, stamp, mom)
    except ImportError as exc:
        raise SystemExit("Missing dependency. Run: python -m pip install -r requirements-mom-like-export.txt"
                         f"\nDetails: {exc}") from exc
    except (argparse.ArgumentTypeError, ValueError, OSError) as exc:
        raise SystemExit(str(exc)) from exc
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
