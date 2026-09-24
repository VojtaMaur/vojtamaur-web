#!/usr/bin/env python3
"""Manually archive EVERY live sitemap URL, including /ns/, via Wayback SPN2.

Python 3.10+; standard library only. Run from any directory:
    python G:/vojtamaur-web/scripts/export-wayback-snapshots.py
    python G:/vojtamaur-web/scripts/export-wayback-snapshots.py --dry-run

Set IA_ACCESS_KEY_ID and IA_SECRET_ACCESS_KEY in the process environment.
Obtain S3 API keys at https://archive.org/account/s3.php; never commit them.
Each run creates exports/vojtamaur-web-wayback-<date-time>.txt containing only
confirmed snapshot URLs, one per line. Successful lines are flushed and synced
immediately. Ctrl+C keeps these lines; a new run starts a fresh capture batch.
This script is intentionally independent of export-all.bat and the site build.

SPN2 reference: https://github.com/internetarchive/gospn
Exit codes: 0 = complete, 1 = partial/failed, 130 = interrupted.
"""

from __future__ import annotations

import argparse
import gzip
import http.client
import json
import os
import re
import sys
import time
import xml.etree.ElementTree as ET
from collections import deque
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


SITEMAP_URL = "https://vojtamaur.cz/sitemap-index.xml"
EXPORT_DIR = Path(__file__).resolve().parent.parent / "exports"
SAVE_URL = "https://web.archive.org/save"
USER_AGENT = "vojtamaur.cz-wayback-exporter/1.0 (https://vojtamaur.cz/)"
REQUEST_TIMEOUT = 60
MAX_RETRIES = 6
BACKOFF_SECONDS = 15
MAX_BACKOFF_SECONDS = 300
CAPTURE_DELAY = 5
POLL_INTERVAL = 5
# Pending jobs are polled until completion; Ctrl+C can stop a stuck server job.
RETRYABLE_SPN_ERRORS = {
    "error:too-many-requests", "error:user-session-limit",
    "error:internal-server-error", "error:bad-gateway",
    "error:service-unavailable", "error:gateway-timeout",
    "error:no-browsers-available", "error:cannot-fetch", "error:celery",
}


class ExportError(Exception):
    """An operational failure that can be reported without exposing credentials."""


class UnexpectedFavicon(ExportError):
    """SPN2 reported a favicon instead of the requested page."""


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Authenticated requests stay on the SPN endpoint; never forward keys.
        return None


def log(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def backoff(attempt: int, retry_after: str | None = None) -> float:
    delay = min(BACKOFF_SECONDS * 2 ** attempt, MAX_BACKOFF_SECONDS)
    if retry_after:
        try:
            seconds = int(retry_after)
        except ValueError:
            try:
                date = parsedate_to_datetime(retry_after)
                if date.tzinfo is None:
                    date = date.replace(tzinfo=timezone.utc)
                seconds = (date - datetime.now(timezone.utc)).total_seconds()
            except (ValueError, TypeError, OverflowError):
                seconds = 0
        delay = max(delay, seconds)
    return delay


def request_bytes(opener, url: str, *, data: bytes | None = None,
                  authorization: str | None = None) -> bytes:
    for attempt in range(MAX_RETRIES + 1):
        headers = {"User-Agent": USER_AGENT}
        if authorization:
            headers.update({"Authorization": authorization,
                            "Accept": "application/json",
                            "Cache-Control": "no-cache"})
        if data is not None:
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        request = Request(url, data=data, headers=headers)
        retry_after = None
        try:
            with opener.open(request, timeout=REQUEST_TIMEOUT) as response:
                body = response.read()
                if response.headers.get("Content-Encoding", "").lower() == "gzip":
                    body = gzip.decompress(body)
                return body
        except HTTPError as exc:
            status = exc.code
            retry_after = exc.headers.get("Retry-After")
            exc.close()
            reason = f"HTTP {status}"
            if status != 429 and not 500 <= status <= 599:
                raise ExportError(reason) from None
        except (URLError, OSError, http.client.HTTPException) as exc:
            reason = f"Network failure ({type(exc).__name__})"
            # A POST may already have created a job even if its reply was lost.
            # Without a job ID we cannot poll it or safely repeat that request.
            if data is not None:
                raise ExportError(reason + "; capture submission outcome unknown") from None
        if attempt == MAX_RETRIES:
            raise ExportError(f"{reason}; retries exhausted")
        delay = backoff(attempt, retry_after)
        log(f"  {reason}; retry {attempt + 1}/{MAX_RETRIES} in {delay:.0f}s")
        time.sleep(delay)
    raise AssertionError("unreachable")


def collect_urls() -> tuple[list[str], int]:
    """Follow nested indices; deduplicate exact URLs without changing/filtering them."""
    opener = build_opener()  # No authentication is ever sent to sitemap hosts.
    pending = deque([SITEMAP_URL])
    seen_maps: set[str] = set()
    urls: dict[str, None] = {}
    failures = 0
    while pending:
        sitemap_url = pending.popleft()
        if sitemap_url in seen_maps:
            continue
        seen_maps.add(sitemap_url)
        log(f"Sitemap: {sitemap_url}")
        try:
            content = request_bytes(opener, sitemap_url)
            if content.startswith(b"\x1f\x8b"):
                content = gzip.decompress(content)
            root = ET.fromstring(content)
            kind = root.tag.rsplit("}", 1)[-1]
            if kind not in ("sitemapindex", "urlset"):
                raise ExportError(f"Unsupported sitemap root: {kind}")
            entry_tag = "sitemap" if kind == "sitemapindex" else "url"
            # Direct children only: image/video extension <loc>s are not pages.
            for entry in root:
                if entry.tag.rsplit("}", 1)[-1] != entry_tag:
                    continue
                loc = next((child for child in entry
                            if child.tag == root.tag.replace(kind, "loc")), None)
                if loc is None or not (loc.text or "").strip():
                    failures += 1
                    log(f"  ERROR: Missing <loc> in {sitemap_url}")
                    continue
                url = loc.text.strip()
                if kind == "sitemapindex":
                    pending.append(url)
                else:
                    urls[url] = None
        except (ExportError, ET.ParseError, OSError, EOFError, ValueError) as exc:
            failures += 1
            log(f"  ERROR: {sitemap_url}: {exc}")
    return list(urls), failures


def api_json(opener, authorization: str, url: str,
             form: dict[str, str] | None = None) -> dict:
    data = None if form is None else urlencode(form).encode("utf-8")
    raw = request_bytes(opener, url, data=data, authorization=authorization)
    try:
        result = json.loads(raw)
    except (ValueError, UnicodeError):
        raise ExportError("SPN2 returned invalid JSON") from None
    if not isinstance(result, dict):
        raise ExportError("SPN2 response is not an object")
    return result


def snapshot_url(result: dict, requested_url: str) -> str:
    timestamp = result.get("timestamp")
    original = result.get("original_url")
    if (not isinstance(timestamp, str) or not re.fullmatch(r"[0-9]{14}", timestamp)
            or not isinstance(original, str) or not original
            or any(char.isspace() or ord(char) < 32 for char in original)):
        raise ExportError("SPN2 success has no valid timestamp/original_url")
    parsed = urlsplit(original)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ExportError("SPN2 success has an invalid original_url")
    # SPN2 sometimes reports a captured favicon as the successful page result.
    # Keep deliberate favicon requests and legitimate page redirects working.
    if (parsed.path.rsplit("/", 1)[-1].lower() == "favicon.ico"
            and urlsplit(requested_url).path.rsplit("/", 1)[-1].lower() != "favicon.ico"):
        raise UnexpectedFavicon(f"SPN2 returned favicon.ico instead of {requested_url}; "
                                "omitted from TXT")
    return f"https://web.archive.org/web/{timestamp}/{original}"


def capture(opener, authorization: str, url: str) -> str:
    retried_favicon = False
    for attempt in range(MAX_RETRIES + 1):
        result = api_json(opener, authorization, SAVE_URL, {
            "url": url, "capture_all": "1", "skip_first_archive": "1",
            "if_not_archived_within": "0",
        })
        job_id = result.get("job_id")
        if job_id and result.get("status") not in ("success", "error"):
            log(f"  Job: {job_id}")
            last_progress = time.monotonic()
            while True:
                time.sleep(POLL_INTERVAL)
                status_url = (f"{SAVE_URL}/status/{quote(str(job_id), safe='')}"
                              f"?_t={time.time_ns()}")
                try:
                    result = api_json(opener, authorization, status_url)
                except ExportError as exc:
                    raise ExportError(f"Job {job_id}: {exc}") from None
                if result.get("status") != "pending":
                    break
                if time.monotonic() - last_progress >= 60:
                    log(f"  Still waiting for job {job_id} (Ctrl+C to stop)")
                    last_progress = time.monotonic()
        if result.get("status") == "success":
            try:
                return snapshot_url(result, url)
            except UnexpectedFavicon as exc:
                if retried_favicon or attempt == MAX_RETRIES:
                    raise
                retried_favicon = True
                delay = backoff(0)
                log(f"  {exc}; retry capture once in {delay}s")
                time.sleep(delay)
                continue
        error_code = str(result.get("status_ext", "unknown-status"))
        message = str(result.get("message", "No confirmed capture returned"))
        if (result.get("status") == "error" and error_code in RETRYABLE_SPN_ERRORS
                and attempt < MAX_RETRIES):
            delay = backoff(attempt)
            log(f"  {error_code}; retry capture {attempt + 1}/{MAX_RETRIES} in {delay}s")
            time.sleep(delay)
            continue
        raise ExportError(f"{error_code}: {message}")
    raise AssertionError("unreachable")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true",
                        help="Read live sitemaps and list URLs; no keys, captures or files.")
    args = parser.parse_args()
    output_path = None
    saved = failed = 0
    try:
        authorization = None
        if not args.dry_run:
            access = os.environ.get("IA_ACCESS_KEY_ID", "").strip()
            secret = os.environ.get("IA_SECRET_ACCESS_KEY", "").strip()
            if not access or not secret:
                raise ExportError("Set IA_ACCESS_KEY_ID and IA_SECRET_ACCESS_KEY; "
                                  "get S3 keys at https://archive.org/account/s3.php")
            if any(ord(char) < 33 or ord(char) > 126 for char in access + secret):
                raise ExportError("S3 keys contain invalid characters")
            authorization = f"LOW {access}:{secret}"
        urls, sitemap_failures = collect_urls()
        log(f"Found {len(urls)} unique URLs; sitemap errors: {sitemap_failures}")
        if args.dry_run:
            for url in urls:
                print(url)
            return int(bool(sitemap_failures) or not urls)
        if not urls:
            raise ExportError("No URLs found; nothing to archive")
        EXPORT_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        output_path = EXPORT_DIR / f"vojtamaur-web-wayback-{stamp}.txt"
        opener = build_opener(NoRedirect())
        with output_path.open("x", encoding="utf-8", newline="\n") as output:
            log(f"Output: {output_path}")
            for index, url in enumerate(urls, 1):
                if index > 1:
                    time.sleep(CAPTURE_DELAY)
                log(f"[{index}/{len(urls)}] {url}")
                try:
                    snapshot = capture(opener, authorization, url)
                except (ExportError, ValueError) as exc:
                    failed += 1
                    log(f"  ERROR: {exc}")
                    continue
                # Disk failures must stop the run, not discard further captures.
                output.write(snapshot + "\n")
                output.flush()
                os.fsync(output.fileno())
                saved += 1
                log(f"  OK: {snapshot}")
        log(f"Finished: {saved} saved, {failed} failed, {sitemap_failures} sitemap errors.")
        log(f"TXT: {output_path}")
        return int(bool(failed or sitemap_failures))
    except KeyboardInterrupt:
        log(f"Interrupted: {saved} saved, {failed} failed. Completed lines are preserved.")
        if output_path:
            log(f"TXT: {output_path}")
        return 130
    except (ExportError, OSError) as exc:
        log(f"ERROR: {exc}")
        if output_path:
            log(f"Completed lines remain in: {output_path}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
