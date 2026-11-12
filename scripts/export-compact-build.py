#!/usr/bin/env python3
"""Build and package a standalone, size-capped edition of the site."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from hashlib import sha256
from html.parser import HTMLParser
from io import BytesIO
from itertools import chain
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from urllib.parse import quote, unquote, urljoin, urlsplit
from zipfile import ZIP_DEFLATED, ZipFile

from export_naming import new_timestamp, stamped_path
from pdf_export_common import Settings, check_conversion, convert, find_ghostscript, inspect

ROOT = Path(__file__).resolve().parent.parent
EXPORTS = ROOT / "exports"
RAT = "kurt-godel-rat.jpg"
STATIC_RASTERS = {".jpg", ".jpeg", ".png", ".webp"}
TEXT_ASSETS = {".html", ".css", ".js", ".mjs", ".svg"}


@dataclass(frozen=True)
class Profile:
    edge: int
    quality: int
    animation_edge: int | None
    thumbnail_width: int
    pdf: Settings


PROFILES = {
    40: Profile(600, 30, 360, 400, Settings(110, 72)),
    100: Profile(1600, 58, None, 480, Settings(180, 85)),
}


def log(message: str) -> None:
    print(f"[compact] {message}", flush=True)


def node(script: str, *args: str, env: dict[str, str]) -> None:
    subprocess.run(["node", script, *args], cwd=ROOT, env=env, check=True)


def build_environment(target: str, dist: Path) -> dict[str, str]:
    return {
        **os.environ,
        "BUILD_TARGET": target,
        "DIST_DIR": str(dist),
        "COMPACT_BUILD": "1",
        "EN_TRANSLATE": "off",
        "EN_STRICT": "1",
        "EN_PRUNE_CACHE": "0",
    }


def build_base(target: str, dist: Path) -> None:
    env = build_environment(target, dist)
    node("node_modules/astro/astro.js", "build", "--outDir", str(dist), env=env)
    node("scripts/en-postprocess.mjs", env=env)
    node("scripts/generate-source-bundle.mjs", str(dist), "--no-jpeg-carrier", env=env)


class ImageReferences(HTMLParser):
    def __init__(self, page_url: str) -> None:
        super().__init__()
        self.page_url = page_url
        self.thumbnails: set[str] = set()
        self.other: set[str] = set()
        self.article_card = False
        self.thumbnail_child = False

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        classes = (attributes.get("class") or "").split()
        if tag == "a":
            self.article_card = "post-card" in classes and attributes.get("target") != "_blank"

        is_thumbnail = tag == "img" and self.article_card and self.thumbnail_child
        self.thumbnail_child = "post-card__thumb" in classes

        for attribute, value in attrs:
            if not value:
                continue
            if attribute == "srcset":
                urls = [item.strip().split()[0] for item in value.split(",") if item.strip()]
            elif attribute in {"src", "href", "poster"} or (tag == "object" and attribute == "data"):
                urls = [value]
            else:
                continue
            for url in urls:
                if "images/" not in url:
                    continue
                parsed = urlsplit(urljoin(self.page_url, url))
                path = unquote(parsed.path).lstrip("/")
                if parsed.hostname != "vojtamaur.cz" or not path.startswith("images/"):
                    continue
                group = self.thumbnails if is_thumbnail and attribute in {"src", "srcset"} else self.other
                group.add(path)

    def handle_endtag(self, tag):
        self.thumbnail_child = False
        if tag == "a":
            self.article_card = False


def find_thumbnail_paths(dist: Path) -> set[str]:
    thumbnails = set()
    other = set()
    for file in dist.rglob("*.html"):
        page = file.relative_to(dist).as_posix()
        references = ImageReferences("https://vojtamaur.cz/" + quote(page))
        references.feed(file.read_text(encoding="utf-8"))
        thumbnails.update(references.thumbnails)
        other.update(references.other)
    # A full-size illustration can also be used in a card.
    return thumbnails - other


def static_raster(source, profile: Profile, thumbnail: bool = False) -> tuple[bytes, str] | None:
    from PIL import Image, ImageOps

    if getattr(source, "is_animated", False) or source.mode.startswith(("I", "F")):
        return None
    image = ImageOps.exif_transpose(source)
    metadata = {key: image.info[key] for key in ("icc_profile", "exif", "xmp") if image.info.get(key)}
    lossless = source.format != "JPEG" and image.getcolors(256) is not None
    resize_thumbnail = thumbnail and image.width > profile.thumbnail_width
    if resize_thumbnail:
        height = max(1, round(image.height * profile.thumbnail_width / image.width))
        image = image.convert("RGBA" if image.has_transparency_data else "RGB")
        image = image.resize((profile.thumbnail_width, height), Image.Resampling.LANCZOS)

    webp = None
    if lossless:
        output = BytesIO()
        image.save(output, "WEBP", lossless=True, method=6, exact=True, **metadata)
        webp = output.getvalue()
        if not resize_thumbnail:
            return webp, ".webp"

    image = image.convert("RGBA" if image.has_transparency_data else "RGB")
    image.thumbnail((profile.edge, profile.edge), Image.Resampling.LANCZOS)
    output = BytesIO()
    image.save(output, "AVIF", quality=profile.quality, speed=5, max_threads=1, **metadata)
    if webp is not None and len(webp) <= output.tell():
        return webp, ".webp"
    return output.getvalue(), ".avif"


def gif_raster(source, profile: Profile) -> tuple[bytes, str] | None:
    from PIL import Image, ImageSequence

    # Preserve GIFs with finite repetition or browser-dependent short delays.
    if source.info.get("loop") != 0:
        return None
    frames = []
    durations = []
    for frame in ImageSequence.Iterator(source):
        duration = frame.info.get("duration", 0)
        if duration < 20:
            return None
        frames.append(frame.convert("RGBA"))
        durations.append(duration)

    output = BytesIO()
    frames[0].save(
        output, "WEBP", save_all=True, append_images=frames[1:], duration=durations,
        loop=0, lossless=True, method=4, minimize_size=True,
    )
    candidate = output.getvalue(), ".webp"
    if profile.animation_edge is None:
        return candidate

    for frame in frames:
        frame.thumbnail((profile.animation_edge, profile.animation_edge), Image.Resampling.LANCZOS)
    output = BytesIO()
    frames[0].save(
        output, "AVIF", save_all=True, append_images=frames[1:], duration=durations,
        quality=42, speed=6, max_threads=2,
    )
    avif = output.getvalue()
    if len(avif) >= len(candidate[0]):
        return candidate

    with Image.open(BytesIO(avif)) as encoded:
        encoded_durations = []
        for frame in ImageSequence.Iterator(encoded):
            frame.load()
            encoded_durations.append(frame.info["duration"])
        if encoded_durations != durations:
            return candidate
    return avif, ".avif"


def optimize_image(file: Path, profile: Profile, thumbnail: bool = False) -> tuple[bytes, str] | None:
    from PIL import Image

    must_resize = False
    with Image.open(file) as source:
        if source.format == "GIF":
            result = gif_raster(source, profile)
        else:
            result = static_raster(source, profile, thumbnail)
            if thumbnail:
                width = source.height if source.getexif().get(274) in {5, 6, 7, 8} else source.width
                must_resize = width > profile.thumbnail_width
    return result if result and (must_resize or len(result[0]) < file.stat().st_size) else None


def rewrite_media_urls(dist: Path, renamed: dict[str, str]) -> None:
    if not renamed:
        return
    encoded = {quote(old): quote(new) for old, new in renamed.items()}
    paths = {**renamed, **encoded}
    choices = "|".join(re.escape(name.removeprefix("images/")) for name in sorted(paths, key=len, reverse=True))
    pattern = re.compile(
        r"(?<![\w./:@%+-])(?P<prefix>https://vojtamaur\.cz/|/|(?:\.\.?/)*)"
        rf"(?P<path>images/(?:{choices}))(?=$|[\s\"'?#,)<>&])"
    )
    for file in dist.rglob("*"):
        if file.suffix.lower() not in TEXT_ASSETS or not file.is_file():
            continue
        original = file.read_bytes()
        text = original.decode("utf-8")
        updated = pattern.sub(lambda match: match["prefix"] + paths[match["path"]], text)
        if updated != text:
            file.write_bytes(updated.encode("utf-8"))


def optimize_images(dist: Path, profile: Profile, thumbnails: frozenset[str]) -> dict[str, str]:
    images = dist / "images"
    files = [
        file for file in sorted(images.rglob("*"))
        if file.is_file() and file.name != RAT and file.suffix.lower() in STATIC_RASTERS | {".gif"}
    ]
    renamed = {}
    saved = 0
    changed = 0
    occupied = {file.relative_to(dist).as_posix().casefold() for file in images.rglob("*")}
    # Animations can have hundreds of decoded frames. Run them one at a time.
    animations = [file for file in files if file.suffix.lower() == ".gif"]
    stills = [file for file in files if file.suffix.lower() != ".gif"]
    with ThreadPoolExecutor(max_workers=min(6, os.cpu_count() or 1)) as pool:
        results = pool.map(
            lambda file: optimize_image(file, profile, file.relative_to(dist).as_posix() in thumbnails),
            stills,
        )
        animated_results = ((file, optimize_image(file, profile)) for file in animations)
        for file, result in chain(zip(stills, results), animated_results):
            if result is None:
                continue
            payload, suffix = result
            saved += file.stat().st_size - len(payload)
            changed += 1
            original = file.relative_to(dist).as_posix()
            destination = file.with_suffix(suffix)
            while destination != file and destination.relative_to(dist).as_posix().casefold() in occupied:
                destination = destination.with_name(destination.stem + "-" + file.suffix[1:] + suffix)
            destination.write_bytes(payload)
            if destination != file:
                replacement = destination.relative_to(dist).as_posix()
                renamed[original] = replacement
                occupied.add(replacement.casefold())
                file.unlink()
    log(f"Optimized {changed}/{len(files)} images, saved {saved / 1e6:.2f} MB before ZIP.")
    return renamed


def optimize_pdfs(dist: Path, profile: Profile, ghostscript: Path, scratch: Path) -> list[str]:
    args = SimpleNamespace(_ghostscript=ghostscript, pdfa=False)
    optimized = []
    candidate = scratch / "optimized.pdf"
    for file in sorted((dist / "files").rglob("*.pdf")):
        before = file.stat().st_size
        if before < 250_000:
            continue
        try:
            convert(file, candidate, profile.pdf, args, None)
            if candidate.stat().st_size >= before:
                continue
            check_conversion(inspect(file), candidate, pdfa=False)
            path = file.relative_to(dist).as_posix()
            log(f"{path}: {before / 1e6:.2f} -> {candidate.stat().st_size / 1e6:.2f} MB")
            optimized.append(path)
            candidate.replace(file)
        except SystemExit as error:
            log(f"Kept {file.name}: {error}")
        finally:
            candidate.unlink(missing_ok=True)
    return optimized


def reuse_media(source: Path, dist: Path, renamed: dict[str, str], pdfs: list[str]) -> None:
    # Both Astro targets copy the same public media.
    shutil.copytree(source / "images", dist / "images", dirs_exist_ok=True)
    for original in renamed:
        (dist / original).unlink()
    for path in pdfs:
        shutil.copyfile(source / path, dist / path)


def finish_build(target: str, budget: int, dist: Path, renamed: dict[str, str], pdfs: list[str]) -> None:
    env = build_environment(target, dist)
    node("scripts/generate-all-posts.mjs", env=env)
    if target == "usb":
        node("scripts/usb-rewrite.mjs", env=env)
    else:
        node("scripts/enrich-sitemap.mjs", str(dist), env=env)
    node("scripts/generate-link-graph.mjs", str(dist), env=env)
    entry = "Open index.html directly from the extracted folder." if target == "usb" else (
        "Serve the extracted folder at the root of a static HTTP server."
    )
    readme = [
        f"VOJTAMAUR.CZ COMPACT {target.upper()} BUILD", "",
        f"ZIP limit: {budget * 1_000_000:,} bytes.", entry, "",
        f"Article card thumbnail width limit: {PROFILES[budget].thumbnail_width} pixels.",
        "Images and PDFs in this edition may differ from the published originals.",
        "The source ZIP and its media checksums refer to the original assets.",
        "kurt-godel-rat.jpg contains its original JPEG and metadata.",
        "The reconstructable package is available at source/vojtamaur-web-source.zip.",
        "Verify the files in this edition against SHA256SUMS.txt.", "",
        "Recompressed PDF files:", *pdfs, "",
        "Renamed image files (original -> compact):",
        *(f"{source} -> {destination}" for source, destination in sorted(renamed.items())), "",
    ]
    (dist / "COMPACT_BUILD.txt").write_bytes("\n".join(readme).encode("utf-8"))
    # Use a portable label in the integrity metadata instead of the staging path.
    subprocess.run(
        ["node", str(ROOT / "scripts" / "generate-integrity.mjs"), ".", target],
        cwd=dist, env=env, check=True,
    )


def find_7zip() -> str | None:
    for name in ("7zz", "7z"):
        if executable := shutil.which(name):
            return executable
    for variable in ("ProgramFiles", "ProgramFiles(x86)"):
        folder = os.environ.get(variable)
        if folder and (executable := Path(folder) / "7-Zip" / "7z.exe").is_file():
            return str(executable)
    return None


def make_zip(dist: Path, output: Path, seven_zip: str | None) -> None:
    files = sorted(path for path in dist.rglob("*") if path.is_file())
    with ZipFile(output, "w", ZIP_DEFLATED, compresslevel=9) as archive:
        for file in files:
            archive.write(file, file.relative_to(dist).as_posix())
    if seven_zip:
        alternative = output.with_name("7zip-" + output.name)
        subprocess.run(
            [seven_zip, "a", "-tzip", "-mm=Deflate", "-mx=9", "-mfb=258", "-mpass=15",
             "-mmt=6", "-bd", "-bb0", str(alternative), "*"],
            cwd=dist, check=True,
        )
        python_size = output.stat().st_size
        seven_zip_size = alternative.stat().st_size
        log(f"ZIP sizes: Python {python_size:,} bytes, 7-Zip {seven_zip_size:,} bytes.")
        if seven_zip_size < python_size:
            alternative.replace(output)
        else:
            alternative.unlink()

    with ZipFile(output) as archive:
        names = {info.filename for info in archive.infolist() if not info.is_dir()}
        if names != {file.relative_to(dist).as_posix() for file in files}:
            raise ValueError("ZIP entry list differs from the staged build.")
        if bad_entry := archive.testzip():
            raise ValueError(f"ZIP integrity check failed: {bad_entry}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--target", choices=("usb", "web", "both"), default="both",
        help="Build target (default: both USB and web).",
    )
    parser.add_argument(
        "--limit", choices=(*map(str, PROFILES), "both", "all"), default="all",
        help="ZIP size limit in decimal MB. Both 'all' and 'both' select 40 and 100 MB.",
    )
    parser.add_argument("--ghostscript", help="Path to the Ghostscript executable.")
    args = parser.parse_args()

    from PIL import features
    if not features.check("avif") or not features.check("webp"):
        raise SystemExit("Install Pillow with AVIF and WebP support: python -m pip install -r requirements-compact-export.txt")
    ghostscript = find_ghostscript(args.ghostscript)
    if not ghostscript:
        raise SystemExit("Install Ghostscript or pass its executable with --ghostscript.")
    seven_zip = find_7zip()
    log("ZIP: Deflate level 9 and 15-pass 7-Zip comparison." if seven_zip else "ZIP: Python Deflate, level 9.")
    targets = ("usb", "web") if args.target == "both" else (args.target,)
    budgets = tuple(PROFILES) if args.limit in {"all", "both"} else (int(args.limit),)
    timestamp = new_timestamp()
    EXPORTS.mkdir(exist_ok=True)
    with TemporaryDirectory(prefix=".compact-", dir=EXPORTS) as staging:
        staging = Path(staging)
        pending = []
        media = {}
        for target in targets:
            base = staging / target
            build_base(target, base)
            thumbnails = frozenset(find_thumbnail_paths(base))
            log(f"Found {len(thumbnails)} images used only as article card thumbnails.")
            for budget in budgets:
                profile = PROFILES[budget]
                log(f"Preparing {target.upper()} for the {budget} MB limit.")
                dist = staging / f"{target}-{budget}mb"
                shutil.copytree(base, dist)
                media_key = (budget, thumbnails)
                if media_key in media:
                    first_build, renamed, pdfs = media[media_key]
                    reuse_media(first_build, dist, renamed, pdfs)
                else:
                    renamed = optimize_images(dist, profile, thumbnails)
                    pdfs = optimize_pdfs(dist, profile, ghostscript, staging)
                    media[media_key] = dist, renamed, pdfs
                rewrite_media_urls(dist, renamed)
                finish_build(target, budget, dist, renamed, pdfs)
                final = stamped_path(EXPORTS / f"vojtamaur-web-compact-{target}-{budget}mb.zip", timestamp)
                temporary = staging / final.name
                make_zip(dist, temporary, seven_zip)
                size = temporary.stat().st_size
                if size > budget * 1_000_000:
                    raise ValueError(f"{target.upper()} ZIP is {size:,} bytes and exceeds the {budget} MB limit.")
                pending.append((temporary, final, size))
        for temporary, final, size in pending:
            if final.exists():
                raise FileExistsError(final)
            temporary.rename(final)
            digest = sha256(final.read_bytes()).hexdigest()
            log(f"{final} ({size:,} bytes, SHA-256 {digest})")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        sys.exit(f"[compact] Failed: {error}")
