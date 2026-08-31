#!/usr/bin/env python3
"""Shared EPUB conversion, packaging, and validation helpers.

The existing PDF exporters intentionally do not import this module.  Their
rendering pipeline is browser/PDF-specific, while this module contains only the
logic genuinely shared by the two reflowable EPUB exporters.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import hashlib
import html
import io
import os
import posixpath
import re
import stat
import tempfile
import unicodedata
import uuid
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any, Iterable
from urllib.parse import quote, unquote, urljoin, urlsplit, urlunsplit


EPUB_MIMETYPE = b"application/epub+zip"
CONTAINER_PATH = "META-INF/container.xml"
PACKAGE_PATH = "EPUB/package.opf"
XHTML_NS = "http://www.w3.org/1999/xhtml"
OPF_NS = "http://www.idpf.org/2007/opf"
DC_NS = "http://purl.org/dc/elements/1.1/"
CONTAINER_NS = "urn:oasis:names:tc:opendocument:xmlns:container"
XML_NS = "http://www.w3.org/XML/1998/namespace"
MATHML_NS = "http://www.w3.org/1998/Math/MathML"
SVG_NS = "http://www.w3.org/2000/svg"

CORE_IMAGE_MEDIA_TYPES = {
    ".gif": "image/gif",
    ".jpeg": "image/jpeg",
    ".jpg": "image/jpeg",
    ".png": "image/png",
    ".svg": "image/svg+xml",
    ".webp": "image/webp",
}
LOCAL_IMAGE_EXTENSIONS = frozenset((*CORE_IMAGE_MEDIA_TYPES, ".avif"))

IMAGE_QUALITY_PRESETS: dict[str, tuple[int | None, int | None]] = {
    "archive": (None, None),
    "printer": (2400, 90),
    "ebook": (1600, 82),
    "screen": (1200, 72),
    "compact": (800, 60),
}

XML_INVALID_CHARS = re.compile(
    "[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x84\x86-\x9f]"
)

EPUB_CSS = """\
@namespace epub "http://www.idpf.org/2007/ops";

html {
  color: #171717;
  background: #ffffff;
}

body {
  font-family: Arial, Helvetica, sans-serif;
  line-height: 1.6;
  margin: 5%;
  overflow-wrap: anywhere;
}

.post-header {
  border-bottom: 1px dotted #bdbdbd;
  margin-bottom: 1em;
  padding-bottom: 0.6em;
}

.post-title {
  font-size: 2em;
  margin: 0 0 0.25em;
}

.post-body h2,
.post-body h3,
.post-body h4 {
  line-height: 1.25;
  margin-top: 2em;
}

.post-body pre {
  background: #f5f5f5;
  border: 1px solid #d8d8d8;
  padding: 1em;
}

.publication-title-page {
  min-height: 70vh;
  padding-top: 18vh;
  text-align: center;
}

.publication-title-page h1 {
  font-size: 2.2em;
  margin-bottom: 0.2em;
}

.publication-title-page .subtitle {
  color: #555555;
  font-size: 1.35em;
  margin-top: 0;
}

.publication-title-page .author {
  margin-top: 3em;
}

.frontmatter-meta {
  border-bottom: 1px solid #aaaaaa;
  border-top: 1px solid #aaaaaa;
  display: grid;
  grid-template-columns: minmax(8em, 0.7fr) minmax(0, 1.3fr);
  margin: 1.5em 0;
}

.frontmatter-meta dt,
.frontmatter-meta dd {
  border-bottom: 1px solid #dddddd;
  margin: 0;
  padding: 0.45em 0.3em;
}

.frontmatter-meta dt {
  font-weight: bold;
}

.epub-notice {
  background: #f3f6f7;
  border: 1px solid #b8c5c9;
  border-left: 0.3em solid #2d6675;
  margin: 1em 0;
  padding: 0.75em 0.9em;
}

.book-index-list,
.gallery-list,
.registry-cards {
  list-style: none;
  padding-left: 0;
}

.book-index-item,
.gallery-card,
.registry-card {
  border: 1px solid #cccccc;
  break-inside: avoid;
  margin: 0.8em 0;
  padding: 0.8em;
}

.book-index-item h3,
.gallery-card h2,
.registry-card h3 {
  margin-top: 0;
}

.book-index-item .metadata,
.gallery-card .metadata,
.raw-document .source {
  color: #555555;
  font-size: 0.9em;
}

.registry-fields {
  display: grid;
  grid-template-columns: minmax(7em, 0.7fr) minmax(0, 1.3fr);
  margin: 0;
}

.registry-fields dt,
.registry-fields dd {
  border-top: 1px solid #dddddd;
  margin: 0;
  padding: 0.35em 0;
}

.registry-fields dt {
  font-weight: bold;
  padding-right: 0.6em;
}

.gallery-card img {
  background: #f4f4f1;
  max-height: 75vh;
  object-fit: contain;
}

.caption-language {
  margin: 0.4em 0;
}

.caption-language strong {
  color: #2d6675;
  display: inline-block;
  min-width: 2.4em;
}

.section-intro {
  padding: 10vh 4% 4%;
}

.section-intro .eyebrow {
  color: #2d6675;
  font-size: 0.8em;
  font-weight: bold;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.raw-text {
  background: #f5f5f2;
  border: 1px solid #cccccc;
  font-size: 0.78em;
  padding: 0.8em;
  white-space: pre-wrap;
}

article,
main,
section,
figure,
table,
pre,
blockquote {
  max-width: 100%;
}

h1,
h2,
h3,
h4,
h5,
h6 {
  line-height: 1.2;
  break-after: avoid;
}

a {
  color: #174f78;
  text-decoration: underline;
}

img,
svg {
  display: block;
  height: auto;
  margin: 0.8em auto;
  max-width: 100%;
}

figure {
  break-inside: avoid;
  margin: 1em 0;
}

figcaption,
.post-meta {
  color: #555555;
  font-size: 0.9em;
}

.media-row,
.post-grid {
  display: block;
}

.media-row__item,
.post-card {
  display: block;
  margin: 0.8em 0;
}

table {
  border-collapse: collapse;
  table-layout: fixed;
  width: 100%;
}

th,
td {
  border: 1px solid #999999;
  padding: 0.35em;
  text-align: left;
  vertical-align: top;
  word-break: break-word;
}

pre,
code {
  font-family: monospace;
  white-space: pre-wrap;
  word-break: break-word;
}

blockquote {
  border-left: 0.2em solid #999999;
  margin-left: 0;
  padding-left: 1em;
}

.epub-interactive-fallback,
.epub-remote-image {
  border-left: 0.2em solid #777777;
  margin: 1em 0;
  padding: 0.5em 0.8em;
}

nav[epub|type~="toc"] ol {
  padding-left: 1.4em;
}

nav[epub|type~="toc"] li {
  margin: 0.35em 0;
}
"""

CONTAINER_XML = """\
<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0"
  xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="EPUB/package.opf"
      media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
"""


@dataclasses.dataclass(frozen=True)
class EpubSourcePage:
    source_file: Path | None
    public_url: str
    lang: str
    title: str
    output_name: str
    nav_group: str | None = None
    html_fragment: str | None = None
    content_selector: str | None = None
    reference_file: Path | None = None
    map_public_url: bool = True

    @property
    def href(self) -> str:
        return f"text/{self.output_name}"


@dataclasses.dataclass(frozen=True)
class EpubAsset:
    source_file: Path
    href: str
    media_type: str
    manifest_id: str


@dataclasses.dataclass(frozen=True)
class EpubPackagedAsset:
    source_file: Path
    href: str
    media_type: str
    manifest_id: str
    source_bytes: int
    source_sha256: str
    packaged_bytes: int
    packaged_sha256: str
    optimized: bool


@dataclasses.dataclass(frozen=True)
class EpubBuildResult:
    output_path: Path
    page_count: int
    asset_count: int
    interactive_fallback_count: int
    remote_image_fallback_count: int
    entry_count: int
    optimized_asset_count: int
    source_asset_bytes: int
    packaged_asset_bytes: int
    jpeg_quality_used: int | None
    empty_image_placeholder_count: int
    assets: tuple[EpubPackagedAsset, ...]


@dataclasses.dataclass(frozen=True)
class BuiltPost:
    title: str
    slug: str
    lang: str
    section: str
    date: str
    declared_url: str
    declared_built_html: str


SITE_SECTION_ORDER = ("volna-tvorba", "vystavy", "cestovani")


def parse_all_posts_index(path: Path) -> list[BuiltPost]:
    """Read article selection metadata generated inside a finished dist/."""

    if not path.is_file():
        raise SystemExit(
            f"Finished build index not found: {path}\n"
            "Run a current web build first; EPUB selection is read from "
            "dist/ALL_POSTS.txt."
        )

    lines = path.read_text(encoding="utf-8-sig", errors="strict").splitlines()
    required = {
        "TITLE",
        "SLUG",
        "URL",
        "LANGUAGE",
        "SECTION",
        "DATE",
        "BUILT_HTML",
    }
    posts: list[BuiltPost] = []
    seen: set[tuple[str, str]] = set()

    for index, line in enumerate(lines):
        if not re.fullmatch(r"={20,}", line.strip()):
            continue

        data: dict[str, str] = {}
        closed = False
        for candidate in lines[index + 1 : index + 14]:
            if re.fullmatch(r"={20,}", candidate.strip()):
                closed = True
                break
            if ":" not in candidate:
                continue
            key, value = candidate.split(":", 1)
            data[key.strip()] = value.strip()

        if not closed or not required.issubset(data):
            continue
        lang = data["LANGUAGE"].lower()
        if lang not in {"cs", "en"}:
            continue
        key = (data["SLUG"].strip("/"), lang)
        if key in seen:
            raise SystemExit(
                "Duplicate article metadata in dist/ALL_POSTS.txt: "
                f"{lang.upper()} {key[0]}"
            )
        seen.add(key)
        posts.append(
            BuiltPost(
                title=data["TITLE"],
                slug=key[0],
                lang=lang,
                section=data["SECTION"],
                date=data["DATE"],
                declared_url=data["URL"],
                declared_built_html=data["BUILT_HTML"],
            )
        )

    if not posts:
        raise SystemExit(
            f"No article metadata blocks found in finished build index: {path}"
        )
    return posts


def _date_key(value: str) -> tuple[int, int, int]:
    try:
        parsed = dt.date.fromisoformat(value.strip()[:10])
        return parsed.year, parsed.month, parsed.day
    except ValueError:
        return 0, 0, 0


def _section_index(section: str) -> int:
    try:
        return SITE_SECTION_ORDER.index(section)
    except ValueError:
        return len(SITE_SECTION_ORDER)


def sorted_built_posts(posts: Iterable[BuiltPost]) -> list[BuiltPost]:
    return sorted(
        posts,
        key=lambda post: (
            _section_index(post.section),
            tuple(-part for part in _date_key(post.date)),
            post.title.casefold(),
        ),
    )


def find_built_article_html(
    dist_dir: Path,
    slug: str,
    lang: str,
) -> Path | None:
    slug = slug.strip("/")
    if lang == "cs":
        candidates = [
            dist_dir / slug / "index.html",
            dist_dir / f"{slug}.html",
        ]
    else:
        candidates = [
            dist_dir / "en" / slug / "index.html",
            dist_dir / "en" / f"{slug}.html",
        ]
    return next((candidate for candidate in candidates if candidate.is_file()), None)


def require_epub_dependencies() -> None:
    try:
        import bs4  # noqa: F401
        import html5lib  # noqa: F401
    except ImportError:
        raise SystemExit(
            "Missing Python EPUB export dependencies: beautifulsoup4 and/or html5lib\n"
            "Install EPUB export dependencies with:\n"
            "  python -m pip install -r requirements-epub-export.txt"
        ) from None


def require_image_dependency() -> None:
    try:
        import PIL  # noqa: F401
    except ImportError:
        raise SystemExit(
            "Missing Python dependency required for image optimization: Pillow\n"
            "Install EPUB export dependencies with:\n"
            "  python -m pip install -r requirements-epub-export.txt"
        ) from None


def resolve_path(project_root: Path, value: str) -> Path:
    path = Path(value).expanduser()
    return path.resolve() if path.is_absolute() else (project_root / path).resolve()


def normalize_site_url(value: str) -> str:
    parsed = urlsplit(value.strip())
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        raise SystemExit(
            "--site-url must be an absolute HTTP(S) site root, for example "
            "https://vojtamaur.cz"
        )
    if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        raise SystemExit(
            "--site-url must contain only a scheme and host, without a path, "
            "query, or fragment."
        )
    return urlunsplit((parsed.scheme.lower(), parsed.netloc, "/", "", ""))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_write_text(path: Path, value: str, *, encoding: str = "utf-8") -> None:
    """Write a text file through a same-directory temporary and preserve mode."""

    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.stem}-",
        suffix=".tmp",
        dir=path.parent,
    )
    os.close(descriptor)
    temporary_path = Path(temporary_name)
    try:
        if path.exists():
            mode = stat.S_IMODE(path.stat().st_mode)
        else:
            current_umask = os.umask(0)
            os.umask(current_umask)
            mode = 0o666 & ~current_umask
        os.chmod(temporary_path, mode)
        temporary_path.write_text(value, encoding=encoding)
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


def safe_filename(value: str, fallback: str = "item") -> str:
    normalized = unicodedata.normalize("NFKD", value)
    ascii_value = normalized.encode("ascii", errors="ignore").decode("ascii")
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", ascii_value).strip("._-")
    return cleaned or fallback


def stable_identifier(seed: str) -> str:
    return "urn:uuid:" + str(uuid.uuid5(uuid.NAMESPACE_URL, seed))


def image_settings(
    preset: str,
    image_max_px: int | None,
    jpeg_quality: int | None,
) -> tuple[int | None, int | None]:
    try:
        default_max_px, default_jpeg_quality = IMAGE_QUALITY_PRESETS[preset]
    except KeyError:
        raise SystemExit(f"Unknown image quality preset: {preset}") from None

    effective_max_px = (
        image_max_px if image_max_px is not None else default_max_px
    )
    effective_jpeg_quality = (
        jpeg_quality if jpeg_quality is not None else default_jpeg_quality
    )
    if effective_max_px is not None and effective_max_px < 1:
        raise SystemExit("--image-max-px must be a positive integer.")
    if (
        effective_jpeg_quality is not None
        and not 1 <= effective_jpeg_quality <= 100
    ):
        raise SystemExit("--jpeg-quality must be between 1 and 100.")
    return effective_max_px, effective_jpeg_quality


def utc_modified() -> str:
    return (
        dt.datetime.now(dt.timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def read_built_page_metadata(
    html_file: Path,
    fallback_title: str,
) -> tuple[str, bool]:
    """Return the built H1/title and whether robots marks the page noindex."""

    require_epub_dependencies()
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html_file.read_bytes(), "html.parser")
    root = (
        soup.select_one("main article")
        or soup.find("article")
        or soup.find("main")
    )
    heading = root.find("h1") if root is not None else None
    title = heading.get_text(" ", strip=True) if heading is not None else ""
    if not title and soup.title is not None:
        title = soup.title.get_text(" ", strip=True)
        title = re.sub(
            r"\s*\|\s*Vojta Maur\s*$",
            "",
            title,
            flags=re.IGNORECASE,
        ).strip()
    robots = " ".join(
        item.get("content", "")
        for item in soup.find_all(
            "meta",
            attrs={"name": re.compile(r"^robots$", re.IGNORECASE)},
        )
    ).lower()
    return title or fallback_title, "noindex" in robots


def _xml_clean(value: str) -> str:
    return XML_INVALID_CHARS.sub("", value)


def _escaped(value: str) -> str:
    return html.escape(_xml_clean(value), quote=True)


def _safe_zip_href(value: str) -> bool:
    path = PurePosixPath(unquote(value))
    return (
        not value.startswith("/")
        and not path.is_absolute()
        and ".." not in path.parts
        and "\\" not in value
    )


def _relative_href(from_href: str, to_href: str) -> str:
    return posixpath.relpath(to_href, posixpath.dirname(from_href))


def _append_query_fragment(href: str, query: str, fragment: str) -> str:
    if query:
        href += "?" + query
    if fragment:
        href += "#" + fragment
    return href


def _youtube_public_url(value: str) -> str:
    parsed = urlsplit(value)
    host = parsed.netloc.lower().split(":", 1)[0]
    match = re.match(r"^/embed/([^/?#]+)", parsed.path)
    if host in {
        "youtube.com",
        "www.youtube.com",
        "m.youtube.com",
        "youtube-nocookie.com",
        "www.youtube-nocookie.com",
    } and match:
        return f"https://www.youtube.com/watch?v={quote(match.group(1), safe='-_')}"
    return value


class EpubBookBuilder:
    def __init__(
        self,
        *,
        dist_dir: Path,
        site_url: str,
        title: str,
        author: str,
        languages: Iterable[str],
        identifier: str,
        pages: Iterable[EpubSourcePage],
        toc_title: str,
        image_max_px: int | None = None,
        jpeg_quality: int | None = None,
        png_mode: str = "preserve",
        gif_mode: str = "preserve",
    ) -> None:
        self.dist_dir = dist_dir.resolve()
        self.site_url = normalize_site_url(site_url)
        self.site_netloc = urlsplit(self.site_url).netloc.lower()
        self.title = title
        self.author = author
        self.languages = tuple(dict.fromkeys(languages))
        self.identifier = identifier
        self.pages = tuple(pages)
        self.toc_title = toc_title
        self.image_max_px = image_max_px
        self.jpeg_quality = jpeg_quality
        self.png_mode = png_mode
        self.gif_mode = gif_mode

        if not self.pages:
            raise SystemExit("Cannot create an EPUB without content pages.")
        if not self.languages:
            raise SystemExit("Cannot create an EPUB without dc:language metadata.")
        if self.image_max_px is not None and self.image_max_px < 1:
            raise SystemExit("--image-max-px must be a positive integer.")
        if self.jpeg_quality is not None and not 1 <= self.jpeg_quality <= 100:
            raise SystemExit("--jpeg-quality must be between 1 and 100.")
        if self.png_mode not in {"preserve", "jpeg"}:
            raise SystemExit("--png-mode must be preserve or jpeg.")
        if self.gif_mode not in {"preserve", "poster"}:
            raise SystemExit("--gif-mode must be preserve or poster.")
        if (
            self.image_max_px is not None
            or self.jpeg_quality is not None
            or self.png_mode != "preserve"
            or self.gif_mode != "preserve"
        ):
            require_image_dependency()

        hrefs = [page.href for page in self.pages]
        if len(hrefs) != len(set(hrefs)):
            raise SystemExit("EPUB content page filenames must be unique.")

        self._page_by_source: dict[Path, EpubSourcePage] = {}
        self._page_by_route: dict[str, EpubSourcePage] = {}
        for page in self.pages:
            if page.source_file is None and page.html_fragment is None:
                raise SystemExit(
                    f"EPUB page has neither a source file nor generated HTML: {page.title}"
                )
            source = (
                page.source_file.resolve()
                if page.source_file is not None
                else None
            )
            if source is not None:
                if not source.is_file():
                    raise SystemExit(f"EPUB source file not found: {source}")
                if not source.is_relative_to(self.dist_dir):
                    raise SystemExit(f"EPUB source file is outside dist/: {source}")
            if page.reference_file is not None:
                reference = page.reference_file.resolve()
                if not reference.is_file():
                    raise SystemExit(f"EPUB reference file not found: {reference}")
                if not reference.is_relative_to(self.dist_dir):
                    raise SystemExit(
                        f"EPUB reference file is outside dist/: {reference}"
                    )
            if not page.output_name.endswith(".xhtml") or "/" in page.output_name:
                raise SystemExit(
                    f"Unsafe EPUB content filename: {page.output_name}"
                )
            if source is not None:
                self._page_by_source.setdefault(source, page)
            if page.map_public_url:
                route = urlsplit(page.public_url).path
                self._page_by_route.setdefault(route.rstrip("/") or "/", page)

        self._assets_by_source: dict[Path, EpubAsset] = {}
        self._interactive_fallback_count = 0
        self._remote_image_fallback_count = 0
        self._empty_image_placeholder_count = 0

    def _inside_dist(self, candidate: Path) -> Path | None:
        resolved = candidate.resolve()
        if not resolved.is_relative_to(self.dist_dir):
            return None
        return resolved

    def _dist_path_for_public_path(self, public_path: str) -> Path | None:
        decoded = unquote(public_path).lstrip("/")
        direct = self._inside_dist(self.dist_dir / decoded)
        if direct is None:
            return None

        candidates: list[Path] = []
        if not decoded:
            candidates.extend(
                [self.dist_dir / "index.html"]
            )
        else:
            candidates.append(direct)
            if public_path.endswith("/") or not Path(decoded).suffix:
                candidates.extend(
                    [
                        direct / "index.html",
                        self.dist_dir / f"{decoded.rstrip('/')}.html",
                    ]
                )

        for candidate in candidates:
            safe = self._inside_dist(candidate)
            if safe is not None and safe.is_file():
                return safe

        return direct

    def _local_reference(
        self,
        page: EpubSourcePage,
        raw_value: str,
    ) -> tuple[Path | None, Any]:
        parsed = urlsplit(raw_value.strip())
        scheme = parsed.scheme.lower()

        if scheme and scheme not in {"http", "https"}:
            return None, parsed
        if parsed.netloc and parsed.netloc.lower() != self.site_netloc:
            return None, parsed

        if scheme in {"http", "https"} or parsed.netloc or parsed.path.startswith("/"):
            return self._dist_path_for_public_path(parsed.path), parsed

        reference_file = (
            page.reference_file.resolve()
            if page.reference_file is not None
            else page.source_file.resolve()
            if page.source_file is not None
            else (self.dist_dir / "index.html").resolve()
        )

        if not parsed.path:
            return reference_file, parsed

        candidate = self._inside_dist(
            reference_file.parent / unquote(parsed.path)
        )
        if candidate is None:
            return None, parsed

        if candidate.is_dir():
            index_candidate = self._inside_dist(candidate / "index.html")
            if index_candidate is not None and index_candidate.is_file():
                candidate = index_candidate
        elif not candidate.exists() and not candidate.suffix:
            directory_candidate = self._inside_dist(candidate / "index.html")
            file_candidate = self._inside_dist(
                candidate.with_name(candidate.name + ".html")
            )
            if directory_candidate is not None and directory_candidate.is_file():
                candidate = directory_candidate
            elif file_candidate is not None and file_candidate.is_file():
                candidate = file_candidate

        return candidate, parsed

    def _public_url_for_local(self, local_path: Path) -> str:
        resolved = local_path.resolve()
        included = self._page_by_source.get(resolved)
        if included is not None:
            return included.public_url

        if not resolved.is_relative_to(self.dist_dir):
            return self.site_url

        rel = resolved.relative_to(self.dist_dir)
        parts = rel.parts
        rel_posix = rel.as_posix()

        if rel_posix == "index.html":
            public_path = ""
        elif rel_posix == "en.html":
            public_path = "en/"
        elif rel.name == "index.html":
            public_path = rel.parent.as_posix().rstrip("/") + "/"
        elif len(parts) == 1 and rel.suffix.lower() == ".html":
            public_path = rel.stem + "/"
        elif (
            len(parts) == 2
            and parts[0].lower() == "en"
            and rel.suffix.lower() == ".html"
        ):
            public_path = f"en/{rel.stem}/"
        else:
            public_path = rel_posix

        return urljoin(self.site_url, quote(public_path, safe="/"))

    def _public_url_for_reference(
        self,
        page: EpubSourcePage,
        raw_value: str,
    ) -> str:
        local_path, parsed = self._local_reference(page, raw_value)
        if local_path is not None:
            base = self._public_url_for_local(local_path)
            return _append_query_fragment(base, parsed.query, parsed.fragment)

        if parsed.scheme or parsed.netloc:
            return raw_value
        return urljoin(page.public_url, raw_value)

    def _register_asset(self, source_file: Path) -> EpubAsset:
        source = source_file.resolve()
        if not source.is_relative_to(self.dist_dir):
            raise SystemExit(f"EPUB asset is outside dist/: {source}")
        if not source.is_file():
            raise SystemExit(f"EPUB asset is missing from dist/: {source}")

        existing = self._assets_by_source.get(source)
        if existing is not None:
            return existing

        suffix = source.suffix.lower()
        package_suffix = suffix
        if suffix == ".png" and self.png_mode == "jpeg":
            from PIL import Image

            try:
                with Image.open(source) as image:
                    has_alpha = (
                        "A" in image.getbands()
                        or "transparency" in image.info
                    )
            except OSError as exc:
                raise SystemExit(
                    f"Could not inspect EPUB image {source}: {exc}"
                ) from exc
            if not has_alpha:
                package_suffix = ".jpg"
        elif suffix == ".avif":
            require_image_dependency()
            from PIL import Image

            try:
                with Image.open(source) as image:
                    image.load()
                    has_alpha = (
                        "A" in image.getbands()
                        or "transparency" in image.info
                    )
            except OSError as exc:
                raise SystemExit(
                    "Could not decode AVIF image for EPUB conversion. Install "
                    "Pillow 11.3 or newer from requirements-epub-export.txt: "
                    f"{source}: {exc}"
                ) from exc
            package_suffix = ".png" if has_alpha else ".jpg"
        elif suffix == ".gif" and self.gif_mode == "poster":
            package_suffix = ".png"

        media_type = CORE_IMAGE_MEDIA_TYPES.get(package_suffix)
        if media_type is None:
            raise SystemExit(
                f"Unsupported local EPUB image format: {source.name}"
            )

        rel = source.relative_to(self.dist_dir).as_posix()
        digest = hashlib.sha1(rel.encode("utf-8")).hexdigest()[:10]
        stem = safe_filename(source.stem, fallback="asset")
        package_name = f"{digest}-{stem}{package_suffix}"
        asset = EpubAsset(
            source_file=source,
            href=f"assets/{package_name}",
            media_type=media_type,
            manifest_id=f"asset-{len(self._assets_by_source) + 1:04d}",
        )
        self._assets_by_source[source] = asset
        return asset

    def _internal_page_href(
        self,
        page: EpubSourcePage,
        local_path: Path | None,
        parsed: Any,
    ) -> str | None:
        target_page = (
            self._page_by_source.get(local_path.resolve())
            if local_path is not None and local_path.exists()
            else None
        )
        if target_page is None:
            route = parsed.path.rstrip("/") or "/"
            target_page = self._page_by_route.get(route)
        if target_page is None:
            return None
        href = _relative_href(page.href, target_page.href)
        return _append_query_fragment(href, parsed.query, parsed.fragment)

    def _fallback_label(self, lang: str, kind: str, detail: str) -> str:
        if lang == "cs":
            prefix = {
                "interactive": "Interaktivní nebo vložený obsah",
                "image": "Externí obrázek",
            }.get(kind, "Externí obsah")
        else:
            prefix = {
                "interactive": "Interactive or embedded content",
                "image": "External image",
            }.get(kind, "External content")
        return f"{prefix}: {detail}" if detail else prefix

    def _replace_interactive(self, soup: Any, page: EpubSourcePage, tag: Any) -> None:
        source = (
            tag.get("src")
            or tag.get("data")
            or (tag.find("source").get("src") if tag.find("source") else "")
        )
        title = tag.get("title", "").strip()
        if not title and source:
            parsed = urlsplit(source)
            title = Path(unquote(parsed.path)).name or parsed.netloc

        paragraph = soup.new_tag("p")
        paragraph["class"] = ["epub-interactive-fallback"]
        label = self._fallback_label(page.lang, "interactive", title)
        if source:
            anchor = soup.new_tag("a")
            target = self._public_url_for_reference(page, source)
            anchor["href"] = _youtube_public_url(target)
            anchor.string = label
            paragraph.append(anchor)
        else:
            paragraph.string = label
        tag.replace_with(paragraph)
        self._interactive_fallback_count += 1

    def _replace_remote_image(
        self,
        soup: Any,
        page: EpubSourcePage,
        image: Any,
        source: str,
    ) -> None:
        alt = image.get("alt", "").strip()
        label = self._fallback_label(
            page.lang,
            "image",
            alt or Path(unquote(urlsplit(source).path)).name,
        )
        parent = image.parent
        if parent is not None and parent.name == "a":
            span = soup.new_tag("span")
            span["class"] = ["epub-remote-image"]
            span.string = label
            image.replace_with(span)
        else:
            paragraph = soup.new_tag("p")
            paragraph["class"] = ["epub-remote-image"]
            anchor = soup.new_tag("a")
            anchor["href"] = self._public_url_for_reference(page, source)
            anchor.string = label
            paragraph.append(anchor)
            image.replace_with(paragraph)
        self._remote_image_fallback_count += 1

    def _sanitize_fragment(
        self,
        soup: Any,
        root: Any,
        page: EpubSourcePage,
    ) -> str:
        from bs4 import NavigableString

        for tag in list(root.find_all(["script", "style", "link", "base", "noscript"])):
            tag.decompose()

        for tag in list(
            root.find_all(["iframe", "video", "audio", "object", "embed", "canvas"])
        ):
            self._replace_interactive(soup, page, tag)

        for picture in list(root.find_all("picture")):
            for source in list(picture.find_all("source")):
                source.decompose()
            picture.unwrap()

        for details in root.find_all("details"):
            details["open"] = "open"

        # BeautifulSoup parses source HTML with HTML namespace rules, while
        # EPUB content documents use XML serialization. Explicit namespace
        # declarations keep inline MathML and SVG in their required namespaces
        # after the fragment is inserted into the XHTML wrapper.
        for math in root.find_all("math"):
            math["xmlns"] = MATHML_NS
        for svg in root.find_all("svg"):
            svg["xmlns"] = SVG_NS

        for image in list(root.find_all("img")):
            source = image.get("src", "").strip()
            for attr in (
                "srcset",
                "sizes",
                "loading",
                "decoding",
                "fetchpriority",
                "crossorigin",
                "referrerpolicy",
            ):
                image.attrs.pop(attr, None)
            image["alt"] = image.get("alt", "")

            if not source:
                image.decompose()
                self._empty_image_placeholder_count += 1
                continue

            local_path, parsed = self._local_reference(page, source)
            if (
                local_path is not None
                and local_path.suffix.lower() in LOCAL_IMAGE_EXTENSIONS
            ):
                if not local_path.is_file():
                    raise SystemExit(
                        f"Image referenced by built HTML is missing: {local_path}"
                    )
                asset = self._register_asset(local_path)
                image["src"] = _append_query_fragment(
                    _relative_href(page.href, asset.href),
                    parsed.query,
                    parsed.fragment,
                )
                continue

            self._replace_remote_image(soup, page, image, source)

        for anchor in list(root.find_all("a")):
            raw_href = anchor.get("href", "").strip()
            force_external = anchor.attrs.pop("data-epub-external", None)
            for attr in ("target", "rel", "download", "ping", "referrerpolicy"):
                anchor.attrs.pop(attr, None)
            if not raw_href:
                if anchor.get_text(" ", strip=True) or anchor.find(True):
                    anchor.unwrap()
                else:
                    anchor.decompose()
                continue
            if raw_href.startswith("#"):
                continue

            if force_external is not None:
                anchor["href"] = self._public_url_for_reference(page, raw_href)
                continue

            local_path, parsed = self._local_reference(page, raw_href)
            internal_href = self._internal_page_href(page, local_path, parsed)
            if internal_href is not None:
                anchor["href"] = internal_href
                continue

            if (
                local_path is not None
                and local_path.suffix.lower() in LOCAL_IMAGE_EXTENSIONS
            ):
                if not local_path.is_file():
                    raise SystemExit(
                        f"Image linked by built HTML is missing: {local_path}"
                    )
                asset = self._register_asset(local_path)
                href = _relative_href(page.href, asset.href)
                anchor["href"] = _append_query_fragment(
                    href,
                    parsed.query,
                    parsed.fragment,
                )
                continue

            if local_path is not None:
                anchor["href"] = self._public_url_for_reference(page, raw_href)

        for control in list(
            root.find_all(["form", "input", "button", "select", "textarea"])
        ):
            control.decompose()

        for tag in root.find_all(True):
            for attr in list(tag.attrs):
                lowered = attr.lower()
                if lowered.startswith("on") or lowered.startswith("data-astro-"):
                    tag.attrs.pop(attr, None)
            for attr, value in list(tag.attrs.items()):
                if isinstance(value, list):
                    tag.attrs[attr] = [_xml_clean(str(item)) for item in value]
                else:
                    tag.attrs[attr] = _xml_clean(str(value))

        for node in list(root.descendants):
            if isinstance(node, NavigableString):
                cleaned = _xml_clean(str(node))
                if cleaned != str(node):
                    node.replace_with(cleaned)

        return root.decode(formatter="minimal")

    def _convert_page(self, page: EpubSourcePage) -> bytes:
        require_epub_dependencies()
        from bs4 import BeautifulSoup

        if page.html_fragment is not None:
            soup = BeautifulSoup(page.html_fragment, "html5lib")
        elif page.source_file is not None:
            soup = BeautifulSoup(page.source_file.read_bytes(), "html5lib")
        else:
            raise SystemExit(f"Missing EPUB page input: {page.title}")

        root = (
            soup.select_one(page.content_selector)
            if page.content_selector
            else soup.select_one("main article")
            or soup.find("article")
            or soup.find("main")
        )
        if root is None:
            source_label = page.source_file or "generated HTML"
            raise SystemExit(
                f"Content container not found for EPUB page {page.title}: "
                f"{source_label}"
            )

        fragment = self._sanitize_fragment(soup, root, page)
        xhtml = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html>
<html xmlns="{XHTML_NS}" lang="{_escaped(page.lang)}" xml:lang="{_escaped(page.lang)}">
  <head>
    <meta charset="utf-8" />
    <title>{_escaped(page.title)}</title>
    <link rel="stylesheet" type="text/css" href="../styles/epub.css" />
  </head>
  <body>
{fragment}
  </body>
</html>
"""
        payload = xhtml.encode("utf-8")
        try:
            ET.fromstring(payload)
        except ET.ParseError as exc:
            source_label = page.source_file or "generated HTML"
            raise SystemExit(
                f"Generated XHTML is not well-formed for {source_label}: {exc}"
            ) from exc
        return payload

    def _nav_xhtml(self) -> bytes:
        groups: list[tuple[str | None, list[EpubSourcePage]]] = []
        for page in self.pages:
            if not groups or groups[-1][0] != page.nav_group:
                groups.append((page.nav_group, [page]))
            else:
                groups[-1][1].append(page)

        if any(group is not None for group, _ in groups):
            items: list[str] = []
            for group, pages in groups:
                page_items = "".join(
                    f'<li><a href="{_escaped(page.href)}">{_escaped(page.title)}</a></li>'
                    for page in pages
                )
                if group is None:
                    items.append(page_items)
                else:
                    items.append(
                        f"<li><span>{_escaped(group)}</span><ol>{page_items}</ol></li>"
                    )
            toc_items = "".join(items)
        else:
            toc_items = "".join(
                f'<li><a href="{_escaped(page.href)}">{_escaped(page.title)}</a></li>'
                for page in self.pages
            )

        lang = self.languages[0]
        nav = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html>
<html xmlns="{XHTML_NS}" xmlns:epub="http://www.idpf.org/2007/ops"
  lang="{_escaped(lang)}" xml:lang="{_escaped(lang)}">
  <head>
    <meta charset="utf-8" />
    <title>{_escaped(self.toc_title)}</title>
    <link rel="stylesheet" type="text/css" href="styles/epub.css" />
  </head>
  <body>
    <nav epub:type="toc" id="toc">
      <h1>{_escaped(self.toc_title)}</h1>
      <ol>{toc_items}</ol>
    </nav>
  </body>
</html>
"""
        return nav.encode("utf-8")

    def _package_opf(
        self,
        converted_pages: list[tuple[EpubSourcePage, bytes]],
        modified: str,
    ) -> bytes:
        language_xml = "\n".join(
            f"    <dc:language>{_escaped(language)}</dc:language>"
            for language in self.languages
        )

        page_items: list[str] = []
        spine_items: list[str] = []
        for index, (page, payload) in enumerate(converted_pages, start=1):
            page_root = ET.fromstring(payload)
            properties = []
            if any(
                element.tag == f"{{{SVG_NS}}}svg"
                for element in page_root.iter()
            ):
                properties.append("svg")
            if any(
                element.tag == f"{{{MATHML_NS}}}math"
                for element in page_root.iter()
            ):
                properties.append("mathml")
            property_attr = (
                f' properties="{_escaped(" ".join(properties))}"'
                if properties
                else ""
            )
            page_items.append(
                f'    <item id="page-{index:04d}" href="{_escaped(page.href)}" '
                f'media-type="application/xhtml+xml"{property_attr}/>'
            )
            spine_items.append(f'    <itemref idref="page-{index:04d}"/>')

        asset_items = [
            f'    <item id="{_escaped(asset.manifest_id)}" '
            f'href="{_escaped(asset.href)}" '
            f'media-type="{_escaped(asset.media_type)}"/>'
            for asset in self._assets_by_source.values()
        ]

        package = f"""<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="{OPF_NS}" version="3.0"
  unique-identifier="pub-id" xml:lang="{_escaped(self.languages[0])}">
  <metadata xmlns:dc="{DC_NS}">
    <dc:identifier id="pub-id">{_escaped(self.identifier)}</dc:identifier>
    <dc:title>{_escaped(self.title)}</dc:title>
    <dc:creator>{_escaped(self.author)}</dc:creator>
{language_xml}
    <dc:source>{_escaped(self.site_url)}</dc:source>
    <meta property="dcterms:modified">{_escaped(modified)}</meta>
  </metadata>
  <manifest>
    <item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>
    <item id="css" href="styles/epub.css" media-type="text/css"/>
{chr(10).join(page_items)}
{chr(10).join(asset_items)}
  </manifest>
  <spine>
{chr(10).join(spine_items)}
  </spine>
</package>
"""
        return package.encode("utf-8")

    def _optimized_asset_payload(self, asset: EpubAsset) -> bytes | None:
        """Return optimized image bytes, or None when the source should be copied."""

        source_suffix = asset.source_file.suffix.lower()
        is_gif_poster = source_suffix == ".gif" and self.gif_mode == "poster"
        is_avif_conversion = source_suffix == ".avif"
        is_png_to_jpeg = (
            source_suffix == ".png" and asset.media_type == "image/jpeg"
        )
        if (
            source_suffix not in {".jpg", ".jpeg", ".png"}
            and not is_gif_poster
            and not is_avif_conversion
        ):
            return None
        if (
            self.image_max_px is None
            and self.jpeg_quality is None
            and not is_gif_poster
            and not is_png_to_jpeg
            and not is_avif_conversion
        ):
            return None

        from PIL import Image, ImageOps

        try:
            with Image.open(asset.source_file) as source_image:
                source_image.load()
                image = (
                    source_image.convert("RGBA")
                    if is_gif_poster
                    else ImageOps.exif_transpose(source_image)
                )
                resized = False
                if (
                    self.image_max_px is not None
                    and max(image.size) > self.image_max_px
                ):
                    image.thumbnail(
                        (self.image_max_px, self.image_max_px),
                        Image.Resampling.LANCZOS,
                    )
                    resized = True

                if asset.media_type == "image/png":
                    if not resized and not is_gif_poster and not is_avif_conversion:
                        return None
                    buffer = io.BytesIO()
                    image.save(
                        buffer,
                        format="PNG",
                        optimize=True,
                        compress_level=9,
                    )
                else:
                    if (
                        self.jpeg_quality is None
                        and not resized
                        and not is_png_to_jpeg
                        and not is_avif_conversion
                    ):
                        return None
                    if image.mode not in {"RGB", "L"}:
                        if "A" in image.getbands():
                            rgba = image.convert("RGBA")
                            background = Image.new("RGB", rgba.size, "white")
                            background.paste(rgba, mask=rgba.getchannel("A"))
                            image = background
                        else:
                            image = image.convert("RGB")

                    buffer = io.BytesIO()
                    save_options: dict[str, Any] = {
                        "format": "JPEG",
                        "quality": self.jpeg_quality or 90,
                        "optimize": True,
                        "progressive": True,
                    }
                    icc_profile = source_image.info.get("icc_profile")
                    if icc_profile:
                        save_options["icc_profile"] = icc_profile
                    image.save(buffer, **save_options)
        except (OSError, ValueError) as exc:
            raise SystemExit(
                f"Could not optimize EPUB image {asset.source_file}: {exc}"
            ) from exc

        payload = buffer.getvalue()
        if (
            not resized
            and not is_gif_poster
            and not is_png_to_jpeg
            and not is_avif_conversion
            and len(payload) >= asset.source_file.stat().st_size
        ):
            return None
        return payload

    def build(self, output_path: Path) -> EpubBuildResult:
        output_path = output_path.resolve()
        if output_path.suffix.lower() != ".epub":
            raise SystemExit("EPUB output path must end with .epub")

        converted_pages = [
            (page, self._convert_page(page))
            for page in self.pages
        ]
        nav_payload = self._nav_xhtml()
        package_payload = self._package_opf(converted_pages, utc_modified())

        output_path.parent.mkdir(parents=True, exist_ok=True)
        building_path = output_path.with_name(output_path.name + ".building")
        building_path.unlink(missing_ok=True)
        source_asset_bytes = sum(
            asset.source_file.stat().st_size
            for asset in self._assets_by_source.values()
        )
        packaged_asset_bytes = 0
        optimized_asset_count = 0
        jpeg_quality_used: int | None = None
        packaged_assets: list[EpubPackagedAsset] = []

        try:
            with zipfile.ZipFile(
                building_path,
                "w",
                compression=zipfile.ZIP_DEFLATED,
                compresslevel=9,
            ) as archive:
                mimetype_info = zipfile.ZipInfo("mimetype")
                mimetype_info.compress_type = zipfile.ZIP_STORED
                archive.writestr(mimetype_info, EPUB_MIMETYPE)
                archive.writestr(CONTAINER_PATH, CONTAINER_XML.encode("utf-8"))
                archive.writestr(PACKAGE_PATH, package_payload)
                archive.writestr("EPUB/nav.xhtml", nav_payload)
                archive.writestr("EPUB/styles/epub.css", EPUB_CSS.encode("utf-8"))
                for page, payload in converted_pages:
                    archive.writestr(f"EPUB/{page.href}", payload)
                for asset in self._assets_by_source.values():
                    optimized = self._optimized_asset_payload(asset)
                    source_bytes = asset.source_file.stat().st_size
                    source_sha256 = sha256_file(asset.source_file)
                    if optimized is None:
                        archive.write(
                            asset.source_file,
                            f"EPUB/{asset.href}",
                            compress_type=zipfile.ZIP_DEFLATED,
                            compresslevel=9,
                        )
                        packaged_bytes = source_bytes
                        packaged_sha256 = source_sha256
                    else:
                        archive.writestr(f"EPUB/{asset.href}", optimized)
                        packaged_bytes = len(optimized)
                        packaged_sha256 = hashlib.sha256(optimized).hexdigest()
                        if asset.media_type == "image/jpeg":
                            jpeg_quality_used = self.jpeg_quality or 90
                        optimized_asset_count += 1
                    packaged_asset_bytes += packaged_bytes
                    packaged_assets.append(
                        EpubPackagedAsset(
                            source_file=asset.source_file,
                            href=asset.href,
                            media_type=asset.media_type,
                            manifest_id=asset.manifest_id,
                            source_bytes=source_bytes,
                            source_sha256=source_sha256,
                            packaged_bytes=packaged_bytes,
                            packaged_sha256=packaged_sha256,
                            optimized=optimized is not None,
                        )
                    )

            validation = validate_epub(building_path)
            os.replace(building_path, output_path)
        finally:
            building_path.unlink(missing_ok=True)

        return EpubBuildResult(
            output_path=output_path,
            page_count=len(self.pages),
            asset_count=len(self._assets_by_source),
            interactive_fallback_count=self._interactive_fallback_count,
            remote_image_fallback_count=self._remote_image_fallback_count,
            entry_count=validation["entry_count"],
            optimized_asset_count=optimized_asset_count,
            source_asset_bytes=source_asset_bytes,
            packaged_asset_bytes=packaged_asset_bytes,
            jpeg_quality_used=jpeg_quality_used,
            empty_image_placeholder_count=self._empty_image_placeholder_count,
            assets=tuple(packaged_assets),
        )


def validate_epub(epub_path: Path) -> dict[str, int]:
    """Perform strict structural checks without requiring Java/EPUBCheck."""

    try:
        archive = zipfile.ZipFile(epub_path)
    except (OSError, zipfile.BadZipFile) as exc:
        raise SystemExit(f"Invalid EPUB ZIP container: {epub_path}: {exc}") from exc

    with archive:
        infos = archive.infolist()
        names = archive.namelist()
        name_set = set(names)
        if not infos:
            raise SystemExit(f"EPUB is empty: {epub_path}")
        if len(names) != len(name_set):
            raise SystemExit(f"EPUB contains duplicate ZIP entry names: {epub_path}")
        if infos[0].filename != "mimetype":
            raise SystemExit("EPUB mimetype must be the first ZIP entry.")
        if infos[0].compress_type != zipfile.ZIP_STORED:
            raise SystemExit("EPUB mimetype entry must be stored without compression.")
        if archive.read("mimetype") != EPUB_MIMETYPE:
            raise SystemExit("EPUB mimetype entry has the wrong payload.")
        if CONTAINER_PATH not in name_set:
            raise SystemExit("EPUB is missing META-INF/container.xml.")

        try:
            container_root = ET.fromstring(archive.read(CONTAINER_PATH))
        except ET.ParseError as exc:
            raise SystemExit(f"Invalid EPUB container.xml: {exc}") from exc

        rootfiles = container_root.findall(
            f".//{{{CONTAINER_NS}}}rootfile"
        )
        if len(rootfiles) != 1:
            raise SystemExit("EPUB container.xml must declare exactly one rootfile.")
        package_path = rootfiles[0].get("full-path", "")
        if package_path not in name_set:
            raise SystemExit(
                f"EPUB package document is missing: {package_path or '(empty)'}"
            )

        try:
            package_root = ET.fromstring(archive.read(package_path))
        except ET.ParseError as exc:
            raise SystemExit(f"Invalid EPUB package document: {exc}") from exc

        ns = {"opf": OPF_NS, "dc": DC_NS}
        required_metadata = {
            "identifier": package_root.find(".//dc:identifier", ns),
            "title": package_root.find(".//dc:title", ns),
            "language": package_root.find(".//dc:language", ns),
        }
        for label, node in required_metadata.items():
            if node is None or not (node.text or "").strip():
                raise SystemExit(f"EPUB package metadata is missing dc:{label}.")
        modified_nodes = [
            node
            for node in package_root.findall(".//opf:meta", ns)
            if node.get("property") == "dcterms:modified"
        ]
        if len(modified_nodes) != 1 or not (modified_nodes[0].text or "").strip():
            raise SystemExit(
                "EPUB package metadata must contain one dcterms:modified value."
            )

        manifest_items = package_root.findall(".//opf:manifest/opf:item", ns)
        manifest_by_id: dict[str, ET.Element] = {}
        manifest_targets: dict[str, ET.Element] = {}
        nav_items: list[ET.Element] = []
        package_dir = posixpath.dirname(package_path)

        for item in manifest_items:
            item_id = item.get("id", "")
            href = item.get("href", "")
            if not item_id or item_id in manifest_by_id:
                raise SystemExit("EPUB manifest contains a missing or duplicate id.")
            if not href or not _safe_zip_href(href):
                raise SystemExit(f"Unsafe EPUB manifest href: {href!r}")
            target = posixpath.normpath(
                posixpath.join(package_dir, unquote(urlsplit(href).path))
            )
            if target in manifest_targets:
                raise SystemExit(f"Duplicate EPUB manifest target: {target}")
            if target not in name_set:
                raise SystemExit(f"EPUB manifest target is missing: {target}")
            manifest_by_id[item_id] = item
            manifest_targets[target] = item
            if "nav" in item.get("properties", "").split():
                nav_items.append(item)

            if target.startswith(package_dir + "/assets/"):
                suffix = PurePosixPath(target).suffix.lower()
                expected_media_type = CORE_IMAGE_MEDIA_TYPES.get(suffix)
                declared_media_type = item.get("media-type", "")
                if expected_media_type != declared_media_type:
                    raise SystemExit(
                        f"EPUB asset media type mismatch for {target}: "
                        f"{declared_media_type!r}, expected {expected_media_type!r}"
                    )
                payload_start = archive.read(target)[:16]
                signature_ok = {
                    ".gif": payload_start.startswith((b"GIF87a", b"GIF89a")),
                    ".jpeg": payload_start.startswith(b"\xff\xd8\xff"),
                    ".jpg": payload_start.startswith(b"\xff\xd8\xff"),
                    ".png": payload_start.startswith(b"\x89PNG\r\n\x1a\n"),
                    ".svg": payload_start.lstrip().startswith(
                        (b"<?xml", b"<svg")
                    ),
                    ".webp": (
                        payload_start.startswith(b"RIFF")
                        and payload_start[8:12] == b"WEBP"
                    ),
                }.get(suffix, False)
                if not signature_ok:
                    raise SystemExit(
                        f"EPUB asset payload does not match its extension: {target}"
                    )

        if len(nav_items) != 1:
            raise SystemExit("EPUB manifest must contain exactly one nav item.")

        spine_items = package_root.findall(".//opf:spine/opf:itemref", ns)
        if not spine_items:
            raise SystemExit("EPUB spine is empty.")
        for itemref in spine_items:
            if itemref.get("idref", "") not in manifest_by_id:
                raise SystemExit(
                    f"EPUB spine references unknown id: {itemref.get('idref', '')}"
                )

        expected_manifest_entries = {
            name
            for name in name_set
            if name.startswith(package_dir + "/") and name != package_path
        }
        unmanifested = sorted(expected_manifest_entries - set(manifest_targets))
        if unmanifested:
            raise SystemExit(
                "EPUB contains unmanifested publication resources:\n  - "
                + "\n  - ".join(unmanifested)
            )

        xml_roots: dict[str, ET.Element] = {}
        for name in names:
            if name.endswith((".xml", ".opf", ".xhtml", ".svg")):
                try:
                    xml_roots[name] = ET.fromstring(archive.read(name))
                except ET.ParseError as exc:
                    raise SystemExit(f"Malformed XML resource {name}: {exc}") from exc

        for name, root in xml_roots.items():
            if name.endswith(".xhtml") and root.tag != f"{{{XHTML_NS}}}html":
                raise SystemExit(f"XHTML resource has the wrong root namespace: {name}")
            if name.endswith(".xhtml"):
                has_mathml = any(
                    element.tag == f"{{{MATHML_NS}}}math"
                    for element in root.iter()
                )
                has_svg = any(
                    element.tag == f"{{{SVG_NS}}}svg"
                    for element in root.iter()
                )
                properties = manifest_targets[name].get("properties", "").split()
                if has_mathml != ("mathml" in properties):
                    raise SystemExit(
                        "EPUB XHTML MathML content/property mismatch: " + name
                    )
                if has_svg != ("svg" in properties):
                    raise SystemExit(
                        "EPUB XHTML SVG content/property mismatch: " + name
                    )

        ids_by_resource: dict[str, set[str]] = {}
        for name, root in xml_roots.items():
            ids: set[str] = set()
            for element in root.iter():
                for attr_name in ("id", f"{{{XML_NS}}}id"):
                    value = element.get(attr_name)
                    if value:
                        if value in ids:
                            raise SystemExit(
                                f"Duplicate XML id {value!r} in {name}"
                            )
                        ids.add(value)
            ids_by_resource[name] = ids

        for name, root in xml_roots.items():
            if not name.endswith(".xhtml"):
                continue
            for element in root.iter():
                for attr_name in ("href", "src"):
                    raw = element.get(attr_name)
                    if not raw:
                        continue
                    parsed = urlsplit(raw)
                    if parsed.scheme or parsed.netloc:
                        continue
                    if parsed.path.startswith("/"):
                        raise SystemExit(
                            f"Root-relative packaged reference in {name}: {raw}"
                        )
                    target = (
                        name
                        if not parsed.path
                        else posixpath.normpath(
                            posixpath.join(
                                posixpath.dirname(name),
                                unquote(parsed.path),
                            )
                        )
                    )
                    if target not in name_set:
                        raise SystemExit(
                            f"Broken packaged reference in {name}: {raw}"
                        )
                    if parsed.fragment and target in ids_by_resource:
                        if unquote(parsed.fragment) not in ids_by_resource[target]:
                            raise SystemExit(
                                f"Broken fragment reference in {name}: {raw}"
                            )

        xhtml_count = sum(name.endswith(".xhtml") for name in names)
        asset_count = sum(name.startswith("EPUB/assets/") for name in names)
        return {
            "entry_count": len(names),
            "xhtml_count": xhtml_count,
            "asset_count": asset_count,
        }
