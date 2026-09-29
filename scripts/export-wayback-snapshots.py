#!/usr/bin/env python3
"""Archive live sitemap pages, images and PDF/TXT files via Wayback SPN2.

Python 3.10+; standard library only. Run from any directory:
    python F:/vojtamaur-web/scripts/export-wayback-snapshots.py --pages-only
    python F:/vojtamaur-web/scripts/export-wayback-snapshots.py --with-files
    python F:/vojtamaur-web/scripts/export-wayback-snapshots.py --with-files --dry-run
    python scripts/export-wayback-snapshots.py --dry-run --dist dist --types images pdf txt

Set IA_ACCESS_KEY_ID and IA_SECRET_ACCESS_KEY in the process environment.
Obtain S3 API keys at https://archive.org/account/s3.php; never commit them.
Each run creates exports/vojtamaur-web-wayback-<date-time>.txt containing only
confirmed snapshot URLs, one per line. Successful lines are flushed and synced
immediately. Ctrl+C keeps these lines. By default, successful captures from the
last 24 hours in previous exports are reused, so restarting can make progress.
The default selection is pages only; --with-files also selects images/PDF/TXT.
This script is intentionally independent of export-all.bat and the site build.

SPN2 reference: https://github.com/internetarchive/gospn
Exit codes: 0 = complete, 1 = partial/failed, 130 = interrupted.
"""

from __future__ import annotations

import argparse
import gzip
import http.client
import json
import ipaddress
import math
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
from urllib.parse import quote, unquote, urlencode, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


SITEMAP_URL = "https://vojtamaur.cz/sitemap-index.xml"
EXPORT_DIR = Path(__file__).resolve().parent.parent / "exports"
SAVE_URL = "https://web.archive.org/save"
USER_AGENT = "vojtamaur.cz-wayback-exporter/1.0 (https://vojtamaur.cz/)"
REQUEST_TIMEOUT = 60
MAX_RETRIES = 6
BACKOFF_SECONDS = 15
MAX_BACKOFF_SECONDS = 300
CAPTURE_DELAY = 15
REUSE_SECONDS = 86400
POLL_INTERVAL = 5
POLL_TIMEOUT = 900
IMAGE_NS = "http://www.google.com/schemas/sitemap-image/1.1"
SITEMAP_NS = "http://www.sitemaps.org/schemas/sitemap/0.9"
TYPES = ("pages", "images", "pdf", "txt")


class ExportError(Exception):
    """An operational failure that can be reported without exposing credentials."""


class UnexpectedFavicon(ExportError):
    """SPN2 reported a favicon instead of the requested page."""


class RateLimited(ExportError):
    """Stop the batch instead of submitting more URLs while quota is exhausted."""


class AuthenticationFailed(RateLimited):
    """Do not repeat requests with credentials the service has rejected."""


def validate_url(value: str, origin: str | None = None) -> str:
    """Canonical public HTTP(S) URL, optionally restricted to the sitemap origin."""
    if (not isinstance(value, str) or not value
            or any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in value)
            or "\\" in value or re.search(r"%(?![0-9a-fA-F]{2})", value)):
        raise ExportError("Invalid URL characters")
    try:
        parts = urlsplit(value)
        if (parts.scheme not in ("http", "https") or not parts.hostname
                or parts.username is not None or parts.password is not None):
            raise ValueError()
        host = parts.hostname.encode("idna").decode("ascii").lower()
        port = parts.port
        if port not in (None, 80 if parts.scheme == "http" else 443):
            raise ValueError()
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            if ("." not in host or host.rsplit(".", 1)[-1].isdigit()
                    or host.endswith((".localhost", ".local", ".internal", ".test", ".invalid"))
                    or not all(re.fullmatch(r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?", label)
                               for label in host.split("."))):
                raise ValueError()
        else:
            if not address.is_global:
                raise ValueError()
            if address.version == 6:
                host = f"[{host}]"
        decoded = unquote(parts.path)
        if ("\\" in decoded or any(ord(c) < 32 or ord(c) == 127 for c in decoded)
                or any(segment in (".", "..") for segment in decoded.split("/"))):
            raise ValueError()
        # Normalize escapes of unreserved characters; retain reserved path/query semantics.
        def normalize(component):
            component = quote(component, safe="/%:@!$&'()*+,;=-._~?")
            return re.sub(r"%([0-9a-fA-F]{2})", lambda m:
                          chr(int(m[1], 16)) if chr(int(m[1], 16)) in
                          "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~"
                          else "%" + m[1].upper(), component)
        result = urlunsplit((parts.scheme, host, normalize(parts.path or "/"),
                            normalize(parts.query), ""))
        if origin and urlsplit(result)[:2] != urlsplit(origin)[:2]:
            raise ValueError()
        return result
    except (ValueError, UnicodeError):
        raise ExportError("URL must use a public HTTP(S) host and the permitted origin") from None


def url_type(url: str) -> str:
    suffix = Path(unquote(urlsplit(url).path)).suffix.lower()
    if suffix in (".avif", ".bmp", ".gif", ".jpg", ".jpeg", ".png", ".svg", ".webp", ".ico"):
        return "images"
    return suffix[1:] if suffix in (".pdf", ".txt") else "pages"


class SitemapRedirect(HTTPRedirectHandler):
    def __init__(self, origin):
        self.origin = origin

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return super().redirect_request(req, fp, code, msg, headers,
                                        validate_url(newurl, self.origin))


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
                  authorization: str | None = None, deadline: float | None = None) -> bytes:
    for attempt in range(MAX_RETRIES + 1):
        remaining = REQUEST_TIMEOUT if deadline is None else deadline - time.monotonic()
        if remaining <= 0:
            raise ExportError("Polling deadline reached; capture may still finish; not resubmitted")
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
            with opener.open(request, timeout=min(REQUEST_TIMEOUT, remaining)) as response:
                body = response.read()
                if response.headers.get("Content-Encoding", "").lower() == "gzip":
                    body = gzip.decompress(body)
                return body
        except HTTPError as exc:
            status = exc.code
            retry_after = exc.headers.get("Retry-After")
            # A 429 is a rejected submission, not an accepted capture. If an
            # unusual response nevertheless supplies a job, poll that job.
            accepted = None
            if data is not None and status == 429:
                try:
                    raw = exc.read()
                    body = json.loads(raw)
                    if isinstance(body, dict) and (body.get("job_id") or body.get("status") == "success"):
                        accepted = raw
                except (ValueError, OSError, http.client.HTTPException):
                    pass
            exc.close()
            if accepted is not None:
                return accepted
            reason = f"HTTP {status}"
            if authorization and status in (401, 403):
                raise AuthenticationFailed(f"HTTP {status}; check Internet Archive credentials/access; stop batch") from None
            if data is not None and status != 429:
                # A server error can follow creation of a capture job. Never
                # repeat a submission, including after an ambiguous HTTP 5xx.
                raise ExportError(reason + "; submission not repeated") from None
            if status != 429 and not 500 <= status <= 599:
                raise ExportError(reason) from None
        except (URLError, OSError, http.client.HTTPException) as exc:
            reason = f"Network failure ({type(exc).__name__})"
            # A POST may already have created a job even if its reply was lost.
            # Without a job ID we cannot poll it or safely repeat that request.
            if data is not None:
                raise ExportError(reason + "; capture submission outcome unknown") from None
        if attempt == MAX_RETRIES:
            if authorization and reason == "HTTP 429":
                raise RateLimited("HTTP 429; retries exhausted; stop batch")
            raise ExportError(f"{reason}; retries exhausted")
        delay = backoff(attempt, retry_after)
        if data is not None and reason == "HTTP 429":
            delay = max(300, delay)
        if deadline is not None and time.monotonic() + delay >= deadline:
            if authorization and reason == "HTTP 429":
                raise RateLimited("Retry-After exceeds polling deadline; stop batch")
            raise ExportError("Retry would exceed polling deadline; not resubmitted")
        log(f"  {reason}; retry {attempt + 1}/{MAX_RETRIES} in {delay:.0f}s")
        time.sleep(delay)
    raise AssertionError("unreachable")


def collect_urls(sitemap_url: str = SITEMAP_URL, *, dist: Path | None = None,
                 types=TYPES) -> tuple[list[str], int]:
    """Follow indices and image extensions; local dry-runs never use the network."""
    sitemap_url = validate_url(sitemap_url)
    opener = build_opener(SitemapRedirect(sitemap_url))
    pending = deque([sitemap_url])
    origin = sitemap_url
    local_root = dist.resolve() if dist else None
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
            if local_root:
                parts = unquote(urlsplit(sitemap_url).path).lstrip("/").split("/")
                if any(":" in part for part in parts):
                    raise ExportError("Invalid local sitemap path")
                local = local_root.joinpath(*parts).resolve()
                if not local.is_relative_to(local_root):
                    raise ExportError("Sitemap path escapes --dist")
                content = local.read_bytes()
            else:
                content = request_bytes(opener, sitemap_url)
            if content.startswith(b"\x1f\x8b"):
                content = gzip.decompress(content)
            root = ET.fromstring(content)
            kind = root.tag.rsplit("}", 1)[-1]
            namespace = root.tag[1:].split("}")[0] if root.tag.startswith("{") else ""
            prefix = "{" + namespace + "}" if namespace else ""
            if kind not in ("sitemapindex", "urlset") or namespace not in ("", SITEMAP_NS):
                raise ExportError(f"Unsupported sitemap root: {kind}")
            entry_tag = "sitemap" if kind == "sitemapindex" else "url"
            for entry in root:
                if entry.tag != prefix + entry_tag:
                    continue
                loc = next((child for child in entry
                            if child.tag == root.tag.replace(kind, "loc")), None)
                if loc is None or not (loc.text or "").strip():
                    failures += 1
                    log(f"  ERROR: Missing <loc> in {sitemap_url}")
                    continue
                try:
                    url = validate_url(loc.text.strip(), origin)
                    if kind == "sitemapindex":
                        pending.append(url)
                    elif url_type(url) in types:
                        urls[url] = None
                except ExportError as exc:
                    failures += 1
                    log(f"  ERROR: Invalid <loc>: {exc}")
                if kind == "urlset":
                    for image in entry.findall(f"{{{IMAGE_NS}}}image"):
                        image_loc = image.find(f"{{{IMAGE_NS}}}loc")
                        try:
                            image_url = validate_url((image_loc.text or "").strip()
                                                     if image_loc is not None else "", origin)
                            if "images" in types:
                                urls[image_url] = None
                        except ExportError as exc:
                            failures += 1
                            log(f"  ERROR: Invalid image:loc: {exc}")
        except (ExportError, ET.ParseError, OSError, EOFError, ValueError) as exc:
            failures += 1
            log(f"  ERROR: {sitemap_url}: {exc}")
    return list(urls), failures


def api_json(opener, authorization: str, url: str,
             form: dict[str, str] | None = None, *, deadline=None) -> dict:
    data = None if form is None else urlencode(form).encode("utf-8")
    raw = request_bytes(opener, url, data=data, authorization=authorization, deadline=deadline)
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
    original = validate_url(original)
    parsed = urlsplit(original)
    # SPN2 sometimes reports a captured favicon as the successful page result.
    # Keep deliberate favicon requests and legitimate page redirects working.
    if (parsed.path.rsplit("/", 1)[-1].lower() == "favicon.ico"
            and urlsplit(requested_url).path.rsplit("/", 1)[-1].lower() != "favicon.ico"):
        raise UnexpectedFavicon(f"SPN2 returned favicon.ico instead of {requested_url}; "
                                "omitted from TXT")
    return f"https://web.archive.org/web/{timestamp}/{original}"


def recent_snapshots(directory: Path, max_age: int, *, now=None) -> dict[str, str]:
    """Reuse only validated, recent success links; never infer success from jobs."""
    if max_age <= 0:
        return {}
    now = now or datetime.now(timezone.utc)
    newest = {}
    for file in sorted(directory.glob("vojtamaur-web-wayback-*.txt")):
        # Existing exports are user data. An unreadable file is reported rather
        # than silently losing resume information and issuing duplicate work.
        for line in file.read_text(encoding="utf-8-sig").splitlines():
            match = re.fullmatch(r"https://web\.archive\.org/web/([0-9]{14})/(https?://\S+)", line.strip())
            if not match:
                continue
            try:
                stamp = datetime.strptime(match[1], "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
                age = (now - stamp).total_seconds()
                original = validate_url(match[2])
            except (ValueError, ExportError):
                continue
            if 0 <= age < max_age and (original not in newest or stamp > newest[original][0]):
                newest[original] = (stamp, f"https://web.archive.org/web/{match[1]}/{original}")
    return {url: record[1] for url, record in newest.items()}


def submit_capture(opener, authorization, form):
    for attempt in range(MAX_RETRIES + 1):
        result = api_json(opener, authorization, SAVE_URL, form)
        # Retry only explicit admission rejections with NO accepted job.
        code = result.get("status_ext")
        if (not result.get("job_id") and result.get("status") == "error"
                and code in ("error:too-many-requests", "error:user-session-limit")):
            if attempt == MAX_RETRIES:
                raise RateLimited(f"{code}; admission retries exhausted; stop batch")
            delay = max(300, backoff(attempt))
            log(f"  {code}; waiting {delay:.0f}s before retrying rejected submission ({attempt + 1}/{MAX_RETRIES})")
            time.sleep(delay)
            continue
        return result
    raise AssertionError("unreachable")


def capture(opener, authorization: str, url: str, *, poll_timeout=POLL_TIMEOUT,
            if_not_archived_within=str(REUSE_SECONDS), capture_errors=False) -> str:
    url = validate_url(url)
    form = {"url": url, "skip_first_archive": "1",
            "if_not_archived_within": if_not_archived_within, "capture_outlinks": "0"}
    if capture_errors:
        form["capture_all"] = "1"
    if url_type(url) != "pages":
        form["force_get"] = "1"
    result = submit_capture(opener, authorization, form)
    job_id = result.get("job_id")
    if job_id and result.get("status") not in ("success", "error"):
        log(f"  Job: {job_id}")
        started = last_progress = time.monotonic()
        deadline = started + poll_timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ExportError(f"Job {job_id}: polling timed out; capture may still finish; not resubmitted")
            time.sleep(min(POLL_INTERVAL, remaining))
            status_url = (f"{SAVE_URL}/status/{quote(str(job_id), safe='')}"
                          f"?_t={time.time_ns()}")
            result = api_json(opener, authorization, status_url, deadline=deadline)
            if result.get("status") != "pending":
                break
            if time.monotonic() - last_progress >= 60:
                log(f"  Still waiting for job {job_id} (Ctrl+C to stop)")
                last_progress = time.monotonic()
    if result.get("status") == "success":
        return snapshot_url(result, url)
    error_code = str(result.get("status_ext", "unknown-status"))
    message = str(result.get("message", "No confirmed capture returned"))
    if error_code == "error:too-many-daily-captures":
        raise ExportError(f"{error_code}: per-URL daily limit; deferred until a later run. {message}")
    if any(term in error_code for term in ("limit", "quota", "too-many-requests")):
        raise RateLimited(f"{error_code}: {message}; stop batch")
    raise ExportError(f"{error_code}: {message}; submission not repeated")


def seconds_at_least_five(value):
    seconds = float(value)
    if not math.isfinite(seconds) or seconds < 5:
        raise argparse.ArgumentTypeError("Must be a finite number >= 5 seconds")
    return seconds


def positive_int(value):
    result = int(value)
    if result < 1:
        raise argparse.ArgumentTypeError("Must be a positive integer")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true",
                        help="List URLs; no keys, capture requests or output files.")
    parser.add_argument("--sitemap", default=SITEMAP_URL,
                        help="HTTP(S) sitemap URL; children and targets must share its origin.")
    parser.add_argument("--dist", type=Path,
                        help="Read sitemap paths from local dist, without network; requires --dry-run.")
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument("--pages-only", action="store_true",
                           help="Archive only page URLs, without separate file submissions (default).")
    selection.add_argument("--with-files", action="store_true",
                           help="Archive pages first, then all sitemap images/PDF/TXT.")
    selection.add_argument("--types", nargs="+", choices=TYPES,
                           help="Custom selection: pages, images, pdf and/or txt.")
    parser.add_argument("--limit", type=positive_int, help="Process at most N unique URLs.")
    parser.add_argument("--delay", type=seconds_at_least_five, default=CAPTURE_DELAY,
                        help="Seconds between submissions, minimum 5 (default: 15).")
    parser.add_argument("--poll-timeout", type=seconds_at_least_five, default=POLL_TIMEOUT,
                        help="Stop polling a job after N seconds; never resubmit it (default: 900).")
    parser.add_argument("--if-not-archived-within", type=int, default=REUSE_SECONDS, metavar="SECONDS",
                        help="Reuse recent confirmed captures locally and at SPN2 (default: 86400 = 24h; 0 disables reuse).")
    parser.add_argument("--capture-errors", action="store_true",
                        help="Also archive HTTP error responses (legacy capture_all behavior).")
    args = parser.parse_args()
    if args.dist and not args.dry_run:
        parser.error("--dist requires --dry-run; publish and use the live sitemap for captures")
    if args.if_not_archived_within < 0:
        parser.error("--if-not-archived-within must be >= 0")
    output_path = None
    saved = reused = failed = 0
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
        types = args.types or (TYPES if args.with_files else ("pages",))
        urls, sitemap_failures = collect_urls(args.sitemap, dist=args.dist, types=types)
        urls.sort(key=lambda url: TYPES.index(url_type(url)))
        log(f"Found {len(urls)} unique URLs; sitemap errors: {sitemap_failures}")
        if args.limit:
            urls = urls[:args.limit]
        log("Selection: " + ", ".join(f"{kind}={sum(url_type(url) == kind for url in urls)}" for kind in TYPES))
        if args.dry_run:
            for url in urls:
                print(url)
            return int(bool(sitemap_failures) or not urls)
        if not urls:
            raise ExportError("No URLs found; nothing to archive")
        recent = recent_snapshots(EXPORT_DIR, args.if_not_archived_within)
        log(f"Recent confirmed exports reusable: {sum(url in recent for url in urls)}; delay: {args.delay:g}s")
        EXPORT_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        output_path = EXPORT_DIR / f"vojtamaur-web-wayback-{stamp}.txt"
        opener = build_opener(NoRedirect())
        failure_path = output_path.with_suffix(".failures.jsonl")
        attempted = False
        with output_path.open("x", encoding="utf-8", newline="\n") as output, failure_path.open("x", encoding="utf-8", newline="\n") as errors:
            log(f"Output: {output_path}")
            for index, url in enumerate(urls, 1):
                log(f"[{index}/{len(urls)}] {url}")
                try:
                    if url in recent:
                        snapshot = recent[url]
                        reused += 1
                        log("  Reusing confirmed recent snapshot; no submission")
                    else:
                        if attempted:
                            time.sleep(args.delay)
                        attempted = True
                        snapshot = capture(opener, authorization, url,
                                           poll_timeout=args.poll_timeout,
                                           if_not_archived_within=str(args.if_not_archived_within),
                                           capture_errors=args.capture_errors)
                except (ExportError, ValueError) as exc:
                    failed += 1
                    errors.write(json.dumps({"url": url, "error": str(exc)}, ensure_ascii=False) + "\n")
                    errors.flush()
                    os.fsync(errors.fileno())
                    if isinstance(exc, RateLimited):
                        raise
                    log(f"  ERROR: {exc}")
                    continue
                # Disk failures must stop the run, not discard further captures.
                output.write(snapshot + "\n")
                output.flush()
                os.fsync(output.fileno())
                saved += 1
                log(f"  OK: {snapshot}")
        log(f"Finished: {saved} confirmed ({reused} reused locally), {failed} failed, {sitemap_failures} sitemap errors.")
        log(f"TXT: {output_path}")
        log(f"Failure details: {failure_path}")
        return int(bool(failed or sitemap_failures))
    except KeyboardInterrupt:
        log(f"Interrupted: {saved} saved, {failed} failed. Completed lines are preserved.")
        if output_path:
            log(f"TXT: {output_path}")
        return 130
    except (ExportError, OSError, UnicodeError) as exc:
        log(f"ERROR: {exc}")
        if output_path:
            log(f"Completed lines remain in: {output_path}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
