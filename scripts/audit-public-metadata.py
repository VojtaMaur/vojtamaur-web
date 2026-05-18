#!/usr/bin/env python3
"""
Audit and optionally strip privacy-relevant metadata in public/images and public/files.

Requires:
  - Python 3.10+
  - ExifTool installed somewhere outside the project
  - Optional: qpdf, only if you want stronger PDF cleanup

Default mode is audit-only. It does NOT modify files.

Run from project root:
  python scripts/audit-public-metadata.py --exiftool "D:\Programs\exiftool-13.58_64\exiftool.exe"

Strip image metadata from reported files, except allowlisted files:
  python scripts/audit-public-metadata.py --exiftool "D:\Programs\exiftool-13.58_64\exiftool.exe" --strip

Preview strip targets without modifying anything:
  python scripts/audit-public-metadata.py --exiftool "D:\Programs\exiftool-13.58_64\exiftool.exe" --strip --dry-run

Default allowlist:
  public/images/kurt-godel-rat.jpg
  kurt-godel-rat.jpg
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


DEFAULT_PATHS = [
    "public/images",
    "public/files",
]

DEFAULT_ALLOWLIST = {
    "public/images/kurt-godel-rat.jpg",
    "kurt-godel-rat.jpg",
}

EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".webp",
    ".tif",
    ".tiff",
    ".gif",
    ".bmp",
    ".avif",
    ".heic",
    ".heif",
    ".svg",
    ".pdf",
}

RASTER_IMAGE_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".webp",
    ".tif",
    ".tiff",
    ".gif",
    ".bmp",
    ".avif",
    ".heic",
    ".heif",
}

PDF_EXTENSIONS = {".pdf"}


# Metadata that is usually structural, not privacy-relevant.
# This intentionally ignores file-system dates, image dimensions, MIME type,
# compression info, color profiles, and EXIF boilerplate.
NOISE_TAGS = {
    "SourceFile",
    "FileName",
    "Directory",
    "FileSize",
    "FileModifyDate",
    "FileAccessDate",
    "FileCreateDate",
    "FilePermissions",
    "FileType",
    "FileTypeExtension",
    "MIMEType",
    "ImageWidth",
    "ImageHeight",
    "ImageSize",
    "Megapixels",
    "ExifImageWidth",
    "ExifImageHeight",
    "Orientation",
    "XResolution",
    "YResolution",
    "ResolutionUnit",
    "BitsPerSample",
    "ColorComponents",
    "ColorSpace",
    "ColorType",
    "Compression",
    "EncodingProcess",
    "YCbCrSubSampling",
    "YCbCrPositioning",
    "ComponentsConfiguration",
    "ExifVersion",
    "FlashpixVersion",
    "InteropVersion",
    "JFIFVersion",
    "CurrentIPTCDigest",
    "IPTCDigest",
    "ThumbnailOffset",
    "ThumbnailLength",
    "ThumbnailImage",
    "PreviewImage",
    "ProfileCMMType",
    "ProfileVersion",
    "ProfileClass",
    "ProfileConnectionSpace",
    "ProfileFileSignature",
    "PrimaryPlatform",
    "CMMFlags",
    "RenderingIntent",
    "ConnectionSpaceIlluminant",
    "ProfileDescription",
    "ProfileCopyright",
    "MediaWhitePoint",
    "MediaBlackPoint",
    "RedMatrixColumn",
    "GreenMatrixColumn",
    "BlueMatrixColumn",
    "RedTRC",
    "GreenTRC",
    "BlueTRC",
    "PDFVersion",
    "Linearized",
    "PageCount",
    "TaggedPDF",
    "Encrypted",
    "ColorMode",
    "ICCProfileName",
    "LegacyIPTCDigest",
    "HistoryChanged",
    "HistoryAction",
    "HistoryWhen",
    "HistoryInstanceID",
    "InstanceID",
    "DocumentAncestors",
    "OriginalDocumentID",
    "DocumentID",
    "XMPToolkit",
    "Aria-label",

    # ICC/color-profile and camera-profile boilerplate. These can look scary,
    # but usually say more about color management than about the person.
    "DeviceAttributes",
    "DeviceManufacturer",
    "DeviceModel",
    "ProfileCreator",
    "CameraProfile",
    "CameraProfileDigest",

    # Technical capture parameters. Usually not privacy-relevant by themselves.
    "FocalLength",
    "FocalLength35efl",
    "FocalLengthIn35mmFormat",
    "FileSource",
    "SubjectDistanceRange",

    # Empty/boilerplate IPTC fields.
    "ApplicationRecordVersion",
    "CodedCharacterSet",
    "Format",
}

NOISE_GROUPS = {
    "File",
    "System",
    "ICC_Profile",
    "ICC-header",
    "ICC-view",
    "JFIF",
}

DATE_HINTS = {
    "date",
    "time",
    "timestamp",
}


class StripResult(dict):
    pass


def split_exiftool_key(key: str) -> tuple[str, str]:
    if ":" in key:
        group, tag = key.split(":", 1)
        return group, tag
    return "", key


def is_date_like(tag: str) -> bool:
    lower = tag.lower()
    return any(hint in lower for hint in DATE_HINTS)


def is_noise(key: str, include_dates: bool) -> bool:
    group, tag = split_exiftool_key(key)

    if key in NOISE_TAGS or tag in NOISE_TAGS:
        return True

    if group in NOISE_GROUPS:
        return True

    if not include_dates and is_date_like(tag):
        return True

    return False


def classify_metadata(key: str, value: Any) -> tuple[list[str], str | None]:
    _group, tag = split_exiftool_key(key)
    tag_lower = tag.lower()

    important_rules = [
        ("GPS / poloha", [
            "gps",
            "latitude",
            "longitude",
            "location",
            "city",
            "country",
            "geotag",
        ], "HIGH"),

        ("zařízení / foťák", [
            "make",
            "model",
            "lensmodel",
            "camera",
        ], "MEDIUM"),

        ("software", [
            "software",
            "creatortool",
            "historysoftwareagent",
            "processingsoftware",
            "producer",
        ], "MEDIUM"),

        ("autor / copyright", [
            "author",
            "artist",
            "creator",
            "copyright",
            "rights",
            "owner",
        ], "MEDIUM"),

        ("komentář / text", [
            "comment",
            "description",
            "caption",
            "keywords",
            "title",
            "subject",
            "usercomment",
        ], "HIGH"),

        ("serial / identifikátor", [
            "serial",
            "documentid",
            "instanceid",
            "originaldocumentid",
            "derivedfromdocumentid",
            "derivedfrominstanceid",
            "derivedfromoriginaldocumentid",
        ], "HIGH"),
    ]

    for category, hints, severity in important_rules:
        if any(hint in tag_lower for hint in hints):
            return [category], severity

    return [], None


def max_severity(a: str | None, b: str) -> str:
    order = {
        None: 0,
        "LOW": 1,
        "MEDIUM": 2,
        "HIGH": 3,
    }
    return b if order[b] > order[a] else a  # type: ignore[index]


def normalize_value(value: Any) -> str:
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def is_empty_value(value: Any) -> bool:
    if value is None:
        return True

    if isinstance(value, str):
        return value.strip() == ""

    if isinstance(value, (list, tuple, set, dict)):
        return len(value) == 0

    return False


def dedupe_value(value: Any) -> str:
    if isinstance(value, list):
        unique_values: list[str] = []
        for item in value:
            normalized = normalize_value(item)
            if normalized not in unique_values:
                unique_values.append(normalized)
        return json.dumps(unique_values, ensure_ascii=False)

    return normalize_value(value)


def normalize_path_text(path_text: str) -> str:
    return path_text.replace("\\", "/").strip().lower()


def load_allowlist(values: list[str], allowlist_file: str | None) -> set[str]:
    allowlist = set(DEFAULT_ALLOWLIST)

    for value in values:
        allowlist.add(value)

    if allowlist_file:
        path = Path(allowlist_file)
        if not path.exists():
            raise SystemExit(f"Allowlist soubor neexistuje: {path}")

        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            allowlist.add(stripped)

    return {normalize_path_text(item) for item in allowlist}


def is_allowlisted(file_path: str, allowlist: set[str]) -> bool:
    normalized_path = normalize_path_text(file_path)
    basename = Path(file_path).name.lower()

    for item in allowlist:
        if not item:
            continue

        # If the allowlist item contains a slash, treat it as a full or suffix path.
        if "/" in item:
            if normalized_path == item or normalized_path.endswith("/" + item):
                return True
        else:
            if basename == item:
                return True

    return False


def find_exiftool(explicit_path: str | None) -> str:
    if explicit_path:
        path = Path(explicit_path)
        if path.exists():
            return str(path)
        raise SystemExit(f"ExifTool nenalezen: {explicit_path}")

    found = shutil.which("exiftool")
    if found:
        return found

    fallback_paths = [
        Path(r"D:\Program Files\exiftool\exiftool.exe"),
        Path(r"C:\Tools\exiftool\exiftool.exe"),
    ]

    for fallback in fallback_paths:
        if fallback.exists():
            return str(fallback)

    raise SystemExit(
        "ExifTool není v PATH.\n\n"
        "Spusť například:\n"
        "  python scripts/audit-public-metadata.py --exiftool \"D:\\Program Files\\exiftool\\exiftool.exe\"\n\n"
        "Nebo dej exiftool.exe mimo repozitář a přidej ho do PATH. Nedávej ho do projektu,\n"
        "pokud nechceš archivovat i náhodné nástroje jako digitální sediment."
    )


def find_qpdf(explicit_path: str | None) -> str | None:
    if explicit_path:
        path = Path(explicit_path)
        if path.exists():
            return str(path)
        raise SystemExit(f"qpdf nenalezen: {explicit_path}")

    return shutil.which("qpdf")


def collect_existing_paths(paths: list[str]) -> list[Path]:
    existing: list[Path] = []

    for raw_path in paths:
        path = Path(raw_path)
        if path.exists():
            existing.append(path)
        else:
            print(f"[WARN] Cesta neexistuje, přeskakuju: {path}", file=sys.stderr)

    if not existing:
        raise SystemExit("Žádná auditovatelná cesta neexistuje.")

    return existing


def run_exiftool_read(exiftool: str, paths: list[Path]) -> list[dict[str, Any]]:
    cmd = [
        exiftool,
        "-j",
        "-G1",
        "-a",
        "-s",
        "-r",
    ]

    for ext in sorted(EXTENSIONS):
        cmd.extend(["-ext", ext.lstrip(".")])

    cmd.extend(str(path) for path in paths)

    result = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    if result.stderr.strip():
        print(result.stderr.strip(), file=sys.stderr)

    if not result.stdout.strip():
        return []

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"ExifTool vrátil nečitelný JSON: {exc}") from exc

    if not isinstance(data, list):
        raise SystemExit("ExifTool vrátil neočekávaný formát.")

    return data


def audit_item(
    item: dict[str, Any],
    include_dates: bool,
    show_other: bool,
) -> dict[str, Any] | None:
    source = item.get("SourceFile", "<unknown>")
    findings: list[dict[str, Any]] = []
    file_severity: str | None = None
    seen: set[tuple[str, str]] = set()

    for key, value in sorted(item.items()):
        if key == "SourceFile":
            continue

        if is_empty_value(value):
            continue

        if is_noise(key, include_dates=include_dates):
            continue

        categories, severity = classify_metadata(key, value)

        if not categories and not show_other:
            continue

        if not categories:
            categories = ["jiná netechnická metadata"]
            severity = "LOW"

        normalized_value = dedupe_value(value)
        primary_category = categories[0]
        fingerprint = (primary_category, normalized_value)

        # Same information often appears in IFD0, XMP, IPTC and Photoshop history.
        # Keep one representative row. The point is to find leaks, not print a
        # family tree of Adobe's metadata bureaucracy.
        if fingerprint in seen:
            continue

        seen.add(fingerprint)

        file_severity = max_severity(file_severity, severity or "LOW")

        findings.append(
            {
                "key": key,
                "value": normalized_value,
                "categories": categories,
                "severity": severity or "LOW",
            }
        )

    if not findings:
        return None

    return {
        "file": source,
        "severity": file_severity or "LOW",
        "findings": findings,
    }


def severity_sort_key(result: dict[str, Any]) -> tuple[int, str]:
    order = {
        "HIGH": 0,
        "MEDIUM": 1,
        "LOW": 2,
    }
    return order.get(result["severity"], 9), result["file"]


def audit_all(raw_items: list[dict[str, Any]], include_dates: bool, show_other: bool) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []

    for item in raw_items:
        audited = audit_item(
            item,
            include_dates=include_dates,
            show_other=show_other,
        )
        if audited:
            results.append(audited)

    return sorted(results, key=severity_sort_key)


def print_report(results: list[dict[str, Any]], scanned_count: int, allowlist: set[str] | None = None) -> None:
    print()
    print("Metadata audit")
    print("==============")
    print(f"Zkontrolováno souborů: {scanned_count}")
    print(f"Soubory s podezřelými metadaty: {len(results)}")

    if allowlist:
        allowlisted_hits = sum(1 for result in results if is_allowlisted(result["file"], allowlist))
        print(f"Z toho allowlist: {allowlisted_hits}")

    print()

    if not results:
        print("OK: Nenašel jsem privacy-relevantní metadata podle nastaveného filtru.")
        return

    for result in results:
        marker = " [ALLOWLIST]" if allowlist and is_allowlisted(result["file"], allowlist) else ""
        print(f"[{result['severity']}] {result['file']}{marker}")

        for finding in result["findings"]:
            cats = ", ".join(finding["categories"])
            print(f"  - {finding['key']} [{cats}]")
            print(f"    {finding['value']}")

        print()


def supported_strip_kind(path: Path, include_pdf: bool) -> str | None:
    suffix = path.suffix.lower()

    if suffix in RASTER_IMAGE_EXTENSIONS:
        return "image"

    if suffix in PDF_EXTENSIONS and include_pdf:
        return "pdf"

    return None


def strip_image_metadata(exiftool: str, file_path: Path, preserve_color: bool) -> subprocess.CompletedProcess[str]:
    cmd = [exiftool, "-overwrite_original"]

    if preserve_color:
        # Remove metadata, but preserve ICC/color-space data that can affect rendering.
        cmd.extend(["-all=", "--ICC_Profile:all", "-tagsFromFile", "@", "-ColorSpaceTags"])
    else:
        cmd.append("-all=")

    cmd.append(str(file_path))

    return subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def strip_pdf_metadata(exiftool: str, file_path: Path, qpdf: str | None) -> subprocess.CompletedProcess[str]:
    # ExifTool updates PDFs incrementally. Without qpdf, old metadata may remain
    # physically recoverable in the file. This still hides normal metadata from
    # readers, but it is not a forensic wipe. PDF is always a haunted filing cabinet.
    result = subprocess.run(
        [exiftool, "-overwrite_original", "-all=", str(file_path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    if result.returncode != 0 or not qpdf:
        return result

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir) / file_path.name
        qpdf_result = subprocess.run(
            [qpdf, "--linearize", str(file_path), str(tmp_path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )

        if qpdf_result.returncode != 0:
            return qpdf_result

        shutil.move(str(tmp_path), str(file_path))

    return result


def strip_targets(
    exiftool: str,
    results: list[dict[str, Any]],
    allowlist: set[str],
    include_pdf: bool,
    qpdf: str | None,
    preserve_color: bool,
    dry_run: bool,
) -> list[dict[str, Any]]:
    operations: list[dict[str, Any]] = []

    for result in results:
        file_text = result["file"]
        file_path = Path(file_text)

        if is_allowlisted(file_text, allowlist):
            operations.append({"file": file_text, "status": "allowlisted"})
            continue

        strip_kind = supported_strip_kind(file_path, include_pdf=include_pdf)

        if not strip_kind:
            operations.append({"file": file_text, "status": "skipped", "reason": "unsupported file type for strip mode"})
            continue

        if dry_run:
            operations.append({"file": file_text, "status": "would_strip", "kind": strip_kind})
            continue

        if strip_kind == "image":
            proc = strip_image_metadata(exiftool, file_path, preserve_color=preserve_color)
        elif strip_kind == "pdf":
            proc = strip_pdf_metadata(exiftool, file_path, qpdf=qpdf)
        else:
            operations.append({"file": file_text, "status": "skipped", "reason": "unknown strip kind"})
            continue

        stdout = proc.stdout.strip()
        stderr = proc.stderr.strip()

        if proc.returncode == 0:
            operations.append({"file": file_text, "status": "stripped", "kind": strip_kind, "stdout": stdout, "stderr": stderr})
        else:
            operations.append({"file": file_text, "status": "error", "kind": strip_kind, "stdout": stdout, "stderr": stderr})

    return operations


def print_strip_report(operations: list[dict[str, Any]], include_pdf: bool, qpdf: str | None, dry_run: bool) -> None:
    print()
    print("Metadata strip")
    print("==============")

    counts: dict[str, int] = {}
    for operation in operations:
        counts[operation["status"]] = counts.get(operation["status"], 0) + 1

    for key in ["would_strip", "stripped", "allowlisted", "skipped", "error"]:
        if key in counts:
            print(f"{key}: {counts[key]}")

    if include_pdf and not qpdf:
        print()
        print("[WARN] PDF metadata byla/ budou mazána jen přes ExifTool.")
        print("       U PDF to nemusí být forenzně definitivní odstranění, protože PDF změny mohou být inkrementální.")
        print("       Pro silnější PDF cleanup použij --qpdf cestu k qpdf.exe.")

    print()

    for operation in operations:
        status = operation["status"]
        file_text = operation["file"]

        if status == "would_strip":
            print(f"[DRY-RUN] strip {file_text}")
        elif status == "stripped":
            print(f"[OK] stripped {file_text}")
        elif status == "allowlisted":
            print(f"[KEEP] allowlist {file_text}")
        elif status == "skipped":
            print(f"[SKIP] {file_text} ({operation.get('reason', 'bez důvodu, jak je lidským zvykem')})")
        elif status == "error":
            print(f"[ERROR] {file_text}")
            if operation.get("stdout"):
                print(operation["stdout"])
            if operation.get("stderr"):
                print(operation["stderr"])

    if dry_run:
        print()
        print("Dry-run: soubory nebyly změněny.")


def write_json_report(
    output_path: Path,
    scanned_count: int,
    results: list[dict[str, Any]],
    strip_operations: list[dict[str, Any]] | None,
) -> None:
    payload = {
        "scanned_files": scanned_count,
        "files_with_metadata": len(results),
        "results": results,
    }

    if strip_operations is not None:
        payload["strip_operations"] = strip_operations

    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"JSON report uložen: {output_path}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Audit and optionally strip privacy-relevant metadata in public/images and public/files."
    )

    parser.add_argument(
        "--paths",
        nargs="+",
        default=DEFAULT_PATHS,
        help="Cesty ke kontrole. Výchozí: public/images public/files",
    )

    parser.add_argument(
        "--exiftool",
        default=None,
        help="Explicitní cesta k exiftool.exe / exiftool.",
    )

    parser.add_argument(
        "--qpdf",
        default=None,
        help="Volitelná cesta k qpdf.exe. Použije se jen pro silnější PDF cleanup.",
    )

    parser.add_argument(
        "--include-dates",
        action="store_true",
        help="Zahrnout i datumové tagy. Výchozí je ignorovat je.",
    )

    parser.add_argument(
        "--show-other",
        action="store_true",
        help="Ukázat i netechnická metadata, která nespadají do známých rizikových kategorií.",
    )

    parser.add_argument(
        "--json",
        dest="json_output",
        default=None,
        help="Uložit report jako JSON.",
    )

    parser.add_argument(
        "--fail-on-findings",
        action="store_true",
        help="Vrátit exit code 1, pokud se najdou metadata. Hodí se pro ruční preflight, ne pro build.",
    )

    parser.add_argument(
        "--strip",
        action="store_true",
        help="Smazat metadata ze souborů, které audit označí. Allowlist zůstává zachovaný.",
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="S --strip jen vypsat, co by se změnilo. Soubory zůstanou beze změny.",
    )

    parser.add_argument(
        "--allowlist",
        nargs="*",
        default=[],
        help="Soubory, u kterých metadata záměrně ponechat. Může být basename nebo cesta.",
    )

    parser.add_argument(
        "--allowlist-file",
        default=None,
        help="Textový soubor s allowlistem, jeden soubor na řádek. # komentáře jsou ignorované.",
    )

    parser.add_argument(
        "--strip-pdf",
        action="store_true",
        help="Zahrnout do strip režimu i PDF. Bez qpdf to není forenzně definitivní cleanup.",
    )

    parser.add_argument(
        "--strip-all-color-metadata",
        action="store_true",
        help="Neponechávat ani ICC/color-space metadata. Riziko barevného posunu. Výchozí je barvy zachovat.",
    )

    args = parser.parse_args()

    exiftool = find_exiftool(args.exiftool)
    qpdf = find_qpdf(args.qpdf) if args.strip_pdf else None
    paths = collect_existing_paths(args.paths)
    allowlist = load_allowlist(args.allowlist, args.allowlist_file)

    raw_items = run_exiftool_read(exiftool, paths)
    results = audit_all(raw_items, include_dates=args.include_dates, show_other=args.show_other)

    print_report(results, scanned_count=len(raw_items), allowlist=allowlist)

    strip_operations: list[dict[str, Any]] | None = None

    if args.strip:
        strip_operations = strip_targets(
            exiftool=exiftool,
            results=results,
            allowlist=allowlist,
            include_pdf=args.strip_pdf,
            qpdf=qpdf,
            preserve_color=not args.strip_all_color_metadata,
            dry_run=args.dry_run,
        )
        print_strip_report(strip_operations, include_pdf=args.strip_pdf, qpdf=qpdf, dry_run=args.dry_run)

        if not args.dry_run:
            raw_after = run_exiftool_read(exiftool, paths)
            results_after = audit_all(raw_after, include_dates=args.include_dates, show_other=args.show_other)
            print()
            print("Audit po stripu")
            print("===============")
            print(f"Soubory s podezřelými metadaty po stripu: {len(results_after)}")
            if results_after:
                print_report(results_after, scanned_count=len(raw_after), allowlist=allowlist)

    if args.json_output:
        write_json_report(
            output_path=Path(args.json_output),
            scanned_count=len(raw_items),
            results=results,
            strip_operations=strip_operations,
        )

    if results and args.fail_on_findings:
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
