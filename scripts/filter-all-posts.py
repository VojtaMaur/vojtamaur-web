#!/usr/bin/env python3
"""Create a filtered plain-text subset of dist/ALL_POSTS.txt.

The script is deliberately independent of the website build. When stored as
scripts/filter-all-posts.py, it finds the repository root automatically and
uses dist/ALL_POSTS.txt as its default input.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import sys
import tempfile
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Iterable, Sequence


SEPARATOR = "=" * 60
HEADER_RE = re.compile(
    rf"(?m)^{re.escape(SEPARATOR)}\n"
    rf"(?P<metadata>(?:[A-Z][A-Z0-9_]*: [^\n]*\n)+)"
    rf"^{re.escape(SEPARATOR)}(?:\n|$)"
)
METADATA_PROFILES: dict[str, tuple[str, ...] | None] = {
    "full": None,
    "archive": ("TITLE", "URL", "LANGUAGE", "SECTION", "DATE"),
    "minimal": ("TITLE", "LANGUAGE", "SECTION", "DATE"),
    "none": (),
}
COMPACT_EMBED_KINDS = {
    "[VIDEO EMBED]": "video",
    "[PDF EMBED]": "pdf",
    "[INTERACTIVE EMBED]": "interactive",
}
COMPACT_DETAIL_PREFIXES = (
    "FILE: ",
    "ALT: ",
    "CAPTION: ",
    "SOURCE: ",
    "TITLE: ",
    "NOTE: ",
)
GENERIC_EMBED_NOTE = (
    "NOTE: Embedded or binary content is not represented in this plain-text export."
)
RENDERED_MONTH_RE = re.compile(
    r"^(?:"
    r"leden|únor|březen|duben|květen|červen|červenec|srpen|září|říjen|listopad|prosinec|"
    r"january|february|march|april|may|june|july|august|september|october|november|december"
    r")\s+(?:19|20)\d{2}$",
    re.IGNORECASE,
)


class ExportError(ValueError):
    """Raised when the source export is malformed or arguments are invalid."""


@dataclass(frozen=True)
class Entry:
    metadata: dict[str, str]
    metadata_order: tuple[str, ...]
    body: str


@dataclass(frozen=True)
class ParsedExport:
    preamble: str
    entries: tuple[Entry, ...]


def repository_root() -> Path:
    """Return the expected repository root for a script stored in scripts/."""
    script_dir = Path(__file__).resolve().parent
    if script_dir.name.lower() == "scripts":
        return script_dir.parent
    return script_dir


def parse_iso_date(value: str, option_name: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ExportError(
            f"{option_name} must use the YYYY-MM-DD format, got {value!r}."
        ) from exc


def parse_export(path: Path) -> ParsedExport:
    try:
        data = path.read_bytes()
    except FileNotFoundError as exc:
        raise ExportError(f"Input file does not exist: {path}") from exc
    except OSError as exc:
        raise ExportError(f"Cannot read input file {path}: {exc}") from exc

    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ExportError(f"Input is not valid UTF-8: {path}") from exc

    # Parsing is independent of whether the build was produced on Windows or Unix.
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    matches = list(HEADER_RE.finditer(text))
    if not matches:
        raise ExportError(
            "No article blocks were found. Expected blocks delimited by a "
            f"{len(SEPARATOR)}-character '=' line."
        )

    entries: list[Entry] = []
    for index, match in enumerate(matches):
        metadata: dict[str, str] = {}
        order: list[str] = []
        for line in match.group("metadata").splitlines():
            key, value = line.split(": ", 1)
            if key in metadata:
                raise ExportError(
                    f"Article block {index + 1} contains duplicate metadata key {key}."
                )
            metadata[key] = value
            order.append(key)

        body_end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        body = text[match.end() : body_end].strip("\n")
        if not body.strip():
            raise ExportError(f"Article block {index + 1} has an empty body.")
        entries.append(Entry(metadata, tuple(order), body))

    preamble = text[: matches[0].start()].strip("\n")
    return ParsedExport(preamble, tuple(entries))


def split_values(raw_values: Sequence[str] | None) -> set[str] | None:
    if not raw_values:
        return None
    values = {
        item.strip()
        for raw in raw_values
        for item in raw.split(",")
        if item.strip()
    }
    if not values or values == {"all"}:
        return None
    if "all" in values:
        raise ExportError("'all' cannot be combined with specific values.")
    return values


def available_values(entries: Iterable[Entry], field: str) -> set[str]:
    return {entry.metadata[field] for entry in entries if field in entry.metadata}


def validate_requested_values(
    requested: set[str] | None,
    available: set[str],
    option_name: str,
) -> None:
    if requested is None:
        return
    unknown = requested - available
    if unknown:
        raise ExportError(
            f"Unknown {option_name} value(s): {', '.join(sorted(unknown))}. "
            f"Available: {', '.join(sorted(available))}."
        )


def ensure_field(entries: Iterable[Entry], field: str, purpose: str) -> None:
    missing = [
        str(index)
        for index, entry in enumerate(entries, start=1)
        if field not in entry.metadata
    ]
    if missing:
        sample = ", ".join(missing[:5])
        suffix = "..." if len(missing) > 5 else ""
        raise ExportError(
            f"Cannot {purpose}: metadata field {field} is missing in article "
            f"block(s) {sample}{suffix}."
        )


def filtered_entries(
    entries: Sequence[Entry],
    languages: set[str] | None,
    sections: set[str] | None,
    date_from: date | None,
    date_to: date | None,
) -> list[Entry]:
    if languages is not None:
        ensure_field(entries, "LANGUAGE", "filter by language")
    if sections is not None:
        ensure_field(entries, "SECTION", "filter by section")
    if date_from is not None or date_to is not None:
        ensure_field(entries, "DATE", "filter by date")

    result: list[Entry] = []
    for entry in entries:
        if languages is not None and entry.metadata["LANGUAGE"] not in languages:
            continue
        if sections is not None and entry.metadata["SECTION"] not in sections:
            continue
        if date_from is not None or date_to is not None:
            entry_date = parse_iso_date(entry.metadata["DATE"], "article DATE")
            if date_from is not None and entry_date < date_from:
                continue
            if date_to is not None and entry_date > date_to:
                continue
        result.append(entry)
    return result


def parse_metadata_fields(
    raw_fields: Sequence[str] | None,
    profile: str,
    entries: Sequence[Entry],
) -> tuple[str, ...] | None:
    if not raw_fields:
        fields = METADATA_PROFILES[profile]
    else:
        parsed = [
            item.strip().upper()
            for raw in raw_fields
            for item in raw.split(",")
            if item.strip()
        ]
        fields = tuple(dict.fromkeys(parsed))

    if fields is None:
        return None

    for field in fields:
        ensure_field(entries, field, "write selected metadata")
    return fields


def extract_source_generated(preamble: str) -> str | None:
    match = re.search(r"(?m)^Generated: (.+)$", preamble)
    return match.group(1).strip() if match else None


def selected_label(values: set[str] | None) -> str:
    return "all" if values is None else ", ".join(sorted(values))


def metadata_label(fields: tuple[str, ...] | None, profile: str) -> str:
    if fields is None:
        return "full (all source fields)"
    if not fields:
        return "none"
    return f"{profile} ({', '.join(fields)})"


def make_document_header(
    output_name: str,
    parsed: ParsedExport,
    selected: Sequence[Entry],
    languages: set[str] | None,
    sections: set[str] | None,
    date_from: date | None,
    date_to: date | None,
    fields: tuple[str, ...] | None,
    profile: str,
) -> str:
    source_generated = extract_source_generated(parsed.preamble)
    lines = [
        output_name,
        "Filtered plain-text export derived from vojtamaur.cz ALL_POSTS.txt.",
        "",
        "Primary website: https://vojtamaur.cz/",
    ]
    if source_generated:
        lines.append(f"Source generated: {source_generated}")
    lines.extend(
        [
            "Encoding: UTF-8 with BOM",
            f"Articles: {len(selected)} of {len(parsed.entries)}",
            f"Languages: {selected_label(languages)}",
            f"Sections: {selected_label(sections)}",
            "Date range: "
            + (
                f"{date_from.isoformat() if date_from else 'unbounded'} to "
                f"{date_to.isoformat() if date_to else 'unbounded'}"
                if date_from or date_to
                else "all"
            ),
            f"Article metadata: {metadata_label(fields, profile)}",
            "",
            "Notes:",
            "- Article order and textual content are preserved from the source export.",
            "- Media and embedded content remain represented by textual placeholders.",
            "- Filtering does not recover content truncated in the source export.",
        ]
    )
    return "\n".join(lines)


def make_compact_document_header(
    output_name: str,
    parsed: ParsedExport,
    selected: Sequence[Entry],
    languages: set[str] | None,
    sections: set[str] | None,
    date_from: date | None,
    date_to: date | None,
) -> str:
    source_generated = extract_source_generated(parsed.preamble)
    lines = [
        output_name,
        "Compact plain-text export derived from vojtamaur.cz ALL_POSTS.txt.",
        "",
        "Primary website: https://vojtamaur.cz/",
    ]
    if source_generated:
        lines.append(f"Source generated: {source_generated}")
    lines.extend(
        [
            "Encoding: UTF-8 with BOM",
            f"Articles: {len(selected)} of {len(parsed.entries)}",
            f"Languages: {selected_label(languages)}",
            f"Sections: {selected_label(sections)}",
            "Date range: "
            + (
                f"{date_from.isoformat() if date_from else 'unbounded'} to "
                f"{date_to.isoformat() if date_to else 'unbounded'}"
                if date_from or date_to
                else "all"
            ),
            "Format: [rendered title|YYYY-MM]; one article per compact block.",
            "Media: [img:filename|ALT: ...|CAPTION: ...].",
            "Embeds: [video|SOURCE: ...], [pdf|SOURCE: ...], or [interactive|SOURCE: ...].",
            "Blank lines inside articles and generic embed notes are omitted.",
            "This compact format is intended for reading and transfer, not refiltering.",
        ]
    )
    return "\n".join(lines)


def serialize_entry(entry: Entry, fields: tuple[str, ...] | None) -> str:
    if fields is None:
        keys = entry.metadata_order
    else:
        keys = fields

    if not keys:
        return entry.body

    metadata = "\n".join(f"{key}: {entry.metadata[key]}" for key in keys)
    return f"{SEPARATOR}\n{metadata}\n{SEPARATOR}\n\n{entry.body}"


def compact_token(value: str) -> str:
    """Escape the delimiters used by the compact one-line records."""
    return value.replace("\\", "\\\\").replace("|", "\\|").replace("]", "\\]")


def compact_detail_lines(lines: Sequence[str], start: int) -> tuple[list[str], int]:
    details: list[str] = []
    index = start
    while index < len(lines) and lines[index].startswith(COMPACT_DETAIL_PREFIXES):
        details.append(lines[index].strip())
        index += 1
    return details, index


def compact_image_line(details: Sequence[str]) -> str | None:
    file_value = next(
        (line.removeprefix("FILE: ") for line in details if line.startswith("FILE: ")),
        None,
    )
    if not file_value:
        # Empty image placeholders occur in some grids; they carry no recoverable data.
        return None
    filename = file_value.replace("\\", "/").rsplit("/", 1)[-1]
    parts = [f"img:{compact_token(filename)}"]
    for prefix in ("ALT: ", "CAPTION: "):
        for line in details:
            if line.startswith(prefix):
                parts.append(f"{prefix}{compact_token(line.removeprefix(prefix))}")
    return "[" + "|".join(parts) + "]"


def compact_embed_line(marker: str, details: Sequence[str]) -> str:
    parts = [COMPACT_EMBED_KINDS[marker]]
    for line in details:
        if line == GENERIC_EMBED_NOTE or line.startswith("FILE: "):
            continue
        parts.append(compact_token(line))
    return "[" + "|".join(parts) + "]"


def compact_title_and_content(entry: Entry) -> tuple[str, list[str]]:
    lines = entry.body.splitlines()
    first_content = next((i for i, line in enumerate(lines) if line.strip()), None)
    if first_content is None:
        raise ExportError(f"Article {entry.metadata.get('SLUG', '<unknown>')} has no title.")

    rendered_title = lines[first_content].strip()
    del lines[first_content]

    # Normal post pages repeat a localized month/year below the rendered title.
    # Travel and exhibition pages use different secondary lines, which are content.
    next_content = next((i for i, line in enumerate(lines) if line.strip()), None)
    if next_content is not None and RENDERED_MONTH_RE.fullmatch(lines[next_content].strip()):
        del lines[next_content]
    return rendered_title, lines


def serialize_compact_entry(entry: Entry) -> str:
    ensure_field((entry,), "DATE", "write compact article headers")
    article_date = parse_iso_date(entry.metadata["DATE"], "article DATE")
    rendered_title, lines = compact_title_and_content(entry)
    output = [f"[{compact_token(rendered_title)}|{article_date.isoformat()[:7]}]"]

    in_code = False
    index = 0
    while index < len(lines):
        raw_line = lines[index].rstrip()
        stripped = raw_line.strip()
        if not stripped:
            index += 1
            continue

        if stripped == "[CODE BLOCK]":
            in_code = True
            output.append(stripped)
            index += 1
            continue
        if stripped == "[/CODE BLOCK]":
            in_code = False
            output.append(stripped)
            index += 1
            continue

        if not in_code and stripped == "[MEDIA: image]":
            details, next_index = compact_detail_lines(lines, index + 1)
            image_line = compact_image_line(details)
            if image_line:
                output.append(image_line)
            index = next_index
            continue

        if not in_code and stripped in COMPACT_EMBED_KINDS:
            details, next_index = compact_detail_lines(lines, index + 1)
            output.append(compact_embed_line(stripped, details))
            index = next_index
            continue

        # The HTML-to-text export can isolate terminal punctuation on its own line.
        if not in_code and stripped in {".", ",", ";", ":", "!", "?"} and output:
            output[-1] += stripped
        else:
            output.append(raw_line if in_code else stripped)
        index += 1

    if in_code:
        output.append("[TRUNCATED: source export code block incomplete at this point.]")
        output.append("[/CODE BLOCK]")

    return "\n".join(output)


def validate_compact_image_names(entries: Sequence[Entry]) -> None:
    """Prevent basename shortening from making two media references ambiguous."""
    paths_by_name: dict[str, set[str]] = {}
    for entry in entries:
        lines = entry.body.splitlines()
        for index, line in enumerate(lines):
            if line.strip() != "[MEDIA: image]":
                continue
            details, _ = compact_detail_lines(lines, index + 1)
            for detail in details:
                if detail.startswith("FILE: "):
                    path = detail.removeprefix("FILE: ").replace("\\", "/")
                    paths_by_name.setdefault(path.rsplit("/", 1)[-1], set()).add(path)

    ambiguous = {name: paths for name, paths in paths_by_name.items() if len(paths) > 1}
    if ambiguous:
        names = ", ".join(sorted(ambiguous)[:5])
        suffix = "..." if len(ambiguous) > 5 else ""
        raise ExportError(
            "Compact image names would be ambiguous because different paths use "
            f"the same basename: {names}{suffix}. Use --format structured instead."
        )


def serialize_export(
    parsed: ParsedExport,
    selected: Sequence[Entry],
    output_name: str,
    languages: set[str] | None,
    sections: set[str] | None,
    date_from: date | None,
    date_to: date | None,
    fields: tuple[str, ...] | None,
    profile: str,
    header_mode: str,
    output_format: str,
) -> str:
    parts: list[str] = []
    if header_mode == "generated" and output_format == "structured":
        parts.append(
            make_document_header(
                output_name,
                parsed,
                selected,
                languages,
                sections,
                date_from,
                date_to,
                fields,
                profile,
            )
        )

    if output_format == "compact":
        validate_compact_image_names(selected)
        if header_mode == "generated":
            parts.append(
                make_compact_document_header(
                    output_name,
                    parsed,
                    selected,
                    languages,
                    sections,
                    date_from,
                    date_to,
                )
            )
        parts.extend(serialize_compact_entry(entry) for entry in selected)
        return "\n\n".join(part for part in parts if part) + "\n"

    if fields == ():
        # A single separator keeps a metadata-free reading copy visually clear.
        body = f"\n\n{SEPARATOR}\n\n".join(entry.body for entry in selected)
        parts.append(body)
    else:
        parts.extend(serialize_entry(entry, fields) for entry in selected)

    return "\n\n\n".join(part for part in parts if part) + "\n"


def safe_filename_part(value: str) -> str:
    value = re.sub(r"[^A-Za-z0-9._+-]+", "-", value).strip("-.")
    return value or "none"


def default_output_path(
    root: Path,
    languages: set[str] | None,
    sections: set[str] | None,
    date_from: date | None,
    date_to: date | None,
    profile: str,
    selected_fields: tuple[str, ...] | None,
    custom_fields: Sequence[str] | None,
    output_format: str,
) -> Path:
    language_part = "all" if languages is None else "+".join(sorted(languages))
    section_part = "all" if sections is None else "+".join(sorted(sections))
    parts = [
        "ALL_POSTS",
        f"lang-{safe_filename_part(language_part)}",
        f"section-{safe_filename_part(section_part)}",
    ]
    if date_from:
        parts.append(f"from-{date_from.isoformat()}")
    if date_to:
        parts.append(f"to-{date_to.isoformat()}")
    if output_format == "compact":
        parts.append("format-compact")
    else:
        if custom_fields:
            metadata_part = "custom-" + "+".join(selected_fields or ("none",))
        else:
            metadata_part = profile
        parts.append(f"metadata-{metadata_part}")
    return root / "exports" / ("__".join(parts) + ".txt")


def atomic_write_utf8_bom(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = text.encode("utf-8-sig")
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", dir=path.parent, prefix=f".{path.name}.", delete=False
        ) as temporary:
            temporary.write(payload)
            temporary.flush()
            os.fsync(temporary.fileno())
            temporary_name = temporary.name
        os.replace(temporary_name, path)
    except OSError as exc:
        if temporary_name:
            try:
                Path(temporary_name).unlink(missing_ok=True)
            except OSError:
                pass
        raise ExportError(f"Cannot write output file {path}: {exc}") from exc


def is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def build_argument_parser(root: Path) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Filter dist/ALL_POSTS.txt by language, section, and date without "
            "running or modifying the website build."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Examples:
  python scripts/filter-all-posts.py --language cs
  python scripts/filter-all-posts.py --language cs --section volna-tvorba,vystavy --metadata archive
  python scripts/filter-all-posts.py --language en --section volna-tvorba --format compact
  python scripts/filter-all-posts.py --list-values
""",
    )
    parser.add_argument(
        "input",
        nargs="?",
        type=Path,
        default=root / "dist" / "ALL_POSTS.txt",
        help="source export (default: <repository>/dist/ALL_POSTS.txt)",
    )
    parser.add_argument("-o", "--output", type=Path, help="output file path")
    parser.add_argument(
        "--language",
        action="append",
        metavar="LANG",
        help="language(s), repeat or comma-separate; omitted means all",
    )
    parser.add_argument(
        "--section",
        action="append",
        metavar="SECTION",
        help="section(s), repeat or comma-separate; omitted means all",
    )
    parser.add_argument("--from-date", metavar="YYYY-MM-DD", help="inclusive minimum date")
    parser.add_argument("--to-date", metavar="YYYY-MM-DD", help="inclusive maximum date")
    parser.add_argument(
        "--format",
        choices=("structured", "compact"),
        default="structured",
        help=(
            "structured keeps metadata blocks; compact uses MoM-style one-line "
            "headers and media records (default: structured)"
        ),
    )
    parser.add_argument(
        "--metadata",
        choices=tuple(METADATA_PROFILES),
        default="full",
        help=(
            "article metadata profile: full; archive removes internal paths; "
            "minimal also removes URL; none creates a reading copy (default: full)"
        ),
    )
    parser.add_argument(
        "--metadata-fields",
        action="append",
        metavar="FIELD",
        help="custom metadata fields; overrides --metadata",
    )
    parser.add_argument(
        "--header",
        choices=("generated", "none"),
        default="generated",
        help="generated filter description or no document header (default: generated)",
    )
    parser.add_argument(
        "--list-values",
        action="store_true",
        help="list languages, sections, fields, and article counts, then exit",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="validate and report the selection without writing a file",
    )
    parser.add_argument(
        "--allow-empty",
        action="store_true",
        help="allow a filter that selects no articles",
    )
    return parser


def list_values(parsed: ParsedExport) -> None:
    print(f"Articles: {len(parsed.entries)}")
    for field, label in (("LANGUAGE", "Languages"), ("SECTION", "Sections")):
        counts: dict[str, int] = {}
        for entry in parsed.entries:
            value = entry.metadata.get(field, "<missing>")
            counts[value] = counts.get(value, 0) + 1
        print(f"{label}:")
        for value in sorted(counts):
            print(f"  {value}: {counts[value]}")

    all_fields = sorted(
        {field for entry in parsed.entries for field in entry.metadata_order}
    )
    print("Metadata fields:")
    for field in all_fields:
        print(f"  {field}")


def main(argv: Sequence[str] | None = None) -> int:
    root = repository_root()
    parser = build_argument_parser(root)
    args = parser.parse_args(argv)

    try:
        parsed = parse_export(args.input.resolve())
        if args.list_values:
            list_values(parsed)
            return 0

        languages = split_values(args.language)
        sections = split_values(args.section)
        available_languages = available_values(parsed.entries, "LANGUAGE")
        available_sections = available_values(parsed.entries, "SECTION")
        validate_requested_values(languages, available_languages, "language")
        validate_requested_values(sections, available_sections, "section")

        date_from = parse_iso_date(args.from_date, "--from-date") if args.from_date else None
        date_to = parse_iso_date(args.to_date, "--to-date") if args.to_date else None
        if date_from and date_to and date_from > date_to:
            raise ExportError("--from-date must not be later than --to-date.")

        selected = filtered_entries(
            parsed.entries, languages, sections, date_from, date_to
        )
        if not selected and not args.allow_empty:
            raise ExportError(
                "The filters selected no articles. Use --allow-empty only if an "
                "empty export is intentional."
            )

        fields = parse_metadata_fields(
            args.metadata_fields, args.metadata, parsed.entries
        )
        profile_label = "custom" if args.metadata_fields else args.metadata
        if args.format == "compact" and (
            args.metadata != "full" or args.metadata_fields
        ):
            raise ExportError(
                "--metadata and --metadata-fields apply only to --format structured. "
                "Compact output has its own fixed article header."
            )
        output = (
            args.output
            if args.output is not None
            else default_output_path(
                root,
                languages,
                sections,
                date_from,
                date_to,
                args.metadata,
                fields,
                args.metadata_fields,
                args.format,
            )
        ).resolve()
        input_path = args.input.resolve()
        if output == input_path:
            raise ExportError("Output must not overwrite the source ALL_POSTS.txt.")

        result = serialize_export(
            parsed,
            selected,
            output.name,
            languages,
            sections,
            date_from,
            date_to,
            fields,
            profile_label,
            args.header,
            args.format,
        )
        payload = result.encode("utf-8-sig")

        print(f"Selected articles: {len(selected)} of {len(parsed.entries)}")
        print(f"Languages: {selected_label(languages)}")
        print(f"Sections: {selected_label(sections)}")
        print(f"Format: {args.format}")
        if args.format == "structured":
            print(f"Metadata: {metadata_label(fields, profile_label)}")
        print(f"Output: {output}")
        print(f"SHA-256: {hashlib.sha256(payload).hexdigest()}")

        dist_directory = root / "dist"
        if is_relative_to(output, dist_directory.resolve()):
            print(
                "WARNING: output is inside dist/. Existing build integrity files "
                "do not cover this newly generated file.",
                file=sys.stderr,
            )

        if not args.dry_run:
            atomic_write_utf8_bom(output, result)
        else:
            print("Dry run: no file was written.")
        return 0
    except ExportError as exc:
        parser.error(str(exc))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
