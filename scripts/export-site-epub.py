#!/usr/bin/env python3
"""Export finished vojtamaur.cz article pages from dist/ to reflowable EPUB."""

from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import html
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urljoin

from export_common import (
    atomic_write_text,
    BuiltPost,
    EpubBookBuilder,
    EpubBuildResult,
    EpubSourcePage,
    IMAGE_QUALITY_PRESETS,
    find_built_article_html,
    image_settings,
    normalize_site_url,
    parse_all_posts_index,
    read_built_page_metadata,
    require_epub_dependencies,
    resolve_path,
    safe_filename,
    sha256_file,
    sorted_built_posts,
    stable_identifier,
)


SCRIPT_VERSION = "1.2.1"
DEFAULT_SITE_URL = "https://vojtamaur.cz"
MANIFEST_NAME = "vojtamaur-web-export-epub.manifest.json"
SECTION_LABELS = {
    "cs": {
        "volna-tvorba": "Volná tvorba",
        "vystavy": "Výstavy",
        "cestovani": "Cestování",
    },
    "en": {
        "volna-tvorba": "Personal Work",
        "vystavy": "Exhibitions",
        "cestovani": "Travel",
    },
}


@dataclasses.dataclass(frozen=True)
class SiteJob:
    post: BuiltPost
    html_file: Path
    public_url: str
    display_title: str
    translation_status: str

    @property
    def section_label(self) -> str:
        return SECTION_LABELS.get(self.post.lang, {}).get(
            self.post.section,
            self.post.section,
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Export built vojtamaur-web article pages from dist/ to reflowable "
            "EPUB. With --lang both, separate Czech and English books are made."
        )
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {SCRIPT_VERSION}",
    )
    parser.add_argument(
        "--project-root",
        default=".",
        help="Project root containing dist/. Default: current directory.",
    )
    parser.add_argument(
        "--dist",
        default="dist",
        help="Finished site directory, relative to project root unless absolute. Default: dist",
    )
    parser.add_argument(
        "--site-url",
        default=DEFAULT_SITE_URL,
        help=(
            "Public site root retained for links that cannot be embedded in EPUB. "
            f"Default: {DEFAULT_SITE_URL}"
        ),
    )
    parser.add_argument(
        "--output-dir",
        default="exports",
        help="Output directory, relative to project root unless absolute. Default: exports",
    )
    parser.add_argument(
        "--output",
        default=None,
        help=(
            "Output EPUB path in combined single-language mode. With --lang both "
            "the two default output names are used."
        ),
    )
    parser.add_argument(
        "--lang",
        choices=["cs", "en", "both"],
        default="both",
        help="Language export. 'both' creates two independent EPUB files. Default: both",
    )
    parser.add_argument(
        "--section",
        action="append",
        default=[],
        help=(
            "Section filter. Can be repeated or comma-separated. "
            "Examples: --section cestovani --section vystavy or "
            "--section cestovani,vystavy"
        ),
    )
    parser.add_argument(
        "--separate",
        action="store_true",
        help="Create one EPUB per selected article instead of one book per language.",
    )
    parser.add_argument(
        "--allow-missing",
        action="store_true",
        help="Skip missing built HTML pages. By default, missing pages fail the export.",
    )
    parser.add_argument(
        "--build-command",
        default=None,
        help=(
            'Optional command to run before export, for example: '
            '"npm run build:web:strict". Not used unless explicitly passed.'
        ),
    )
    parser.add_argument(
        "--no-cover",
        action="store_true",
        help=(
            "Do not add the generated title/frontmatter and article index to "
            "combined EPUB books. Separate article exports never add it."
        ),
    )
    parser.add_argument(
        "--no-manifest",
        action="store_true",
        help=f"Do not write {MANIFEST_NAME}.",
    )
    parser.add_argument(
        "--title",
        default=None,
        help=(
            "Combined book title override. In --lang both mode, (CS) or (EN) "
            "is appended. By default a language-specific title is generated."
        ),
    )
    parser.add_argument(
        "--author",
        default="Vojta Maur",
        help="dc:creator metadata. Default: Vojta Maur",
    )
    parser.add_argument(
        "--image-quality",
        choices=list(IMAGE_QUALITY_PRESETS),
        default="archive",
        help=(
            "Image preset: archive keeps EPUB-core source bytes; printer, ebook, and "
            "screen progressively reduce raster dimensions and JPEG quality; "
            "compact also converts opaque PNG files and GIFs to static images. "
            "AVIF is always converted to JPEG or PNG. Default: archive"
        ),
    )
    parser.add_argument(
        "--image-max-px",
        type=int,
        default=None,
        help=(
            "Override the preset maximum width/height in pixels. JPEG and PNG "
            "images larger than this are downscaled."
        ),
    )
    parser.add_argument(
        "--jpeg-quality",
        type=int,
        default=None,
        help="Override JPEG quality from 1 to 100.",
    )
    parser.add_argument(
        "--png-mode",
        choices=["preserve", "jpeg"],
        default=None,
        help=(
            "How to package opaque PNG files. Default: preserve, except compact "
            "uses jpeg. PNG files with transparency always remain PNG."
        ),
    )
    parser.add_argument(
        "--gif-mode",
        choices=["preserve", "poster"],
        default=None,
        help=(
            "How to package animated GIF files. preserve keeps animation; poster "
            "uses the first frame as PNG. Default: preserve, except compact uses poster."
        ),
    )
    return parser.parse_args()


def split_csv(values: Iterable[str]) -> list[str]:
    items: list[str] = []
    for value in values:
        for item in value.split(","):
            item = item.strip()
            if item and item not in items:
                items.append(item)
    return items


def languages_from_arg(value: str) -> list[str]:
    return ["cs", "en"] if value == "both" else [value]


def public_page_url(site_url: str, slug: str, lang: str) -> str:
    prefix = "en/" if lang == "en" else ""
    return urljoin(site_url, f"{prefix}{slug.strip('/')}/")


def make_jobs(
    posts: list[BuiltPost],
    dist_dir: Path,
    sections: list[str],
    languages: list[str],
    site_url: str,
    allow_missing: bool,
) -> list[SiteJob]:
    wanted_sections = set(sections)
    wanted_languages = set(languages)
    selected = [
        post
        for post in posts
        if post.lang in wanted_languages
        and (not wanted_sections or post.section in wanted_sections)
    ]

    jobs: list[SiteJob] = []
    missing: list[str] = []
    for post in sorted_built_posts(selected):
        html_file = find_built_article_html(dist_dir, post.slug, post.lang)
        if html_file is None:
            missing.append(f"{post.lang.upper()} {post.section}/{post.slug}")
            continue
        display_title, noindex = read_built_page_metadata(
            html_file,
            post.title,
        )
        jobs.append(
            SiteJob(
                post=post,
                html_file=html_file.resolve(),
                public_url=public_page_url(site_url, post.slug, post.lang),
                display_title=display_title,
                translation_status=(
                    "source"
                    if post.lang == "cs"
                    else "incomplete"
                    if noindex
                    else "translated"
                ),
            )
        )

    if missing and not allow_missing:
        rendered = "\n  - " + "\n  - ".join(missing[:50])
        extra = "" if len(missing) <= 50 else f"\n  ... and {len(missing) - 50} more"
        raise SystemExit(
            "Built HTML is missing for requested pages. Run the correct build "
            "or use --allow-missing if intentional. Missing:"
            + rendered
            + extra
        )
    return jobs


def run_build(command: str | None, project_root: Path) -> None:
    if not command:
        return
    print(f"[build] {command}")
    subprocess.run(command, cwd=project_root, shell=True, check=True)


def default_book_title(lang: str) -> str:
    if lang == "cs":
        return "Vojta Maur — export webu (čeština)"
    return "Vojta Maur — website export (English)"


def book_title(args: argparse.Namespace, lang: str, language_count: int) -> str:
    if not args.title:
        return default_book_title(lang)
    if language_count > 1:
        return f"{args.title} ({lang.upper()})"
    return args.title


def combined_output_path(
    args: argparse.Namespace,
    project_root: Path,
    output_dir: Path,
    lang: str,
    selected_sections: list[str],
) -> Path:
    if args.output:
        return resolve_path(project_root, args.output)
    section_part = (
        "all"
        if not selected_sections
        else "-".join(safe_filename(item) for item in selected_sections)
    )
    return output_dir / f"vojtamaur-web-export-{section_part}-{lang}.epub"


def frontmatter_html(
    *,
    title: str,
    author: str,
    lang: str,
    jobs: list[SiteJob],
    dist_dir: Path,
    site_url: str,
) -> str:
    generated = dt.datetime.now().astimezone().isoformat(timespec="seconds")
    if lang == "cs":
        labels = {
            "generated": "Vygenerováno",
            "website": "Veřejný web",
            "source": "Zdrojový build",
            "mode": "Režim",
            "mode_value": "kombinovaný reflowable EPUB z hotového statického HTML",
            "count": "Zahrnuté články",
            "index": "Zahrnuté články",
            "motto": "Tvořit je můj základní instinkt",
            "layout_title": "Reflowable sazba",
            "layout": (
                "EPUB není pevně stránkovaná kopie webu. Velikost písma, řádkování "
                "a zalomení se přizpůsobují čtečce; obsah a pořadí článků vycházejí "
                "z hotového buildu. Interaktivní vložený obsah je nahrazen odkazem "
                "na veřejnou verzi."
            ),
            "translation_title": "Stav anglického překladu",
            "translation": (
                "Anglické trasy pocházejí z hotového EN buildu. Případné stránky "
                "s českým fallbackem jsou v seznamu označeny."
            ),
            "source_status": "český zdroj",
            "translated_status": "přeloženo",
            "incomplete_status": "neúplné / český fallback",
        }
    else:
        labels = {
            "generated": "Generated",
            "website": "Public website",
            "source": "Source build",
            "mode": "Mode",
            "mode_value": "combined reflowable EPUB from finished static HTML",
            "count": "Articles included",
            "index": "Included article pages",
            "motto": "Creating is my basic instinct",
            "layout_title": "Reflowable layout",
            "layout": (
                "This EPUB is not a fixed-page copy of the website. Font size, "
                "line spacing, and pagination adapt to the reading system; article "
                "content and order come from the finished build. Interactive embeds "
                "are replaced by links to their public versions."
            ),
            "translation_title": "English translation status",
            "translation": (
                "English routes come from the finished EN build. Any page using a "
                "Czech fallback is marked in the list below."
            ),
            "source_status": "Czech source",
            "translated_status": "translated",
            "incomplete_status": "incomplete / Czech fallback",
        }

    status_labels = {
        "source": labels["source_status"],
        "translated": labels["translated_status"],
        "incomplete": labels["incomplete_status"],
    }
    items: list[str] = []
    for job in jobs:
        route = ("/en/" if lang == "en" else "/") + job.post.slug.strip("/") + "/"
        items.append(
            '<li class="book-index-item">'
            f'<h3><a href="{html.escape(job.public_url, quote=True)}">'
            f"{html.escape(job.display_title)}</a></h3>"
            f'<p class="metadata">{html.escape(job.post.date)} · '
            f"{html.escape(job.section_label)} · "
            f"{html.escape(status_labels.get(job.translation_status, job.translation_status))}</p>"
            f"<code>{html.escape(route)}</code>"
            "</li>"
        )

    translation_notice = (
        f'<div class="epub-notice"><strong>{html.escape(labels["translation_title"])}</strong>'
        f'<p>{html.escape(labels["translation"])}</p></div>'
        if lang == "en"
        else ""
    )
    return f"""
<main class="publication-frontmatter">
  <header class="publication-title-page">
    <h1>{html.escape(title)}</h1>
    <p class="subtitle">{html.escape(author)}</p>
    <p>{html.escape(labels["motto"])}</p>
    <p><a href="{html.escape(site_url, quote=True)}">www.vojtamaur.cz</a></p>
  </header>
  <section>
    <dl class="frontmatter-meta">
      <dt>{html.escape(labels["generated"])}</dt><dd>{html.escape(generated)}</dd>
      <dt>{html.escape(labels["website"])}</dt><dd><a href="{html.escape(site_url, quote=True)}">{html.escape(site_url)}</a></dd>
      <dt>{html.escape(labels["source"])}</dt><dd><code>{html.escape(str(dist_dir))}</code></dd>
      <dt>{html.escape(labels["mode"])}</dt><dd>{html.escape(labels["mode_value"])}</dd>
      <dt>{html.escape(labels["count"])}</dt><dd>{len(jobs)}</dd>
    </dl>
    <div class="epub-notice"><strong>{html.escape(labels["layout_title"])}</strong>
      <p>{html.escape(labels["layout"])}</p>
    </div>
    {translation_notice}
    <h2>{html.escape(labels["index"])}</h2>
    <ol class="book-index-list">{''.join(items)}</ol>
  </section>
</main>
"""


def source_pages_for_jobs(
    jobs: list[SiteJob],
    lang: str,
    *,
    title: str,
    author: str,
    dist_dir: Path,
    site_url: str,
    include_frontmatter: bool,
) -> list[EpubSourcePage]:
    pages: list[EpubSourcePage] = []
    if include_frontmatter:
        home_candidates = (
            [dist_dir / "index.html"]
            if lang == "cs"
            else [dist_dir / "en" / "index.html", dist_dir / "en.html"]
        )
        reference_file = next(
            (candidate for candidate in home_candidates if candidate.is_file()),
            None,
        )
        if reference_file is None:
            raise SystemExit(
                f"Finished {lang.upper()} homepage not found in dist/: {dist_dir}"
            )
        pages.append(
            EpubSourcePage(
                source_file=None,
                public_url=site_url,
                lang=lang,
                title="Index exportu" if lang == "cs" else "Export index",
                output_name="0000-export-index.xhtml",
                nav_group="Úvod" if lang == "cs" else "Front matter",
                html_fragment=frontmatter_html(
                    title=title,
                    author=author,
                    lang=lang,
                    jobs=jobs,
                    dist_dir=dist_dir,
                    site_url=site_url,
                ),
                reference_file=reference_file,
                map_public_url=False,
            )
        )
    for index, job in enumerate(jobs, start=1):
        pages.append(
            EpubSourcePage(
                source_file=job.html_file,
                public_url=job.public_url,
                lang=lang,
                title=job.display_title,
                output_name=(
                    f"{index:04d}-{safe_filename(job.post.slug, fallback='article')}.xhtml"
                ),
                nav_group=job.section_label,
            )
        )
    return pages


def build_book(
    *,
    dist_dir: Path,
    site_url: str,
    title: str,
    author: str,
    lang: str,
    jobs: list[SiteJob],
    output_path: Path,
    identifier_suffix: str,
    image_max_px: int | None,
    jpeg_quality: int | None,
    png_mode: str,
    gif_mode: str,
    include_frontmatter: bool,
) -> EpubBuildResult:
    pages = source_pages_for_jobs(
        jobs,
        lang,
        title=title,
        author=author,
        dist_dir=dist_dir,
        site_url=site_url,
        include_frontmatter=include_frontmatter,
    )
    identifier = stable_identifier(
        f"{site_url}|site-epub|{lang}|{identifier_suffix}|"
        + "|".join(page.public_url for page in pages)
    )
    builder = EpubBookBuilder(
        dist_dir=dist_dir,
        site_url=site_url,
        title=title,
        author=author,
        languages=[lang],
        identifier=identifier,
        pages=pages,
        toc_title="Obsah" if lang == "cs" else "Contents",
        image_max_px=image_max_px,
        jpeg_quality=jpeg_quality,
        png_mode=png_mode,
        gif_mode=gif_mode,
    )
    return builder.build(output_path)


def write_manifest(
    path: Path,
    *,
    args: argparse.Namespace,
    project_root: Path,
    dist_dir: Path,
    selected_sections: list[str],
    jobs: list[SiteJob],
    results: list[EpubBuildResult],
) -> None:
    data = {
        "generated_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "generator": f"export-site-epub.py {SCRIPT_VERSION}",
        "project_root": str(project_root),
        "source_build": str(dist_dir),
        "source_index": str(dist_dir / "ALL_POSTS.txt"),
        "mode": "separate" if args.separate else "combined",
        "generated_frontmatter": not args.separate and not args.no_cover,
        "language": args.lang,
        "sections": selected_sections,
        "site_url": args.site_url,
        "image_quality": args.image_quality,
        "image_max_px": args.effective_image_max_px,
        "jpeg_quality": args.effective_jpeg_quality,
        "png_mode": args.effective_png_mode,
        "gif_mode": args.effective_gif_mode,
        "article_page_count": len(jobs),
        "outputs": [
            {
                "path": str(result.output_path),
                "bytes": result.output_path.stat().st_size,
                "sha256": sha256_file(result.output_path),
                "pages": result.page_count,
                "spine_pages": result.page_count,
                "assets": result.asset_count,
                "zip_entries": result.entry_count,
                "interactive_fallbacks": result.interactive_fallback_count,
                "remote_image_fallbacks": result.remote_image_fallback_count,
                "optimized_assets": result.optimized_asset_count,
                "jpeg_quality_used": result.jpeg_quality_used,
                "source_asset_bytes": result.source_asset_bytes,
                "packaged_asset_bytes": result.packaged_asset_bytes,
                "empty_image_placeholders_removed": (
                    result.empty_image_placeholder_count
                ),
            }
            for result in results
        ],
        "pages": [
            {
                "lang": job.post.lang,
                "section": job.post.section,
                "section_label": job.section_label,
                "title": job.display_title,
                "index_title": job.post.title,
                "translation_status": job.translation_status,
                "slug": job.post.slug,
                "date": job.post.date,
                "built_html": str(job.html_file),
                "public_url": job.public_url,
            }
            for job in jobs
        ],
    }
    atomic_write_text(
        path,
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
    )


def unique_sibling_path(output_path: Path, marker: str) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{output_path.stem}-",
        suffix=f".{marker}.epub",
        dir=output_path.parent,
    )
    os.close(descriptor)
    return Path(temporary_name)


def commit_staged_books(
    staged: list[tuple[EpubBuildResult, Path]],
) -> list[EpubBuildResult]:
    """Install a prepared output set and restore the old set on failure."""

    processed: list[tuple[Path, Path | None]] = []
    try:
        for result, final_path in staged:
            backup_path: Path | None = None
            if final_path.exists():
                backup_path = unique_sibling_path(final_path, "backup")
                try:
                    os.replace(final_path, backup_path)
                except BaseException:
                    backup_path.unlink(missing_ok=True)
                    raise
            processed.append((final_path, backup_path))
            os.replace(result.output_path, final_path)
    except BaseException as exc:
        rollback_errors: list[str] = []
        for final_path, backup_path in reversed(processed):
            try:
                final_path.unlink(missing_ok=True)
                if backup_path is not None and backup_path.exists():
                    os.replace(backup_path, final_path)
            except OSError as rollback_exc:
                rollback_errors.append(f"{final_path}: {rollback_exc}")
        if rollback_errors:
            raise RuntimeError(
                "Could not fully restore EPUB outputs after a commit failure:\n  - "
                + "\n  - ".join(rollback_errors)
            ) from exc
        raise
    else:
        for _, backup_path in processed:
            if backup_path is not None:
                try:
                    backup_path.unlink(missing_ok=True)
                except OSError as exc:
                    print(
                        f"[warn] Old EPUB backup could not be removed: "
                        f"{backup_path}: {exc}",
                        file=sys.stderr,
                    )

    return [
        dataclasses.replace(result, output_path=final_path)
        for result, final_path in staged
    ]


def main() -> int:
    args = parse_args()
    args.site_url = normalize_site_url(args.site_url)
    project_root = Path(args.project_root).resolve()
    dist_dir = resolve_path(project_root, args.dist)
    output_dir = resolve_path(project_root, args.output_dir)
    selected_sections = split_csv(args.section)
    languages = languages_from_arg(args.lang)
    (
        args.effective_image_max_px,
        args.effective_jpeg_quality,
    ) = image_settings(
        args.image_quality,
        args.image_max_px,
        args.jpeg_quality,
    )
    args.effective_png_mode = (
        args.png_mode
        if args.png_mode is not None
        else "jpeg"
        if args.image_quality == "compact"
        else "preserve"
    )
    args.effective_gif_mode = (
        args.gif_mode
        if args.gif_mode is not None
        else "poster"
        if args.image_quality == "compact"
        else "preserve"
    )

    unknown_sections = [
        section
        for section in selected_sections
        if section not in SECTION_LABELS["cs"]
    ]
    if unknown_sections:
        raise SystemExit(
            "Unknown section(s): "
            + ", ".join(unknown_sections)
            + "\nValid sections: "
            + ", ".join(SECTION_LABELS["cs"])
        )
    if args.output and args.separate:
        raise SystemExit("--output cannot be used with --separate.")
    if args.title and args.separate:
        raise SystemExit("--title applies only to combined books, not --separate.")
    if args.output and len(languages) != 1:
        raise SystemExit(
            "--output requires --lang cs or --lang en. "
            "With --lang both, two default output names are created."
        )
    if args.output and Path(args.output).suffix.lower() != ".epub":
        raise SystemExit("--output must end with .epub")

    run_build(args.build_command, project_root)
    if not dist_dir.is_dir():
        raise SystemExit(
            f"Built directory not found: {dist_dir}\n"
            "Run a build first, for example: npm run build:web:strict"
        )

    require_epub_dependencies()
    posts = parse_all_posts_index(dist_dir / "ALL_POSTS.txt")
    jobs = make_jobs(
        posts,
        dist_dir,
        selected_sections,
        languages,
        args.site_url,
        args.allow_missing,
    )
    if not jobs:
        raise SystemExit(
            "No matching article pages found. Filters are too strict or dist/ is incomplete."
        )

    outputs: list[EpubBuildResult] = []
    staged: list[tuple[EpubBuildResult, Path]] = []
    reserved_outputs: set[Path] = set()
    print(f"[source] {dist_dir}")
    print(f"[export] {len(jobs)} article page(s)")

    def stage_book(output_path: Path, **kwargs: Any) -> None:
        output_path = output_path.resolve()
        if output_path in reserved_outputs:
            raise SystemExit(
                "Multiple selected articles resolve to the same EPUB output: "
                f"{output_path}"
            )
        reserved_outputs.add(output_path)
        candidate_path = unique_sibling_path(output_path, "candidate")
        try:
            result = build_book(output_path=candidate_path, **kwargs)
        except BaseException:
            candidate_path.unlink(missing_ok=True)
            raise
        staged.append((result, output_path))

    try:
        if args.separate:
            for index, job in enumerate(jobs, start=1):
                lang = job.post.lang
                output_path = (
                    output_dir
                    / lang
                    / safe_filename(job.post.section)
                    / f"{safe_filename(job.post.slug, fallback='article')}.epub"
                )
                print(
                    f"[{index}/{len(jobs)}] {lang.upper()} · "
                    f"{job.section_label} · {job.display_title}"
                )
                stage_book(
                    output_path,
                    dist_dir=dist_dir,
                    site_url=args.site_url,
                    title=job.display_title,
                    author=args.author,
                    lang=lang,
                    jobs=[job],
                    identifier_suffix=f"article|{job.post.slug}",
                    image_max_px=args.effective_image_max_px,
                    jpeg_quality=args.effective_jpeg_quality,
                    png_mode=args.effective_png_mode,
                    gif_mode=args.effective_gif_mode,
                    include_frontmatter=False,
                )
        else:
            for lang in languages:
                language_jobs = [job for job in jobs if job.post.lang == lang]
                if not language_jobs:
                    raise SystemExit(
                        f"No matching {lang.upper()} article pages found in dist/."
                    )
                output_path = combined_output_path(
                    args,
                    project_root,
                    output_dir,
                    lang,
                    selected_sections,
                )
                title = book_title(args, lang, len(languages))
                print(
                    f"[book] {lang.upper()} · {len(language_jobs)} article(s) -> "
                    f"{output_path}"
                )
                stage_book(
                    output_path,
                    dist_dir=dist_dir,
                    site_url=args.site_url,
                    title=title,
                    author=args.author,
                    lang=lang,
                    jobs=language_jobs,
                    identifier_suffix=",".join(selected_sections) or "all",
                    image_max_px=args.effective_image_max_px,
                    jpeg_quality=args.effective_jpeg_quality,
                    png_mode=args.effective_png_mode,
                    gif_mode=args.effective_gif_mode,
                    include_frontmatter=not args.no_cover,
                )

        outputs = commit_staged_books(staged)
    finally:
        for result, _ in staged:
            result.output_path.unlink(missing_ok=True)

    manifest_path = output_dir / MANIFEST_NAME
    if args.no_manifest:
        manifest_path.unlink(missing_ok=True)
    else:
        write_manifest(
            manifest_path,
            args=args,
            project_root=project_root,
            dist_dir=dist_dir,
            selected_sections=selected_sections,
            jobs=jobs,
            results=outputs,
        )
        print(f"[manifest] {manifest_path}")

    print("[done]")
    for result in outputs:
        print(
            f"  {result.output_path} ({result.output_path.stat().st_size:,} bytes; "
            f"{result.page_count} page(s); {result.asset_count} asset(s); "
            f"{result.interactive_fallback_count} interactive fallback(s); "
            f"{result.optimized_asset_count} optimized image(s); "
            f"{result.source_asset_bytes:,} -> "
            f"{result.packaged_asset_bytes:,} image bytes; "
            f"{result.empty_image_placeholder_count} empty image "
            f"placeholder(s) removed)"
        )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        raise SystemExit(130) from None
