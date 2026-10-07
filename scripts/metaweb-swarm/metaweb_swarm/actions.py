"""Narrow operator-declared deposit connectors. Never execute agent-supplied host code."""
import hashlib
import os
import re
import shutil
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import quote, urlsplit

from .context import _is_link


RESOURCE_FIELDS = {"id", "kind", "directory", "endpoint", "credential_env", "authorization_scheme",
                   "max_bytes", "cost_usd", "allow_loopback_http"}


def validate_resources(resources):
    if not isinstance(resources, list) or len(resources) > 30:
        raise ValueError("external_resources must be a bounded list")
    identities = set()
    for resource in resources:
        if not isinstance(resource, dict) or set(resource) - RESOURCE_FIELDS:
            raise ValueError("Unknown external resource fields")
        identity = resource.get("id", "")
        if not isinstance(identity, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", identity) or identity in identities:
            raise ValueError("Resource IDs must be unique simple names")
        identities.add(identity)
        if type(resource.get("max_bytes")) is not int or resource["max_bytes"] < 1:
            raise ValueError("Each resource requires a positive max_bytes")
        # These initial connectors perform free deposits; payment/account connectors are not implemented.
        if resource.get("cost_usd", 0) != 0:
            raise ValueError("Initial deposit connectors support only zero-cost actions")
        kind = resource.get("kind")
        if kind == "local_directory":
            if not isinstance(resource.get("directory"), str) or not Path(resource["directory"]).is_absolute():
                raise ValueError("Local deposit directory must be absolute")
            if resource.get("credential_env") or resource.get("endpoint"):
                raise ValueError("Local deposit does not accept credentials or endpoint")
        elif kind == "http_put":
            parsed = urlsplit(resource.get("endpoint", ""))
            loopback = parsed.hostname in {"127.0.0.1", "localhost", "::1"}
            if (parsed.scheme != "https" and not (parsed.scheme == "http" and loopback and resource.get("allow_loopback_http") is True)) or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
                raise ValueError("PUT endpoint must be HTTPS without embedded credentials/query; explicit loopback HTTP is for tests")
            name = resource.get("credential_env", "")
            runtime_names = {"PATH", "HOME", "TMP", "TEMP", "WINDIR", "SYSTEMROOT", "USERPROFILE", "LOCALAPPDATA", "APPDATA", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY"}
            if name and (not isinstance(name, str) or not re.fullmatch(r"[A-Z][A-Z0-9_]{1,79}", name) or name.startswith(("OPENAI", "PYTHON", "DOCKER")) or name in runtime_names):
                raise ValueError("Use a dedicated resource credential environment variable")
            if resource.get("authorization_scheme", "Bearer") not in {"Bearer", "Basic"}:
                raise ValueError("Only Bearer/Basic resource authorization is supported")
        else:
            raise ValueError("Resource kind must be local_directory or http_put")


def object_name(value, digest):
    value = value or (digest + ".bin")
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,159}", value) or ".." in value or value.endswith(".") or re.fullmatch(r"(?i:con|prn|aux|nul|com[1-9]|lpt[1-9])", value.split(".")[0]):
        raise ValueError("Deposit object name must be a single simple filename")
    return value


def digest_file(path, maximum):
    path = Path(path)
    if _is_link(path) or not path.is_file() or path.stat().st_size > maximum:
        raise ValueError("Deposit file is absent, linked or exceeds the resource limit")
    size, digest = 0, hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(65536), b""):
            size += len(chunk)
            if size > maximum:
                raise ValueError("Deposit source grew beyond its resource limit")
            digest.update(chunk)
    return {"bytes": size, "sha256": digest.hexdigest()}


def safe_directory(directory, forbidden):
    directory = Path(directory)
    if not directory.is_absolute():
        raise ValueError("Resource directory must be absolute")
    for node in (directory, *directory.parents):
        if node.exists() and _is_link(node):
            raise ValueError("Linked resource directories are forbidden")
    target = directory.resolve()
    for root in forbidden:
        root = Path(root).resolve()
        if target == root or target.is_relative_to(root) or root.is_relative_to(target):
            raise ValueError("Deposit target overlaps production or a run workspace")
    directory.mkdir(parents=True, exist_ok=True)
    return directory


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        fp.close()
        raise ValueError("Resource redirects are forbidden")


def execute_deposit(resource, source, name, expected, forbidden, timeout=30):
    """One reserved deposit attempt, read-back verified; exact retry handled by caller."""
    if digest_file(source, resource["max_bytes"]) != expected:
        raise ValueError("Source changed after action was bound/approved")
    if resource["kind"] == "local_directory":
        directory = safe_directory(resource["directory"], forbidden)
        target = directory / name
        if _is_link(target):
            raise ValueError("Linked deposit target is forbidden")
        if target.exists():
            # Never overwrite a different object, including after uncertain process interruption.
            if digest_file(target, resource["max_bytes"]) != expected:
                raise ValueError("Deposit object already exists with different bytes")
            return {"location": str(target), **expected, "host_verified": True, "verification": "independent SHA256 read-back", "already_present": True}
        # Exclusive creation avoids replacing existing unrelated files. A partial crash is UNKNOWN, not success.
        with target.open("xb") as out, Path(source).open("rb") as inp:
            shutil.copyfileobj(inp, out, length=65536)
            out.flush()
            os.fsync(out.fileno())
        if digest_file(target, resource["max_bytes"]) != expected:
            raise ValueError("Deposit read-back differs from source")
        return {"location": str(target), **expected, "host_verified": True, "verification": "independent SHA256 read-back"}
    endpoint = resource["endpoint"].rstrip("/") + "/" + quote(name, safe="")
    headers = {"Content-Type": "application/octet-stream", "If-None-Match": "*", "X-Content-SHA256": expected["sha256"]}
    credential_name = resource.get("credential_env")
    if credential_name:
        credential = os.environ.get(credential_name)
        if not credential or any(c in credential for c in "\r\n"):
            raise ValueError("Configured resource credential is unavailable/invalid")
        headers["Authorization"] = resource.get("authorization_scheme", "Bearer") + " " + credential
    opener = urllib.request.build_opener(NoRedirect())
    deadline = time.monotonic() + timeout
    # Bounded file payload, no agent-supplied headers, credentials never leave this host connector.
    payload = Path(source).read_bytes()
    if len(payload) != expected["bytes"] or hashlib.sha256(payload).hexdigest() != expected["sha256"]:
        raise ValueError("Deposit source changed while preparing upload")
    try:
        with opener.open(urllib.request.Request(endpoint, data=payload, headers=headers, method="PUT"), timeout=max(.1, deadline-time.monotonic())) as response:
            if response.status not in (200, 201, 204):
                raise ValueError("PUT endpoint did not accept the object")
    except urllib.error.HTTPError as error:
        # Conditional PUT collision is recoverable only by independently reading the exact same bytes.
        code = error.code
        error.close()
        if code not in (409, 412):
            raise ValueError(f"PUT failed with HTTP {code}") from None
    digest, size = hashlib.sha256(), 0
    read_headers = {k: v for k, v in headers.items() if k == "Authorization"}
    try:
        with opener.open(urllib.request.Request(endpoint, headers=read_headers, method="GET"), timeout=max(.1, deadline-time.monotonic())) as response:
            while True:
                if time.monotonic() >= deadline:
                    raise TimeoutError("Deposit verification deadline reached")
                chunk = response.read(65536)
                if not chunk:
                    break
                size += len(chunk)
                if size > resource["max_bytes"]:
                    raise ValueError("Read-back exceeds resource size limit")
                digest.update(chunk)
    except urllib.error.HTTPError as error:
        code = error.code
        error.close()
        raise ValueError(f"Deposit verification failed with HTTP {code}") from None
    if {"bytes": size, "sha256": digest.hexdigest()} != expected:
        raise ValueError("Uploaded object could not be independently verified")
    return {"location": endpoint, **expected, "host_verified": True, "verification": "HTTP GET SHA256 read-back"}
