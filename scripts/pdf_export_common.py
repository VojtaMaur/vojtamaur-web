"""Optional PDF compression and PDF/A-2b derivation for the manual exporters.

All trials read the original PDF. Nothing rewrites the selected PDF/A after
Ghostscript; structural checks and veraPDF are read-only.
"""
from __future__ import annotations

import argparse
import dataclasses
from decimal import Decimal
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path


PRESETS = {"none": (None, None), "light": (300, 90),
           "medium": (150, 80), "high": (96, 60)}
LEGACY = {"archive": (None, None), "printer": (300, 90),
          "ebook": (150, 75), "screen": (96, 60)}


def target_bytes(value: str) -> int:
    match = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*(B|K|KB|M|MB|G|GB|KiB|MiB|GiB)?\s*", value, re.I)
    if not match:
        raise argparse.ArgumentTypeError("Use bytes or a size such as 2M or 2MiB.")
    suffix = (match[2] or "B").upper()
    multipliers = {"B": 1, "K": 1000, "KB": 1000, "M": 1000000,
                   "MB": 1000000, "G": 1000000000, "GB": 1000000000,
                   "KIB": 1024, "MIB": 1024**2, "GIB": 1024**3}
    size = int(Decimal(match[1]) * multipliers[suffix])
    if size < 1:
        raise argparse.ArgumentTypeError("Target size must be positive.")
    return size


def add_arguments(parser: argparse.ArgumentParser, *, existing_images=False,
                  existing_ghostscript=False) -> None:
    group = parser.add_argument_group("Optional compression and archival PDF/A")
    group.add_argument("--pdfa", choices=["2b"], help="Also create a separate *-pdfa-2b.pdf; ordinary PDF remains the original export.")
    group.add_argument("--compress", choices=list(PRESETS), default=None,
                       help="Compression preset: none, light (300 DPI/Q90), medium (150/Q80), high (96/Q60). Default: existing export behaviour.")
    if not existing_images:
        group.add_argument("--image-dpi", type=int, help="Maximum effective raster DPI, at least 36; overrides preset.")
        group.add_argument("--jpeg-quality", type=int, help="JPEG quality 1-100; overrides preset.")
    group.add_argument("--target-size", type=target_bytes, metavar="SIZE",
                       help="Try up to 10 conversions to fit strictly below SIZE (2M = 2,000,000 bytes; 2MiB = 2,097,152). Settings are starting ceilings; exit 2 if unattainable.")
    if not existing_ghostscript:
        group.add_argument("--ghostscript", help="Ghostscript executable; normally detected.")
    group.add_argument("--icc-profile", help="RGB ICC output profile for PDF/A; normally Ghostscript's srgb.icc.")
    group.add_argument("--verapdf", help="veraPDF CLI executable or .bat; normally detected. A failed validation aborts publication of the derivative.")


def find_tool(explicit: str | None, names: tuple[str, ...]) -> Path | None:
    if explicit:
        path = Path(explicit).expanduser()
        resolved = path.resolve() if path.is_file() else shutil.which(explicit)
        if not resolved:
            raise SystemExit(f"Executable not found: {explicit}")
        return Path(resolved)
    for name in names:
        resolved = shutil.which(name)
        if resolved:
            return Path(resolved).resolve()
    return None


def find_ghostscript(explicit: str | None) -> Path | None:
    found = find_tool(explicit, ("gswin64c", "gswin32c", "gs"))
    if found or os.name != "nt":
        return found
    candidates = []
    for name in ("ProgramFiles", "ProgramFiles(x86)"):
        root = Path(os.environ.get(name, "C:/Program Files")) / "gs"
        candidates.extend(root.glob("gs*/bin/gswin*c.exe"))
    return sorted(candidates, reverse=True)[0].resolve() if candidates else None


def find_icc(gs: Path, explicit: str | None) -> Path:
    candidates = [Path(explicit).expanduser()] if explicit else [
        gs.parent.parent / "iccprofiles/srgb.icc",
        gs.parent.parent / "iccprofiles/default_rgb.icc",
        *sorted(Path("/usr/share/ghostscript").glob("*/iccprofiles/srgb.icc"), reverse=True),
        Path("/usr/share/color/icc/ghostscript/srgb.icc"),
    ]
    for path in candidates:
        if path.is_file():
            data = path.read_bytes()
            if len(data) < 128 or data[36:40] != b"acsp" or data[16:20] != b"RGB ":
                raise SystemExit(f"PDF/A requires a valid RGB ICC profile: {path}")
            return path.resolve()
    raise SystemExit("RGB ICC profile not found. Pass --icc-profile PATH (e.g. Ghostscript iccprofiles/srgb.icc).")


@dataclasses.dataclass(frozen=True)
class Settings:
    dpi: int | None
    quality: int | None


def prepare(args: argparse.Namespace, *, ultra=False) -> None:
    """Validate before rendering and retain the legacy defaults for plain runs."""
    explicit_dpi, explicit_q = args.image_dpi, args.jpeg_quality
    if explicit_dpi is not None and explicit_dpi < 36:
        raise SystemExit("--image-dpi must be at least 36.")
    if explicit_q is not None and not 1 <= explicit_q <= 100:
        raise SystemExit("--jpeg-quality must be between 1 and 100.")
    legacy = getattr(args, "pdf_quality", "archive")
    if args.compress is not None and legacy != "archive":
        raise SystemExit("Choose either --compress or legacy --pdf-quality, not both.")
    if (args.icc_profile or args.verapdf) and not args.pdfa:
        raise SystemExit("--icc-profile and --verapdf require --pdfa 2b.")
    preset = args.compress
    if preset is None:
        dpi, quality = LEGACY[legacy]
        if args.target_size or (not ultra and (explicit_dpi is not None or explicit_q is not None)):
            dpi, quality = PRESETS["medium"] if legacy == "archive" else (dpi, quality)
    else:
        dpi, quality = PRESETS[preset]
    args._pdf_settings = Settings(explicit_dpi if explicit_dpi is not None else dpi,
                                  explicit_q if explicit_q is not None else quality)
    args._pdf_records = []
    args._target_failed = False
    args._ordinary_processing = bool(not args.pdfa and (
        args.compress is not None and args.compress != "none" or args.target_size is not None
        or not ultra and (legacy != "archive" or explicit_dpi is not None or explicit_q is not None)
        or args.compress is not None and (explicit_dpi is not None or explicit_q is not None)))
    needs_gs = args.pdfa or args._ordinary_processing or legacy != "archive"
    args._ghostscript = find_ghostscript(args.ghostscript) if needs_gs else None
    if needs_gs and not args._ghostscript:
        raise SystemExit("Ghostscript is required for PDF/A or compression. Install it or pass --ghostscript PATH.")
    args._icc = find_icc(args._ghostscript, args.icc_profile) if args.pdfa else None
    args._verapdf = find_tool(args.verapdf, ("verapdf", "verapdf.bat")) if args.pdfa else None
    if args.pdfa and args._verapdf is None and os.name == "nt":
        for root in (Path(os.environ.get("ProgramFiles", "C:/Program Files")),
                     Path(os.environ.get("LOCALAPPDATA", "C:/nonexistent"))):
            candidates = list(root.glob("*vera*/verapdf.bat"))
            if candidates:
                args._verapdf = candidates[0].resolve()
                break
    if ultra:
        # Existing thumbnail options still affect the original render. New
        # presets/target only affect final processing, preserving its baseline.
        args.image_dpi = explicit_dpi if explicit_dpi is not None else 240
        args.jpeg_quality = explicit_q if explicit_q is not None else 70


def inspect(path: Path) -> dict:
    from pypdf import PdfReader
    reader = PdfReader(path)
    if reader.is_encrypted or not reader.pages:
        raise SystemExit(f"Empty/encrypted PDF: {path}")
    links = []
    for page in reader.pages:
        for ref in page.get("/Annots", []):
            action = ref.get_object().get("/A")
            if action and action.get_object().get("/URI"):
                links.append(str(action.get_object()["/URI"]))
    return {"pages": len(reader.pages), "page_boxes": [
        [round(float(x), 2) for x in page.mediabox] for page in reader.pages],
        "uri_links": sorted(links), "outline_items": len(reader.outline),
        "has_text": any(bool(page.extract_text().strip()) for page in reader.pages)}


def check_conversion(source_info: dict, output: Path, *, pdfa: bool) -> dict:
    from pypdf import PdfReader
    result = inspect(output)
    if result["pages"] != source_info["pages"]:
        raise SystemExit("Ghostscript changed the page count.")
    for before, after in zip(source_info["page_boxes"], result["page_boxes"]):
        if any(abs(a-b) > 0.1 for a, b in zip(before, after)):
            raise SystemExit("Ghostscript changed page dimensions.")
    if result["uri_links"] != source_info["uri_links"]:
        raise SystemExit("Ghostscript changed public URI links.")
    if source_info["outline_items"] and not result["outline_items"]:
        raise SystemExit("Ghostscript removed the document outline.")
    if source_info["has_text"] and not result["has_text"]:
        raise SystemExit("Ghostscript removed searchable text.")
    if pdfa:
        reader = PdfReader(output)
        xmp = reader.xmp_metadata
        intents = reader.trailer["/Root"].get("/OutputIntents", [])
        if xmp is None or str(xmp.pdfaid_part) != "2" or str(xmp.pdfaid_conformance).upper() != "B":
            raise SystemExit("Ghostscript output lacks PDF/A-2b identification metadata.")
        if not any(ref.get_object().get("/DestOutputProfile") for ref in intents):
            raise SystemExit("Ghostscript output lacks an embedded ICC output intent.")
        # Fonts can occur inside reusable form resources, not just on pages.
        visited = set()

        def check_fonts(resources):
            resources = resources.get_object() if hasattr(resources, "get_object") else resources
            if id(resources) in visited:
                return
            visited.add(id(resources))
            fonts = resources.get("/Font", {})
            for ref in fonts.get_object().values() if hasattr(fonts, "get_object") else fonts.values():
                font = ref.get_object()
                descendants = font.get("/DescendantFonts", [font])
                for item in descendants:
                    item = item.get_object()
                    if item.get("/Subtype") == "/Type3":
                        continue  # Type 3 glyph programs are embedded directly.
                    descriptor = item.get("/FontDescriptor")
                    if descriptor is None or not any(
                        descriptor.get_object().get(key) for key in ("/FontFile", "/FontFile2", "/FontFile3")
                    ):
                        raise SystemExit(f"PDF/A output has an unembedded font: {item.get('/BaseFont', 'unknown')}")
            xobjects = resources.get("/XObject", {})
            for ref in xobjects.get_object().values() if hasattr(xobjects, "get_object") else xobjects.values():
                nested = ref.get_object().get("/Resources")
                if nested is not None:
                    check_fonts(nested)

        for page in reader.pages:
            check_fonts(page.get("/Resources", {}))
        result["pdfa_identification"] = "2b"
        result["embedded_output_intent"] = True
        result["fonts_embedded"] = True
    return result


def convert(source: Path, output: Path, settings: Settings, args, prefix: Path | None) -> None:
    command = [str(args._ghostscript), "-sDEVICE=pdfwrite", "-dCompatibilityLevel=1.7",
               "-dBATCH", "-dNOPAUSE", "-dSAFER", "-dAutoRotatePages=/None",
               "-dDetectDuplicateImages=true", "-dCompressFonts=true", "-dSubsetFonts=true",
               "-dEmbedAllFonts=true", "-dPreserveAnnots=true", f"-sOutputFile={output}"]
    if args.pdfa:
        command += ["-dPDFA=2", "-dPDFACompatibilityPolicy=2",
                    # Managed blending crashes on some site pages in local GS
                    # 10.07.1. Simple is also supported for PDF/A-2 transparency.
                    "-sColorConversionStrategy=RGB", "-sBlendConversionStrategy=Simple",
                    f"-sOutputICCProfile={args._icc}", f"--permit-file-read={args._icc}"]
    for kind in ("Color", "Gray", "Mono"):
        enabled = settings.dpi is not None
        command.append(f"-dDownsample{kind}Images={'true' if enabled else 'false'}")
        if enabled:
            command += [f"-d{kind}ImageResolution={settings.dpi}",
                        f"-d{kind}ImageDownsampleThreshold=1.0",
                        f"-d{kind}ImageDownsampleType=/{'Subsample' if kind == 'Mono' else 'Bicubic'}"]
    params = "<< /NeverEmbed []"
    if settings.quality is not None:
        command += ["-dPassThroughJPEGImages=false", "-dPassThroughJPXImages=false"]
        # pdfwrite uses image dictionaries, not the raster-device -dJPEGQ.
        # DCTEncode QFactor scales quantization: lower means higher quality.
        qfactor = max(0.01, 2 - 2*settings.quality/100) if settings.quality >= 50 else 50/settings.quality
        for kind in ("Color", "Gray"):
            command += [f"-dAutoFilter{kind}Images=false", f"-d{kind}ImageFilter=/DCTEncode"]
            params += f" /{kind}ImageDict << /QFactor {qfactor:.4f} /Blend 1 /HSamples [2 1 1 2] /VSamples [2 1 1 2] >>"
    command += ["-c", params + " >> setdistillerparams", "-f"]
    if prefix:
        command.append(str(prefix))
    command.append(str(source))
    result = subprocess.run(command, capture_output=True, text=True, errors="replace")
    if result.returncode or not output.is_file() or output.stat().st_size == 0:
        raise SystemExit(f"Ghostscript failed ({result.returncode}):\n{result.stdout}\n{result.stderr}")
    if result.stderr.strip():
        print(result.stderr.strip(), file=sys.stderr)


def validate_pdfa(path: Path, args) -> dict:
    if args._verapdf is None:
        print("[warn] veraPDF is unavailable: external PDF/A-2b validation was NOT performed. Structural checks alone do not prove compliance.", file=sys.stderr)
        return {"status": "not_performed", "reason": "veraPDF unavailable"}
    command = [str(args._verapdf), "--format", "xml", "--flavour", "2b", str(path)]
    result = subprocess.run(command, capture_output=True, text=True, errors="replace")
    try:
        root = ET.fromstring(result.stdout)
        reports = [node for node in root.iter() if node.tag.split("}")[-1] == "validationReport"]
        passed = len(reports) == 1 and reports[0].get("isCompliant") == "true"
    except ET.ParseError:
        passed = False
    if result.returncode or not passed:
        raise SystemExit(f"veraPDF PDF/A-2b validation failed; derivative not published.\n{result.stdout[-8000:]}\n{result.stderr[-2000:]}")
    print("[veraPDF] PDF/A-2b PASS")
    return {"status": "passed", "flavour": "2b", "validator": str(args._verapdf)}


def process(original: Path, args) -> list[dict]:
    """Derive PDF/A or compress plain output; preserve original during trials."""
    if not args.pdfa and not args._ordinary_processing:
        return []
    destination = original.with_name(original.stem + "-pdfa-2b.pdf") if args.pdfa else original
    source_info = inspect(original)
    settings = args._pdf_settings
    if args.target_size:
        settings = Settings(settings.dpi or 300, settings.quality or 95)
    with tempfile.TemporaryDirectory(prefix="pdf-final-", dir=original.parent) as tmp:
        directory = Path(tmp)
        prefix = None
        if args.pdfa:
            prefix = directory / "PDFA_def.ps"
            # Hex strings avoid PostScript escaping/injection for Unicode paths.
            icc_hex = os.fsencode(str(args._icc).replace("\\", "/")).hex()
            prefix.write_text(
                "%!\n/ICCProfile <" + icc_hex + "> def\n"
                "[/_objdef {icc_PDFA} /type /stream /OBJ pdfmark\n"
                "[{icc_PDFA} << /N 3 >> /PUT pdfmark\n"
                "[{icc_PDFA} ICCProfile (r) file /PUT pdfmark\n"
                "[/_objdef {OutputIntent_PDFA} /type /dict /OBJ pdfmark\n"
                "[{OutputIntent_PDFA} << /Type /OutputIntent /S /GTS_PDFA1 "
                "/DestOutputProfile {icc_PDFA} /OutputConditionIdentifier (sRGB) >> /PUT pdfmark\n"
                "[{Catalog} << /OutputIntents [{OutputIntent_PDFA}] >> /PUT pdfmark\n",
                encoding="ascii")
        trials = []
        best = None
        last_failed = 1.0
        first_passed = None

        def attempt(factor: float):
            trial_settings = settings if factor == 1 else Settings(
                max(36, round(settings.dpi * factor)),
                max(min(30, settings.quality), round(settings.quality * factor)))
            output = directory / f"trial-{len(trials)+1}.pdf"
            convert(original, output, trial_settings, args, prefix)
            size = output.stat().st_size
            trials.append({"image_dpi": trial_settings.dpi, "jpeg_quality": trial_settings.quality, "bytes": size})
            print(f"[pdf{'a-2b' if args.pdfa else ''}] attempt {len(trials)}: DPI {trial_settings.dpi}, JPEG {trial_settings.quality}, {size:,} bytes")
            return output, size, trial_settings

        factors = (1.0, 0.9, 0.8, 0.7, 0.6, 0.45, 0.3) if args.target_size else (1.0,)
        smallest = None
        for factor in factors:
            candidate = attempt(factor)
            if smallest is None or candidate[1] < smallest[1]:
                smallest = candidate
            if args.target_size is None or candidate[1] < args.target_size:
                best, first_passed = candidate, factor
                break
            last_failed = factor
        # Refine the first successful quality bracket without assuming that
        # file size is perfectly monotonic. Only measured fitting trials win.
        if best is not None and first_passed != 1.0 and args.target_size:
            low, high = first_passed, last_failed
            for _ in range(3):
                factor = (low+high)/2
                candidate = attempt(factor)
                if candidate[1] < args.target_size:
                    best, low = candidate, factor
                else:
                    high = factor
        met = args.target_size is None or best is not None
        selected = best or smallest
        selected_path, size, final_settings = selected
        checks = check_conversion(source_info, selected_path, pdfa=bool(args.pdfa))
        validation = validate_pdfa(selected_path, args) if args.pdfa else None
        if not args.pdfa and getattr(args, "keep_uncompressed", False):
            shutil.copy2(original, original.with_name(original.stem + "-uncompressed.pdf"))
        selected_path.replace(destination)
    checks["uri_link_count"] = len(checks.pop("uri_links"))
    record = {"path": str(destination), "kind": "pdfa-2b" if args.pdfa else "pdf",
              "bytes": size, "sha256": hashlib.sha256(destination.read_bytes()).hexdigest(),
              "compression": dataclasses.asdict(final_settings), "target_bytes": args.target_size,
              "target_met": met, "trials": trials, "checks": checks,
              "external_validation": validation}
    args._pdf_records.append(record)
    if not met:
        args._target_failed = True
        print(f"[warn] Target < {args.target_size:,} bytes was not reached; smallest trial saved ({size:,} bytes). Exit status 2.", file=sys.stderr)
    print(f"[output] {destination} ({size:,} bytes)")
    if args.pdfa and not args.no_manifest:
        destination.with_suffix(".manifest.json").write_text(
            json.dumps({"source_pdf": str(original), "source_sha256": hashlib.sha256(original.read_bytes()).hexdigest(),
                        "output": record}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    elif args.pdfa:
        destination.with_suffix(".manifest.json").unlink(missing_ok=True)
    return [record]
