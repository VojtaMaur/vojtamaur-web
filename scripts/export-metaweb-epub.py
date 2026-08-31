#!/usr/bin/env python3
"""Create one bilingual, reflowable Metaweb EPUB from the finished dist/ build.

The publication carries the EPUB-suitable scope of export-metaweb-pdf.py: title
and contents, both Metaweb article languages, the linked-image appendix,
ARCHIVE.txt, technical documentation, and build identity files. The standalone
ultra-compact PDF section is intentionally omitted without a replacement.
"""

from __future__ import annotations

import argparse
import copy
import dataclasses
import datetime as dt
import html
import json
import os
import re
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urljoin, urlsplit

from export_common import (
    atomic_write_text,
    EpubBookBuilder,
    EpubBuildResult,
    EpubSourcePage,
    IMAGE_QUALITY_PRESETS,
    image_settings,
    normalize_site_url,
    require_epub_dependencies,
    resolve_path,
    safe_filename,
    sha256_file,
    stable_identifier,
)


SCRIPT_VERSION = "1.3.0"
DEFAULT_SITE_URL = "https://vojtamaur.cz"
DEFAULT_OUTPUT_NAME = "vojtamaur-web-export-metaweb.epub"
ARTICLE_ROUTES = (
    ("cs", "/metawebovy-clanek/", "Metawebový článek"),
    ("en", "/en/metawebovy-clanek/", "Metaweb Article"),
)
DOCUMENTATION_ROUTE = "/documentation/"
ARCHIVE_PATH = "/ARCHIVE.txt"
EXCLUDED_PAYLOADS = {
    "/ALL_POSTS.txt",
    "/source/vojtamaur-web-source.zip",
}
IMAGE_EXTENSIONS = {".avif", ".gif", ".jpeg", ".jpg", ".png", ".svg", ".webp"}
ENGLISH_INTEGRITY_ITEMS = (
    (
        "/SHA256SUMS.txt",
        "SHA256SUMS.txt",
        "a list of SHA-256 checksums for the build files",
    ),
    (
        "/SHA256SUMS.txt.asc",
        "SHA256SUMS.txt.asc",
        "a separate OpenPGP signature for the SHA256SUMS.txt file",
    ),
    (
        "/BUILD_SHA256.txt",
        "BUILD_SHA256.txt",
        "the SHA-256 checksum of the SHA256SUMS.txt file",
    ),
    (
        "/integrity.json",
        "integrity.json",
        "machine-readable descriptive information about the build's integrity",
    ),
    (
        "/SIGNING_STATUS.txt",
        "SIGNING_STATUS.txt",
        "descriptive status of the signing for a specific build",
    ),
    (
        "/keys/vojta-maur-openpgp.asc",
        "vojta-maur-openpgp.asc",
        "the public OpenPGP key for verifying the signature",
    ),
)


@dataclasses.dataclass(frozen=True)
class LinkedImage:
    public_path: str
    file_path: Path
    title: str
    description_cs: str
    description_en: str


@dataclasses.dataclass(frozen=True)
class LinkedFile:
    public_path: str
    file_path: Path
    label: str
    optional: bool = False


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Export the complete bilingual Metaweb publication from finished "
            "dist/ HTML: articles, image appendix, archive map, documentation, "
            "and build identity files. The ultra PDF is not substituted."
        )
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {SCRIPT_VERSION}",
    )
    parser.add_argument(
        "--project-root",
        default=None,
        help=(
            "Project root containing dist/. By default it is detected from "
            "the script location."
        ),
    )
    parser.add_argument(
        "--dist",
        default="dist",
        help="Finished site directory, relative to project root unless absolute.",
    )
    parser.add_argument(
        "--output-dir",
        default="exports",
        help="Output directory, relative to project root unless absolute.",
    )
    parser.add_argument(
        "--output",
        default=None,
        help=f"Output EPUB path. Default: exports/{DEFAULT_OUTPUT_NAME}",
    )
    parser.add_argument(
        "--site-url",
        default=DEFAULT_SITE_URL,
        help=(
            "Public site root retained for source and unsupported-content "
            f"links. Default: {DEFAULT_SITE_URL}"
        ),
    )
    parser.add_argument(
        "--title",
        default="Metawebový článek",
        help="Czech publication title.",
    )
    parser.add_argument(
        "--title-en",
        default="Metaweb Article",
        help="English publication title.",
    )
    parser.add_argument(
        "--author",
        default="Vojta Maur",
        help="dc:creator metadata. Default: Vojta Maur",
    )
    parser.add_argument(
        "--no-manifest",
        action="store_true",
        help="Do not write the adjacent JSON export manifest.",
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
        help="Override the preset maximum width/height in pixels.",
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
            "uses jpeg. PNG transparency is always preserved."
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


def route_file(dist_dir: Path, route: str) -> Path:
    clean = route.strip("/")
    if not clean:
        return (dist_dir / "index.html").resolve()
    candidates = [
        dist_dir / clean / "index.html",
        dist_dir / f"{clean}.html",
    ]
    return next(
        (candidate.resolve() for candidate in candidates if candidate.is_file()),
        candidates[0].resolve(),
    )


def normalize_space(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def public_url(site_url: str, public_path: str) -> str:
    return urljoin(site_url, public_path.lstrip("/"))


def generated_url(site_url: str, name: str) -> str:
    return urljoin(site_url, f"__epub__/metaweb/{name.strip('/')}/")


def local_public_path(
    raw_href: str,
    page_url: str,
    site_url: str,
) -> str | None:
    parsed = urlsplit(urljoin(page_url, raw_href))
    site = urlsplit(site_url)
    if parsed.scheme.lower() not in {"http", "https"}:
        return None
    if parsed.netloc.lower() != site.netloc.lower():
        return None
    return "/" + unquote(parsed.path).lstrip("/")


def safe_dist_path(dist_dir: Path, public_path: str) -> Path:
    candidate = (dist_dir / unquote(public_path).lstrip("/")).resolve()
    if not candidate.is_relative_to(dist_dir.resolve()):
        raise SystemExit(f"Unsafe path discovered in built HTML: {public_path}")
    return candidate


def article_root(html_file: Path) -> tuple[Any, Any]:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html_file.read_bytes(), "html5lib")
    root = (
        soup.select_one("main article")
        or soup.find("article")
        or soup.find("main")
    )
    if root is None:
        raise SystemExit(f"Article content container not found: {html_file}")
    return soup, root


def collect_article_data(
    html_file: Path,
    lang: str,
    page_url: str,
    site_url: str,
) -> tuple[str, list[dict[str, str]], list[dict[str, str]]]:
    _, root = article_root(html_file)
    heading = root.find("h1")
    title = normalize_space(heading.get_text(" ", strip=True)) if heading else ""
    anchors: list[dict[str, str]] = []

    for anchor in root.find_all("a", href=True):
        row = anchor.find_parent("tr")
        cells = row.find_all(["th", "td"], recursive=False) if row else []
        section_heading = anchor.find_previous(["h2", "h3"])
        anchors.append(
            {
                "href": anchor.get("href", ""),
                "text": normalize_space(anchor.get_text(" ", strip=True)),
                "rowId": normalize_space(cells[0].get_text(" ", strip=True))
                if len(cells) > 0
                else "",
                "rowName": normalize_space(cells[1].get_text(" ", strip=True))
                if len(cells) > 1
                else "",
                "rowDescription": normalize_space(
                    cells[5].get_text(" ", strip=True)
                )
                if len(cells) > 5
                else "",
                "section": normalize_space(
                    section_heading.get_text(" ", strip=True)
                )
                if section_heading is not None
                else "",
                "language": lang,
            }
        )

    integrity: list[dict[str, str]] = []
    if lang == "cs":
        integrity_heading = next(
            (
                item
                for item in root.find_all("h2")
                if normalize_space(item.get_text(" ", strip=True)).upper()
                == "INTEGRITA A IDENTITA BUILDU"
            ),
            None,
        )
        if integrity_heading is not None:
            node = integrity_heading.next_sibling
            while node is not None:
                if getattr(node, "name", None) == "h2":
                    break
                if getattr(node, "find_all", None):
                    for anchor in node.find_all("a", href=True):
                        integrity.append(
                            {
                                "href": anchor.get("href", ""),
                                "text": normalize_space(
                                    anchor.get_text(" ", strip=True)
                                ),
                            }
                        )
                node = node.next_sibling

    return title, anchors, integrity


def image_title(item: dict[str, str]) -> str:
    return " - ".join(
        part
        for part in (
            normalize_space(item.get("rowId", "")),
            normalize_space(item.get("rowName", "")),
        )
        if part
    ) or "Linked image"


def image_description(item: dict[str, str], fallback: str) -> str:
    link_text = normalize_space(item.get("text", ""))
    row_description = normalize_space(item.get("rowDescription", ""))
    section = normalize_space(item.get("section", ""))
    if link_text and link_text.casefold() not in {"image", "obrazek", "obrázek"}:
        return link_text
    return row_description or section or link_text or fallback


def collect_inputs(
    dist_dir: Path,
    site_url: str,
) -> tuple[
    list[LinkedImage],
    list[LinkedFile],
    dict[str, str],
    dict[str, Path],
]:
    collected: dict[str, dict[str, dict[str, str]]] = {}
    titles: dict[str, str] = {}
    article_files: dict[str, Path] = {}
    integrity_items: list[dict[str, str]] = []

    for lang, route, fallback_title in ARTICLE_ROUTES:
        html_file = route_file(dist_dir, route)
        if not html_file.is_file():
            raise SystemExit(
                f"Finished build is missing the {lang.upper()} Metaweb page: {html_file}"
            )
        article_files[lang] = html_file
        page_url = public_url(site_url, route)
        title, anchors, integrity = collect_article_data(
            html_file,
            lang,
            page_url,
            site_url,
        )
        titles[lang] = title or fallback_title
        if lang == "cs":
            integrity_items = integrity

        for anchor in anchors:
            path = local_public_path(anchor["href"], page_url, site_url)
            if path is None or Path(path).suffix.lower() not in IMAGE_EXTENSIONS:
                continue
            collected.setdefault(path, {}).setdefault(lang, anchor)

    linked_images: list[LinkedImage] = []
    for path, descriptions in collected.items():
        file_path = safe_dist_path(dist_dir, path)
        if not file_path.is_file():
            raise SystemExit(f"Metaweb image is missing from dist/: {file_path}")
        missing_languages = [lang for lang in ("cs", "en") if lang not in descriptions]
        if missing_languages:
            raise SystemExit(
                "A Metaweb image lacks a description in both article languages: "
                f"{path} (missing: {', '.join(missing_languages)})"
            )
        linked_images.append(
            LinkedImage(
                public_path=path,
                file_path=file_path,
                title=image_title(descriptions["cs"]),
                description_cs=image_description(
                    descriptions["cs"],
                    "Odkazovaný obrázek",
                ),
                description_en=image_description(
                    descriptions["en"],
                    "Linked image",
                ),
            )
        )

    linked_files: list[LinkedFile] = []
    seen_files: set[str] = set()
    cs_page_url = public_url(site_url, ARTICLE_ROUTES[0][1])
    for item in integrity_items:
        path = local_public_path(item["href"], cs_page_url, site_url)
        if path is None or path in seen_files:
            continue
        if path in EXCLUDED_PAYLOADS:
            raise SystemExit(
                f"Excluded payload unexpectedly appeared in integrity links: {path}"
            )
        seen_files.add(path)
        linked_files.append(
            LinkedFile(
                public_path=path,
                file_path=safe_dist_path(dist_dir, path),
                label=item["text"] or Path(path).name,
                optional=Path(path).name.casefold() == "sha256sums.txt.asc",
            )
        )

    if not linked_images:
        raise SystemExit("No linked Metaweb images were discovered in finished HTML.")
    if not linked_files:
        raise SystemExit(
            "No build identity files were discovered in the Czech Metaweb article."
        )
    missing_required = [
        item.file_path
        for item in linked_files
        if not item.optional and not item.file_path.is_file()
    ]
    if missing_required:
        raise SystemExit(
            "Required build identity files are missing:\n  - "
            + "\n  - ".join(str(path) for path in missing_required)
        )
    return linked_images, linked_files, titles, article_files


def transform_wide_tables(soup: Any, root: Any) -> tuple[int, int]:
    table_count = 0
    record_count = 0
    for table in list(root.find_all("table")):
        headers = table.select("thead th")
        rows = table.select("tbody tr")
        if len(headers) < 7 or not rows:
            continue
        table_count += 1
        cards = soup.new_tag("section")
        cards["class"] = ["registry-cards"]
        cards["aria-label"] = "Reflowable registry records"

        for row in rows:
            cells = row.find_all(["th", "td"], recursive=False)
            if not cells:
                continue
            values = [normalize_space(cell.get_text(" ", strip=True)) for cell in cells]
            card = soup.new_tag("article")
            card["class"] = ["registry-card"]
            heading = soup.new_tag("h3")
            heading.string = " - ".join(value for value in values[:2] if value)
            card.append(heading)
            fields = soup.new_tag("dl")
            fields["class"] = ["registry-fields"]
            for index in range(2, len(cells)):
                label = soup.new_tag("dt")
                label.string = (
                    normalize_space(headers[index].get_text(" ", strip=True))
                    if index < len(headers)
                    else f"Field {index + 1}"
                )
                value = soup.new_tag("dd")
                for child in list(cells[index].contents):
                    value.append(copy.copy(child))
                fields.append(label)
                fields.append(value)
            card.append(fields)
            card_text = normalize_space(card.get_text(" ", strip=True))
            if not all(not value or value in card_text for value in values):
                raise SystemExit("Metaweb registry card conversion lost cell content.")
            cards.append(card)
            record_count += 1
        table.replace_with(cards)
    return table_count, record_count


def normalize_english_integrity_list(soup: Any, root: Any) -> None:
    heading = root.find("h2", id="integrita-a-identita-buildu")
    if heading is None:
        heading = next(
            (
                item
                for item in root.find_all("h2")
                if normalize_space(item.get_text(" ", strip=True)).upper()
                == "BUILD INTEGRITY AND IDENTITY"
            ),
            None,
        )
    if heading is None:
        raise SystemExit("English build-integrity heading was not found.")

    source = None
    node = heading.next_sibling
    while node is not None:
        if getattr(node, "name", None) == "h2":
            break
        if (
            getattr(node, "name", None) == "p"
            and len(node.find_all("a", href=True)) >= 6
        ):
            source = node
            break
        node = node.next_sibling
    if source is None:
        raise SystemExit("English build-integrity links could not be normalized.")

    links: dict[str, Any] = {}
    for anchor in source.find_all("a", href=True):
        path = urlsplit(
            urljoin(DEFAULT_SITE_URL, anchor.get("href", ""))
        ).path.casefold()
        links[path] = anchor
    if not all(path.casefold() in links for path, _, _ in ENGLISH_INTEGRITY_ITEMS):
        raise SystemExit("English build-integrity link list is incomplete.")

    listing = soup.new_tag("ul")
    listing["class"] = ["integrity-list"]
    for path, label, description in ENGLISH_INTEGRITY_ITEMS:
        row = soup.new_tag("li")
        link = copy.copy(links[path.casefold()])
        link.clear()
        link.string = label
        row.append(link)
        row.append(f" — {description}")
        listing.append(row)
    source.replace_with(listing)


def prepared_metaweb_fragment(html_file: Path, lang: str) -> str:
    soup, root = article_root(html_file)
    table_count, record_count = transform_wide_tables(soup, root)
    if table_count < 1 or record_count < 1:
        raise SystemExit(
            f"Physical archive registry was not found in {lang.upper()} Metaweb HTML."
        )
    if lang == "en":
        normalize_english_integrity_list(soup, root)
    for details in root.find_all("details"):
        details["open"] = "open"
    return root.decode(formatter="minimal")


def title_page_html(args: argparse.Namespace) -> str:
    return f"""
<main class="publication-title-page">
  <h1>{html.escape(args.title)}</h1>
  <p class="subtitle" lang="en">{html.escape(args.title_en)}</p>
  <p class="author">{html.escape(args.author)}</p>
  <p><a href="{html.escape(args.site_url, quote=True)}" data-epub-external="true">www.vojtamaur.cz</a></p>
</main>
"""


def contents_html(
    args: argparse.Namespace,
    dist_dir: Path,
    linked_images: list[LinkedImage],
    linked_files: list[LinkedFile],
) -> str:
    generated = dt.datetime.now().astimezone().isoformat(timespec="seconds")
    identity_items = "".join(
        f'<li><a href="{html.escape(public_url(args.site_url, item.public_path), quote=True)}">'
        f"<code>{html.escape(item.public_path)}</code></a></li>"
        for item in linked_files
    )
    return f"""
<main class="publication-contents">
  <h1>Obsah / <span lang="en">Contents</span></h1>
  <dl class="frontmatter-meta">
    <dt>Vygenerováno<br /><span lang="en">Generated</span></dt><dd>{html.escape(generated)}</dd>
    <dt>Veřejný web<br /><span lang="en">Public website</span></dt><dd><a href="{html.escape(args.site_url, quote=True)}" data-epub-external="true">{html.escape(args.site_url)}</a></dd>
    <dt>Zdrojový build<br /><span lang="en">Source build</span></dt><dd><code>{html.escape(str(dist_dir))}</code></dd>
    <dt>Obrazová příloha<br /><span lang="en">Image appendix</span></dt><dd>{len(linked_images)} odkazovaných obrázků<br /><span lang="en">{len(linked_images)} linked images</span></dd>
    <dt>Identita a integrita<br /><span lang="en">Identity and integrity</span></dt><dd>{len(linked_files)} odkazovaných souborů<br /><span lang="en">{len(linked_files)} linked files</span></dd>
  </dl>
  <h2>Oddíly EPUB / <span lang="en">EPUB sections</span></h2>
  <ol class="toc">
    <li><a href="{html.escape(public_url(args.site_url, ARTICLE_ROUTES[0][1]), quote=True)}">Metawebový článek — česká verze</a></li>
    <li><a href="{html.escape(public_url(args.site_url, ARTICLE_ROUTES[1][1]), quote=True)}" lang="en">Metaweb Article — English version</a></li>
    <li><a href="{html.escape(generated_url(args.site_url, 'image-appendix'), quote=True)}">Obrazová příloha / <span lang="en">Image appendix</span></a></li>
    <li><a href="{html.escape(public_url(args.site_url, ARCHIVE_PATH), quote=True)}"><code>ARCHIVE.txt</code></a></li>
    <li><a href="{html.escape(public_url(args.site_url, DOCUMENTATION_ROUTE), quote=True)}">Technická dokumentace projektu / <span lang="en">Project technical documentation</span></a></li>
    <li>Soubory identity a integrity buildu / <span lang="en">Build identity and integrity files</span><ul>{identity_items}</ul></li>
  </ol>
  <div class="epub-notice">
    <strong>Záměrně nevloženo / <span lang="en">Deliberately not embedded</span></strong>
    <p lang="cs">Payloady <code>ALL_POSTS.txt</code> a <code>source/vojtamaur-web-source.zip</code>, stejně jako v PDF. Jejich zmínky a veřejné odkazy zůstávají v článku.</p>
    <p lang="en">The payloads of <code>ALL_POSTS.txt</code> and <code>source/vojtamaur-web-source.zip</code>, as in the PDF. Their mentions and public links remain in the article.</p>
  </div>
</main>
"""


def gallery_html(images: list[LinkedImage], site_url: str) -> str:
    cards: list[str] = []
    for item in images:
        source_url = public_url(site_url, item.public_path)
        cards.append(
            f"""
<li class="gallery-card">
  <figure>
    <a href="{html.escape(source_url, quote=True)}"><img src="{html.escape(item.public_path, quote=True)}" alt="{html.escape(item.title, quote=True)}" /></a>
    <figcaption>
      <h2>{html.escape(item.title)}</h2>
      <p class="caption-language" lang="cs"><strong>CS</strong> {html.escape(item.description_cs)}</p>
      <p class="caption-language" lang="en"><strong>EN</strong> {html.escape(item.description_en)}</p>
      <p class="metadata"><code>{html.escape(Path(item.public_path).name)}</code></p>
      <p><a href="{html.escape(source_url, quote=True)}" data-epub-external="true">{html.escape(source_url)}</a></p>
    </figcaption>
  </figure>
</li>
"""
        )
    return f"""
<main class="image-appendix">
  <h1>Obrazová příloha / <span lang="en">Image appendix</span></h1>
  <p>{len(images)} odkazovaných obrázků z fyzické archivní vrstvy / <span lang="en">{len(images)} linked images from the physical archival layer</span></p>
  <ol class="gallery-list">{''.join(cards)}</ol>
</main>
"""


def raw_appendix_html(item: LinkedFile, site_url: str) -> str:
    source_url = public_url(site_url, item.public_path)
    if item.file_path.is_file():
        content = item.file_path.read_text(encoding="utf-8-sig", errors="replace")
        return f"""
<main class="raw-document">
  <h1>{html.escape(item.label)}</h1>
  <p class="source">Zdroj / Source: <a href="{html.escape(source_url, quote=True)}" data-epub-external="true">{html.escape(source_url)}</a><br />
  Velikost / Size: {item.file_path.stat().st_size:,} B · SHA-256: <code>{sha256_file(item.file_path)}</code></p>
  <pre class="raw-text">{html.escape(content)}</pre>
</main>
"""
    if not item.optional:
        raise SystemExit(f"Required appendix file is missing: {item.file_path}")
    return f"""
<main class="raw-document">
  <h1>{html.escape(item.label)}</h1>
  <p class="source">Očekávaná cesta / Expected path: <code>{html.escape(item.public_path)}</code></p>
  <div class="epub-notice">
    <p lang="cs">Tento volitelný soubor není v aktuálním buildu přítomen. U nepodepsaného buildu je nepřítomnost odděleného OpenPGP podpisu <code>.asc</code> očekávána; žádný obsah nebyl nahrazen ani domyšlen.</p>
    <p lang="en">This optional file is absent from the current build. A missing detached OpenPGP <code>.asc</code> signature is expected for an unsigned build; no replacement content has been invented.</p>
  </div>
</main>
"""


def archive_appendix_html(archive_file: Path, site_url: str) -> str:
    return raw_appendix_html(
        LinkedFile(
            public_path=ARCHIVE_PATH,
            file_path=archive_file,
            label="ARCHIVE.txt",
        ),
        site_url,
    )


def build_pages(
    *,
    args: argparse.Namespace,
    dist_dir: Path,
    linked_images: list[LinkedImage],
    linked_files: list[LinkedFile],
    titles: dict[str, str],
    article_files: dict[str, Path],
) -> tuple[list[EpubSourcePage], list[str]]:
    pages: list[EpubSourcePage] = []
    roles: list[str] = []
    home_file = route_file(dist_dir, "/")
    if not home_file.is_file():
        raise SystemExit(f"Finished site homepage is missing: {home_file}")

    def add(page: EpubSourcePage, role: str) -> None:
        pages.append(page)
        roles.append(role)

    add(
        EpubSourcePage(
            source_file=None,
            public_url=generated_url(args.site_url, "title"),
            lang="cs",
            title="Titulní strana / Title page",
            output_name="0000-title-page.xhtml",
            nav_group="Úvod / Front matter",
            html_fragment=title_page_html(args),
            reference_file=home_file,
        ),
        "title-page",
    )
    add(
        EpubSourcePage(
            source_file=None,
            public_url=generated_url(args.site_url, "contents"),
            lang="cs",
            title="Obsah / Contents",
            output_name="0001-contents.xhtml",
            nav_group="Úvod / Front matter",
            html_fragment=contents_html(
                args,
                dist_dir,
                linked_images,
                linked_files,
            ),
            reference_file=home_file,
        ),
        "contents",
    )

    for index, (lang, route, fallback_title) in enumerate(ARTICLE_ROUTES, start=2):
        source = article_files[lang]
        add(
            EpubSourcePage(
                source_file=source,
                public_url=public_url(args.site_url, route),
                lang=lang,
                title=titles.get(lang) or fallback_title,
                output_name=f"{index:04d}-metaweb-{lang}.xhtml",
                nav_group="Metawebový článek / Metaweb Article",
                html_fragment=prepared_metaweb_fragment(source, lang),
            ),
            f"metaweb-article-{lang}",
        )

    add(
        EpubSourcePage(
            source_file=None,
            public_url=generated_url(args.site_url, "image-appendix"),
            lang="cs",
            title="Obrazová příloha / Image appendix",
            output_name="0004-image-appendix.xhtml",
            nav_group="Obrazová příloha / Image appendix",
            html_fragment=gallery_html(linked_images, args.site_url),
            reference_file=home_file,
        ),
        "image-appendix",
    )
    archive_file = safe_dist_path(dist_dir, ARCHIVE_PATH)
    if not archive_file.is_file():
        raise SystemExit(f"Required archive map is missing: {archive_file}")
    add(
        EpubSourcePage(
            source_file=archive_file,
            public_url=public_url(args.site_url, ARCHIVE_PATH),
            lang="cs",
            title="ARCHIVE.txt",
            output_name="0900-archive-txt.xhtml",
            nav_group=(
                "Archivní a technické přílohy / "
                "Archival and technical appendices"
            ),
            html_fragment=archive_appendix_html(archive_file, args.site_url),
            reference_file=home_file,
        ),
        "archive-map",
    )

    documentation_file = route_file(dist_dir, DOCUMENTATION_ROUTE)
    if not documentation_file.is_file():
        raise SystemExit(
            f"Finished technical documentation is missing: {documentation_file}"
        )
    add(
        EpubSourcePage(
            source_file=documentation_file,
            public_url=public_url(args.site_url, DOCUMENTATION_ROUTE),
            lang="en",
            title="Technical documentation",
            output_name="0901-technical-documentation.xhtml",
            nav_group=(
                "Archivní a technické přílohy / "
                "Archival and technical appendices"
            ),
            content_selector="body > div.site-shell",
        ),
        "technical-documentation",
    )

    for index, item in enumerate(linked_files, start=1):
        add(
            EpubSourcePage(
                source_file=item.file_path if item.file_path.is_file() else None,
                public_url=public_url(args.site_url, item.public_path),
                lang="cs",
                title=item.label,
                output_name=(
                    f"{1000 + index:04d}-identity-"
                    f"{safe_filename(Path(item.public_path).name)}.xhtml"
                ),
                nav_group="Identita a integrita / Identity and integrity",
                html_fragment=raw_appendix_html(item, args.site_url),
                reference_file=home_file,
            ),
            "identity-or-integrity-file",
        )

    return pages, roles


def validate_metaweb_composition(
    epub_path: Path,
    *,
    pages: list[EpubSourcePage],
    roles: list[str],
    linked_images: list[LinkedImage],
    linked_files: list[LinkedFile],
) -> None:
    expected_roles = {
        "title-page": 1,
        "contents": 1,
        "metaweb-article-cs": 1,
        "metaweb-article-en": 1,
        "image-appendix": 1,
        "archive-map": 1,
        "technical-documentation": 1,
        "identity-or-integrity-file": len(linked_files),
    }
    for role, expected in expected_roles.items():
        actual = roles.count(role)
        if actual != expected:
            raise SystemExit(
                f"Metaweb EPUB composition error for {role}: "
                f"{actual}, expected {expected}"
            )
    if len(pages) != len(roles):
        raise SystemExit("Metaweb EPUB page-role bookkeeping is inconsistent.")

    gallery_page = pages[roles.index("image-appendix")]
    with zipfile.ZipFile(epub_path) as archive:
        gallery = archive.read(f"EPUB/{gallery_page.href}").decode("utf-8")
        found_images = gallery.count("<img ")
        if found_images != len(linked_images):
            raise SystemExit(
                "Metaweb image appendix is incomplete: "
                f"found {found_images} images, expected {len(linked_images)}"
            )
        forbidden = [
            name
            for name in archive.namelist()
            if name.endswith("/ALL_POSTS.txt")
            or name.endswith("/vojtamaur-web-source.zip")
        ]
        if forbidden:
            raise SystemExit(
                "Payloads deliberately excluded by the PDF composition were "
                "embedded in EPUB: " + ", ".join(forbidden)
            )


def write_manifest(
    manifest_path: Path,
    *,
    project_root: Path,
    dist_dir: Path,
    output_path: Path,
    result: EpubBuildResult,
    args: argparse.Namespace,
    pages: list[EpubSourcePage],
    roles: list[str],
    linked_images: list[LinkedImage],
    linked_files: list[LinkedFile],
) -> None:
    data = {
        "generated_at": dt.datetime.now().astimezone().isoformat(
            timespec="seconds"
        ),
        "generator": f"export-metaweb-epub.py {SCRIPT_VERSION}",
        "project_root": str(project_root),
        "source_build": str(dist_dir),
        "site_url": args.site_url,
        "title": args.title,
        "title_en": args.title_en,
        "languages": ["cs", "en"],
        "image_quality": args.image_quality,
        "image_max_px": args.effective_image_max_px,
        "jpeg_quality": args.effective_jpeg_quality,
        "jpeg_quality_used": result.jpeg_quality_used,
        "png_mode": args.effective_png_mode,
        "gif_mode": args.effective_gif_mode,
        "scope": {
            "title_and_contents": True,
            "metaweb_article_languages": ["cs", "en"],
            "linked_image_appendix_count": len(linked_images),
            "ultra_compact_pdf_embedded": False,
            "ultra_compact_pdf_replacement": None,
            "archive_txt": True,
            "technical_documentation": True,
            "identity_and_integrity_file_count": len(linked_files),
            "not_embedded_payloads": sorted(EXCLUDED_PAYLOADS),
            "pdf_mapping": (
                "The standalone ultra-compact PDF section is intentionally "
                "omitted from EPUB without a substitute."
            ),
        },
        "spine": [
            {
                "position": index,
                "role": role,
                "title": page.title,
                "lang": page.lang,
                "href": page.href,
                "nav_group": page.nav_group,
                "source": str(page.source_file)
                if page.source_file
                else "generated",
                "public_url": page.public_url,
            }
            for index, (page, role) in enumerate(zip(pages, roles), start=1)
        ],
        "linked_images": [
            {
                "public_path": item.public_path,
                "source": str(item.file_path),
                "title": item.title,
                "description_cs": item.description_cs,
                "description_en": item.description_en,
                "bytes": item.file_path.stat().st_size,
                "sha256": sha256_file(item.file_path),
            }
            for item in linked_images
        ],
        "identity_and_integrity_files": [
            {
                "public_path": item.public_path,
                "source": str(item.file_path),
                "label": item.label,
                "optional": item.optional,
                "present": item.file_path.is_file(),
                "bytes": item.file_path.stat().st_size
                if item.file_path.is_file()
                else None,
                "sha256": sha256_file(item.file_path)
                if item.file_path.is_file()
                else None,
            }
            for item in linked_files
        ],
        "assets": [
            {
                "source_path": asset.source_file.relative_to(dist_dir).as_posix(),
                "package_href": asset.href,
                "package_media_type": asset.media_type,
                "source_bytes": asset.source_bytes,
                "source_sha256": asset.source_sha256,
                "packaged_bytes": asset.packaged_bytes,
                "packaged_sha256": asset.packaged_sha256,
                "optimized": asset.optimized,
            }
            for asset in result.assets
        ],
        "output": {
            "path": str(output_path),
            "bytes": output_path.stat().st_size,
            "sha256": sha256_file(output_path),
            "spine_pages": result.page_count,
            "assets": result.asset_count,
            "zip_entries": result.entry_count,
            "interactive_fallbacks": result.interactive_fallback_count,
            "remote_image_fallbacks": result.remote_image_fallback_count,
            "optimized_assets": result.optimized_asset_count,
            "source_asset_bytes": result.source_asset_bytes,
            "packaged_asset_bytes": result.packaged_asset_bytes,
            "empty_image_placeholders_removed": (
                result.empty_image_placeholder_count
            ),
        },
    }
    atomic_write_text(
        manifest_path,
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
    )


def main() -> int:
    args = parse_args()
    args.site_url = normalize_site_url(args.site_url)
    project_root = (
        Path(args.project_root).resolve()
        if args.project_root
        else Path(__file__).resolve().parent.parent
    )
    dist_dir = resolve_path(project_root, args.dist)
    output_dir = resolve_path(project_root, args.output_dir)
    output_path = (
        resolve_path(project_root, args.output)
        if args.output
        else output_dir / DEFAULT_OUTPUT_NAME
    )
    if output_path.suffix.lower() != ".epub":
        raise SystemExit("--output must end with .epub")
    if not dist_dir.is_dir():
        raise SystemExit(
            f"Finished build directory not found: {dist_dir}\n"
            "Create or restore a current dist/ build, then run this exporter."
        )

    require_epub_dependencies()
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

    linked_images, linked_files, titles, article_files = collect_inputs(
        dist_dir,
        args.site_url,
    )
    pages, roles = build_pages(
        args=args,
        dist_dir=dist_dir,
        linked_images=linked_images,
        linked_files=linked_files,
        titles=titles,
        article_files=article_files,
    )
    identifier = stable_identifier(
        f"{args.site_url}|metaweb-epub|complete|"
        + "|".join(page.public_url for page in pages)
    )
    builder = EpubBookBuilder(
        dist_dir=dist_dir,
        site_url=args.site_url,
        title=f"{args.title} / {args.title_en}",
        author=args.author,
        languages=["cs", "en"],
        identifier=identifier,
        pages=pages,
        toc_title="Obsah / Contents",
        image_max_px=args.effective_image_max_px,
        jpeg_quality=args.effective_jpeg_quality,
        png_mode=args.effective_png_mode,
        gif_mode=args.effective_gif_mode,
    )

    print(f"[source] {dist_dir}")
    print(
        f"[inputs] {len(linked_images)} linked image(s), "
        f"{len(linked_files)} identity/integrity file(s)"
    )
    print(f"[book] {len(pages)} reflowable spine document(s) -> {output_path}")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, candidate_name = tempfile.mkstemp(
        prefix=f".{output_path.stem}-",
        suffix=".candidate.epub",
        dir=output_path.parent,
    )
    os.close(descriptor)
    candidate_path = Path(candidate_name)
    try:
        result = builder.build(candidate_path)
        validate_metaweb_composition(
            candidate_path,
            pages=pages,
            roles=roles,
            linked_images=linked_images,
            linked_files=linked_files,
        )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        os.replace(candidate_path, output_path)
        result = dataclasses.replace(result, output_path=output_path)
    finally:
        candidate_path.unlink(missing_ok=True)

    manifest_path = output_path.with_suffix(".manifest.json")
    if args.no_manifest:
        manifest_path.unlink(missing_ok=True)
    else:
        write_manifest(
            manifest_path,
            project_root=project_root,
            dist_dir=dist_dir,
            output_path=output_path,
            result=result,
            args=args,
            pages=pages,
            roles=roles,
            linked_images=linked_images,
            linked_files=linked_files,
        )
        print(f"[manifest] {manifest_path}")

    print(
        f"[done] {output_path} ({output_path.stat().st_size:,} bytes; "
        f"{result.page_count} spine document(s); {result.asset_count} asset(s); "
        f"{result.optimized_asset_count} optimized image(s); "
        f"{result.source_asset_bytes:,} -> {result.packaged_asset_bytes:,} "
        "image bytes)"
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        raise SystemExit(130) from None
