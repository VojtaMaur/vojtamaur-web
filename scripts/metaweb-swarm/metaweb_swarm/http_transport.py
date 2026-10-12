"""Provider-independent HTTP, with explicit credentials and pinned public sockets.

This executor deliberately bypasses urllib proxy handling, cookie jars, netrc,
Git credential helpers and the host's ordinary authentication environment.  It
does not follow redirects or execute downloaded content.  The engine owns
approval, run-wide counters and writing the returned, sanitized response bytes.
"""
from __future__ import annotations

import hashlib
import http.client
import io
import ipaddress
import json
import math
import os
import re
import socket
import ssl
import threading
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlencode, urlsplit, urlunsplit, unquote

from .workspace import _confined, _relative, _read_bytes

READ_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
METHODS = READ_METHODS | {"POST", "PUT", "PATCH", "DELETE"}
DEFAULTS = {
    "http_access": "disabled", "max_http_requests": 100,
    "max_http_request_bytes": 16 * 1024 * 1024,
    "max_http_response_bytes": 16 * 1024 * 1024,
    "max_http_total_bytes": 128 * 1024 * 1024,
    "http_timeout_seconds": 30, "http_credentials": [], "http_test_origins": [],
}
_TOKEN = re.compile(r"^[!#$%&'*+.^_`|~0-9A-Za-z-]+$")
_IDENTIFIER = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,79}$")
_ENV = re.compile(r"^META_SWARM_CRED_[A-Z0-9_]+$")
_SECRET_FIELD = re.compile(r"(?:authorization|password|passwd|secret|token|api[_-]?key|cookie|signature|credential)", re.I)
_SECRET_TEXT = re.compile(
    r"\b(?:sk-[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9_]{20,}|"
    r"github_pat_[A-Za-z0-9_]{20,}|glpat-[A-Za-z0-9_-]{10,}|"
    r"AKIA[A-Z0-9]{16})\b"
)
_FORGE_HOSTS = ("github.com", "githubusercontent.com", "gitlab.com", "codeberg.org")
_PRODUCTION_HOSTS = ("vojtamaur.cz",)
_FORBIDDEN_HEADERS = {
    "host", "content-length", "transfer-encoding", "connection", "upgrade",
    "te", "trailer", "expect", "proxy-connection", "forwarded",
    "x-forwarded-host", "x-forwarded-for", "proxy-authorization", "cookie",
    "authorization", "accept-encoding", "x-http-method-override",
    "x-method-override", "x-http-method",
}
_DNS_SLOTS = threading.BoundedSemaphore(4)


class HttpPolicyError(ValueError):
    """A request cannot be represented or authorized safely."""


class HttpTransportError(RuntimeError):
    """A transport failure, with no secret-bearing diagnostic arguments."""

    def __init__(self, message: str, *, outcome_uncertain: bool = False, stage: str = ""):
        super().__init__(message)
        self.outcome_uncertain = outcome_uncertain
        self.stage = stage


def redact(value: Any, secrets: tuple[str, ...] | list[str] = ()) -> Any:
    """Redact explicit values and common credential fields in audit material."""
    if isinstance(value, dict):
        return {str(key): "[REDACTED]" if _SECRET_FIELD.search(str(key)) else redact(item, secrets)
                for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact(item, secrets) for item in value]
    if isinstance(value, str):
        result = value
        for secret in sorted((s for s in secrets if s), key=len, reverse=True):
            result = result.replace(secret, "[REDACTED]")
        result = _SECRET_TEXT.sub("[REDACTED]", result)
        result = re.sub(r'(?i)([?&](?:[^=&\s]*?(?:token|signature|credential|secret|api[_-]?key))=)[^&\s"\x27<>]+', r'\1[REDACTED]', result)
        return re.sub(r'(?i)(["\']?(?:password|passwd|access[_-]?token|refresh[_-]?token|api[_-]?key|secret)["\']?\s*[:=]\s*)["\']?[^\s,}\r\n"\']+', r'\1[REDACTED]', result)
    return value


def _host(value: str) -> str:
    if not isinstance(value, str) or not value or any(c.isspace() or ord(c) < 32 for c in value):
        raise HttpPolicyError("Invalid HTTP host")
    if value.endswith(".") or "%" in value or "\\" in value:
        raise HttpPolicyError("Ambiguous HTTP host")
    try:
        return str(ipaddress.ip_address(value))
    except ValueError:
        try:
            encoded = value.encode("idna").decode("ascii").lower()
        except UnicodeError as exc:
            raise HttpPolicyError("Invalid HTTP host") from exc
        if len(encoded) > 253 or any(not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label)
                                      for label in encoded.split(".")):
            raise HttpPolicyError("Invalid HTTP host")
        return encoded


def _public_ip(value: str) -> bool:
    address = ipaddress.ip_address(value)
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
        address = address.ipv4_mapped
    if isinstance(address, ipaddress.IPv6Address):
        # Transition/translation addresses can encode a private IPv4 target.
        if (address.sixtofour is not None or address.teredo is not None
                or address in ipaddress.ip_network("64:ff9b::/96")
                or address in ipaddress.ip_network("64:ff9b:1::/48")):
            return False
    # is_global by itself includes multicast on some Python releases.
    return address.is_global and not (address.is_multicast or address.is_reserved or address.is_unspecified)


def _origin(parts) -> str:
    host = _host(parts.hostname or "")
    port = parts.port if parts.port is not None else (443 if parts.scheme == "https" else 80)
    displayed = f"[{host}]" if ":" in host else host
    default = 443 if parts.scheme == "https" else 80
    return f"{parts.scheme}://{displayed}" + (f":{port}" if port != default else "")


def _test_origins(config: dict) -> set[str]:
    result = set()
    origins = config.get("http_test_origins", [])
    if not isinstance(origins, list):
        raise HttpPolicyError("http_test_origins must be a list")
    for origin in origins:
        try:
            parts = urlsplit(origin)
            address = ipaddress.ip_address(parts.hostname or "")
            if (parts.scheme != "http" or not address.is_loopback or parts.username is not None
                    or parts.password is not None or parts.path or parts.query or parts.fragment
                    or not 1 <= (parts.port if parts.port is not None else 80) <= 65535):
                raise ValueError()
            normalized = _origin(parts)
        except (ValueError, TypeError) as exc:
            raise HttpPolicyError("Test origins must be exact loopback HTTP origins without paths") from exc
        if normalized != origin:
            raise HttpPolicyError("Test origins must use their canonical exact origin")
        result.add(normalized)
    return result


def validate_http_config(config: dict) -> None:
    if config.get("http_access", "disabled") not in {"disabled", "read-only", "enabled"}:
        raise HttpPolicyError("http_access must be disabled, read-only or enabled")
    for name in ("max_http_requests", "max_http_request_bytes", "max_http_response_bytes", "max_http_total_bytes"):
        value = config.get(name, DEFAULTS[name])
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise HttpPolicyError(f"{name} must be a positive integer")
    timeout = config.get("http_timeout_seconds", 30)
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout <= 0:
        raise HttpPolicyError("http_timeout_seconds must be finite and positive")
    credentials = config.get("http_credentials", [])
    if not isinstance(credentials, list):
        raise HttpPolicyError("http_credentials must be a list")
    seen = set()
    test_hosts = {urlsplit(origin).hostname for origin in _test_origins(config)}
    for resource in credentials:
        if not isinstance(resource, dict) or set(resource) - {"id", "env", "hosts", "header", "scheme"}:
            raise HttpPolicyError("Invalid HTTP credential resource")
        ident, variable = resource.get("id", ""), resource.get("env", "")
        if not isinstance(ident, str) or not _IDENTIFIER.fullmatch(ident) or ident in seen:
            raise HttpPolicyError("HTTP credential IDs must be valid and unique")
        seen.add(ident)
        if not isinstance(variable, str) or not _ENV.fullmatch(variable):
            raise HttpPolicyError("Only dedicated META_SWARM_CRED_* environment variables may be assigned")
        hosts = resource.get("hosts", [])
        if not isinstance(hosts, list) or not hosts:
            raise HttpPolicyError("Credential resources need exact public HTTPS host scopes")
        for host in hosts:
            normalized = _host(host)
            if host != normalized or "." not in host and ":" not in host or host in {"localhost", "localhost.localdomain"}:
                raise HttpPolicyError("Credential scope must be a canonical public host, not an origin or wildcard")
            try:
                address = ipaddress.ip_address(host)
            except ValueError:
                if host.endswith((".local", ".localhost", ".internal", ".test", ".invalid")):
                    raise HttpPolicyError("Credential scopes cannot use private or reserved names")
            else:
                if not _public_ip(str(address)) and not (address.is_loopback and host in test_hosts):
                    raise HttpPolicyError("Credential scopes cannot use private addresses")
        header = resource.get("header", "Authorization")
        scheme = resource.get("scheme", "Bearer" if str(header).lower() == "authorization" else "")
        if not isinstance(header, str) or not _TOKEN.fullmatch(header) or header.lower() in (_FORBIDDEN_HEADERS - {"authorization"}):
            raise HttpPolicyError("Invalid assigned credential header")
        if not isinstance(scheme, str) or any(ord(c) < 32 or ord(c) > 126 for c in scheme) or len(scheme) > 80:
            raise HttpPolicyError("Invalid credential scheme")
    _test_origins(config)


def _url(value: str, config: dict) -> tuple[str, str, int, bool]:
    if not isinstance(value, str) or not value or len(value) > 16384 or any(c.isspace() or ord(c) < 32 for c in value) or "\\" in value:
        raise HttpPolicyError("URL must be an HTTP URL without whitespace or control characters")
    try:
        parts = urlsplit(value)
        host = _host(parts.hostname or "")
        port = parts.port if parts.port is not None else (443 if parts.scheme == "https" else 80)
        origin = _origin(parts)
    except (ValueError, TypeError) as exc:
        raise HttpPolicyError("Invalid HTTP URL") from exc
    if parts.username is not None or parts.password is not None or parts.fragment or not 1 <= port <= 65535:
        raise HttpPolicyError("URL credentials, fragments and invalid ports are forbidden")
    local_test = origin in _test_origins(config)
    if parts.scheme != "https" and not (parts.scheme == "http" and local_test):
        raise HttpPolicyError("Public HTTP requires verified HTTPS; loopback HTTP requires an explicit test origin")
    if not local_test:
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            if host == "localhost" or "." not in host or host.endswith((".localhost", ".local", ".internal", ".test", ".invalid")):
                raise HttpPolicyError("Local and reserved HTTP names are forbidden")
        else:
            if not _public_ip(str(address)):
                raise HttpPolicyError("Non-public HTTP addresses are forbidden")
    authority = origin.split("://", 1)[1]
    path = parts.path or "/"
    # http.client accepts an ASCII request target.  Explicitly reject malformed
    # Unicode rather than silently changing approval-bound request bytes.
    try:
        (path + parts.query).encode("ascii")
    except UnicodeEncodeError as exc:
        raise HttpPolicyError("Non-ASCII URL paths must be percent encoded") from exc
    return urlunsplit((parts.scheme, authority, path, parts.query, "")), host, port, local_test


def _protected(host: str) -> bool:
    return any(host == suffix or host.endswith("." + suffix) for suffix in (*_FORGE_HOSTS, *_PRODUCTION_HOSTS))


def _deny_git_write(url: str) -> None:
    decoded = url.lower()
    for _ in range(4):
        decoded = unquote(decoded)
    if "git-receive-pack" in decoded or re.search(r"(?:/|=)receive-pack(?:[/?&]|$)", decoded):
        raise HttpPolicyError("Git repository writes are forbidden, regardless of HTTP method")


def _headers(value: Any) -> dict[str, str]:
    if not isinstance(value, dict) or len(value) > 64:
        raise HttpPolicyError("headers must be an object with at most 64 entries")
    result, seen = {}, set()
    for name, content in value.items():
        if not isinstance(name, str) or not _TOKEN.fullmatch(name):
            raise HttpPolicyError("Invalid HTTP header name")
        lower = name.lower()
        if lower in seen or lower in _FORBIDDEN_HEADERS or _SECRET_FIELD.search(lower):
            raise HttpPolicyError("Authentication, routing and framing headers must not be supplied by an agent")
        seen.add(lower)
        if not isinstance(content, str) or len(content) > 8192 or any(ord(c) < 32 and c != "\t" or ord(c) == 127 for c in content):
            raise HttpPolicyError("Invalid HTTP header value")
        try:
            content.encode("latin-1")
        except UnicodeEncodeError as exc:
            raise HttpPolicyError("HTTP header values must be Latin-1") from exc
        result[name] = content
    if sum(len(k) + len(v) + 4 for k, v in result.items()) > 32768:
        raise HttpPolicyError("Request headers exceed 32768 bytes")
    return result


def _file(workspace, relative: str, maximum: int) -> tuple[bytes, dict]:
    _confined(workspace.root, relative)
    if str(relative).replace("\\", "/") == ".metaweb-workspace.json":
        raise HttpPolicyError("Workspace metadata cannot be uploaded")
    data = _read_bytes(workspace.root, _relative(relative), maximum)
    return data, {"path": str(relative).replace("\\", "/"), "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


@dataclass(frozen=True)
class PreparedRequest:
    method: str
    url: str
    host: str
    port: int
    headers: dict[str, str]
    body: bytes = field(repr=False)
    response_path: str = ""
    credential_id: str = ""
    local_test: bool = False
    descriptor: dict = field(default_factory=dict)


def normalize_request(spec: dict, config: dict, workspace) -> tuple[dict, PreparedRequest]:
    """Validate and bind exact request bytes before host approval or networking."""
    validate_http_config(config)
    if config.get("http_access", "disabled") == "disabled":
        raise HttpPolicyError("HTTP access is disabled")
    if not isinstance(spec, dict) or set(spec) - {"method", "url", "headers", "query", "body_text", "body_json", "upload_path", "multipart_fields", "multipart_files", "credential_id", "response_path"}:
        raise HttpPolicyError("Unknown HTTP request fields")
    method = spec.get("method", "GET")
    if not isinstance(method, str) or method.upper() not in METHODS:
        raise HttpPolicyError("Supported HTTP methods: GET HEAD OPTIONS POST PUT PATCH DELETE")
    method = method.upper()
    if config.get("http_access") == "read-only" and method not in READ_METHODS:
        raise HttpPolicyError("HTTP access is read-only")
    headers = _headers(spec.get("headers", {}))
    query = spec.get("query", {})
    if not isinstance(query, dict):
        raise HttpPolicyError("query must be an object")
    for key, value in query.items():
        if not isinstance(key, str) or not isinstance(value, (str, int, float, bool, list)):
            raise HttpPolicyError("Query values must be strings, scalar values or lists")
        if isinstance(value, list) and any(not isinstance(v, (str, int, float, bool)) for v in value):
            raise HttpPolicyError("Query lists must contain scalar values")
    url = spec.get("url", "")
    if query:
        url += ("&" if "?" in url else "?") + urlencode(query, doseq=True)
    url, host, port, local_test = _url(url, config)
    _deny_git_write(url)
    if _protected(host) and method not in READ_METHODS:
        raise HttpPolicyError("Mutations to GitHub, GitLab, Codeberg and the production Metaweb site are forbidden")
    credential_id = spec.get("credential_id", "")
    if not isinstance(credential_id, str):
        raise HttpPolicyError("credential_id must be a string")
    resource = None
    if credential_id:
        resource = next((c for c in config.get("http_credentials", []) if c["id"] == credential_id), None)
        if resource is None or host not in resource["hosts"]:
            raise HttpPolicyError("Credential is not explicitly assigned to this HTTPS host")
    response_path = spec.get("response_path", "")
    if not isinstance(response_path, str):
        raise HttpPolicyError("response_path must be a relative string")
    if response_path:
        _confined(workspace.root, response_path)
        if response_path.replace("\\", "/") == ".metaweb-workspace.json":
            raise HttpPolicyError("Workspace metadata is protected")
    maximum = config.get("max_http_request_bytes", DEFAULTS["max_http_request_bytes"])
    text, raw_json = spec.get("body_text", ""), spec.get("body_json", "")
    upload, fields, files = spec.get("upload_path", ""), spec.get("multipart_fields", {}), spec.get("multipart_files", [])
    if not isinstance(text, str) or not isinstance(upload, str) or not isinstance(fields, dict) or not isinstance(files, list):
        raise HttpPolicyError("Invalid HTTP body fields")
    has_json = raw_json != "" and raw_json is not None
    if sum(bool(v) for v in (text, has_json, upload, bool(fields or files))) > 1:
        raise HttpPolicyError("Choose exactly one body: text, JSON, file, or multipart")
    artifacts, body, json_value = [], b"", None
    if text:
        body = text.encode("utf-8")
    elif has_json:
        try:
            json_value = json.loads(raw_json) if isinstance(raw_json, str) else raw_json
            body = json.dumps(json_value, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
        except (ValueError, TypeError) as exc:
            raise HttpPolicyError("body_json must be valid JSON") from exc
        if not any(k.lower() == "content-type" for k in headers):
            headers["Content-Type"] = "application/json"
    elif upload:
        body, record = _file(workspace, upload, maximum)
        artifacts.append(record)
    elif fields or files:
        if len(fields) + len(files) > 128:
            raise HttpPolicyError("Too many multipart entries")
        parts, parts_bytes = [], 0
        for name, content in fields.items():
            if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,120}", name) or not isinstance(content, str):
                raise HttpPolicyError("Multipart field names must be simple names and values must be strings")
            prefix, content_bytes = f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode(), content.encode("utf-8")
            parts_bytes += len(prefix) + len(content_bytes) + 55
            if parts_bytes + 55 > maximum:
                raise HttpPolicyError("Multipart request exceeds max_http_request_bytes")
            parts.append((prefix, content_bytes))
        for record in files:
            if not isinstance(record, dict) or set(record) - {"field", "path", "filename", "content_type"}:
                raise HttpPolicyError("Invalid multipart file")
            name, path = record.get("field", ""), record.get("path", "")
            filename = record.get("filename", str(path).replace("\\", "/").rsplit("/", 1)[-1])
            content_type = record.get("content_type", "application/octet-stream")
            if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,120}", name):
                raise HttpPolicyError("Invalid multipart file field")
            if (not isinstance(filename, str) or not filename or len(filename) > 240
                    or any(ord(c) < 32 or ord(c) > 126 or c in {'"', "\\", "/"} for c in filename)):
                raise HttpPolicyError("Multipart filename must be a plain ASCII filename")
            if not isinstance(content_type, str) or not re.fullmatch(r"[A-Za-z0-9.+-]+/[A-Za-z0-9.+-]+", content_type):
                raise HttpPolicyError("Invalid multipart content type")
            prefix = f'Content-Disposition: form-data; name="{name}"; filename="{filename}"\r\nContent-Type: {content_type}\r\n\r\n'.encode()
            if maximum - parts_bytes - len(prefix) - 110 <= 0:
                raise HttpPolicyError("Multipart request exceeds max_http_request_bytes")
            content, metadata = _file(workspace, path, maximum - parts_bytes - len(prefix) - 110)
            parts_bytes += len(prefix) + len(content) + 55
            artifacts.append(metadata)
            parts.append((prefix, content))
        # A deterministic boundary makes repeated approval-bound normalization
        # identical.  Reject a collision rather than creating a different body.
        digest = hashlib.sha256(b"".join(prefix + content for prefix, content in parts)).hexdigest()
        boundary = "metaweb-" + digest[:40]
        if any(boundary.encode() in content for _, content in parts):
            raise HttpPolicyError("Multipart boundary collision")
        body = b"".join(b"--" + boundary.encode() + b"\r\n" + prefix + content + b"\r\n" for prefix, content in parts)
        body += b"--" + boundary.encode() + b"--\r\n"
        headers = {k: v for k, v in headers.items() if k.lower() != "content-type"}
        headers["Content-Type"] = "multipart/form-data; boundary=" + boundary
    if len(body) > maximum:
        raise HttpPolicyError("HTTP request body exceeds max_http_request_bytes")
    if method in READ_METHODS and body:
        raise HttpPolicyError("GET, HEAD and OPTIONS must not carry a request body")
    descriptor = {
        "method": method, "url": _redact_url(url), "headers": redact(headers),
        "bytes": len(body), "body_sha256": hashlib.sha256(body).hexdigest(),
        "credential_id": credential_id, "response_path": response_path,
        "files": artifacts,
    }
    wire_bound = {"method": method, "url": url, "headers": headers,
                  "body_sha256": descriptor["body_sha256"], "credential_grant": resource}
    descriptor["wire_sha256"] = hashlib.sha256(json.dumps(wire_bound, sort_keys=True, ensure_ascii=False,
                                                          separators=(",", ":")).encode("utf-8")).hexdigest()
    if json_value is not None:
        descriptor["body_preview"] = json.dumps(redact(json_value), ensure_ascii=False)[:1200]
    elif text:
        descriptor["body_preview"] = redact(text)[:1200]
    return descriptor, PreparedRequest(method, url, host, port, headers, body, response_path, credential_id, local_test, descriptor)


def _redact_url(url: str, secrets: tuple[str, ...] = ()) -> str:
    from urllib.parse import parse_qsl
    parts = urlsplit(url)
    query = [(key, "[REDACTED]" if _SECRET_FIELD.search(key) else redact(value, secrets))
             for key, value in parse_qsl(parts.query, keep_blank_values=True)]
    return redact(urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), "")), secrets)


def _remaining(deadline: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("HTTP deadline exceeded")
    return remaining


def _resolve(host: str, port: int, local_test: bool, deadline: float) -> list[tuple]:
    try:
        literal = ipaddress.ip_address(host)
        entries = [(socket.AF_INET6 if literal.version == 6 else socket.AF_INET, socket.SOCK_STREAM, 0, "", (host, port))]
    except ValueError:
        if not _DNS_SLOTS.acquire(blocking=False):
            raise HttpTransportError("HTTP DNS resolver capacity exhausted")
        complete, result = threading.Event(), []
        def resolve():
            try:
                result.append(socket.getaddrinfo(host, port, type=socket.SOCK_STREAM))
            except Exception as exc:
                result.append(exc)
            finally:
                complete.set()
                _DNS_SLOTS.release()
        threading.Thread(target=resolve, daemon=True, name="metaweb-http-dns").start()
        if not complete.wait(_remaining(deadline)):
            raise TimeoutError("HTTP DNS deadline exceeded")
        if isinstance(result[0], Exception):
            raise HttpTransportError("HTTP DNS resolution failed")
        entries = result[0]
    if not entries:
        raise HttpTransportError("HTTP DNS resolution returned no addresses")
    normalized = []
    for family, _, proto, _, address in entries:
        if family not in {socket.AF_INET, socket.AF_INET6}:
            raise HttpPolicyError("Unsupported DNS address family")
        ip = address[0]
        if local_test:
            if not ipaddress.ip_address(ip).is_loopback:
                raise HttpPolicyError("Test origins cannot resolve outside loopback")
        elif not _public_ip(ip):
            raise HttpPolicyError("DNS returned a non-public address; request refused")
        item = (family, proto, address)
        if item not in normalized:
            normalized.append(item)
    return normalized


class _SocketInput(io.RawIOBase):
    def __init__(self, sock: socket.socket, deadline: float, on_close):
        super().__init__()
        self.sock, self.deadline, self.on_close = sock, deadline, on_close

    def readable(self):
        return True

    def readinto(self, buffer):
        self.sock.settimeout(_remaining(self.deadline))
        return self.sock.recv_into(buffer)

    def close(self):
        if not self.closed:
            super().close()
            self.on_close()


class _BoundReader(io.BufferedReader):
    def __init__(self, raw):
        super().__init__(raw, buffer_size=8192)
        self.header_bytes, self.count_headers = 0, True

    def readline(self, size=-1):
        line = super().readline(size)
        if self.count_headers:
            self.header_bytes += len(line)
            if self.header_bytes > 65536:
                raise HttpTransportError("HTTP response headers exceed 65536 bytes", outcome_uncertain=True)
        return line


class _DeadlineSocket:
    def __init__(self, sock, deadline):
        self.sock, self.deadline = sock, deadline
        self.reader, self.close_requested, self.reader_open = None, False, False

    def makefile(self, mode):
        if mode != "rb":
            raise HttpTransportError("Unsupported HTTP stream mode")
        self.reader_open = True
        self.reader = _BoundReader(_SocketInput(self.sock, self.deadline, self._reader_closed))
        return self.reader

    def sendall(self, data):
        self.sock.settimeout(_remaining(self.deadline))
        self.sock.sendall(data)

    def close(self):
        # HTTPConnection closes a will_close connection immediately after
        # parsing HTTP/1.0 headers. Native socket.makefile keeps its descriptor
        # alive for the response reader; this wrapper must do the same.
        self.close_requested = True
        if not self.reader_open:
            self.sock.close()

    def _reader_closed(self):
        self.reader_open = False
        if self.close_requested:
            self.sock.close()

    def force_close(self):
        self.close_requested = True
        if self.reader is not None and not self.reader.closed:
            self.reader.close()
        self.sock.close()


def _sanitize_body(body: bytes, content_type: str, secrets: tuple[str, ...]) -> bytes:
    # Even a nominally binary response must not persist an echoed assigned key.
    cleaned = body
    for secret in sorted((s for s in secrets if s), key=len, reverse=True):
        cleaned = cleaned.replace(secret.encode("utf-8"), b"[REDACTED]")
    try:
        text = cleaned.decode("utf-8")
    except UnicodeDecodeError:
        return cleaned
    if "json" in content_type.lower() or text.lstrip().startswith(("{", "[")):
        try:
            parsed = json.loads(text)
            safe = redact(parsed, secrets)
            if safe != parsed:
                return json.dumps(safe, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        except (ValueError, TypeError):
            pass
    text = redact(text, secrets)
    # Textual key=value responses and truncated JSON must also be safe.
    text = re.sub(r'(?i)(["\']?(?:password|passwd|access[_-]?token|refresh[_-]?token|api[_-]?key|secret)["\']?\s*[:=]\s*)["\']?[^\s,}\r\n"\']+', r'\1[REDACTED]', text)
    return text.encode("utf-8")


def execute_request(prepared: PreparedRequest, config: dict, timeout: float | None = None, private_capture=None) -> tuple[dict, bytes]:
    """Execute once, returning metadata and sanitized bytes; never follow redirects.

    ``request_bytes`` counts body bytes. ``response_bytes`` counts received body
    bytes before sanitization (including one overflow probe byte).  Raw and stored
    hashes differ when credentials or sensitive response fields were redacted.
    DNS/connection failures raise sanitized exceptions.  Failures after sending
    starts return an uncertain result, preventing silent retries of mutations.
    """
    validate_http_config(config)
    duration = min(float(config.get("http_timeout_seconds", 30)), float(timeout) if timeout is not None else float("inf"))
    if not math.isfinite(duration) or duration <= 0:
        raise HttpPolicyError("HTTP timeout must be finite and positive")
    deadline = time.monotonic() + duration
    # Recheck policy at execution, in case permission was lowered after approval.
    normalized_url, host, port, local_test = _url(prepared.url, config)
    if normalized_url != prepared.url or host != prepared.host or port != prepared.port or local_test != prepared.local_test:
        raise HttpPolicyError("Prepared HTTP target changed")
    access = config.get("http_access", "disabled")
    if access == "disabled" or access == "read-only" and prepared.method not in READ_METHODS:
        raise HttpPolicyError("HTTP request is outside the configured access mode")
    _deny_git_write(prepared.url)
    if prepared.method not in METHODS:
        raise HttpPolicyError("Unsupported HTTP method")
    if _protected(host) and prepared.method not in READ_METHODS:
        raise HttpPolicyError("Protected site mutations are forbidden")
    if len(prepared.body) > config.get("max_http_request_bytes", DEFAULTS["max_http_request_bytes"]):
        raise HttpPolicyError("HTTP request body exceeds its configured limit")
    headers, secrets = _headers(prepared.headers), ()
    if prepared.credential_id:
        resource = next((c for c in config.get("http_credentials", []) if c["id"] == prepared.credential_id), None)
        if resource is None or host not in resource["hosts"]:
            raise HttpPolicyError("HTTP credential is not assigned to this HTTPS host")
        secret = os.environ.get(resource["env"], "")  # The sole credential lookup.
        if not secret or len(secret) > 16384 or any(ord(c) < 32 or ord(c) > 126 for c in secret):
            raise HttpPolicyError("Assigned HTTP credential is unavailable or malformed")
        secrets = (secret,)
        scheme = resource.get("scheme", "Bearer" if resource.get("header", "Authorization").lower() == "authorization" else "")
        headers[resource.get("header", "Authorization")] = (scheme + " " if scheme else "") + secret
    try:
        addresses = _resolve(host, port, local_test, deadline)
    except TimeoutError as exc:
        raise HttpTransportError("HTTP DNS deadline exceeded") from exc
    conn = http.client.HTTPConnection(host, port, timeout=_remaining(deadline))
    wrapped, last_error = None, None
    failure_stage = "connect"
    failures = []
    for family, proto, address in addresses:
        sock = socket.socket(family, socket.SOCK_STREAM, proto)
        try:
            failure_stage = "connect"
            sock.settimeout(_remaining(deadline))
            sock.connect(address)
            if urlsplit(prepared.url).scheme == "https":
                failure_stage = "tls"
                sock.settimeout(_remaining(deadline))
                sock = ssl.create_default_context().wrap_socket(sock, server_hostname=host)
            wrapped = _DeadlineSocket(sock, deadline)
            conn.sock = wrapped
            break
        except (OSError, TimeoutError) as exc:
            last_error = exc
            # These socket/TLS errors occur before HTTP request bytes are sent.
            # Include safe per-address diagnostics, never request headers/secrets.
            failures.append(f"{failure_stage}: {type(exc).__name__}: {redact(str(exc), secrets)}")
            sock.close()
    if wrapped is None:
        if isinstance(last_error, (TimeoutError, socket.timeout)):
            raise HttpTransportError("HTTP connection deadline exceeded; " + "; ".join(failures)[-1500:], stage=failure_stage)
        raise HttpTransportError("HTTP connection or verified TLS handshake failed; " + "; ".join(failures)[-1500:], stage=failure_stage)
    parts = urlsplit(prepared.url)
    target = parts.path + ("?" + parts.query if parts.query else "")
    # Host, framing, compression and connection lifetime are host-controlled.
    headers.update({"Host": parts.netloc, "Accept-Encoding": "identity", "Connection": "close"})
    if prepared.body or prepared.method not in READ_METHODS:
        headers["Content-Length"] = str(len(prepared.body))
    if not any(k.lower() == "user-agent" for k in headers):
        headers["User-Agent"] = "MetawebSwarm/HTTP"
    metadata = {"status": None, "headers": {}, "request_bytes": len(prepared.body), "response_bytes": 0,
                "stored_bytes": 0, "truncated": False, "timed_out": False, "outcome_uncertain": False,
                "redirected": False, "url": _redact_url(prepared.url, secrets)}
    raw = bytearray()
    maximum = config.get("max_http_response_bytes", DEFAULTS["max_http_response_bytes"])
    sent = False
    response = None
    try:
        sent = True  # A failed send can still have transmitted bytes.
        conn.request(prepared.method, target, body=prepared.body or None, headers=headers)
        response = conn.getresponse()
        if wrapped.reader:
            wrapped.reader.count_headers = False
        metadata["status"] = response.status
        public_headers = {}
        for key, value in response.getheaders():
            if key.lower() in {"set-cookie", "set-cookie2"}:
                continue
            value = _redact_url(value, secrets) if key.lower() == "location" and value.startswith(("https://", "http://")) else redact(value, secrets)
            public_headers[key] = "[REDACTED]" if _SECRET_FIELD.search(key) else value
        metadata["headers"] = public_headers
        while True:
            _remaining(deadline)
            chunk = response.read1(min(65536, maximum + 1 - len(raw)))
            if not chunk:
                if response.length is not None and response.length > 0:
                    metadata.update(truncated=True, error="HTTP response ended before its declared Content-Length")
                break
            raw.extend(chunk)
            if len(raw) > maximum:
                metadata["truncated"] = True
                break
        metadata["outcome_uncertain"] = bool(metadata["truncated"] and prepared.method not in READ_METHODS)
    except (TimeoutError, socket.timeout):
        metadata.update(timed_out=True, outcome_uncertain=sent and prepared.method not in READ_METHODS,
                        error="HTTP request deadline exceeded")
    except (OSError, http.client.HTTPException, HttpTransportError) as exc:
        metadata.update(outcome_uncertain=sent and prepared.method not in READ_METHODS,
                        error=redact(str(exc), secrets), error_type=type(exc).__name__)
    finally:
        if response is not None:
            response.close()
        conn.close()
        wrapped.force_close()
    raw_bytes = bytes(raw)
    private_json = None
    if private_capture is not None and not metadata.get('truncated') and not metadata.get('error'):
        # Host-only callback preserves returned capability URLs for later steps.
        # Never expose an echoed assigned credential even in the private vault.
        private_bytes = raw_bytes
        for secret in secrets:
            private_bytes = private_bytes.replace(secret.encode(), b'[REDACTED]')
        try:
            private_json = json.loads(private_bytes)
        except (ValueError, UnicodeDecodeError):
            private_json = None
        if private_json is not None:
            metadata['private_response'] = private_capture(private_json)
    stored = _sanitize_body(raw_bytes[:maximum], str(response.getheader("Content-Type", "")) if response else "", secrets)
    if private_json is not None:
        # Capabilities may be opaque paths or use nonstandard query keys. Hide
        # every returned URL from the model/audit copy; the bound vault retains it.
        def hide_urls(value):
            if isinstance(value,dict): return {k:hide_urls(v) for k,v in value.items()}
            if isinstance(value,list): return [hide_urls(v) for v in value]
            if isinstance(value,str): return '[PRIVATE_FLOW_VALUE]'
            return value
        stored = _sanitize_body(json.dumps(hide_urls(private_json),ensure_ascii=False,separators=(',',':')).encode(), 'application/json', secrets)
    if len(stored) > maximum:
        metadata["sanitized_truncated"] = True
        stored = stored[:maximum]
    metadata.update(response_bytes=len(raw_bytes), stored_bytes=len(stored),
                    raw_sha256=hashlib.sha256(raw_bytes).hexdigest(), stored_sha256=hashlib.sha256(stored).hexdigest(),
                    sanitized=stored != raw_bytes, headers_bytes=wrapped.reader.header_bytes if wrapped.reader else 0)
    return metadata, stored
