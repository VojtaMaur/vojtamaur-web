#!/usr/bin/env python3
"""
Export built Astro article pages to PDF.

Intended workflow:
  1. Build the site first, for example: npm run build:web:strict
  2. Run this script manually: python scripts/export-site-pdf.py

The script reads article metadata from src/content/posts/*.mdx, but renders PDF
from the finished static output in dist/. This matters because the English pages
are generated after Astro build by the EN postprocess.

Before Ghostscript compression, rendered iframes are replaced with linked PNG
snapshots. This avoids pdfwrite rendering corruption while keeping access to
the original embedded video, scan, map, PDF, or interactive content.

Before every PDF render, local preview links are rewritten to their public site
URLs. Article images and other directly rendered media are linked to their
public source when the page did not already provide a link.
"""

from __future__ import annotations

import argparse
import base64
import contextlib
import dataclasses
import datetime as dt
import hashlib
import html
import http.server
import json
import os
import re
import shutil
import socketserver
import subprocess
import sys
import tempfile
import threading
import time
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterable
from urllib.parse import quote, urljoin, urlsplit, urlunsplit
from urllib.request import urlopen


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

TRANSLATION_LABELS = {
    "source": "Czech source",
    "translated": "Translated",
    "incomplete": "Incomplete / Czech fallback",
}

SECTION_ORDER = ["volna-tvorba", "vystavy", "cestovani"]
VALID_LANGS = {"cs", "en"}
DEFAULT_SITE_URL = "https://vojtamaur.cz"
SCRIPT_VERSION = "3.2.1-public-media-links"


@dataclasses.dataclass(frozen=True)
class Post:
    title: str
    slug: str
    section: str
    date: str
    source_file: Path
    draft: bool


@dataclasses.dataclass(frozen=True)
class PdfJob:
    post: Post
    lang: str
    html_file: Path
    url_path: str
    display_title: str
    translation_status: str

    @property
    def section_label(self) -> str:
        return SECTION_LABELS.get(self.lang, {}).get(self.post.section, self.post.section)

    @property
    def translation_label(self) -> str:
        return TRANSLATION_LABELS.get(self.translation_status, self.translation_status)

    @property
    def label(self) -> str:
        status = "" if self.lang == "cs" or self.translation_status == "translated" else " · EN incomplete"
        return f"{self.lang.upper()} · {self.section_label} · {self.display_title}{status}"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export built vojtamaur-web article pages from dist/ to PDF."
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {SCRIPT_VERSION}",
    )
    parser.add_argument(
        "--project-root",
        default=".",
        help="Project root containing src/content/posts and dist. Default: current directory.",
    )
    parser.add_argument(
        "--dist",
        default="dist",
        help="Built site directory, relative to project root unless absolute. Default: dist",
    )
    parser.add_argument(
        "--posts-dir",
        default="src/content/posts",
        help="Posts content directory, relative to project root unless absolute. Default: src/content/posts",
    )
    parser.add_argument(
        "--site-url",
        default=DEFAULT_SITE_URL,
        help=(
            "Public site root used for hyperlinks embedded in the PDF. "
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
        help="Output PDF path for combined mode. Default is generated automatically inside output-dir.",
    )
    parser.add_argument(
        "--lang",
        choices=["cs", "en", "both"],
        default="both",
        help="Language export. Default: both",
    )
    parser.add_argument(
        "--section",
        action="append",
        default=[],
        help=(
            "Section filter. Can be repeated or comma-separated. "
            "Examples: --section cestovani --section vystavy or --section cestovani,vystavy"
        ),
    )
    parser.add_argument(
        "--separate",
        action="store_true",
        help="Export each article/language page as a separate PDF instead of one combined PDF.",
    )
    parser.add_argument(
        "--include-drafts",
        action="store_true",
        help="Include posts with draft: true if matching built HTML exists.",
    )
    parser.add_argument(
        "--allow-missing",
        action="store_true",
        help="Skip missing built HTML files. By default, missing files fail the export.",
    )
    parser.add_argument(
        "--build-command",
        default=None,
        help='Optional command to run before export, for example: "npm run build:web:strict". Not used unless explicitly passed.',
    )
    parser.add_argument(
        "--paper",
        default="A4",
        help="Paper format passed to Chromium. Default: A4",
    )
    parser.add_argument(
        "--margin",
        default="12mm",
        help="PDF margin applied on all sides. Default: 12mm",
    )
    parser.add_argument(
        "--media",
        choices=["screen", "print"],
        default="screen",
        help="CSS media emulation. Default: screen, because this is a visual web archive export.",
    )
    parser.add_argument(
        "--timeout-ms",
        type=int,
        default=45000,
        help="Page load timeout in milliseconds. Default: 45000",
    )
    parser.add_argument(
        "--wait-ms",
        type=int,
        default=500,
        help="Extra wait after scrolling each page, useful for lazy images. Default: 500",
    )
    parser.add_argument(
        "--no-cover",
        action="store_true",
        help="Do not add the generated cover/index pages to the combined PDF.",
    )
    parser.add_argument(
        "--no-manifest",
        action="store_true",
        help="Do not write pdf-export-manifest.json.",
    )
    parser.add_argument(
        "--title",
        default="vojtamaur-web PDF export",
        help="Title used on the cover page and PDF metadata.",
    )
    parser.add_argument(
        "--pdf-quality",
        choices=["archive", "printer", "ebook", "screen"],
        default="archive",
        help=(
            "Optional Ghostscript post-processing preset. "
            "Compressed modes replace iframes with linked PNG snapshots before processing. "
            "archive keeps the original Chromium PDF unchanged. Default: archive"
        ),
    )
    parser.add_argument(
        "--image-dpi",
        type=int,
        default=None,
        help=(
            "Override image downsampling resolution used during Ghostscript compression. "
            "Ignored with --pdf-quality archive."
        ),
    )
    parser.add_argument(
        "--jpeg-quality",
        type=int,
        default=None,
        help=(
            "Override JPEG quality from 1 to 100 during Ghostscript compression. "
            "Ignored with --pdf-quality archive."
        ),
    )
    parser.add_argument(
        "--ghostscript",
        default=None,
        help="Optional path to Ghostscript executable. Usually detected automatically.",
    )
    parser.add_argument(
        "--keep-uncompressed",
        action="store_true",
        help="When compression is enabled, also keep the original uncompressed PDF.",
    )
    return parser.parse_args()


def resolve_path(project_root: Path, value: str) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return project_root / path


def normalize_site_url(value: str) -> str:
    value = value.strip()
    parsed = urlsplit(value)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        raise SystemExit(
            "--site-url must be an absolute HTTP(S) site root, "
            "for example https://vojtamaur.cz"
        )
    if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        raise SystemExit(
            "--site-url must contain only the scheme and host, without a path, "
            "query, or fragment."
        )
    return urlunsplit((parsed.scheme.lower(), parsed.netloc, "/", "", ""))


def make_public_page_url(site_url: str, url_path: str) -> str:
    return urljoin(site_url, url_path.lstrip("/"))


def split_csv(values: Iterable[str]) -> list[str]:
    items: list[str] = []
    for value in values:
        for item in value.split(","):
            item = item.strip()
            if item:
                items.append(item)
    return items


def strip_quotes(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    return value


def parse_frontmatter(text: str, path: Path) -> dict[str, str]:
    if not text.startswith("---"):
        return {}

    match = re.match(r"^---\s*\r?\n(.*?)\r?\n---\s*\r?\n", text, re.DOTALL)
    if not match:
        raise ValueError(f"Invalid frontmatter block in {path}")

    data: dict[str, str] = {}
    for raw_line in match.group(1).splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, value = line.split(":", 1)
        data[key.strip()] = strip_quotes(value.strip())
    return data


def truthy(value: str | None) -> bool:
    if value is None:
        return False
    return value.strip().lower() in {"true", "1", "yes", "y"}


def read_posts(posts_dir: Path, include_drafts: bool) -> list[Post]:
    if not posts_dir.exists():
        raise SystemExit(f"Posts directory not found: {posts_dir}")

    posts: list[Post] = []
    for path in sorted(posts_dir.glob("*.mdx")):
        text = path.read_text(encoding="utf-8-sig", errors="replace")
        data = parse_frontmatter(text, path)

        slug = data.get("slug")
        section = data.get("section")
        title = data.get("title")
        date = data.get("date", "")
        draft = truthy(data.get("draft"))

        if not slug or not section or not title:
            print(f"[warn] Skipping {path}: missing title, slug, or section", file=sys.stderr)
            continue
        if draft and not include_drafts:
            continue

        posts.append(
            Post(
                title=title,
                slug=slug.strip("/"),
                section=section,
                date=date,
                source_file=path,
                draft=draft,
            )
        )
    return posts


def date_key(value: str) -> tuple[int, int, int]:
    value = value.strip().strip('"')
    try:
        parsed = dt.date.fromisoformat(value[:10])
        return (parsed.year, parsed.month, parsed.day)
    except ValueError:
        return (0, 0, 0)


def section_index(section: str) -> int:
    try:
        return SECTION_ORDER.index(section)
    except ValueError:
        return len(SECTION_ORDER)


def sorted_posts(posts: list[Post]) -> list[Post]:
    return sorted(
        posts,
        key=lambda post: (
            section_index(post.section),
            tuple(-part for part in date_key(post.date)),
            post.title.lower(),
        ),
    )


def languages_from_arg(value: str) -> list[str]:
    if value == "both":
        return ["cs", "en"]
    return [value]


def find_built_html(dist_dir: Path, slug: str, lang: str) -> Path | None:
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

    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def url_path_from_html_file(dist_dir: Path, html_file: Path) -> str:
    rel = html_file.relative_to(dist_dir).as_posix()
    if rel.endswith("/index.html"):
        return "/" + rel[: -len("index.html")]
    return "/" + rel


class BuiltPageMetadataParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._in_title = False
        self._in_h1 = False
        self._title_done = False
        self._h1_done = False
        self.title_parts: list[str] = []
        self.h1_parts: list[str] = []
        self.robots_values: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        attrs_map = {key.lower(): (value or "") for key, value in attrs}

        if tag == "title" and not self._title_done:
            self._in_title = True
        elif tag == "h1" and not self._h1_done:
            self._in_h1 = True
        elif tag == "meta" and attrs_map.get("name", "").lower() == "robots":
            self.robots_values.append(attrs_map.get("content", ""))

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag == "title" and self._in_title:
            self._in_title = False
            self._title_done = True
        elif tag == "h1" and self._in_h1:
            self._in_h1 = False
            self._h1_done = True

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title_parts.append(data)
        if self._in_h1:
            self.h1_parts.append(data)


def normalize_html_text(parts: list[str]) -> str:
    return re.sub(r"\s+", " ", " ".join(parts)).strip()


def strip_site_title_suffix(value: str) -> str:
    return re.sub(r"\s*\|\s*Vojta Maur\s*$", "", value, flags=re.IGNORECASE).strip()


def read_built_page_metadata(html_file: Path, lang: str, source_title: str) -> tuple[str, str]:
    source = html_file.read_text(encoding="utf-8-sig", errors="replace")
    parser = BuiltPageMetadataParser()
    try:
        parser.feed(source)
        parser.close()
    except Exception as exc:
        print(f"[warn] Could not fully parse metadata from {html_file}: {exc}", file=sys.stderr)

    h1 = normalize_html_text(parser.h1_parts)
    page_title = strip_site_title_suffix(normalize_html_text(parser.title_parts))
    display_title = h1 or page_title or source_title

    if lang == "cs":
        translation_status = "source"
    else:
        robots = ",".join(parser.robots_values).lower()
        translation_status = "incomplete" if "noindex" in robots else "translated"

    return display_title, translation_status


def make_jobs(
    posts: list[Post],
    dist_dir: Path,
    sections: list[str],
    langs: list[str],
    allow_missing: bool,
) -> list[PdfJob]:
    if sections:
        wanted = set(sections)
        posts = [post for post in posts if post.section in wanted]

    jobs: list[PdfJob] = []
    missing: list[str] = []

    for post in sorted_posts(posts):
        for lang in langs:
            html_file = find_built_html(dist_dir, post.slug, lang)
            if html_file is None:
                missing.append(f"{lang.upper()} {post.section}/{post.slug}")
                continue
            display_title, translation_status = read_built_page_metadata(
                html_file, lang, post.title
            )
            jobs.append(
                PdfJob(
                    post=post,
                    lang=lang,
                    html_file=html_file,
                    url_path=url_path_from_html_file(dist_dir, html_file),
                    display_title=display_title,
                    translation_status=translation_status,
                )
            )

    if missing and not allow_missing:
        formatted = "\n  - " + "\n  - ".join(missing[:50])
        extra = "" if len(missing) <= 50 else f"\n  ... and {len(missing) - 50} more"
        raise SystemExit(
            "Built HTML is missing for some requested pages. Run the correct build first "
            "or use --allow-missing if this is intentional. Missing:" + formatted + extra
        )

    return jobs


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        return


class ThreadingHTTPServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True


def start_server(root: Path) -> tuple[ThreadingHTTPServer, str]:
    handler = lambda *args, **kwargs: QuietHandler(*args, directory=str(root), **kwargs)
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    host, port = server.server_address
    base_url = f"http://{host}:{port}"

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    for _ in range(50):
        try:
            with urlopen(base_url + "/", timeout=0.5):
                return server, base_url
        except Exception:
            time.sleep(0.1)

    server.shutdown()
    raise SystemExit("Could not start local HTTP server for dist/.")


def ensure_deps() -> None:
    missing: list[str] = []
    try:
        import playwright.sync_api  # noqa: F401
    except ImportError:
        missing.append("playwright")
    try:
        import pypdf  # noqa: F401
    except ImportError:
        missing.append("pypdf")

    if missing:
        raise SystemExit(
            "Missing Python dependencies: "
            + ", ".join(missing)
            + "\nInstall them with:\n  pip install playwright pypdf\n  python -m playwright install chromium"
        )


def safe_filename(value: str) -> str:
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9_.-]+", "-", value, flags=re.IGNORECASE)
    value = re.sub(r"-+", "-", value).strip("-._")
    return value or "untitled"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def css_escape() -> str:
    return """
html {
  -webkit-print-color-adjust: exact !important;
  print-color-adjust: exact !important;
}
img, svg, video, canvas, iframe {
  max-width: 100% !important;
}
.pdf-iframe-snapshot-link {
  display: block !important;
  width: 100% !important;
  max-width: 100% !important;
  break-inside: avoid !important;
  page-break-inside: avoid !important;
  text-decoration: none !important;
}
.pdf-iframe-snapshot {
  display: block !important;
  width: 100% !important;
  height: 100% !important;
  max-width: 100% !important;
  object-fit: contain !important;
}
.pdf-public-media-link {
  color: inherit !important;
  max-width: 100% !important;
  text-decoration: none !important;
}
a[href]::after {
  content: "" !important;
}
""".strip()


def scroll_page(page, wait_ms: int) -> None:
    page.evaluate(
        """
        async () => {
          const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
          const step = Math.max(window.innerHeight, 600);
          const maxY = Math.max(document.body.scrollHeight, document.documentElement.scrollHeight);
          for (let y = 0; y < maxY; y += step) {
            window.scrollTo(0, y);
            await delay(80);
          }
          window.scrollTo(0, 0);
        }
        """
    )
    if wait_ms > 0:
        page.wait_for_timeout(wait_ms)


def iframe_link_url(src: str) -> str:
    if not re.match(r"^https?://", src, flags=re.IGNORECASE):
        return ""

    youtube_match = re.match(
        r"^https?://(?:www\.)?(?:youtube\.com|youtube-nocookie\.com)/embed/([^/?#]+)",
        src,
        flags=re.IGNORECASE,
    )
    if youtube_match:
        video_id = quote(youtube_match.group(1), safe="")
        return f"https://www.youtube.com/watch?v={video_id}"

    return src


def replace_iframes_with_linked_snapshots(
    page,
    public_page_url: str,
    public_site_url: str,
) -> int:
    iframe_locator = page.locator("iframe")
    total = iframe_locator.count()
    replaced = 0

    # Process from the end so replacing one iframe does not change the indexes
    # of the remaining locators.
    for index in range(total - 1, -1, -1):
        iframe = page.locator("iframe").nth(index)
        try:
            metadata = iframe.evaluate(
                """
                (element, payload) => {
                  const rect = element.getBoundingClientRect();
                  const rawSrc = element.getAttribute("src") || "";
                  const localUrl = new URL(window.location.href);
                  const explicitScheme = /^[a-z][a-z0-9+.-]*:/i;
                  const normalizeHost = (hostname) => hostname.replace("[", "").replace("]", "").toLowerCase();
                  const isUInt8 = (part) => (
                    part.length > 0
                    && [...part].every((char) => char >= "0" && char <= "9")
                    && Number(part) <= 255
                  );
                  const isIPv4Loopback = (host) => {
                    const parts = host.split(".");
                    return parts.length === 4
                      && parts[0] === "127"
                      && parts.slice(1).every(isUInt8);
                  };
                  const isLoopbackHost = (hostname) => {
                    const host = normalizeHost(hostname);
                    return host === "localhost"
                      || host === "::1"
                      || isIPv4Loopback(host);
                  };
                  const isLocalPreviewUrl = (url) => (
                    url.origin === localUrl.origin
                    || (
                      isLoopbackHost(url.hostname)
                      && isLoopbackHost(localUrl.hostname)
                      && url.port === localUrl.port
                    )
                  );
                  let publicSrc = "";
                  try {
                    if (!explicitScheme.test(rawSrc) && !rawSrc.startsWith("//")) {
                      publicSrc = new URL(rawSrc, payload.publicPageUrl).href;
                    } else {
                      const resolved = new URL(rawSrc, window.location.href);
                      publicSrc = isLocalPreviewUrl(resolved)
                        ? new URL(
                            `${resolved.pathname}${resolved.search}${resolved.hash}`,
                            payload.publicSiteUrl
                          ).href
                        : resolved.href;
                    }
                  } catch (_) {
                    publicSrc = rawSrc;
                  }
                  return {
                    src: publicSrc,
                    title: element.getAttribute("title") || "Embedded content",
                    width: rect.width,
                    height: rect.height
                  };
                }
                """,
                {
                    "publicPageUrl": public_page_url,
                    "publicSiteUrl": public_site_url,
                },
            )
            if metadata["width"] <= 0 or metadata["height"] <= 0:
                raise RuntimeError("iframe has no visible area")

            screenshot = iframe.screenshot(type="png", animations="disabled")
            image_data_url = "data:image/png;base64," + base64.b64encode(screenshot).decode("ascii")
            link_url = iframe_link_url(str(metadata.get("src", "")))

            iframe.evaluate(
                """
                (element, payload) => {
                  const image = document.createElement("img");
                  image.className = "pdf-iframe-snapshot";
                  image.src = payload.imageDataUrl;
                  image.alt = payload.alt;

                  const replacement = payload.linkUrl
                    ? document.createElement("a")
                    : document.createElement("span");
                  replacement.className = "pdf-iframe-snapshot-link";
                  replacement.style.aspectRatio = `${payload.width} / ${payload.height}`;

                  if (payload.linkUrl) {
                    replacement.href = payload.linkUrl;
                    replacement.target = "_blank";
                    replacement.rel = "noopener noreferrer";
                    replacement.title = `Open original embedded content: ${payload.linkUrl}`;
                  }

                  replacement.appendChild(image);
                  element.replaceWith(replacement);
                }
                """,
                {
                    "imageDataUrl": image_data_url,
                    "linkUrl": link_url,
                    "alt": str(metadata.get("title", "Embedded content")),
                    "width": metadata["width"],
                    "height": metadata["height"],
                },
            )
            replaced += 1
        except Exception as exc:
            print(
                f"[warn] Could not replace iframe {index + 1}/{total} with a snapshot: {exc}",
                file=sys.stderr,
            )

    if total:
        print(f"[snapshot] Replaced {replaced}/{total} iframe(s) with linked images.")
    page.evaluate("window.scrollTo(0, 0)")
    return replaced


def prepare_public_pdf_links(
    page,
    public_page_url: str,
    public_site_url: str,
) -> tuple[int, int]:
    result = page.evaluate(
        r"""
        (payload) => {
          const publicPageUrl = new URL(payload.publicPageUrl);
          const publicSiteUrl = new URL(payload.publicSiteUrl);
          const localUrl = new URL(window.location.href);
          const explicitScheme = /^[a-z][a-z0-9+.-]*:/i;
          const ignoredScheme = /^(?:mailto|tel|sms|javascript|data|blob|about):/i;
          const normalizeHost = (hostname) => hostname.replace("[", "").replace("]", "").toLowerCase();
          const isUInt8 = (part) => (
            part.length > 0
            && [...part].every((char) => char >= "0" && char <= "9")
            && Number(part) <= 255
          );
          const isIPv4Loopback = (host) => {
            const parts = host.split(".");
            return parts.length === 4
              && parts[0] === "127"
              && parts.slice(1).every(isUInt8);
          };
          const isLoopbackHost = (hostname) => {
            const host = normalizeHost(hostname);
            return host === "localhost"
              || host === "::1"
              || isIPv4Loopback(host);
          };
          const isLocalPreviewUrl = (url) => (
            url.origin === localUrl.origin
            || (
              isLoopbackHost(url.hostname)
              && isLoopbackHost(localUrl.hostname)
              && url.port === localUrl.port
            )
          );

          const firstSrcsetUrl = (value) => {
            const raw = String(value || "").trim();
            if (!raw) {
              return "";
            }
            const firstCandidate = raw.split(",")[0]?.trim() || "";
            return firstCandidate.split(/\s+/)[0] || "";
          };

          const rawImageSource = (image) => (
            image.getAttribute("src")
            || firstSrcsetUrl(image.getAttribute("srcset"))
            || firstSrcsetUrl(
              image.parentElement?.querySelector("source[srcset]")?.getAttribute("srcset")
            )
            || image.parentElement?.querySelector("source[src]")?.getAttribute("src")
            || image.getAttribute("data-src")
            || image.getAttribute("data-original")
            || image.currentSrc
            || ""
          );

          const rawMediaSource = (media) => (
            media.getAttribute("src")
            || media.getAttribute("data")
            || media.querySelector("source[src]")?.getAttribute("src")
            || firstSrcsetUrl(media.querySelector("source[srcset]")?.getAttribute("srcset"))
            || media.getAttribute("data-src")
            || media.currentSrc
            || ""
          );

          const toPublicUrl = (rawValue) => {
            const raw = String(rawValue || "").trim();
            if (!raw || raw.startsWith("#") || ignoredScheme.test(raw)) {
              return raw;
            }

            try {
              if (!explicitScheme.test(raw) && !raw.startsWith("//")) {
                return new URL(raw, publicPageUrl).href;
              }

              const resolved = new URL(raw, window.location.href);
              if (!/^https?:$/.test(resolved.protocol)) {
                return raw;
              }
              if (isLocalPreviewUrl(resolved)) {
                return new URL(
                  `${resolved.pathname}${resolved.search}${resolved.hash}`,
                  publicSiteUrl
                ).href;
              }
              return resolved.href;
            } catch (_) {
              return raw;
            }
          };

          let rewrittenLinks = 0;
          for (const link of document.querySelectorAll("a[href], area[href]")) {
            const rawHref = link.getAttribute("href") || "";
            const publicHref = toPublicUrl(rawHref);
            if (publicHref && publicHref !== rawHref) {
              link.setAttribute("href", publicHref);
              rewrittenLinks += 1;
            }
          }

          let linkedMedia = 0;
          const seen = new Set();
          const addMediaLink = (media, rawSource) => {
            if (!media || seen.has(media)) {
              return;
            }
            seen.add(media);

            if (media.classList?.contains("pdf-iframe-snapshot")) {
              return;
            }

            const targetNode = media.tagName === "IMG" && media.parentElement?.tagName === "PICTURE"
              ? media.parentElement
              : media;
            if (
              targetNode.closest("a[href]")
              || targetNode.closest("button, input, select, textarea, summary")
              || !targetNode.parentNode
            ) {
              return;
            }

            const publicSource = toPublicUrl(rawSource);
            if (!/^https?:\/\//i.test(publicSource)) {
              return;
            }

            const link = document.createElement("a");
            link.className = "pdf-public-media-link";
            link.href = publicSource;
            link.target = "_blank";
            link.rel = "noopener noreferrer";
            link.title = `Open original media: ${publicSource}`;

            const display = window.getComputedStyle(targetNode).display;
            link.style.display = ["block", "flex", "grid"].includes(display)
              ? "block"
              : "inline-block";

            targetNode.parentNode.insertBefore(link, targetNode);
            link.appendChild(targetNode);
            linkedMedia += 1;
          };

          for (const image of document.querySelectorAll("main img, article img")) {
            addMediaLink(image, rawImageSource(image));
          }

          for (const media of document.querySelectorAll(
            "main video, article video, main audio, article audio, "
            + "main object[data], article object[data], main embed[src], article embed[src]"
          )) {
            addMediaLink(media, rawMediaSource(media));
          }

          return { rewrittenLinks, linkedMedia };
        }
        """,
        {
            "publicPageUrl": public_page_url,
            "publicSiteUrl": public_site_url,
        },
    )
    rewritten = int(result.get("rewrittenLinks", 0))
    linked_media = int(result.get("linkedMedia", 0))
    if rewritten or linked_media:
        print(
            f"[links] Rewrote {rewritten} link(s); "
            f"linked {linked_media} unlinked media item(s)."
        )
    return rewritten, linked_media


def render_url_to_pdf(
    browser,
    url: str,
    public_page_url: str,
    output_path: Path,
    args: argparse.Namespace,
) -> None:
    page = browser.new_page()
    try:
        page.set_default_timeout(args.timeout_ms)
        page.emulate_media(media=args.media)
        page.goto(url, wait_until="domcontentloaded", timeout=args.timeout_ms)
        with contextlib.suppress(Exception):
            page.wait_for_load_state("networkidle", timeout=min(args.timeout_ms, 8000))
        page.add_style_tag(content=css_escape())
        scroll_page(page, args.wait_ms)
        if args.pdf_quality != "archive":
            replace_iframes_with_linked_snapshots(
                page,
                public_page_url,
                args.site_url,
            )
        prepare_public_pdf_links(page, public_page_url, args.site_url)
        page.pdf(
            path=str(output_path),
            format=args.paper,
            print_background=True,
            margin={
                "top": args.margin,
                "right": args.margin,
                "bottom": args.margin,
                "left": args.margin,
            },
            prefer_css_page_size=False,
        )
    finally:
        page.close()


def render_html_to_pdf(browser, html_content: str, output_path: Path, args: argparse.Namespace) -> None:
    page = browser.new_page()
    try:
        page.emulate_media(media="screen")
        page.set_content(html_content, wait_until="domcontentloaded")
        page.pdf(
            path=str(output_path),
            format=args.paper,
            print_background=True,
            margin={
                "top": args.margin,
                "right": args.margin,
                "bottom": args.margin,
                "left": args.margin,
            },
        )
    finally:
        page.close()


def cover_html(jobs: list[PdfJob], args: argparse.Namespace, dist_dir: Path) -> str:
    now = dt.datetime.now().astimezone().isoformat(timespec="seconds")
    rows = []
    for index, job in enumerate(jobs, start=1):
        public_url = make_public_page_url(args.site_url, job.url_path)
        rows.append(
            "<tr>"
            f"<td>{index}</td>"
            f"<td>{html.escape(job.lang.upper())}</td>"
            f"<td>{html.escape(job.section_label)}</td>"
            f"<td>{html.escape(job.post.date)}</td>"
            f"<td>{html.escape(job.translation_label)}</td>"
            f"<td>{html.escape(job.display_title)}</td>"
            f'<td><a href="{html.escape(public_url, quote=True)}"><code>{html.escape(job.url_path)}</code></a></td>'
            "</tr>"
        )

    return f"""<!doctype html>
<html lang="cs">
<head>
<meta charset="utf-8">
<title>{html.escape(args.title)}</title>
<style>
  body {{ font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; line-height: 1.45; }}
  h1 {{ font-size: 28px; margin-bottom: 0.2em; }}
  .meta {{ color: #555; margin-bottom: 2rem; }}
  table {{ width: 100%; border-collapse: collapse; table-layout: fixed; font-size: 8.5px; }}
  thead {{ display: table-header-group; }}
  tr {{ break-inside: avoid; page-break-inside: avoid; }}
  th, td {{ border-bottom: 1px solid #ddd; padding: 4px 5px; vertical-align: top; overflow-wrap: anywhere; }}
  th {{ text-align: left; background: #f2f2f2; }}
  code {{ font-family: ui-monospace, SFMono-Regular, Consolas, "Liberation Mono", monospace; font-size: 8px; white-space: normal; overflow-wrap: anywhere; }}
  .notice {{ padding: 0.7rem 0.9rem; border: 1px solid #bbb; background: #f7f7f7; }}
</style>
</head>
<body>
  <h1>{html.escape(args.title)}</h1>
  <div class="meta">
    <p><strong>Generated:</strong> {html.escape(now)}</p>
    <p><strong>Source build:</strong> <code>{html.escape(str(dist_dir))}</code></p>
    <p><strong>Mode:</strong> combined article PDF export from finished static HTML.</p>
    <p><strong>Pages included:</strong> {len(jobs)}</p>
    <p class="notice"><strong>Pagination limitations:</strong> This PDF is a paginated visual rendering of the finished HTML, not a lossless replacement for it. Wide tables, long source-code lines, and other horizontally overflowing elements can extend beyond the printable area, be clipped, wrap differently, or otherwise appear incomplete. Use the archived HTML, source files, repository, and text exports as the authoritative complete versions.</p>
    <p class="notice"><strong>English translation status:</strong> English routes are generated from the EN build. If translation data is incomplete, an <code>/en/</code> route may still contain partly or entirely Czech content. Those rows are marked <em>Incomplete / Czech fallback</em>. Titles below are read from the rendered page, so translated titles are used where available.</p>
  </div>
  <h2>Included article pages</h2>
  <table>
    <colgroup>
      <col style="width:4%"><col style="width:6%"><col style="width:12%"><col style="width:10%">
      <col style="width:16%"><col style="width:24%"><col style="width:28%">
    </colgroup>
    <thead>
      <tr><th>#</th><th>Lang</th><th>Section</th><th>Date</th><th>Translation</th><th>Title</th><th>Built route</th></tr>
    </thead>
    <tbody>
      {''.join(rows)}
    </tbody>
  </table>
</body>
</html>"""


def merge_pdfs(pdf_paths: list[tuple[Path, str]], output_path: Path, title: str) -> None:
    from pypdf import PdfReader, PdfWriter

    writer = PdfWriter()
    for pdf_path, bookmark_title in pdf_paths:
        reader = PdfReader(str(pdf_path))
        start_page = len(writer.pages)
        for page in reader.pages:
            writer.add_page(page)
        if reader.pages:
            with contextlib.suppress(Exception):
                writer.add_outline_item(bookmark_title, start_page)

    writer.add_metadata(
        {
            "/Title": title,
            "/Creator": "scripts/export-site-pdf.py",
            "/Producer": "Playwright Chromium + pypdf",
        }
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("wb") as handle:
        writer.write(handle)


QUALITY_DEFAULTS = {
    "printer": {"dpi": 300, "jpeg_quality": 90},
    "ebook": {"dpi": 150, "jpeg_quality": 75},
    "screen": {"dpi": 96, "jpeg_quality": 60},
}


def find_ghostscript(explicit: str | None) -> Path | None:
    if explicit:
        candidate = Path(explicit).expanduser()
        if candidate.exists():
            return candidate.resolve()
        resolved = shutil.which(explicit)
        return Path(resolved).resolve() if resolved else None

    for name in ("gswin64c", "gswin32c", "gs", "gs.exe"):
        resolved = shutil.which(name)
        if resolved:
            return Path(resolved).resolve()

    if os.name == "nt":
        roots = [
            Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "gs",
            Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "gs",
        ]
        candidates: list[Path] = []
        for root in roots:
            if root.exists():
                candidates.extend(root.glob("gs*/bin/gswin64c.exe"))
                candidates.extend(root.glob("gs*/bin/gswin32c.exe"))
        if candidates:
            return sorted(candidates, reverse=True)[0].resolve()

    return None


def compressed_copy_name(path: Path, suffix: str) -> Path:
    return path.with_name(f"{path.stem}{suffix}{path.suffix}")


def compress_pdf(
    source: Path,
    destination: Path,
    args: argparse.Namespace,
    ghostscript: Path,
) -> None:
    defaults = QUALITY_DEFAULTS[args.pdf_quality]
    dpi = args.image_dpi if args.image_dpi is not None else defaults["dpi"]
    jpeg_quality = (
        args.jpeg_quality if args.jpeg_quality is not None else defaults["jpeg_quality"]
    )

    if dpi < 36:
        raise SystemExit("--image-dpi must be at least 36.")
    if not 1 <= jpeg_quality <= 100:
        raise SystemExit("--jpeg-quality must be between 1 and 100.")

    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary_output = destination.with_name(destination.name + ".compressing.pdf")
    temporary_output.unlink(missing_ok=True)

    command = [
        str(ghostscript),
        "-sDEVICE=pdfwrite",
        "-dCompatibilityLevel=1.7",
        f"-dPDFSETTINGS=/{args.pdf_quality}",
        "-dNOPAUSE",
        "-dQUIET",
        "-dBATCH",
        "-dSAFER",
        "-dDetectDuplicateImages=true",
        "-dCompressFonts=true",
        "-dSubsetFonts=true",
        "-dDownsampleColorImages=true",
        "-dColorImageDownsampleType=/Bicubic",
        f"-dColorImageResolution={dpi}",
        "-dDownsampleGrayImages=true",
        "-dGrayImageDownsampleType=/Bicubic",
        f"-dGrayImageResolution={dpi}",
        "-dDownsampleMonoImages=true",
        "-dMonoImageDownsampleType=/Subsample",
        f"-dMonoImageResolution={max(dpi * 2, 300)}",
        "-dAutoFilterColorImages=false",
        "-dColorImageFilter=/DCTEncode",
        "-dAutoFilterGrayImages=false",
        "-dGrayImageFilter=/DCTEncode",
        f"-dJPEGQ={jpeg_quality}",
        f"-sOutputFile={temporary_output}",
        str(source),
    ]

    print(
        f"[compress] {args.pdf_quality}, {dpi} dpi, JPEG {jpeg_quality}: "
        f"{source.name}"
    )
    try:
        subprocess.run(command, check=True)
    except subprocess.CalledProcessError as exc:
        temporary_output.unlink(missing_ok=True)
        raise SystemExit(f"Ghostscript compression failed with exit code {exc.returncode}.") from exc

    if not temporary_output.exists() or temporary_output.stat().st_size == 0:
        temporary_output.unlink(missing_ok=True)
        raise SystemExit("Ghostscript did not produce a valid output PDF.")

    temporary_output.replace(destination)


def finalize_pdf(
    uncompressed: Path,
    destination: Path,
    args: argparse.Namespace,
    ghostscript: Path | None,
    outputs: list[Path],
) -> None:
    if args.pdf_quality == "archive":
        destination.parent.mkdir(parents=True, exist_ok=True)
        if uncompressed.resolve() != destination.resolve():
            shutil.copy2(uncompressed, destination)
        outputs.append(destination)
        return

    if ghostscript is None:
        raise SystemExit(
            "Ghostscript is required for --pdf-quality printer, ebook, or screen. "
            "Install Ghostscript or pass --ghostscript with the executable path."
        )

    if args.keep_uncompressed:
        uncompressed_output = compressed_copy_name(destination, "-uncompressed")
        shutil.copy2(uncompressed, uncompressed_output)
        outputs.append(uncompressed_output)

    compress_pdf(uncompressed, destination, args, ghostscript)
    outputs.append(destination)


def run_build(command: str | None, project_root: Path) -> None:
    if not command:
        return
    print(f"[build] {command}")
    subprocess.run(command, cwd=project_root, shell=True, check=True)


def write_manifest(
    manifest_path: Path,
    args: argparse.Namespace,
    jobs: list[PdfJob],
    outputs: list[Path],
    project_root: Path,
    dist_dir: Path,
) -> None:
    data = {
        "generated_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "title": args.title,
        "project_root": str(project_root),
        "dist_dir": str(dist_dir),
        "mode": "separate" if args.separate else "combined",
        "language": args.lang,
        "sections": split_csv(args.section),
        "pdf_quality": args.pdf_quality,
        "site_url": args.site_url,
        "image_dpi": args.image_dpi,
        "jpeg_quality": args.jpeg_quality,
        "keep_uncompressed": args.keep_uncompressed,
        "article_page_count": len(jobs),
        "outputs": [
            {
                "path": str(path),
                "sha256": sha256_file(path),
                "bytes": path.stat().st_size,
            }
            for path in outputs
            if path.exists()
        ],
        "pages": [
            {
                "lang": job.lang,
                "section": job.post.section,
                "section_label": job.section_label,
                "title": job.display_title,
                "source_title": job.post.title,
                "translation_status": job.translation_status,
                "translation_label": job.translation_label,
                "slug": job.post.slug,
                "date": job.post.date,
                "source_file": str(job.post.source_file),
                "built_html": str(job.html_file),
                "url_path": job.url_path,
                "public_url": make_public_page_url(args.site_url, job.url_path),
            }
            for job in jobs
        ],
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    args = parse_args()
    args.site_url = normalize_site_url(args.site_url)
    project_root = Path(args.project_root).resolve()
    dist_dir = resolve_path(project_root, args.dist).resolve()
    posts_dir = resolve_path(project_root, args.posts_dir).resolve()
    output_dir = resolve_path(project_root, args.output_dir).resolve()

    selected_sections = split_csv(args.section)
    unknown_sections = [section for section in selected_sections if section not in SECTION_LABELS["cs"]]
    if unknown_sections:
        raise SystemExit(
            "Unknown section(s): "
            + ", ".join(unknown_sections)
            + "\nValid sections: "
            + ", ".join(SECTION_LABELS["cs"])
        )

    run_build(args.build_command, project_root)

    if not dist_dir.exists():
        raise SystemExit(f"Built directory not found: {dist_dir}\nRun a build first, for example: npm run build:web:strict")

    ensure_deps()

    posts = read_posts(posts_dir, args.include_drafts)
    langs = languages_from_arg(args.lang)
    jobs = make_jobs(posts, dist_dir, selected_sections, langs, args.allow_missing)

    if not jobs:
        raise SystemExit("No matching article pages found. Filters are too strict or dist/ is incomplete.")

    if args.pdf_quality == "archive" and (
        args.image_dpi is not None or args.jpeg_quality is not None or args.keep_uncompressed
    ):
        print(
            "[warn] --image-dpi, --jpeg-quality, and --keep-uncompressed are ignored "
            "with --pdf-quality archive.",
            file=sys.stderr,
        )

    ghostscript = None
    if args.pdf_quality != "archive":
        ghostscript = find_ghostscript(args.ghostscript)
        if ghostscript is None:
            raise SystemExit(
                "Ghostscript was not found. Install it or pass its executable path, for example:\n"
                '  --ghostscript "C:\\Program Files\\gs\\gs10.xx.x\\bin\\gswin64c.exe"'
            )
        print(f"[ghostscript] {ghostscript}")

    output_dir.mkdir(parents=True, exist_ok=True)
    server, base_url = start_server(dist_dir)
    outputs: list[Path] = []

    print(f"[server] {base_url} -> {dist_dir}")
    print(f"[export] {len(jobs)} article page(s)")

    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            try:
                if args.separate:
                    with tempfile.TemporaryDirectory(prefix="pdf-export-pages-") as tmp:
                        tmp_dir = Path(tmp)
                        for index, job in enumerate(jobs, start=1):
                            section_dir = output_dir / job.lang / safe_filename(job.post.section)
                            section_dir.mkdir(parents=True, exist_ok=True)
                            out = section_dir / f"{safe_filename(job.post.slug)}.pdf"
                            url = base_url + quote(job.url_path, safe="/%")
                            public_url = make_public_page_url(args.site_url, job.url_path)
                            print(f"[{index}/{len(jobs)}] {job.label}")

                            if args.pdf_quality == "archive":
                                render_url_to_pdf(browser, url, public_url, out, args)
                                outputs.append(out)
                            else:
                                raw = tmp_dir / f"{index:04d}-{job.lang}-{safe_filename(job.post.slug)}.pdf"
                                render_url_to_pdf(browser, url, public_url, raw, args)
                                finalize_pdf(raw, out, args, ghostscript, outputs)
                else:
                    with tempfile.TemporaryDirectory(prefix="pdf-export-") as tmp:
                        tmp_dir = Path(tmp)
                        parts: list[tuple[Path, str]] = []

                        if not args.no_cover:
                            cover_path = tmp_dir / "0000-cover.pdf"
                            render_html_to_pdf(browser, cover_html(jobs, args, dist_dir), cover_path, args)
                            parts.append((cover_path, "Export index"))

                        for index, job in enumerate(jobs, start=1):
                            part_path = tmp_dir / f"{index:04d}-{job.lang}-{safe_filename(job.post.slug)}.pdf"
                            url = base_url + quote(job.url_path, safe="/%")
                            public_url = make_public_page_url(args.site_url, job.url_path)
                            print(f"[{index}/{len(jobs)}] {job.label}")
                            render_url_to_pdf(browser, url, public_url, part_path, args)
                            parts.append((part_path, job.label))

                        if args.output:
                            combined_output = resolve_path(project_root, args.output).resolve()
                        else:
                            lang_part = "cs-en" if args.lang == "both" else args.lang
                            section_part = "all" if not selected_sections else "-".join(selected_sections)
                            combined_output = output_dir / f"vojtamaur-web-export-{section_part}-{lang_part}.pdf"

                        raw_combined = tmp_dir / "combined-uncompressed.pdf"
                        merge_pdfs(parts, raw_combined, args.title)
                        finalize_pdf(raw_combined, combined_output, args, ghostscript, outputs)
            finally:
                browser.close()
    finally:
        server.shutdown()
        server.server_close()

    if not args.no_manifest:
        manifest_path = output_dir / "pdf-export-manifest.json"
        write_manifest(manifest_path, args, jobs, outputs, project_root, dist_dir)
        outputs.append(manifest_path)

    print("[done]")
    for path in outputs:
        if path.exists():
            print(f"  {path} ({path.stat().st_size:,} bytes)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
