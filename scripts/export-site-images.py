#!/usr/bin/env python3
"""Gallery edition of the existing bilingual site or Metaweb PDF (no new build).

Requires the existing pypdf/Pillow libraries and either Ghostscript or pdftoppm.
Exit 3 means an optional rendering dependency is unavailable; other errors exit 1.
"""
from __future__ import annotations

import argparse
from collections import Counter
import datetime as dt
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

from export_naming import TIMESTAMP_ENV, stamped_path, new_timestamp, validate_timestamp
from pdf_export_common import find_ghostscript

VERSION = "1.1.0"
LANGUAGES = ("cs", "en")


class DependencyUnavailable(RuntimeError):
    pass


def sha256_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def positive_int(value):
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("Value must be positive.")
    return number


def positive_float(value):
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise argparse.ArgumentTypeError("Value must be finite and positive.")
    return number


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", action="version", version=VERSION)
    parser.add_argument("--project-root", default=str(Path(__file__).resolve().parent.parent))
    parser.add_argument("--scope", choices=["all", "metaweb"], default="all")
    parser.add_argument("--pdf", help="Existing combined PDF; never regenerated or modified.")
    parser.add_argument("--source-manifest", help="PDF exporter manifest (auto-detected for standard names).")
    parser.add_argument("--output-dir", default="exports", help="Parent of a new edition folder.")
    parser.add_argument("--timestamp", type=validate_timestamp, help="Shared input/output edition timestamp.")
    parser.add_argument("--format", choices=["jpg", "png"], default="jpg",
                        help="One format for the complete edition (default: jpg).")
    parser.add_argument("--quality", type=int, choices=range(1, 101), metavar="1..100", default=85,
                        help="JPEG quality (default: 85).")
    parser.add_argument("--dpi", type=positive_int, default=150)
    parser.add_argument("--max-edge", type=positive_int, default=2560,
                        help="Maximum final width/height including footer (default: 2560).")
    parser.add_argument("--no-footer", action="store_true", help="Keep only the unchanged PDF page raster.")
    parser.add_argument("--backend", choices=["auto", "ghostscript", "poppler"], default="auto")
    parser.add_argument("--ghostscript", help="Ghostscript executable; auto-detected by default.")
    parser.add_argument("--pdftoppm", help="Poppler pdftoppm executable; auto-detected by default.")
    parser.add_argument("--batch-size", type=positive_int, default=100,
                        help="Files per upload list; no images are copied (default: 100).")
    parser.add_argument("--max-file-mb", type=positive_float,
                        help="Warn about files exceeding this gallery-specific MiB limit.")
    parser.add_argument("--pages", help="Preview only: source PDF pages/ranges, e.g. 1,6-8,790.")
    parser.add_argument("--timeout", type=positive_int, default=180,
                        help="Renderer timeout per group of at most 8 pages, in seconds.")
    parser.add_argument("--verify", metavar="DIRECTORY", help="Verify a relocated edition without its source PDF.")
    args = parser.parse_args(argv)
    if args.max_edge < 128:
        parser.error("--max-edge must be at least 128 pixels.")
    return args


def basename(value):
    # Manifests may have been produced on a different operating system.
    return str(value).replace("\\", "/").rsplit("/", 1)[-1]


def resolve(root, value):
    path = Path(value).expanduser()
    return (path if path.is_absolute() else root / path).resolve()


def locate_source(args, root):
    edition = args.timestamp or os.environ.get(TIMESTAMP_ENV)
    base = "vojtamaur-web-export-" + ("all-cs-en" if args.scope == "all" else "metaweb")
    if args.pdf:
        pdf = resolve(root, args.pdf)
    elif edition:
        validate_timestamp(edition)
        pdf = root / "exports" / f"{base}-{edition}.pdf"
    else:
        # Restrict discovery to ordinary, timestamped source PDFs, not derivatives.
        pattern = re.compile(re.escape(base) + r"-\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}-\d{6}\.pdf$")
        candidates = sorted(p for p in (root / "exports").glob(f"{base}-*.pdf") if pattern.fullmatch(p.name))
        if not candidates:
            raise ValueError(f"No {args.scope} PDF edition found. Run its PDF exporter first or use --pdf.")
        pdf = candidates[-1]
    if args.source_manifest:
        manifest = resolve(root, args.source_manifest)
    elif args.scope == "metaweb":
        manifest = pdf.with_suffix(".manifest.json")
    else:
        suffix = pdf.stem.removeprefix("vojtamaur-web-export-all-cs-en")
        manifest = pdf.parent / f"vojtamaur-web-export-pdf{suffix}.manifest.json"
    if not pdf.is_file() or not manifest.is_file():
        raise ValueError(f"Source PDF or matching manifest missing: {pdf.name}, {manifest.name}")
    return pdf, manifest


def dependencies():
    try:
        import pypdf  # noqa: F401
        import PIL.Image  # noqa: F401
    except ImportError as exc:
        raise DependencyUnavailable("Install existing export dependencies: python -m pip install -r "
                                    "requirements-pdf-export.txt -r requirements-sstv-export.txt") from exc


def find_renderer(args):
    if args.backend in ("auto", "ghostscript"):
        gs = find_ghostscript(args.ghostscript)
        if gs:
            return "ghostscript", gs
    if args.backend in ("auto", "poppler"):
        value = args.pdftoppm or "pdftoppm"
        executable = shutil.which(value)
        if executable:
            return "poppler", Path(executable).resolve()
    raise DependencyUnavailable("No PDF rasterizer found. Use existing Ghostscript or optional Poppler "
                                "pdftoppm (--ghostscript / --pdftoppm). Other exports can continue.")


def make_plan(reader, data, scope, source_hash, source_bytes):
    """Fail closed on stale manifests, missing bookmarks or ambiguous language maps."""
    page_count = len(reader.pages)
    outputs = data.get("outputs", []) if scope == "all" else [data.get("output", {})]
    matching = [record for record in outputs if record.get("sha256") == source_hash
                and record.get("bytes") == source_bytes]
    if len(matching) != 1:
        raise ValueError("Source PDF hash/size does not match its manifest.")
    outlines = reader.outline
    if any(isinstance(item, list) for item in outlines):
        raise ValueError("Unexpected nested source bookmarks; cannot safely map page languages.")
    starts = [reader.get_destination_page_number(item) + 1 for item in outlines]
    if not starts or starts[0] != 1 or starts != sorted(set(starts)) or starts[-1] > page_count:
        raise ValueError("Source PDF bookmarks do not cover the complete page sequence.")
    parts = []
    if scope == "all":
        if data.get("mode") != "combined" or data.get("language") != "both" or data.get("sections"):
            raise ValueError("The all scope requires the complete combined bilingual site PDF.")
        jobs = data.get("pages", [])
        index = bool(outlines and outlines[0].title == "Export index")
        if len(outlines) != len(jobs) + int(index) or not jobs:
            raise ValueError("Article manifest/bookmark count mismatch.")
        if index:
            parts.append(dict(title="Export index", source="generated bilingual index", source_language="cs-en",
                              targets=list(LANGUAGES), translation_status="shared"))
        for job, outline in zip(jobs, outlines[int(index):]):
            lang = job["lang"]
            expected = f"{lang.upper()} · {job['section_label']} · {job['title']}"
            if lang == "en" and job["translation_status"] != "translated":
                expected += " · EN incomplete"
            if lang not in LANGUAGES or outline.title != expected:
                raise ValueError("Article bookmark does not match the manifest language/title.")
            parts.append(dict(title=job["title"], source=job["url_path"], source_language=lang,
                              targets=[lang], slug=job["slug"], public_url=job["public_url"],
                              translation_status=job["translation_status"]))
    else:
        sections = data.get("sections", [])
        if len(sections) != len(outlines) or matching[0].get("pages") != page_count:
            raise ValueError("Metaweb manifest/bookmark/page count mismatch.")
        for section, outline, start, end in zip(sections, outlines, starts, starts[1:] + [page_count + 1]):
            if (section["title"] != outline.title or section["start_page"] != start
                    or section["pages"] != end - start):
                raise ValueError("Metaweb section range does not match the source PDF.")
            source = section["source"]
            lang = "cs-en"
            if source == "/metawebovy-clanek/":
                lang = "cs"
            elif source == "/en/metawebovy-clanek/":
                lang = "en"
            elif basename(source) == basename(data.get("ultra_export", {}).get("path", "")):
                lang = "cs"
            elif source == "/documentation/":
                lang = "en"
            elif source.startswith(("/SHA256", "/BUILD_", "/integrity.", "/SIGNING_", "/keys/")):
                lang = "und"
            parts.append(dict(title=section["title"], source=source if not re.match(r"^[A-Za-z]:", source)
                              else basename(source), source_language=lang, targets=["cs-en"],
                              translation_status="source"))
    plan = []
    for part, start, end in zip(parts, starts, starts[1:] + [page_count + 1]):
        for number in range(start, end):
            page = reader.pages[number - 1]
            box = page.cropbox
            dimension = max(float(box.width), float(box.height)) * float(page.get("/UserUnit", 1))
            if not math.isfinite(dimension) or dimension <= 0:
                raise ValueError(f"Invalid PDF page dimensions: {number}")
            plan.append(dict(part, source_page=number, dimension_pt=dimension))
    if len(plan) != page_count:
        raise ValueError("Page plan does not cover the entire source PDF.")
    return plan


def select_pages(value, count):
    if value is None:
        return set(range(1, count + 1))
    selected = set()
    for item in value.split(","):
        if not re.fullmatch(r"\d+(?:-\d+)?", item.strip()):
            raise ValueError("--pages must contain source page numbers/ranges, e.g. 1,6-8.")
        bounds = [int(number) for number in item.strip().split("-")]
        first, last = bounds[0], bounds[-1]
        if not 1 <= first <= last <= count:
            raise ValueError(f"Source page range outside 1..{count}: {item}")
        selected.update(range(first, last + 1))
    return selected


def render_group(backend, executable, pdf, pages, folder, dpi, timeout):
    first, last = pages[0]["source_page"], pages[-1]["source_page"]
    if backend == "ghostscript":
        command = [str(executable), "-dSAFER", "-dBATCH", "-dNOPAUSE", "-dQUIET", "-sDEVICE=png16m",
                   "-dTextAlphaBits=4", "-dGraphicsAlphaBits=4", "-dUseCropBox", f"-r{dpi}",
                   f"-dFirstPage={first}", f"-dLastPage={last}",
                   f"-sOutputFile={folder / 'page-%06d.png'}", "-f", str(pdf)]
        extension = "png"
    else:
        command = [str(executable), "-f", str(first), "-l", str(last), "-r", str(dpi), "-cropbox",
                   str(pdf), str(folder / "page")]
        extension = "ppm"
    result = subprocess.run(command, capture_output=True, timeout=timeout)
    if result.returncode:
        message = (result.stderr + result.stdout).decode("utf-8", errors="replace")[-2000:]
        raise ValueError(f"{backend} failed for PDF pages {first}-{last}: {message}")
    files = sorted(folder.glob(f"page-*.{extension}"), key=lambda path: int(path.stem.rsplit("-", 1)[-1]))
    if len(files) != len(pages):
        raise ValueError(f"Rasterizer returned {len(files)} pages, expected {len(pages)}.")
    return files


def prepare_image(image, args, lang, number, total, source_page):
    from PIL import Image, ImageDraw, ImageFont
    image = image.convert("RGB")
    image.thumbnail((args.max_edge, args.max_edge), Image.Resampling.LANCZOS)
    if not args.no_footer:
        band = max(32, round(image.width * 0.03))
        canvas = Image.new("RGB", (image.width, image.height + band), "white")
        canvas.paste(image, (0, 0))
        draw = ImageDraw.Draw(canvas)
        draw.line((0, image.height, image.width, image.height), fill="#aaaaaa")
        label = f"vojtamaur.cz | {lang.upper().replace('-', '+')} | {number:06d}/{total:06d} | PDF {source_page:06d}"
        font = ImageFont.load_default(size=max(10, round(image.width / 85)))
        while draw.textlength(label, font=font) > image.width - 12:
            font = ImageFont.load_default(size=max(1, font.size - 1))
        draw.text((image.width / 2, image.height + band / 2), label, fill="#333333", font=font, anchor="mm")
        image.close()
        image = canvas
        image.thumbnail((args.max_edge, args.max_edge), Image.Resampling.LANCZOS)
    return image


def encode_image(image, args):
    output = io.BytesIO()
    if args.format == "jpg":
        image.save(output, "JPEG", quality=args.quality, subsampling=0, optimize=True, progressive=True)
    elif args.format == "png":
        image.save(output, "PNG", optimize=True)
    else:
        raise ValueError("Choose one format for the complete edition: jpg or png.")
    return output.getvalue()


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def verify_export(folder):
    from PIL import Image
    folder = folder.resolve()
    data = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    checksums = {}
    for line in (folder / "SHA256SUMS.txt").read_text(encoding="utf-8").splitlines():
        digest, name = line.split("  ", 1)
        path = folder / name
        if (not re.fullmatch(r"[a-f0-9]{64}", digest) or name in checksums
                or "\\" in name or not path.resolve().is_relative_to(folder)):
            raise ValueError(f"Invalid checksum entry: {name}")
        if not path.is_file() or sha256_file(path) != digest:
            raise ValueError(f"Missing or changed export file: {name}")
        checksums[name] = digest
    actual = {p.relative_to(folder).as_posix() for p in folder.rglob("*") if p.is_file()
              and p != folder / "SHA256SUMS.txt"}
    if set(checksums) != actual:
        raise ValueError("Checksum inventory differs from the files present.")
    if "manifest.json" not in checksums or len(data["pages"]) != data["page_count"]:
        raise ValueError("Manifest is missing or page count is inconsistent.")
    version = data.get("schema_version", 1)
    if version not in (1, 2):
        raise ValueError(f"Unsupported manifest schema version: {version}")
    single = version == 2 and data["scope"] == "metaweb"
    editions = ("cs-en",) if single else LANGUAGES
    if sum(page["lang"] in editions for page in data["pages"]) != data["page_count"]:
        raise ValueError("Unexpected edition language in page records.")
    if version == 2:
        kind = data["settings"]["format"]
        if kind not in ("jpg", "png") or data["formats"] != {kind: data["page_count"]}:
            raise ValueError("An edition must use one image format consistently.")
        if data["layout"] != ("single-sequence" if single else "language-folders"):
            raise ValueError("Unexpected edition layout.")
        if single and [page["source_page"] for page in data["pages"]] != data["source_pages_exported"]:
            raise ValueError("Metaweb must contain each selected PDF page exactly once, in source order.")
    for lang in editions:
        pages = [page for page in data["pages"] if page["lang"] == lang]
        if [page["number"] for page in pages] != list(range(1, len(pages) + 1)):
            raise ValueError(f"Non-contiguous {lang} page numbering.")
        if version == 2 and data["counts"].get(lang, 0) != len(pages):
            raise ValueError(f"Inconsistent {lang} page count.")
        for page in pages:
            if version == 2:
                expected = ("" if single else f"{lang}/") + f"{page['number']:06d}.{kind}"
                if page["file"] != expected or page["format"] != kind:
                    raise ValueError(f"Page format/path differs from the edition: {page['file']}")
            if checksums.get(page["file"]) != page["sha256"]:
                raise ValueError(f"Page hash differs from inventory: {page['file']}")
            with Image.open(folder / page["file"]) as image:
                if image.size != (page["width"], page["height"]) or image.mode != "RGB":
                    raise ValueError(f"Page dimensions/mode mismatch: {page['file']}")
                if version == 2 and image.format != ("JPEG" if kind == "jpg" else "PNG"):
                    raise ValueError(f"Image encoding differs from its extension: {page['file']}")
                image.verify()
    return data


def run(args):
    dependencies()
    root = Path(args.project_root).resolve()
    if args.verify:
        data = verify_export(resolve(root, args.verify))
        print(f"[verified] {data['page_count']} images; hashes, order and dimensions OK.")
        return 0
    backend, executable = find_renderer(args)
    pdf, source_manifest = locate_source(args, root)
    source_hash, manifest_hash = sha256_file(pdf), sha256_file(source_manifest)
    source_data = json.loads(source_manifest.read_text(encoding="utf-8"))
    from pypdf import PdfReader
    from PIL import Image
    with pdf.open("rb") as handle:
        reader = PdfReader(handle)
        plan = make_plan(reader, source_data, args.scope, source_hash, pdf.stat().st_size)
    selected = select_pages(args.pages, len(plan))
    preview = len(selected) != len(plan)
    selected_plan = [page for page in plan if page["source_page"] in selected]
    editions = LANGUAGES if args.scope == "all" else ("cs-en",)
    single = args.scope == "metaweb"
    totals = Counter(lang for page in selected_plan for lang in page["targets"])
    stamp = args.timestamp or new_timestamp()
    parent = resolve(root, args.output_dir)
    destination = stamped_path(parent / f"vojtamaur-web-export-images-{args.scope}{'-preview' if preview else ''}", stamp)
    if destination.exists():
        raise ValueError(f"Edition already exists; choose a new timestamp: {destination}")
    parent.mkdir(parents=True, exist_ok=True)
    records, warnings, counters = [], [], Counter()
    summary = ", ".join(f"{lang.upper().replace('-', '+')} {totals[lang]}" for lang in editions)
    print(f"[images] {args.scope}: {len(selected_plan)}/{len(plan)} source pages; "
          f"{summary}; {args.format.upper()}; {backend}", flush=True)
    with tempfile.TemporaryDirectory(prefix=".image-export-", dir=parent) as temporary:
        stage = Path(temporary) / "edition"
        stage.mkdir()
        if not single:
            for lang in editions:
                (stage / lang).mkdir()
        offset = 0
        while offset < len(selected_plan):
            # Bound disk/memory use and renderer startup overhead. Avoid rasterizing giant
            # sheets at the nominal DPI before resizing them to the gallery limit.
            page = selected_plan[offset]
            effective_dpi = round(min(args.dpi, args.max_edge * 72 / page["dimension_pt"]), 3)
            group = [page]
            while offset + len(group) < len(selected_plan) and len(group) < 8:
                candidate = selected_plan[offset + len(group)]
                dpi = round(min(args.dpi, args.max_edge * 72 / candidate["dimension_pt"]), 3)
                if candidate["source_page"] != group[-1]["source_page"] + 1 or dpi != effective_dpi:
                    break
                group.append(candidate)
            with tempfile.TemporaryDirectory(prefix="raster-", dir=temporary) as raster_dir:
                files = render_group(backend, executable, pdf, group, Path(raster_dir), effective_dpi, args.timeout)
                for entry, raster in zip(group, files):
                    with Image.open(raster) as original:
                        for lang in entry["targets"]:
                            counters[lang] += 1
                            number = counters[lang]
                            with prepare_image(original, args, lang, number, totals[lang], entry["source_page"]) as image:
                                payload = encode_image(image, args)
                                kind = args.format
                                name = ("" if single else f"{lang}/") + f"{number:06d}.{kind}"
                                (stage / name).write_bytes(payload)
                                record = {key: value for key, value in entry.items()
                                          if key not in {"targets", "dimension_pt"}}
                                record.update(file=name, lang=lang, number=number, width=image.width, height=image.height,
                                              format=kind, bytes=len(payload), sha256=hashlib.sha256(payload).hexdigest(),
                                              render_dpi=effective_dpi)
                                records.append(record)
                                if args.max_file_mb and len(payload) > args.max_file_mb * 1024 * 1024:
                                    warnings.append(f"{name} exceeds --max-file-mb {args.max_file_mb}.")
            offset += len(group)
            print(f"[images] {offset}/{len(selected_plan)} source pages encoded", flush=True)
        # The site has two language editions; Metaweb is one complete PDF sequence.
        records.sort(key=lambda record: (record["lang"], record["number"]))
        batches = []
        for lang in editions:
            pages = [record["file"] for record in records if record["lang"] == lang]
            prefix = "upload" if single else f"upload-{lang}"
            (stage / f"{prefix}.txt").write_text("".join(f"{name}\n" for name in pages), encoding="utf-8")
            for start in range(0, len(pages), args.batch_size):
                name = f"{prefix}-{start // args.batch_size + 1:03d}.txt"
                files = pages[start:start + args.batch_size]
                (stage / name).write_text("".join(f"{file}\n" for file in files), encoding="utf-8")
                batches.append(dict(file=name, lang=lang, count=len(files)))
        limitations = [
            ("The site's shared bilingual index appears in both language folders in its original languages."
             if not single else "Metaweb is one bilingual sequence in original PDF order, including all appendices. "
             "Every source PDF page appears exactly once; no language split or duplication is performed."),
            "English routes retain the PDF's translation/fallback status. No translation is performed.",
            "The source PDF's pagination, clipping and static media limitations are inherited. "
            "Raster images do not preserve selectable text, clickable links or executable/animated media.",
            "JPEG is lossy; use --format png for lossless page rasters. "
            "One chosen format is used for the complete edition; no automatic format selection is performed.",
            "Gallery limits and recompression vary. Upload lists are configurable suggestions, "
            "not a promise that a service accepts a whole edition or batch. Never upload manifest files as images.",
            "Keep originals and SHA256SUMS.txt locally; galleries may strip metadata, rename, reorder or recompress images. "
            "Checksums detect changes but do not provide a digital signature.",
        ]
        data = dict(schema_version=2, generator=f"export-site-images.py {VERSION}", scope=args.scope,
                    layout="single-sequence" if single else "language-folders",
                    generated_at=dt.datetime.now().astimezone().isoformat(timespec="seconds"), timestamp=stamp,
                    source=dict(pdf=pdf.name, sha256=source_hash, bytes=pdf.stat().st_size, pages=len(plan),
                                manifest=source_manifest.name, manifest_sha256=manifest_hash),
                    renderer=dict(backend=backend, executable=executable.name),
                    settings=dict(format=args.format, quality=args.quality, dpi=args.dpi, max_edge=args.max_edge,
                                  footer=not args.no_footer, batch_size=args.batch_size, max_file_mb=args.max_file_mb),
                    partial=preview, source_pages_exported=sorted(selected), page_count=len(records),
                    counts=dict(totals), total_bytes=sum(page["bytes"] for page in records),
                    formats=dict(Counter(page["format"] for page in records)), batches=batches,
                    warnings=warnings, limitations=limitations, pages=records)
        write_json(stage / "manifest.json", data)
        instructions = (
            "CS: Metaweb je jedna bilingvni rada v puvodnim poradi PDF, vcetne vsech priloh. "
            "Kazda stranka je zde prave jednou; bez jazykovych podslozek.\n\n"
            "Read the numbered images in this folder in numeric filename order. "
            "The complete bilingual Metaweb PDF is preserved page for page, with all appendices.\n"
            "upload.txt and numbered upload-001.txt batch lists use paths relative to this folder.\n"
            if single else
            "CS: Obrazova archivni edice. Cislovani je samostatne pro kazdy jazyk. "
            "Sdileny rejstrik zustava v puvodnich jazycich. Zachovejte poradi souboru.\n\n"
            "Read cs/ and en/ separately in numeric filename order. Content marked shared is not translated.\n"
            "upload-cs.txt / upload-en.txt and numbered batch lists use paths relative to this folder.\n"
        )
        (stage / "README.txt").write_text(
            f"Vojta Maur | https://vojtamaur.cz/ | Gallery edition: {args.scope}\n"
            f"{summary} images; format: {args.format.upper()}; partial preview: {preview}\n\n"
            + instructions +
            "Footer: edition language(s), local page/total and original PDF page.\n"
            "manifest.json records source PDF identity, page mapping, language/status, dimensions, "
            "encoding and hashes. No source files need to remain at their original paths.\n"
            "Verify after copying: python scripts/export-site-images.py --verify PATH_TO_THIS_FOLDER\n\n"
            "Public preservation copies must credit Vojta Maur and https://vojtamaur.cz/. "
            "Other reuse requires permission; see the source project's license.\n\n"
            + "\n".join("- " + item for item in limitations) + "\n", encoding="utf-8")
        files = sorted(path for path in stage.rglob("*") if path.is_file())
        (stage / "SHA256SUMS.txt").write_text("".join(
            f"{sha256_file(path)}  {path.relative_to(stage).as_posix()}\n" for path in files), encoding="utf-8")
        verify_export(stage)
        if sha256_file(pdf) != source_hash or sha256_file(source_manifest) != manifest_hash:
            raise ValueError("Source PDF/manifest changed during export; edition was not published.")
        stage.rename(destination)  # Same filesystem; never expose a partial edition or overwrite old output.
    print(f"[done] {destination}\n[done] {len(records)} images, {data['total_bytes']:,} bytes; "
          f"formats: {data['formats']}; warnings: {len(warnings)}", flush=True)
    return 0


def main(argv=None):
    args = parse_args(argv)
    try:
        return run(args)
    except DependencyUnavailable as exc:
        print(f"[unavailable] {exc}", file=sys.stderr)
        return 3
    except (ValueError, OSError, RuntimeError, subprocess.SubprocessError) as exc:
        print(f"[error] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
