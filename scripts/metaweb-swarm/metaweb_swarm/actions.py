"""Narrow operator-declared deposit connectors. Never execute agent-supplied host code."""
import hashlib
import os
import re
import shutil
import time
from pathlib import Path
from urllib.parse import quote, urlsplit, urlunsplit

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
            if name and (not isinstance(name, str) or not re.fullmatch(r"META_SWARM_CRED_[A-Z0-9_]+", name)):
                raise ValueError("Use a dedicated META_SWARM_CRED_* resource credential environment variable")
            if resource.get("authorization_scheme", "Bearer") not in {"Bearer", "Basic"}:
                raise ValueError("Only Bearer/Basic resource authorization is supported")
            # Legacy deposits share the generic transport's protections. Keeping
            # this check at configuration time also rejects old forge grants.
            from .http_transport import normalize_request
            normalize_request({"method": "PUT", "url": resource["endpoint"]},
                              _http_config(resource, 30), None)
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


def _http_config(resource, timeout):
    """Translate the narrow legacy resource into the general host transport."""
    from .http_transport import DEFAULTS
    config = dict(DEFAULTS, http_access="enabled", http_timeout_seconds=timeout,
                  max_http_request_bytes=resource["max_bytes"],
                  max_http_response_bytes=resource["max_bytes"])
    parts = urlsplit(resource["endpoint"])
    if resource.get("allow_loopback_http") is True and parts.scheme == "http":
        config["http_test_origins"] = [urlunsplit((parts.scheme, parts.netloc, "", "", ""))]
    if resource.get("credential_env"):
        config["http_credentials"] = [{"id": "legacy-deposit", "env": resource["credential_env"],
                                       "hosts": [parts.hostname], "header": "Authorization",
                                       "scheme": resource.get("authorization_scheme", "Bearer")}]
    return config


class _DepositWorkspace:
    """Only a reviewed source basename is passed into normalization."""
    def __init__(self, source):
        self.root = Path(source).parent


def execute_deposit(resource, source, name, expected, forbidden, timeout=30):
    """One reserved deposit attempt, read-back verified; exact retry handled by caller."""
    validate_resources([resource])
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
    from .http_transport import execute_request, normalize_request
    config = _http_config(resource, timeout)
    workspace = _DepositWorkspace(source)
    deadline = time.monotonic() + timeout
    credential = "legacy-deposit" if resource.get("credential_env") else ""
    descriptor, upload = normalize_request({"method": "PUT", "url": endpoint, "headers": headers,
                                          "upload_path": Path(source).name, "credential_id": credential},
                                         config, workspace)
    if {"bytes": descriptor["bytes"], "sha256": descriptor["body_sha256"]} != expected:
        raise ValueError("Deposit source changed while preparing upload")
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("Deposit upload deadline reached")
    accepted, _ = execute_request(upload, config, remaining)
    code = accepted.get("status")
    if isinstance(code, int) and 300 <= code < 400:
        raise ValueError("Resource redirects are forbidden")
    if accepted.get("outcome_uncertain") or accepted.get("timed_out"):
        raise ValueError("PUT outcome uncertain; reconcile destination")
    # Conditional PUT collision is recoverable only by reading the exact bytes.
    if code not in (200, 201, 204, 409, 412):
        raise ValueError(f"PUT failed with HTTP {code}")
    _, download = normalize_request({"method": "GET", "url": endpoint, "credential_id": credential},
                                    config, workspace)
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("Deposit verification deadline reached")
    observed, _ = execute_request(download, config, remaining)
    code = observed.get("status")
    if isinstance(code, int) and 300 <= code < 400:
        raise ValueError("Resource redirects are forbidden")
    if observed.get("truncated") or observed.get("response_bytes", 0) > resource["max_bytes"]:
        raise ValueError("Read-back exceeds resource size limit")
    if code != 200 or observed.get("timed_out") or observed.get("error"):
        raise ValueError(f"Deposit verification failed with HTTP {code}")
    if {"bytes": observed.get("response_bytes"), "sha256": observed.get("raw_sha256")} != expected:
        raise ValueError("Uploaded object could not be independently verified")
    return {"location": endpoint, **expected, "host_verified": True, "verification": "HTTP GET SHA256 read-back"}
