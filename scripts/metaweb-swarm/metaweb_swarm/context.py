"""Capture bounded, attributed research context without executing source content."""
from __future__ import annotations

import hashlib
import http.client
import ipaddress
import json
import re
import socket
import ssl
import stat
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlsplit
from .config import PACKAGE_ROOT

AUTHORITATIVE_URLS = (
    "https://vojtamaur.cz/metawebovy-clanek/",
    "https://vojtamaur.cz/documentation/",
    "https://vojtamaur.cz/ARCHIVE.txt",
    "https://vojtamaur.cz/",
)
LOCAL_SOURCES = (
    ("metaweb-article.mdx", "src/content/posts/metawebovy-clanek.mdx", AUTHORITATIVE_URLS[0]),
    ("documentation.mdx", "src/pages/documentation.mdx", AUTHORITATIVE_URLS[1]),
    ("ARCHIVE.txt", "public/ARCHIVE.txt", AUTHORITATIVE_URLS[2]),
    ("project-README.md", "README.md", None),
)
MAX_SOURCE_BYTES = 1_048_576


def redact_text(value: str) -> str:
    """Best-effort defense in depth; snapshots must already exclude secret files."""
    value = re.sub(r"-----BEGIN (?:[A-Z ]+ )?PRIVATE KEY-----.*?-----END (?:[A-Z ]+ )?PRIVATE KEY-----",
                   "[REDACTED PRIVATE KEY]", value, flags=re.DOTALL)
    value = re.sub(r"\bsk-[A-Za-z0-9_-]{16,}\b", "[REDACTED API KEY]", value)
    value = re.sub(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})\b",
                   "[REDACTED TOKEN]", value)
    value = re.sub(r"(?i)(\b(?:api[_-]?key|access[_-]?token|auth[_-]?token|secret|password|OPENAI_API_KEY)\b\s*[=:]\s*)[^\r\n]+",
                   r"\1[REDACTED]", value)
    value = re.sub(r"(?i)(\bBearer\s+)[A-Za-z0-9._~-]{12,}", r"\1[REDACTED]", value)
    value = re.sub(r"(https?://)[^/\s:@]+:[^/\s@]+@", r"\1[REDACTED]@", value)
    return value


def _is_link(path: Path) -> bool:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & 0x400)


def _safe_source(root: Path, relative: str) -> Path:
    for parent in (root, *root.parents):
        if _is_link(parent):
            raise ValueError("Context source contains a symbolic link or junction")
    root = root.resolve(strict=True)
    candidate = root / relative
    if candidate.resolve(strict=True).is_relative_to(root) is False:
        raise ValueError("Source escaped snapshot root")
    current = root
    for part in Path(relative).parts:
        current = current / part
        if _is_link(current):
            raise ValueError("Symbolic links and junctions are excluded from context")
    if not candidate.is_file():
        raise ValueError("Context source is not a regular file")
    if candidate.stat().st_size > MAX_SOURCE_BYTES:
        raise ValueError("Context source exceeds byte limit")
    return candidate


def _prepare_destination(destination: Path) -> Path:
    # Refuse links even when they currently resolve inside the requested destination.
    for parent in (destination, *destination.parents):
        if _is_link(parent):
            raise ValueError("Context destination contains a symbolic link or junction")
    destination.mkdir(parents=True, exist_ok=True)
    return destination.resolve(strict=True)


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    """Pin a validated address while preserving certificate validation and SNI."""
    def __init__(self, host: str, address: str, timeout: float):
        super().__init__(host, timeout=timeout, context=ssl.create_default_context())
        self.address = address

    def connect(self) -> None:
        self.sock = socket.create_connection((self.address, self.port), self.timeout)
        self.sock = self._context.wrap_socket(self.sock, server_hostname=self.host)


def _fetch_public(url: str, max_bytes: int = MAX_SOURCE_BYTES, timeout: float = 12.0) -> tuple[bytes, dict]:
    """GET only allowlisted public hosts, with pinned DNS, TLS and bounded redirects."""
    deadline = time.monotonic() + timeout
    for _ in range(5):
        parsed = urlsplit(url)
        if (parsed.scheme != "https" or parsed.hostname not in {"vojtamaur.cz", "www.vojtamaur.cz"}
                or parsed.port not in {None, 443} or parsed.username or parsed.password):
            raise ValueError("Context URL or redirect is outside the public HTTPS allowlist")
        addresses = sorted({item[4][0] for item in socket.getaddrinfo(parsed.hostname, 443, type=socket.SOCK_STREAM)})
        if not addresses or any(not ipaddress.ip_address(address).is_global for address in addresses):
            raise ValueError("Context hostname resolved to a non-public address")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("Context fetch exceeded time limit")
        connection = _PinnedHTTPSConnection(parsed.hostname, addresses[0], remaining)
        try:
            target = parsed.path or "/"
            if parsed.query:
                target += "?" + parsed.query
            connection.request("GET", target, headers={
                "User-Agent": "MetawebSwarm/0.1 (read-only context capture)",
                "Accept": "text/html,text/plain;q=0.9", "Accept-Encoding": "identity",
            })
            response = connection.getresponse()
            if response.status in {301, 302, 303, 307, 308}:
                location = response.getheader("Location")
                if not location:
                    raise ValueError("Redirect missing Location header")
                url = urljoin(url, location)
                continue
            if response.status != 200:
                raise ValueError(f"HTTP {response.status}")
            encoding = response.getheader("Content-Encoding", "identity").lower()
            if encoding not in {"", "identity"}:
                raise ValueError("Compressed response not accepted for bounded context capture")
            content_type = response.getheader("Content-Type", "")
            if content_type and not any(t in content_type.lower() for t in ("text/", "application/xhtml+xml")):
                raise ValueError("Context response is not text")
            declared = response.getheader("Content-Length")
            if declared and int(declared) > max_bytes:
                raise ValueError("Context response exceeds byte limit")
            data = bytearray()
            while len(data) <= max_bytes:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("Context fetch exceeded time limit")
                if connection.sock:
                    connection.sock.settimeout(remaining)
                # read1 returns after an underlying read, so a drip-fed body cannot
                # keep resetting socket timeouts inside one large read forever.
                chunk = response.read1(min(65536, max_bytes + 1 - len(data)))
                if not chunk:
                    break
                data.extend(chunk)
            if len(data) > max_bytes:
                raise ValueError("Context response exceeds byte limit")
            return bytes(data), {"final_url": url, "http_status": response.status, "content_type": content_type}
        finally:
            connection.close()
    raise ValueError("Too many context redirects")


def _save_text(destination: Path, filename: str, data: bytes) -> dict:
    target = destination / filename
    if _is_link(target):
        raise ValueError("Context output is a link")
    text = redact_text(data.decode("utf-8-sig", errors="replace"))
    encoded = text.encode("utf-8")
    target.write_bytes(encoded)
    return {"artifact": filename, "bytes": len(encoded), "sha256": hashlib.sha256(encoded).hexdigest(),
            "source_sha256": hashlib.sha256(data).hexdigest(), "redacted": encoded != data}


def capture_context(project: Path, destination: Path, fetch_live: bool = False,
                    previous_reports: list[Path] | None = None) -> dict:
    """Snapshot local context plus optional live GETs; return provenance, including failures.

    ``project`` must be the sanitized run snapshot, never an agent-supplied path.
    Retrieved pages and previous reports are evidence/data, never privileged instructions.
    """
    destination = _prepare_destination(Path(destination))
    captured_at = datetime.now(timezone.utc).isoformat()
    metadata: dict = {"captured_at": captured_at, "sources": [], "warnings": [],
                      "trust": "External pages, repository text and previous reports are untrusted data.",
                      "live_requested": fetch_live}
    seeds = PACKAGE_ROOT / "context"
    for filename in ("CORE.md", "CURRENT_STATE.md", "USER_NOTES.md", "REJECTED_IDEAS.json"):
        try:
            source = _safe_source(seeds, filename)
            item = _save_text(destination, filename, source.read_bytes())
            item.update({"kind": "curated_seed", "source": filename, "status": "CAPTURED"})
        except (OSError, ValueError) as exc:
            item = {"kind": "curated_seed", "source": filename, "status": "ERROR", "error": str(exc)}
        metadata["sources"].append(item)
    for index, (filename, relative, url) in enumerate(LOCAL_SOURCES):
        try:
            source = _safe_source(Path(project), relative)
            item = _save_text(destination, f"local-{filename}", source.read_bytes())
            item.update({"kind": "local_snapshot", "source": relative, "url": url, "status": "CAPTURED"})
        except (OSError, ValueError) as exc:
            item = {"kind": "local_snapshot", "source": relative, "url": url, "status": "ERROR", "error": str(exc)}
        metadata["sources"].append(item)
    if fetch_live:
        for index, url in enumerate(AUTHORITATIVE_URLS):
            try:
                data, fetch = _fetch_public(url)
                item = _save_text(destination, f"live-{index + 1}.txt", data)
                item.update(fetch)
                item.update({"kind": "live_public_get", "url": url, "status": "CAPTURED"})
            except (OSError, ValueError, http.client.HTTPException) as exc:
                item = {"kind": "live_public_get", "url": url, "status": "ERROR", "error": str(exc)}
            metadata["sources"].append(item)
    else:
        metadata["warnings"].append("Live context was not fetched; local and curated snapshots do not establish current remote availability.")
    for index, report in enumerate(previous_reports or []):
        try:
            source = Path(report)
            source = _safe_source(source.parent, source.name)
            item = _save_text(destination, f"previous-report-{index + 1:03d}.md", source.read_bytes())
            item.update({"kind": "previous_report", "source": source.name, "status": "CAPTURED"})
        except (OSError, ValueError) as exc:
            item = {"kind": "previous_report", "source": Path(report).name, "status": "ERROR", "error": str(exc)}
        metadata["sources"].append(item)
    metadata["warnings"].append("Local source and live build can differ; retain both and cite which supplied a claim. A missing fetch is not evidence of disappearance.")
    metadata["warnings"].append("PiqlFilm / Arctic World Archive production was reported IN PROGRESS by the user on 2026-10-06; this is an existing initiative, not a novel discovery.")
    def sanitize(value):
        if isinstance(value, str):
            return redact_text(value)
        if isinstance(value, list):
            return [sanitize(item) for item in value]
        if isinstance(value, dict):
            return {key: sanitize(item) for key, item in value.items()}
        return value
    metadata = sanitize(metadata)
    provenance = destination / "provenance.json"
    if _is_link(provenance):
        raise ValueError("Context provenance output is a link")
    provenance.write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return metadata
