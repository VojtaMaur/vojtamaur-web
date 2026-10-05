#!/usr/bin/env python3
"""Export existing ALL_POSTS.json content as ASCII International Morse code.

Uses the compact export's JSON adapter and article serializer; no HTML parsing,
network access, build invocation or third-party dependencies are needed.
"""

from __future__ import annotations

from export_naming import add_arguments, stamped_path, timestamp_for

import argparse
import hashlib
import importlib.util
import json
import os
import re
import sys
import tempfile
import unicodedata
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
GLOSSARY_PATH = Path(__file__).with_name("morse-glossary.json")
ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
MORSE = dict(zip(ALPHABET, (
    ".-", "-...", "-.-.", "-..", ".", "..-.", "--.", "....", "..", ".---",
    "-.-", ".-..", "--", "-.", "---", ".--.", "--.-", ".-.", "...", "-",
    "..-", "...-", ".--", "-..-", "-.--", "--..",
    "-----", ".----", "..---", "...--", "....-", ".....", "-....", "--...",
    "---..", "----.",
)))


def load_compact_module():
    # Same import pattern as export-site-pdf-ultra.py; keep one JSON/media parser.
    name = "vojtamaur_filter_all_posts"
    spec = importlib.util.spec_from_file_location(
        name, Path(__file__).with_name("filter-all-posts.py")
    )
    if spec is None or spec.loader is None:
        raise ValueError("Cannot load the compact export module.")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def load_glossary(path: Path = GLOSSARY_PATH) -> dict:
    glossary = json.loads(path.read_text(encoding="utf-8"))
    if glossary.get("version") != 1:
        raise ValueError("Unsupported Morse glossary version.")
    seen = set()
    for group in ("letters", "symbols"):
        mappings = glossary.get(group)
        if not isinstance(mappings, dict):
            raise ValueError(f"Morse glossary needs a {group} object.")
        for char, replacement in mappings.items():
            pattern = r"[A-Z0-9]+" if group == "letters" else r"[A-Z0-9]+(?: [A-Z0-9]+)*"
            if len(char) != 1 or char in seen or not isinstance(replacement, str) or not re.fullmatch(pattern, replacement):
                raise ValueError(f"Invalid Morse glossary mapping for {char!r}.")
            seen.add(char)
    return glossary


def normalize_ascii(text: str, glossary: dict) -> str:
    """Keep LF boundaries; reduce each line to A-Z, digits and single spaces.

    Named symbols have word boundaries, while letter transliterations stay in
    their word. Unknown characters retain their Unicode code point as text.
    """
    def character(char: str) -> str:
        if char == "\n":
            return char
        if char.isspace():
            return " "
        if char in glossary["letters"]:
            return glossary["letters"][char]
        if char in glossary["symbols"]:
            return " " + glossary["symbols"][char] + " "
        category = unicodedata.category(char)
        if category.startswith("M") or category == "Cf":
            return ""
        decomposed = unicodedata.normalize("NFKD", char)
        if decomposed != char:
            return "".join(character(part) for part in decomposed)
        upper = char.upper()
        if all(part in ALPHABET for part in upper):
            return upper
        if category.startswith("P") or ord(char) < 128:
            return " "
        return f" UNICODE {ord(char):04X} "

    text = text.replace("\r\n", "\n").replace("\r", "\n")
    for separator in ("\u0085", "\u2028", "\u2029"):
        text = text.replace(separator, "\n")
    # Cache per-character expansions for large, untruncated article/code bodies.
    translations = {char: character(char) for char in set(text)}
    expanded = "".join(translations[char] for char in text)
    return "\n".join(" ".join(line.split()) for line in expanded.split("\n"))


def encode_morse(text: str) -> str:
    if re.search(r"[^A-Z0-9 \n]", text):
        raise ValueError("Morse input must be normalized to A-Z, 0-9, space and LF.")
    return "\n".join(
        " / ".join(" ".join(MORSE[char] for char in word) for word in line.split())
        for line in text.split("\n")
    )


def serialize_text(compact, selected, languages: set[str]) -> str:
    compact.validate_compact_image_names(selected)
    parts = ["\n".join((
        "MORSE ARCHIVE VOJTAMAUR CZ",
        "SOURCE ALL POSTS JSON",
        "LANGUAGES " + " ".join(sorted(languages)),
        f"ARTICLES {len(selected)}",
        "NORMALIZATION VERSION 1",
    ))]
    for entry in selected:
        # Title/date, full body and compact media records use the shared renderer.
        body = compact.serialize_compact_entry(entry)
        body = re.sub(r"(?m)^\[/CODE BLOCK\]$", "END CODE BLOCK", body)
        parts.append("\n".join((
            "ARTICLE",
            "LANGUAGE " + entry.metadata["LANGUAGE"],
            "SECTION " + entry.metadata["SECTION"],
            "URL " + entry.metadata["URL"],
            body,
            "END ARTICLE",
        )))
    return "\n\n".join(parts) + "\n"


def atomic_write_ascii(path: Path, text: str) -> None:
    payload = text.encode("ascii")  # Byte writes guarantee no BOM and LF on Windows.
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


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=ROOT)
    parser.add_argument("--input", type=Path, default=Path("dist/ALL_POSTS.json"), help="existing JSON-LD archive; paths resolve from project root")
    parser.add_argument("--lang", "--language", choices=("cs", "en", "both"), default="both", help="both writes one combined file (default: both)")
    parser.add_argument("-o", "--output", type=Path, help="ASCII .txt destination under exports/")
    parser.add_argument("--dry-run", action="store_true", help="validate and report without writing")
    add_arguments(parser)
    args = parser.parse_args(argv)

    try:
        root = args.project_root.resolve()
        source = (root / args.input).resolve()
        compact = load_compact_module()
        # Deliberately do not use parse_export's legacy TXT fallback.
        parsed = compact.parse_json_export(source.read_text(encoding="utf-8-sig"))
        languages = {"cs", "en"} if args.lang == "both" else {args.lang}
        compact.validate_requested_values(languages, compact.available_values(parsed.entries, "LANGUAGE"), "language")
        selected = compact.filtered_entries(parsed.entries, languages, None, None, None)
        default_name = f"ALL_POSTS__lang-{'+'.join(sorted(languages))}__section-all__format-morse.txt"
        output = ((root / args.output) if args.output is not None
                  else stamped_path(root / "exports" / default_name, timestamp_for(args))).resolve()
        if output == source or not output.is_relative_to((root / "exports").resolve()) or output.suffix.lower() != ".txt":
            raise ValueError("Output must be a .txt file under exports/ and must not overwrite the input.")

        text = serialize_text(compact, selected, languages)
        normalized = normalize_ascii(text, load_glossary())
        result = encode_morse(normalized)
        payload = result.encode("ascii")
        if not args.dry_run:
            atomic_write_ascii(output, result)
        print(f"Selected articles: {len(selected)} of {len(parsed.entries)}")
        print(f"Languages: {', '.join(sorted(languages))}")
        print(f"Output: {output}")
        print(f"Encoding: ASCII, LF, no BOM; {len(payload)} bytes")
        print(f"SHA-256: {hashlib.sha256(payload).hexdigest()}")
        if args.dry_run:
            print("Dry run: no file was written.")
        return 0
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
