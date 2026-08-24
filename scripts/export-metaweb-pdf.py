#!/usr/bin/env python3
"""Create one archival PDF for the metaweb article and its supporting files.

The exporter is intentionally manual. It reads the already finished standard
web build in dist/ so that the postprocessed English article and the exact
integrity files of that build are preserved. It never runs as part of a normal
build and it does not rebuild the site by itself.

Included by default:
  - a simple bilingual title page and contents page
  - the Czech and English metaweb article pages
  - every image linked from the article, with a contextual caption
  - a bilingual introduction followed by the Czech ultra PDF export of all
    articles with images
  - ARCHIVE.txt
  - the rendered technical documentation page
  - files linked from the article's build integrity and identity section

The reconstructable source ZIP and ALL_POSTS.txt remain linked from the article
but their payloads are deliberately not appended to the PDF.
"""

from __future__ import annotations

import argparse
import contextlib
import dataclasses
import datetime as dt
import hashlib
import html
import http.server
import json
import os
import re
import socketserver
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import quote, unquote, urljoin, urlsplit, urlunsplit
from urllib.request import urlopen


SCRIPT_VERSION = "1.3.0"
DEFAULT_SITE_URL = "https://vojtamaur.cz"
DEFAULT_OUTPUT_NAME = "vojtamaur-web-export-metaweb.pdf"
ULTRA_OUTPUT_PATH = Path("exports/vojtamaur-web-export-ultra.pdf")
ULTRA_EXPORT_ARGS = (
    "scripts/export-site-pdf-ultra.py",
    "--lang",
    "cs",
    "--image-dpi",
    "400",
)

ARTICLE_ROUTES = (
    ("cs", "/metawebovy-clanek/", "Metawebový článek - CS"),
    ("en", "/en/metawebovy-clanek/", "Metaweb Article - EN"),
)
DOCUMENTATION_ROUTE = "/documentation/"
ARCHIVE_PATH = "/ARCHIVE.txt"

IMAGE_EXTENSIONS = {".avif", ".gif", ".jpeg", ".jpg", ".png", ".webp"}
EXCLUDED_PAYLOADS = {
    "/ALL_POSTS.txt",
    "/source/vojtamaur-web-source.zip",
}


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


@dataclasses.dataclass
class PdfPart:
    title: str
    pdf_path: Path
    source: str
    pages: int = 0
    start_page: int = 0


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        return

    def copyfile(self, source: Any, outputfile: Any) -> None:
        with contextlib.suppress(
            BrokenPipeError,
            ConnectionAbortedError,
            ConnectionResetError,
        ):
            super().copyfile(source, outputfile)


class ThreadingHTTPServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Export the metaweb article, linked images, ARCHIVE.txt, technical "
            "documentation, and build identity files into one PDF."
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
            "Project root containing dist/. By default it is detected from the "
            "script location."
        ),
    )
    parser.add_argument(
        "--dist",
        default="dist",
        help="Finished standard web build, relative to project root unless absolute.",
    )
    parser.add_argument(
        "--output-dir",
        default="exports",
        help="Output directory, relative to project root unless absolute.",
    )
    parser.add_argument(
        "--output",
        default=None,
        help=(
            "Output PDF path. The default is "
            f"exports/{DEFAULT_OUTPUT_NAME}."
        ),
    )
    parser.add_argument(
        "--site-url",
        default=DEFAULT_SITE_URL,
        help=(
            "Public site root used for clickable links in the PDF. "
            f"Default: {DEFAULT_SITE_URL}"
        ),
    )
    parser.add_argument(
        "--title",
        default="Metawebový článek",
        help="Czech cover title. It is combined with --title-en in PDF metadata.",
    )
    parser.add_argument(
        "--title-en",
        default="Metaweb Article",
        help="English cover title. It is combined with --title in PDF metadata.",
    )
    parser.add_argument(
        "--paper",
        default="A4",
        help="Paper format passed to Chromium. Default: A4",
    )
    parser.add_argument(
        "--margin",
        default="12mm",
        help="Left and right page margin. Default: 12mm",
    )
    parser.add_argument(
        "--images-per-page",
        type=int,
        choices=(2, 3, 4),
        default=3,
        help="Number of linked images on each gallery page. Default: 3",
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
        default=400,
        help="Extra wait after loading/scrolling pages. Default: 400",
    )
    parser.add_argument(
        "--no-manifest",
        action="store_true",
        help="Do not write the adjacent JSON export manifest.",
    )
    return parser.parse_args()


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


def public_url(site_url: str, public_path: str) -> str:
    return urljoin(site_url, public_path.lstrip("/"))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def ensure_dependencies() -> None:
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
            + "\nInstall them with:\n"
            "  python -m pip install -r requirements-pdf-export.txt\n"
            "  python -m playwright install chromium"
        )


def start_server(root: Path) -> tuple[ThreadingHTTPServer, str]:
    def handler(*args: Any, **kwargs: Any) -> QuietHandler:
        return QuietHandler(*args, directory=str(root), **kwargs)

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
    server.server_close()
    raise SystemExit("Could not start the temporary local server for dist/.")


def route_file(dist_dir: Path, route: str) -> Path:
    clean = route.strip("/")
    if not clean:
        return dist_dir / "index.html"
    directory_form = dist_dir / clean / "index.html"
    file_form = dist_dir / f"{clean}.html"
    if directory_form.is_file():
        return directory_form
    if file_form.is_file():
        return file_form
    return directory_form


def require_finished_build(dist_dir: Path) -> None:
    required = [
        route_file(dist_dir, ARTICLE_ROUTES[0][1]),
        route_file(dist_dir, ARTICLE_ROUTES[1][1]),
        route_file(dist_dir, DOCUMENTATION_ROUTE),
        dist_dir / ARCHIVE_PATH.lstrip("/"),
    ]
    missing = [path for path in required if not path.is_file()]
    if missing:
        rendered = "\n".join(f"  - {path}" for path in missing)
        raise SystemExit(
            "The finished standard web build is incomplete. Missing:\n"
            f"{rendered}\n"
            "Create or restore a current standard dist/ build, then run this "
            "manual exporter again."
        )


def ensure_ultra_export(project_root: Path, output_path: Path) -> bool:
    if output_path.is_file():
        return False

    exporter = project_root / ULTRA_EXPORT_ARGS[0]
    if not exporter.is_file():
        raise SystemExit(
            "The ultra PDF is missing and its exporter was not found: "
            f"{exporter}"
        )

    display_command = "python " + " ".join(ULTRA_EXPORT_ARGS)
    print(f"[ultra] missing; running: {display_command}")
    command = [sys.executable, str(exporter), *ULTRA_EXPORT_ARGS[1:]]
    completed = subprocess.run(command, cwd=project_root, check=False)
    if completed.returncode != 0:
        raise SystemExit(
            "The required ultra PDF export failed with exit code "
            f"{completed.returncode}: {display_command}"
        )
    if not output_path.is_file():
        raise SystemExit(
            "The ultra exporter completed but did not create the expected file: "
            f"{output_path}"
        )
    return True


def safe_dist_path(dist_dir: Path, public_path: str) -> Path:
    decoded = unquote(urlsplit(public_path).path).lstrip("/")
    candidate = (dist_dir / decoded).resolve()
    dist_root = dist_dir.resolve()
    if not candidate.is_relative_to(dist_root):
        raise SystemExit(f"Unsafe path discovered in built HTML: {public_path}")
    return candidate


def local_public_path(raw_href: str, page_url: str, base_url: str) -> str | None:
    absolute = urljoin(page_url, raw_href)
    parsed = urlsplit(absolute)
    base = urlsplit(base_url)
    if parsed.scheme != base.scheme or parsed.netloc != base.netloc:
        return None
    path = unquote(parsed.path)
    return "/" + path.lstrip("/")


def normalize_space(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def collect_article_links(page, language: str) -> dict[str, Any]:
    data = page.evaluate(
        """
        (language) => {
          const root = document.querySelector("main article") ||
            document.querySelector("article") || document.querySelector("main");
          if (!root) throw new Error("Article content container not found.");
          const clean = (value) => (value || "").replace(/\s+/g, " ").trim();

          const anchors = Array.from(root.querySelectorAll("a[href]")).map((anchor) => {
            const row = anchor.closest("tr");
            const cells = row ? Array.from(row.querySelectorAll("th, td")) : [];
            const headings = Array.from(root.querySelectorAll("h2, h3"));
            let section = "";
            for (const heading of headings) {
              if (heading.compareDocumentPosition(anchor) & Node.DOCUMENT_POSITION_FOLLOWING) {
                section = clean(heading.textContent);
              } else {
                break;
              }
            }
            return {
              href: anchor.getAttribute("href") || "",
              text: clean(anchor.textContent),
              rowId: cells[0] ? clean(cells[0].textContent) : "",
              rowName: cells[1] ? clean(cells[1].textContent) : "",
              rowDescription: cells[5] ? clean(cells[5].textContent) : "",
              section,
              language,
            };
          });

          const integrityHeading = Array.from(root.querySelectorAll("h2")).find((heading) =>
            clean(heading.textContent).toUpperCase() === "INTEGRITA A IDENTITA BUILDU"
          );
          const integrity = [];
          if (integrityHeading) {
            let node = integrityHeading.nextElementSibling;
            while (node && node.tagName.toLowerCase() !== "h2") {
              for (const anchor of node.querySelectorAll("a[href]")) {
                integrity.push({
                  href: anchor.getAttribute("href") || "",
                  text: clean(anchor.textContent),
                });
              }
              node = node.nextElementSibling;
            }
          }

          return {
            title: clean(root.querySelector("h1")?.textContent || document.title),
            anchors,
            integrity,
          };
        }
        """,
        language,
    )
    return data


def image_title(item: dict[str, str]) -> str:
    row_id = normalize_space(item.get("rowId", ""))
    row_name = normalize_space(item.get("rowName", ""))
    return " - ".join(part for part in (row_id, row_name) if part) or "Linked image"


def image_description(item: dict[str, str], fallback: str) -> str:
    link_text = normalize_space(item.get("text", ""))
    row_description = normalize_space(item.get("rowDescription", ""))
    section = normalize_space(item.get("section", ""))
    generic_link = link_text.lower() in {"image", "obrazek", "obrázek"}
    if link_text and not generic_link:
        return link_text
    return row_description or section or link_text or fallback


def collect_inputs(
    browser,
    dist_dir: Path,
    base_url: str,
    timeout_ms: int,
) -> tuple[list[LinkedImage], list[LinkedFile], dict[str, str]]:
    collected: dict[str, dict[str, dict[str, str]]] = {}
    titles: dict[str, str] = {}
    integrity_items: list[dict[str, str]] = []

    for language, route, _ in ARTICLE_ROUTES:
        page = browser.new_page()
        page_url = base_url + route
        try:
            page.set_default_timeout(timeout_ms)
            page.goto(page_url, wait_until="domcontentloaded", timeout=timeout_ms)
            data = collect_article_links(page, language)
            titles[language] = data["title"]
            if language == "cs":
                integrity_items = data["integrity"]

            for anchor in data["anchors"]:
                public_path = local_public_path(anchor["href"], page_url, base_url)
                if public_path is None:
                    continue
                if Path(urlsplit(public_path).path).suffix.lower() not in IMAGE_EXTENSIONS:
                    continue
                collected.setdefault(public_path, {}).setdefault(language, anchor)
        finally:
            page.close()

    linked_images: list[LinkedImage] = []
    for public_path, language_items in collected.items():
        file_path = safe_dist_path(dist_dir, public_path)
        if not file_path.is_file():
            raise SystemExit(
                f"Image linked from the metaweb article is missing: {file_path}"
            )
        missing_languages = [
            language for language in ("cs", "en") if language not in language_items
        ]
        if missing_languages:
            raise SystemExit(
                "A linked image does not have descriptions in both article languages: "
                f"{public_path} (missing: {', '.join(missing_languages)})"
            )
        linked_images.append(
            LinkedImage(
                public_path=public_path,
                file_path=file_path,
                title=image_title(language_items["cs"]),
                description_cs=image_description(
                    language_items["cs"], "Odkazovaný obrázek"
                ),
                description_en=image_description(
                    language_items["en"], "Linked image"
                ),
            )
        )

    linked_files: list[LinkedFile] = []
    seen_files: set[str] = set()
    for item in integrity_items:
        public_path = local_public_path(
            item["href"], base_url + ARTICLE_ROUTES[0][1], base_url
        )
        if public_path is None or public_path in seen_files:
            continue
        if public_path in EXCLUDED_PAYLOADS:
            raise SystemExit(
                f"Excluded payload unexpectedly appeared in integrity links: {public_path}"
            )
        seen_files.add(public_path)
        linked_files.append(
            LinkedFile(
                public_path=public_path,
                file_path=safe_dist_path(dist_dir, public_path),
                label=normalize_space(item.get("text", ""))
                or Path(public_path).name,
                optional=Path(public_path).name.lower() == "sha256sums.txt.asc",
            )
        )

    if not linked_images:
        raise SystemExit("No linked images were discovered in the metaweb article.")
    if not linked_files:
        raise SystemExit(
            "No files were discovered in the article's build integrity section."
        )

    missing_required = [
        item.file_path
        for item in linked_files
        if not item.optional and not item.file_path.is_file()
    ]
    if missing_required:
        rendered = "\n".join(f"  - {path}" for path in missing_required)
        raise SystemExit(f"Required build identity files are missing:\n{rendered}")

    return linked_images, linked_files, titles


COMMON_PRINT_CSS = r"""
html {
  -webkit-print-color-adjust: exact !important;
  print-color-adjust: exact !important;
}
body > header,
body > footer,
body > nav,
.site-header,
.site-footer {
  display: none !important;
}
html, body {
  background: #fff !important;
  color: #161616 !important;
  font-family: Arial, "Liberation Sans", sans-serif !important;
}
body {
  font-size: 9.6pt !important;
  line-height: 1.48 !important;
  margin: 0 !important;
  padding: 0 !important;
}
main, article {
  box-sizing: border-box !important;
  margin: 0 auto !important;
  max-width: none !important;
  overflow: visible !important;
  padding: 0 !important;
  width: 100% !important;
}
h1 { font-size: 23pt !important; line-height: 1.12 !important; margin: 0 0 7mm !important; }
h2 { font-size: 14pt !important; line-height: 1.2 !important; margin: 8mm 0 3mm !important; }
h3 { font-size: 11pt !important; line-height: 1.25 !important; }
h1, h2, h3, h4 { break-after: avoid !important; page-break-after: avoid !important; }
p, li { orphans: 3; widows: 3; }
a, a:visited { color: #174f68 !important; overflow-wrap: anywhere !important; }
a[href]::after { content: "" !important; }
pre {
  background: #f6f6f3 !important;
  border: 0.2mm solid #d7d7d2 !important;
  border-radius: 1.2mm !important;
  box-sizing: border-box !important;
  font-family: Consolas, "Liberation Mono", monospace !important;
  font-size: 7.2pt !important;
  line-height: 1.35 !important;
  max-width: 100% !important;
  overflow: visible !important;
  overflow-wrap: anywhere !important;
  padding: 2.5mm !important;
  tab-size: 2 !important;
  white-space: pre-wrap !important;
  word-break: break-word !important;
}
code {
  font-family: Consolas, "Liberation Mono", monospace !important;
  overflow-wrap: anywhere !important;
  white-space: pre-wrap !important;
  word-break: break-word !important;
}
img, svg, video, canvas, iframe { max-width: 100% !important; }
table {
  border-collapse: collapse !important;
  max-width: 100% !important;
  table-layout: fixed !important;
  width: 100% !important;
}
thead { display: table-header-group !important; }
tr { break-inside: avoid !important; page-break-inside: avoid !important; }
th, td {
  border: 0.2mm solid #d8d8d3 !important;
  font-size: 7.6pt !important;
  overflow-wrap: anywhere !important;
  padding: 1.5mm !important;
  vertical-align: top !important;
  word-break: break-word !important;
}
th { background: #efefeb !important; text-align: left !important; }
"""


ARTICLE_PRINT_CSS = COMMON_PRINT_CSS + r"""
.pdf-registry-cards {
  display: block !important;
  margin-top: 4mm !important;
}
.pdf-registry-card {
  background: #fff !important;
  border: 0.35mm solid #9a9a93 !important;
  border-left: 1.5mm solid #2d5c69 !important;
  border-radius: 1.5mm !important;
  break-inside: avoid !important;
  margin: 0 0 4mm !important;
  padding: 3mm 3.5mm !important;
  page-break-inside: avoid !important;
}
.pdf-registry-card > h3 {
  color: #173f4b !important;
  font-size: 11pt !important;
  margin: 0 0 2.5mm !important;
}
.pdf-registry-fields {
  display: grid !important;
  gap: 0 !important;
  grid-template-columns: 38mm minmax(0, 1fr) !important;
  margin: 0 !important;
}
.pdf-registry-fields dt,
.pdf-registry-fields dd {
  border-top: 0.2mm solid #e2e2dd !important;
  box-sizing: border-box !important;
  margin: 0 !important;
  min-width: 0 !important;
  overflow-wrap: anywhere !important;
  padding: 1.25mm 0 !important;
  word-break: break-word !important;
}
.pdf-registry-fields dt {
  color: #4a4a46 !important;
  font-size: 7.2pt !important;
  font-weight: 700 !important;
  padding-right: 3mm !important;
  text-transform: uppercase !important;
}
.pdf-registry-fields dd { font-size: 8.2pt !important; }
.pdf-integrity-list {
  margin: 3mm 0 !important;
  padding-left: 6mm !important;
}
.pdf-integrity-list li {
  break-inside: avoid !important;
  margin: 0 0 2mm !important;
  page-break-inside: avoid !important;
}
"""


DOCUMENTATION_PRINT_CSS = COMMON_PRINT_CSS + r"""
body { font-size: 8.8pt !important; line-height: 1.42 !important; }
h1 { font-size: 22pt !important; }
h2 {
  break-before: page !important;
  font-size: 16pt !important;
  margin-top: 0 !important;
  page-break-before: always !important;
}
h3 { font-size: 11.5pt !important; margin-top: 5mm !important; }
h4 { font-size: 9.5pt !important; margin-top: 4mm !important; }
pre { font-size: 6.9pt !important; }
pre, pre *, pre code { color: #202020 !important; }
"""


def rewrite_preview_links(page, base_url: str, site_url: str) -> None:
    page.evaluate(
        """
        ({ localOrigin, publicRoot }) => {
          for (const anchor of document.querySelectorAll("a[href]")) {
            const raw = anchor.getAttribute("href");
            if (!raw) continue;
            let resolved;
            try { resolved = new URL(raw, document.baseURI); } catch { continue; }
            if (resolved.origin !== localOrigin) continue;
            const target = new URL(resolved.pathname.replace(/^\//, ""), publicRoot);
            target.search = resolved.search;
            target.hash = resolved.hash;
            anchor.setAttribute("href", target.href);
          }
        }
        """,
        {
            "localOrigin": base_url,
            "publicRoot": site_url,
        },
    )


def transform_wide_tables(page) -> dict[str, Any]:
    return page.evaluate(
        """
        () => {
          const root = document.querySelector("main article") ||
            document.querySelector("article") || document.querySelector("main");
          if (!root) throw new Error("Article content container not found.");
          const clean = (value) => (value || "").replace(/\s+/g, " ").trim();
          let tableCount = 0;
          let recordCount = 0;
          let allValuesPreserved = true;

          for (const table of Array.from(root.querySelectorAll("table"))) {
            const headers = Array.from(table.querySelectorAll("thead th"));
            const rows = Array.from(table.querySelectorAll("tbody tr"));
            if (headers.length < 7 || !rows.length) continue;

            tableCount += 1;
            const cards = document.createElement("section");
            cards.className = "pdf-registry-cards";
            cards.setAttribute("aria-label", "Printable registry records");

            for (const row of rows) {
              const cells = Array.from(row.querySelectorAll("th, td"));
              if (!cells.length) continue;
              const values = cells.map((cell) => clean(cell.textContent));
              const card = document.createElement("article");
              card.className = "pdf-registry-card";

              const heading = document.createElement("h3");
              heading.textContent = [values[0], values[1]].filter(Boolean).join(" - ");
              card.appendChild(heading);

              const fields = document.createElement("dl");
              fields.className = "pdf-registry-fields";
              for (let index = 2; index < cells.length; index += 1) {
                const label = document.createElement("dt");
                label.textContent = clean(headers[index]?.textContent) || `Field ${index + 1}`;
                const value = document.createElement("dd");
                for (const child of Array.from(cells[index].childNodes)) {
                  value.appendChild(child.cloneNode(true));
                }
                fields.append(label, value);
              }
              card.appendChild(fields);
              cards.appendChild(card);
              recordCount += 1;

              const cardText = clean(card.textContent);
              if (!values.every((value) => !value || cardText.includes(value))) {
                allValuesPreserved = false;
              }
            }
            table.replaceWith(cards);
          }

          for (const details of root.querySelectorAll("details")) details.open = true;
          return { tableCount, recordCount, allValuesPreserved };
        }
        """
    )


def normalize_english_integrity_list(page) -> dict[str, Any]:
    """Repair malformed line breaks introduced by the English postprocess.

    The finished English HTML currently splits words and leaves Markdown
    backticks around several links in this one paragraph. Rebuild only that
    paragraph in the temporary print DOM; the signed build remains untouched.
    """
    return page.evaluate(
        """
        () => {
          const heading = document.querySelector("h2#integrita-a-identita-buildu") ||
            Array.from(document.querySelectorAll("h2")).find((item) =>
              (item.textContent || "").trim() === "BUILD INTEGRITY AND IDENTITY"
            );
          if (!heading) return { integrityListNormalized: false, integrityLinkCount: 0 };

          const items = [
            {
              path: "/SHA256SUMS.txt",
              label: "SHA256SUMS.txt",
              description: "a list of SHA-256 checksums for the build files",
            },
            {
              path: "/SHA256SUMS.txt.asc",
              label: "SHA256SUMS.txt.asc",
              description: "a separate OpenPGP signature for the SHA256SUMS.txt file",
            },
            {
              path: "/BUILD_SHA256.txt",
              label: "BUILD_SHA256.txt",
              description: "SHA-256 checksum of the SHA256SUMS.txt file",
            },
            {
              path: "/integrity.json",
              label: "integrity.json",
              description: "machine-readable descriptive information about the build's integrity",
            },
            {
              path: "/SIGNING_STATUS.txt",
              label: "SIGNING_STATUS.txt",
              description: "descriptive status of the signing for a specific build",
            },
            {
              path: "/keys/vojta-maur-openpgp.asc",
              label: "vojta-maur-openpgp.asc",
              description: "public OpenPGP key for verifying the signature",
            },
          ];

          let node = heading.nextElementSibling;
          let source = null;
          while (node && node.tagName !== "H2") {
            if (node.matches("p") && node.querySelectorAll("a[href]").length >= items.length) {
              source = node;
              break;
            }
            node = node.nextElementSibling;
          }
          if (!source) return { integrityListNormalized: false, integrityLinkCount: 0 };

          const links = new Map();
          for (const anchor of source.querySelectorAll("a[href]")) {
            let path;
            try { path = new URL(anchor.getAttribute("href"), document.baseURI).pathname; }
            catch { continue; }
            links.set(path.toLowerCase(), anchor);
          }
          if (!items.every((item) => links.has(item.path.toLowerCase()))) {
            return { integrityListNormalized: false, integrityLinkCount: links.size };
          }

          const list = document.createElement("ul");
          list.className = "pdf-integrity-list";
          for (const item of items) {
            const row = document.createElement("li");
            const link = links.get(item.path.toLowerCase()).cloneNode(true);
            link.textContent = item.label;
            row.append(link, document.createTextNode(` \u2014 ${item.description}`));
            list.appendChild(row);
          }
          source.replaceWith(list);
          return { integrityListNormalized: true, integrityLinkCount: items.length };
        }
        """
    )


def scroll_and_wait(page, wait_ms: int) -> None:
    page.evaluate(
        """
        async () => {
          const step = Math.max(window.innerHeight * 0.8, 500);
          for (let y = 0; y < document.documentElement.scrollHeight; y += step) {
            window.scrollTo(0, y);
            await new Promise((resolve) => setTimeout(resolve, 35));
          }
          window.scrollTo(0, 0);
          await document.fonts.ready;
          await Promise.all(
            Array.from(document.images, (image) =>
              image.decode().catch(() => undefined)
            )
          );
        }
        """
    )
    if wait_ms:
        page.wait_for_timeout(wait_ms)


def header_template(label: str) -> str:
    return (
        '<div style="box-sizing:border-box;color:#676767;font-family:Arial,sans-serif;'
        'font-size:7px;padding:0 12mm;width:100%">'
        + html.escape(label)
        + "</div>"
    )


def footer_template() -> str:
    return (
        '<div style="box-sizing:border-box;color:#676767;font-family:Arial,sans-serif;'
        'font-size:7px;padding:0 12mm;text-align:right;width:100%">'
        '<span class="pageNumber"></span> / <span class="totalPages"></span>'
        "</div>"
    )


def pdf_options(
    args: argparse.Namespace,
    label: str,
    display_header_footer: bool = True,
) -> dict[str, Any]:
    return {
        "format": args.paper,
        "print_background": True,
        "prefer_css_page_size": False,
        "display_header_footer": display_header_footer,
        "header_template": header_template(label),
        "footer_template": footer_template(),
        "margin": {
            "top": "15mm",
            "right": args.margin,
            "bottom": "15mm",
            "left": args.margin,
        },
    }


def render_route_pdf(
    browser,
    route: str,
    output_path: Path,
    label: str,
    css: str,
    args: argparse.Namespace,
    base_url: str,
    transform_registry: bool = False,
    article_language: str | None = None,
) -> dict[str, Any]:
    page = browser.new_page()
    result: dict[str, Any] = {}
    try:
        page.set_default_timeout(args.timeout_ms)
        page.emulate_media(media="print")
        page.goto(
            base_url + route,
            wait_until="domcontentloaded",
            timeout=args.timeout_ms,
        )
        with contextlib.suppress(Exception):
            page.wait_for_load_state("networkidle", timeout=min(args.timeout_ms, 8000))
        if transform_registry:
            result = transform_wide_tables(page)
            if result["tableCount"] < 1 or result["recordCount"] < 1:
                raise SystemExit(
                    f"The physical archive registry was not found on route {route}."
                )
            if not result["allValuesPreserved"]:
                raise SystemExit(
                    f"Registry card conversion lost cell content on route {route}."
                )
        if article_language == "en":
            result.update(normalize_english_integrity_list(page))
            if not result["integrityListNormalized"]:
                raise SystemExit(
                    "The English build-integrity link list could not be normalized "
                    f"on route {route}."
                )
        page.add_style_tag(content=css)
        rewrite_preview_links(page, base_url, args.site_url)
        scroll_and_wait(page, args.wait_ms)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        page.pdf(path=str(output_path), **pdf_options(args, label))
        return result
    finally:
        page.close()


CUSTOM_DOCUMENT_CSS = r"""
@page { size: A4 portrait; }
html, body { background: #fff; color: #181818; margin: 0; padding: 0; }
body {
  font-family: Arial, "Liberation Sans", sans-serif;
  font-size: 9.5pt;
  line-height: 1.48;
}
h1 { color: #173f4b; font-size: 23pt; line-height: 1.12; margin: 0 0 5mm; }
h2 { color: #173f4b; font-size: 13pt; margin: 6mm 0 2mm; }
p, li { orphans: 3; widows: 3; }
a, a:visited { color: #174f68; overflow-wrap: anywhere; }
code, pre { font-family: Consolas, "Liberation Mono", monospace; }
.lead { color: #4d4d49; font-size: 11pt; }
.title-page {
  align-items: center;
  background: #fff;
  box-sizing: border-box;
  display: flex;
  flex-direction: column;
  height: 267mm;
  justify-content: center;
  text-align: center;
}
.title-page h1 {
  color: #111;
  font-size: 31pt;
  margin: 0;
}
.title-page .title-en {
  color: #444;
  display: block;
  font-size: 21pt;
  margin: 3mm 0 0;
}
.title-page .author { font-size: 14pt; margin: 16mm 0 3mm; }
.title-page .website { font-size: 11pt; text-decoration: none; }
.contents h1 { font-size: 20pt; margin-bottom: 3mm; }
.contents .meta-grid [lang="en"] { color: #60605b; }
.contents h2 { margin-top: 4mm; }
.contents .meta-grid { margin: 4mm 0; }
.contents .meta-grid dt, .contents .meta-grid dd { padding: 1.4mm 0; }
.contents .toc { margin-top: 3mm; }
.contents .toc li { margin: 1mm 0; }
.contents .toc-description {
  color: #555;
  display: block;
  font-size: 8.5pt;
  margin-top: 0.5mm;
}
.contents .notice { margin: 2.5mm 0; padding: 2.2mm 3mm; }
.contents .notice p { margin: 1mm 0 0; }
.contents .notice p[lang="en"] { color: #51514d; }
.section-intro {
  box-sizing: border-box;
  display: flex;
  flex-direction: column;
  height: 251mm;
  justify-content: center;
  margin: 0 auto;
  max-width: 148mm;
}
.section-intro .eyebrow {
  color: #2d5c69;
  font-size: 8pt;
  font-weight: 700;
  letter-spacing: 0.08em;
  margin: 0 0 4mm;
  text-transform: uppercase;
}
.section-intro h1 { font-size: 27pt; margin-bottom: 3mm; }
.section-intro h1 [lang="en"] {
  color: #49636a;
  display: block;
  font-size: 18pt;
  margin-top: 2mm;
}
.section-intro .filename { margin: 0 0 10mm; }
.section-intro .intro-copy {
  border-left: 1.5mm solid #2d5c69;
  padding-left: 5mm;
}
.section-intro .intro-copy p {
  font-size: 11pt;
  line-height: 1.5;
  margin: 0;
}
.section-intro .intro-copy p[lang="en"] {
  color: #51514d;
  margin-top: 5mm;
}
.notice {
  background: #f3f6f6;
  border: 0.25mm solid #c4d0d2;
  border-left: 1.5mm solid #2d5c69;
  margin: 5mm 0;
  padding: 3mm 4mm;
}
.toc { margin: 7mm 0 0; padding-left: 6mm; }
.toc li { margin: 2mm 0; }
.meta-grid {
  border-bottom: 0.2mm solid #d8d8d3;
  border-top: 0.2mm solid #d8d8d3;
  display: grid;
  gap: 0;
  grid-template-columns: 43mm minmax(0, 1fr);
  margin: 7mm 0;
}
.meta-grid dt, .meta-grid dd { border-bottom: 0.2mm solid #e6e6e2; margin: 0; padding: 2mm 0; }
.meta-grid dt { color: #555; font-weight: 700; padding-right: 3mm; }
.meta-grid dd { overflow-wrap: anywhere; }
.raw-document h1 { margin-bottom: 2mm; }
.raw-document .source { color: #555; margin: 0 0 6mm; }
.raw-text {
  background: #f7f7f4;
  border: 0.2mm solid #d5d5cf;
  box-sizing: border-box;
  font-size: 7pt;
  line-height: 1.34;
  margin: 0;
  max-width: 100%;
  overflow: visible;
  overflow-wrap: anywhere;
  padding: 3mm;
  tab-size: 2;
  white-space: pre-wrap;
  word-break: break-word;
}
.missing-file {
  background: #fff8e5;
  border: 0.25mm solid #d1ae54;
  margin-top: 7mm;
  padding: 5mm;
}
"""


def html_document(title: str, body: str, base_url: str, extra_css: str = "") -> str:
    return f"""<!doctype html>
<html lang="cs">
<head>
  <meta charset="utf-8">
  <base href="{html.escape(base_url + '/', quote=True)}">
  <title>{html.escape(title)}</title>
  <style>{CUSTOM_DOCUMENT_CSS}\n{extra_css}</style>
</head>
<body>{body}</body>
</html>"""


def render_html_pdf(
    browser,
    html_source: str,
    output_path: Path,
    label: str,
    args: argparse.Namespace,
    display_header_footer: bool = True,
) -> None:
    page = browser.new_page()
    try:
        page.set_default_timeout(args.timeout_ms)
        page.emulate_media(media="print")
        page.set_content(
            html_source,
            wait_until="domcontentloaded",
            timeout=args.timeout_ms,
        )
        with contextlib.suppress(Exception):
            page.wait_for_load_state("networkidle", timeout=min(args.timeout_ms, 8000))
        broken_images = page.evaluate(
            """
            async () => {
              await document.fonts.ready;
              await Promise.all(
                Array.from(document.images, (image) =>
                  image.decode().catch(() => undefined)
                )
              );
              return Array.from(document.images)
                .filter((image) => image.naturalWidth === 0)
                .map((image) => image.getAttribute("src") || "[unknown]");
            }
            """
        )
        if broken_images:
            raise SystemExit(
                "Custom PDF section contains broken images:\n  - "
                + "\n  - ".join(broken_images)
            )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        page.pdf(
            path=str(output_path),
            **pdf_options(args, label, display_header_footer),
        )
    finally:
        page.close()


def title_page_html(args: argparse.Namespace, base_url: str) -> str:
    body = f"""
<main class="title-page">
  <h1>{html.escape(args.title)}</h1>
  <p class="title-en" lang="en">{html.escape(args.title_en)}</p>
  <p class="author">Vojta Maur</p>
  <a class="website" href="{html.escape(args.site_url, quote=True)}">www.vojtamaur.cz</a>
</main>
"""
    return html_document(f"{args.title} / {args.title_en}", body, base_url)


def contents_html(
    args: argparse.Namespace,
    base_url: str,
    dist_dir: Path,
    linked_images: list[LinkedImage],
    linked_files: list[LinkedFile],
    ultra_pages: int,
) -> str:
    generated = dt.datetime.now().astimezone().isoformat(timespec="seconds")
    identity_list = "".join(
        f"<li><code>{html.escape(item.public_path)}</code></li>"
        for item in linked_files
    )
    body = f"""
<main class="contents">
  <h1>Obsah / <span lang="en">Contents</span></h1>
  <dl class="meta-grid">
    <dt>Vygenerováno<br><span lang="en">Generated</span></dt><dd>{html.escape(generated)}</dd>
    <dt>Veřejný web<br><span lang="en">Public website</span></dt><dd><a href="{html.escape(args.site_url, quote=True)}">{html.escape(args.site_url)}</a></dd>
    <dt>Zdrojový build<br><span lang="en">Source build</span></dt><dd><code>{html.escape(str(dist_dir))}</code></dd>
    <dt>Obrazová příloha<br><span lang="en">Image appendix</span></dt><dd>{len(linked_images)} odkazovaných obrázků<br><span lang="en">{len(linked_images)} linked images</span></dd>
    <dt>Identita a integrita<br><span lang="en">Identity and integrity</span></dt><dd>{len(linked_files)} odkazovaných souborů<br><span lang="en">{len(linked_files)} linked files</span></dd>
  </dl>

  <h2>Oddíly PDF / <span lang="en">PDF sections</span></h2>
  <ol class="toc">
    <li>Metawebový článek - česká verze / <span lang="en">Metaweb article - Czech version</span></li>
    <li>Metawebový článek - anglická verze / <span lang="en">Metaweb article - English version</span></li>
    <li>Obrazová příloha fyzické archivní vrstvy / <span lang="en">Physical archival layer image appendix</span></li>
    <li><code>vojtamaur-web-export-ultra.pdf</code> ({ultra_pages} stran / <span lang="en">pages</span>)
      <span class="toc-description">Ultra-kompaktní český export všech článků webu včetně obrázků. / <span lang="en">Ultra-compact Czech export of all website articles, including images.</span></span>
    </li>
    <li><code>ARCHIVE.txt</code></li>
    <li>Technická dokumentace projektu / <span lang="en">Project technical documentation</span></li>
    <li>Soubory identity a integrity buildu / <span lang="en">Build identity and integrity files</span><ul>{identity_list}</ul></li>
  </ol>

  <div class="notice">
    <strong>Široká tabulka / <span lang="en">Wide table</span></strong>
    <p lang="cs">Registr ve fyzické archivní vrstvě je v obou jazykových verzích převeden do čitelných karet. Všechny původní buňky a odkazy zůstávají zachované.</p>
    <p lang="en">The physical archival layer registry is converted into readable cards in both languages. Every original cell and link is preserved.</p>
  </div>
  <div class="notice">
    <strong>Záměrně nevloženo / <span lang="en">Deliberately not embedded</span></strong>
    <p lang="cs">Obsah <code>ALL_POSTS.txt</code> a <code>source/vojtamaur-web-source.zip</code>. Jejich zmínky a klikatelné odkazy zůstávají v článku.</p>
    <p lang="en">The payloads of <code>ALL_POSTS.txt</code> and <code>source/vojtamaur-web-source.zip</code>. Their mentions and clickable links remain in the article.</p>
  </div>
</main>
"""
    return html_document("Obsah / Contents", body, base_url)


def ultra_intro_html(base_url: str, ultra_pages: int) -> str:
    body = f"""
<main class="section-intro">
  <p class="eyebrow">Vložený samostatný dokument / <span lang="en">Embedded standalone document</span></p>
  <h1>Všechny články s obrázky <span lang="en">All articles with images</span></h1>
  <p class="filename"><code>vojtamaur-web-export-ultra.pdf</code></p>
  <div class="intro-copy">
    <p lang="cs">Ultra-kompaktní český export všech článků webu včetně jejich obrázků. Následující {ultra_pages} strany zachovávají celý samostatný export beze změn; hustá vícesloupcová sazba slouží jako archivní přehled.</p>
    <p lang="en">An ultra-compact Czech export of every website article, including its images. The following {ultra_pages} pages preserve the complete standalone export unchanged; the dense multi-column layout is intended as an archival overview.</p>
  </div>
</main>
"""
    return html_document(
        "Všechny články s obrázky / All articles with images",
        body,
        base_url,
    )


def gallery_html(
    images: list[LinkedImage],
    images_per_page: int,
    base_url: str,
    site_url: str,
) -> str:
    groups = [
        images[index : index + images_per_page]
        for index in range(0, len(images), images_per_page)
    ]
    pages: list[str] = []
    for page_index, group in enumerate(groups, start=1):
        cards: list[str] = []
        for item in group:
            source_url = base_url + quote(item.public_path, safe="/")
            destination = public_url(site_url, item.public_path)
            cards.append(
                f"""
<article class="gallery-card">
  <a class="gallery-image" href="{html.escape(destination, quote=True)}">
    <img src="{html.escape(source_url, quote=True)}" alt="{html.escape(item.title, quote=True)}">
  </a>
  <div class="gallery-caption">
    <h2>{html.escape(item.title)}</h2>
    <div class="caption-language" lang="cs"><strong>CS</strong><span>{html.escape(item.description_cs)}</span></div>
    <div class="caption-language" lang="en"><strong>EN</strong><span>{html.escape(item.description_en)}</span></div>
    <code>{html.escape(Path(item.public_path).name)}</code>
    <a href="{html.escape(destination, quote=True)}">{html.escape(destination)}</a>
  </div>
</article>"""
            )
        pages.append(
            f"""
<section class="gallery-page">
  <header><h1><span class="gallery-heading">Obrazová příloha / <span lang="en">Image appendix</span></span><span class="gallery-page-number">{page_index}/{len(groups)}</span></h1></header>
  <div class="gallery-list" style="grid-template-rows:repeat({len(group)}, minmax(0, 1fr))">
    {''.join(cards)}
  </div>
</section>"""
        )

    css = r"""
.gallery-page {
  box-sizing: border-box;
  break-after: page;
  display: grid;
  grid-template-rows: 12mm minmax(0, 1fr);
  height: 251mm;
  page-break-after: always;
}
.gallery-page:last-child { break-after: auto; page-break-after: auto; }
.gallery-page > header h1 {
  border-bottom: 0.3mm solid #9a9a93;
  display: flex;
  font-size: 15pt;
  justify-content: space-between;
  margin: 0;
  padding-bottom: 2mm;
}
.gallery-page > header .gallery-heading {
  color: #173f4b;
  font-size: 15pt;
  font-weight: 700;
}
.gallery-page > header .gallery-heading [lang="en"] { color: #49636a; }
.gallery-page > header .gallery-page-number {
  color: #666;
  font-size: 8pt;
  font-weight: 400;
}
.gallery-list { display: grid; gap: 3mm; min-height: 0; }
.gallery-card {
  border: 0.3mm solid #c8c8c2;
  border-radius: 1.5mm;
  box-sizing: border-box;
  break-inside: avoid;
  display: grid;
  gap: 4mm;
  grid-template-columns: minmax(0, 1.8fr) minmax(45mm, 1fr);
  min-height: 0;
  overflow: hidden;
  padding: 3mm;
  page-break-inside: avoid;
}
.gallery-image {
  align-items: center;
  background: #f4f4f1;
  display: flex;
  justify-content: center;
  min-height: 0;
  overflow: hidden;
  text-decoration: none;
}
.gallery-image img { display: block; height: 100%; object-fit: contain; width: 100%; }
.gallery-caption { align-self: center; min-width: 0; }
.gallery-caption h2 { font-size: 9.5pt; line-height: 1.25; margin: 0 0 3mm; }
.caption-language {
  display: grid;
  font-size: 8.7pt;
  gap: 2mm;
  grid-template-columns: 7mm minmax(0, 1fr);
  line-height: 1.25;
  margin: 0 0 2mm;
}
.caption-language strong {
  color: #2d5c69;
  font-size: 7pt;
  letter-spacing: 0.04em;
}
.caption-language[lang="en"] { color: #4f4f4b; }
.gallery-caption code { display: block; font-size: 7pt; overflow-wrap: anywhere; }
.gallery-caption a { display: block; font-size: 6.5pt; margin-top: 2mm; overflow-wrap: anywhere; }
"""
    return html_document(
        "Obrazová příloha metawebového článku / Metaweb article image appendix",
        "".join(pages),
        base_url,
        css,
    )


def read_text_file(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig", errors="replace")


def text_appendix_html(
    title: str,
    public_path: str,
    file_path: Path,
    optional: bool,
    base_url: str,
    site_url: str,
) -> str:
    source_link = public_url(site_url, public_path)
    if file_path.is_file():
        content = read_text_file(file_path)
        body = f"""
<main class="raw-document">
  <h1>{html.escape(title)}</h1>
  <p class="source">Zdroj: <a href="{html.escape(source_link, quote=True)}">{html.escape(source_link)}</a><br>
  Velikost: {file_path.stat().st_size:,} B - SHA-256: <code>{sha256_file(file_path)}</code></p>
  <pre class="raw-text">{html.escape(content)}</pre>
</main>"""
    elif optional:
        body = f"""
<main class="raw-document">
  <h1>{html.escape(title)}</h1>
  <p class="source">Očekávaná cesta: <code>{html.escape(public_path)}</code></p>
  <div class="missing-file">
    Tento volitelný soubor není v aktuálním buildu přítomen. U nepodepsaného
    buildu je nepřítomnost odděleného OpenPGP podpisu <code>.asc</code> očekávána;
    žádný obsah nebyl nahrazen ani domyšlen.
  </div>
</main>"""
    else:
        raise SystemExit(f"Required appendix file is missing: {file_path}")
    return html_document(title, body, base_url)


def inspect_pdf(path: Path) -> int:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    if not reader.pages:
        raise SystemExit(f"Generated PDF part has no pages: {path}")
    return len(reader.pages)


def merge_pdfs(parts: list[PdfPart], output_path: Path, title: str) -> None:
    from pypdf import PdfReader, PdfWriter

    writer = PdfWriter()
    for part in parts:
        reader = PdfReader(str(part.pdf_path))
        part.start_page = len(writer.pages) + 1
        part.pages = len(reader.pages)
        for page in reader.pages:
            writer.add_page(page)
        if reader.pages:
            with contextlib.suppress(Exception):
                writer.add_outline_item(part.title, part.start_page - 1)

    writer.add_metadata(
        {
            "/Title": title,
            "/Creator": f"scripts/export-metaweb-pdf.py {SCRIPT_VERSION}",
            "/Producer": "Playwright Chromium + pypdf",
            "/Subject": (
                "Metaweb article, linked images, archive map, technical "
                "documentation, and build identity files"
            ),
        }
    )
    with contextlib.suppress(Exception):
        writer.page_mode = "/UseOutlines"

    output_path.parent.mkdir(parents=True, exist_ok=True)
    building_path = output_path.with_name(output_path.name + ".building")
    building_path.unlink(missing_ok=True)
    try:
        with building_path.open("wb") as handle:
            writer.write(handle)
        os.replace(building_path, output_path)
    except Exception:
        building_path.unlink(missing_ok=True)
        raise


def has_embedded_files(reader: Any) -> bool:
    names = reader.trailer["/Root"].get("/Names")
    if names is None:
        return False
    names = names.get_object()
    return names.get("/EmbeddedFiles") is not None


def validate_final_pdf(
    output_path: Path,
    expected_pages: int,
    linked_images: list[LinkedImage],
    registry_results: dict[str, dict[str, Any]],
) -> tuple[int, int]:
    from pypdf import PdfReader

    reader = PdfReader(str(output_path))
    page_count = len(reader.pages)
    if page_count != expected_pages:
        raise SystemExit(
            f"Merged PDF page count mismatch: expected {expected_pages}, got {page_count}."
        )
    if has_embedded_files(reader):
        raise SystemExit(
            "The PDF unexpectedly contains embedded files; source ZIP and "
            "ALL_POSTS.txt must not be embedded."
        )
    for language, result in registry_results.items():
        if result.get("recordCount", 0) < 1 or not result.get("allValuesPreserved"):
            raise SystemExit(f"Registry validation failed for language: {language}")

    link_count = 0
    for page in reader.pages:
        for annotation_ref in page.get("/Annots", []):
            annotation = annotation_ref.get_object()
            if annotation.get("/Subtype") == "/Link":
                link_count += 1

    if not linked_images:
        raise SystemExit("Final validation received an empty linked image list.")
    return page_count, link_count


def write_manifest(
    manifest_path: Path,
    output_path: Path,
    parts: list[PdfPart],
    linked_images: list[LinkedImage],
    linked_files: list[LinkedFile],
    registry_results: dict[str, dict[str, Any]],
    page_count: int,
    link_count: int,
    dist_dir: Path,
    ultra_pdf_path: Path,
    ultra_generated: bool,
    args: argparse.Namespace,
) -> None:
    data = {
        "generated_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "generator": f"export-metaweb-pdf.py {SCRIPT_VERSION}",
        "source_build": str(dist_dir),
        "site_url": args.site_url,
        "ultra_export": {
            "path": str(ultra_pdf_path),
            "generated_by_metaweb_export": ultra_generated,
            "generation_command": "python " + " ".join(ULTRA_EXPORT_ARGS),
            "pages": inspect_pdf(ultra_pdf_path),
            "bytes": ultra_pdf_path.stat().st_size,
            "sha256": sha256_file(ultra_pdf_path),
            "description_cs": "Export všech článků s obrázky.",
            "description_en": "Export of all articles with images.",
        },
        "sections": [
            {
                "title": part.title,
                "source": part.source,
                "start_page": part.start_page,
                "pages": part.pages,
            }
            for part in parts
        ],
        "registry_conversion": registry_results,
        "linked_images": [
            {
                "path": item.public_path,
                "title": item.title,
                "descriptions": {
                    "cs": item.description_cs,
                    "en": item.description_en,
                },
                "bytes": item.file_path.stat().st_size,
                "sha256": sha256_file(item.file_path),
            }
            for item in linked_images
        ],
        "identity_and_integrity_files": [
            {
                "path": item.public_path,
                "label": item.label,
                "present": item.file_path.is_file(),
                "optional": item.optional,
                "bytes": item.file_path.stat().st_size if item.file_path.is_file() else None,
                "sha256": sha256_file(item.file_path) if item.file_path.is_file() else None,
            }
            for item in linked_files
        ],
        "excluded_payloads": sorted(EXCLUDED_PAYLOADS),
        "output": {
            "path": str(output_path),
            "pages": page_count,
            "links": link_count,
            "bytes": output_path.stat().st_size,
            "sha256": sha256_file(output_path),
        },
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = manifest_path.with_name(manifest_path.name + ".tmp")
    temporary.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, manifest_path)


def part_path(temp_dir: Path, index: int, name: str) -> Path:
    safe = re.sub(r"[^a-z0-9_.-]+", "-", name.lower()).strip("-._")
    return temp_dir / f"{index:02d}-{safe or 'part'}.pdf"


def main() -> int:
    args = parse_args()
    ensure_dependencies()
    args.site_url = normalize_site_url(args.site_url)

    script_root = Path(__file__).resolve().parent.parent
    project_root = (
        Path(args.project_root).expanduser().resolve()
        if args.project_root
        else script_root
    )
    dist_dir = resolve_path(project_root, args.dist)
    output_dir = resolve_path(project_root, args.output_dir)
    output_path = (
        resolve_path(project_root, args.output)
        if args.output
        else output_dir / DEFAULT_OUTPUT_NAME
    )
    if output_path.suffix.lower() != ".pdf":
        raise SystemExit("--output must end with .pdf")

    require_finished_build(dist_dir)
    ultra_pdf_path = (project_root / ULTRA_OUTPUT_PATH).resolve()
    ultra_generated = ensure_ultra_export(project_root, ultra_pdf_path)
    ultra_pages = inspect_pdf(ultra_pdf_path)
    print(
        f"[ultra] {ultra_pdf_path} - {ultra_pages} page(s)"
        + (" (generated)" if ultra_generated else " (existing)")
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path = output_path.with_suffix(".manifest.json")

    server, base_url = start_server(dist_dir)
    registry_results: dict[str, dict[str, Any]] = {}
    parts: list[PdfPart] = []

    try:
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import sync_playwright

        with tempfile.TemporaryDirectory(prefix="vojtamaur-metaweb-pdf-") as temp_value:
            temp_dir = Path(temp_value)
            with sync_playwright() as playwright:
                try:
                    browser = playwright.chromium.launch()
                except PlaywrightError as exc:
                    raise SystemExit(
                        "Playwright Chromium is not installed. Run:\n"
                        "  python -m playwright install chromium"
                    ) from exc

                try:
                    linked_images, linked_files, article_titles = collect_inputs(
                        browser,
                        dist_dir,
                        base_url,
                        args.timeout_ms,
                    )
                    print(
                        f"[inputs] {len(linked_images)} linked image(s), "
                        f"{len(linked_files)} identity/integrity file(s)"
                    )

                    title_page_path = part_path(temp_dir, 0, "title-page")
                    render_html_pdf(
                        browser,
                        title_page_html(args, base_url),
                        title_page_path,
                        "",
                        args,
                        display_header_footer=False,
                    )
                    parts.append(
                        PdfPart(
                            "Titulní strana / Title page",
                            title_page_path,
                            "generated title page",
                        )
                    )

                    contents_path = part_path(temp_dir, 1, "contents")
                    render_html_pdf(
                        browser,
                        contents_html(
                            args,
                            base_url,
                            dist_dir,
                            linked_images,
                            linked_files,
                            ultra_pages,
                        ),
                        contents_path,
                        "Obsah / Contents",
                        args,
                    )
                    parts.append(
                        PdfPart(
                            "Obsah / Contents",
                            contents_path,
                            "generated contents",
                        )
                    )

                    part_index = 2
                    for language, route, fallback_label in ARTICLE_ROUTES:
                        article_path = part_path(temp_dir, part_index, f"article-{language}")
                        label = article_titles.get(language) or fallback_label
                        print(f"[render] {language.upper()} article: {route}")
                        registry_results[language] = render_route_pdf(
                            browser,
                            route,
                            article_path,
                            label,
                            ARTICLE_PRINT_CSS,
                            args,
                            base_url,
                            transform_registry=True,
                            article_language=language,
                        )
                        parts.append(PdfPart(label, article_path, route))
                        part_index += 1

                    gallery_path = part_path(temp_dir, part_index, "linked-images")
                    print(f"[render] linked image appendix ({len(linked_images)} images)")
                    render_html_pdf(
                        browser,
                        gallery_html(
                            linked_images,
                            args.images_per_page,
                            base_url,
                            args.site_url,
                        ),
                        gallery_path,
                        "Obrazová příloha / Image appendix",
                        args,
                    )
                    parts.append(
                        PdfPart(
                            "Obrazová příloha / Image appendix",
                            gallery_path,
                            "linked images discovered in both article routes",
                        )
                    )
                    part_index += 1

                    ultra_intro_path = part_path(
                        temp_dir,
                        part_index,
                        "ultra-introduction",
                    )
                    print("[render] ultra export introduction")
                    render_html_pdf(
                        browser,
                        ultra_intro_html(base_url, ultra_pages),
                        ultra_intro_path,
                        "Všechny články s obrázky / All articles with images",
                        args,
                    )
                    parts.append(
                        PdfPart(
                            "Všechny články s obrázky / All articles with images",
                            ultra_intro_path,
                            "generated ultra export introduction",
                        )
                    )
                    part_index += 1

                    print(f"[include] ultra article export: {ultra_pdf_path}")
                    parts.append(
                        PdfPart(
                            "vojtamaur-web-export-ultra.pdf",
                            ultra_pdf_path,
                            str(ultra_pdf_path),
                        )
                    )
                    part_index += 1

                    archive_file = dist_dir / ARCHIVE_PATH.lstrip("/")
                    archive_path = part_path(temp_dir, part_index, "archive-txt")
                    print(f"[render] {ARCHIVE_PATH}")
                    render_html_pdf(
                        browser,
                        text_appendix_html(
                            "ARCHIVE.txt",
                            ARCHIVE_PATH,
                            archive_file,
                            False,
                            base_url,
                            args.site_url,
                        ),
                        archive_path,
                        "ARCHIVE.txt",
                        args,
                    )
                    parts.append(PdfPart("ARCHIVE.txt", archive_path, ARCHIVE_PATH))
                    part_index += 1

                    documentation_path = part_path(temp_dir, part_index, "documentation")
                    print(f"[render] documentation: {DOCUMENTATION_ROUTE}")
                    render_route_pdf(
                        browser,
                        DOCUMENTATION_ROUTE,
                        documentation_path,
                        "Technical documentation",
                        DOCUMENTATION_PRINT_CSS,
                        args,
                        base_url,
                    )
                    parts.append(
                        PdfPart(
                            "Technical documentation",
                            documentation_path,
                            DOCUMENTATION_ROUTE,
                        )
                    )
                    part_index += 1

                    for linked_file in linked_files:
                        file_part_path = part_path(
                            temp_dir,
                            part_index,
                            Path(linked_file.public_path).name,
                        )
                        state = "present" if linked_file.file_path.is_file() else "absent"
                        print(f"[render] {linked_file.public_path} ({state})")
                        render_html_pdf(
                            browser,
                            text_appendix_html(
                                linked_file.label,
                                linked_file.public_path,
                                linked_file.file_path,
                                linked_file.optional,
                                base_url,
                                args.site_url,
                            ),
                            file_part_path,
                            linked_file.label,
                            args,
                        )
                        parts.append(
                            PdfPart(
                                linked_file.label,
                                file_part_path,
                                linked_file.public_path,
                            )
                        )
                        part_index += 1
                finally:
                    browser.close()

            for part in parts:
                part.pages = inspect_pdf(part.pdf_path)
            expected_pages = sum(part.pages for part in parts)
            print(f"[merge] {len(parts)} section(s), {expected_pages} page(s)")
            merge_pdfs(parts, output_path, f"{args.title} / {args.title_en}")
            page_count, link_count = validate_final_pdf(
                output_path,
                expected_pages,
                linked_images,
                registry_results,
            )

            if not args.no_manifest:
                write_manifest(
                    manifest_path,
                    output_path,
                    parts,
                    linked_images,
                    linked_files,
                    registry_results,
                    page_count,
                    link_count,
                    dist_dir,
                    ultra_pdf_path,
                    ultra_generated,
                    args,
                )
            else:
                manifest_path.unlink(missing_ok=True)

            print(
                f"[done] {output_path} - {page_count} page(s), "
                f"{output_path.stat().st_size:,} bytes, {link_count} link(s)"
            )
            if not args.no_manifest:
                print(f"[manifest] {manifest_path}")
            return 0
    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("Interrupted.")
        raise SystemExit(130)
