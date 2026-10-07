"""Reviewed host connector in a killable child; no agent-supplied program runs.

urllib socket timeouts are idle bounds, not wall-clock deadlines. The parent
kills and waits for this fixed child on timeout, retaining the uncertain action
in the caller's ledger. An upload may already have happened: never auto-retry.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import sys

MAX_INPUT_BYTES = 65536
MAX_OUTPUT_BYTES = 16384
_RUNTIME_ENV = {"SYSTEMROOT", "WINDIR", "TMP", "TEMP"}


def _environment(resource):
    environment = {key: value for key, value in os.environ.items() if key.upper() in _RUNTIME_ENV}
    credential_name = resource.get("credential_env")
    if credential_name and credential_name in os.environ:
        environment[credential_name] = os.environ[credential_name]
    return environment


def execute_bounded(resource, source, name, expected, forbidden, timeout=30):
    """Execute one configured deposit with a real process wall-clock bound."""
    from .actions import validate_resources
    validate_resources([resource])
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not 0 < timeout <= 3600:
        raise ValueError("Deposit worker timeout must be positive and at most one hour")
    payload = json.dumps({"resource": resource, "source": os.fspath(source), "name": name,
                          "expected": expected, "forbidden": [os.fspath(path) for path in forbidden],
                          "timeout": timeout}, ensure_ascii=True, allow_nan=False).encode("ascii")
    if len(payload) > MAX_INPUT_BYTES:
        raise ValueError("Deposit worker input exceeds its limit")
    # Isolated Python skips PYTHONPATH, user site, startup hooks and site packages.
    # An absolute reviewed file is the sole entry point, not a model command.
    command = [sys.executable, "-I", "-S", str(Path(__file__).resolve())]
    try:
        result = subprocess.run(command, input=payload, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                env=_environment(resource), timeout=timeout, check=False)
    except subprocess.TimeoutExpired:
        # subprocess.run kills and waits before raising; no orphan worker remains.
        raise TimeoutError("Deposit worker wall-clock deadline reached; reconcile destination") from None
    if len(result.stdout) > MAX_OUTPUT_BYTES or len(result.stderr) > MAX_OUTPUT_BYTES:
        raise ValueError("Deposit worker output exceeded its bound")
    if result.returncode:
        # Deliberately discard worker stderr/server reasons and credential values.
        raise ValueError("Deposit worker failed; reconcile destination")
    try:
        receipt = json.loads(result.stdout.decode("utf-8"))
    except (ValueError, UnicodeError):
        raise ValueError("Deposit worker returned an invalid receipt") from None
    if not isinstance(receipt, dict) or receipt.get("host_verified") is not True or any(receipt.get(key) != expected.get(key) for key in ("bytes", "sha256")):
        raise ValueError("Deposit worker returned an unverified receipt")
    return receipt


def _main():
    try:
        # Add only the package tree containing this reviewed worker; -I removed
        # all host/user path configuration before any package import occurs.
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        from metaweb_swarm.actions import execute_deposit, object_name, validate_resources
        incoming = sys.stdin.buffer.read(MAX_INPUT_BYTES + 1)
        if len(incoming) > MAX_INPUT_BYTES:
            raise ValueError("Worker request exceeds input limit")
        request = json.loads(incoming)
        if not isinstance(request, dict) or set(request) != {"resource", "source", "name", "expected", "forbidden", "timeout"}:
            raise ValueError("Invalid worker request")
        resource, expected = request["resource"], request["expected"]
        validate_resources([resource])
        if (not isinstance(expected, dict) or set(expected) != {"bytes", "sha256"}
                or type(expected["bytes"]) is not int or not 0 <= expected["bytes"] <= resource["max_bytes"]
                or not isinstance(expected["sha256"], str) or not re.fullmatch(r"[a-f0-9]{64}", expected["sha256"])):
            raise ValueError("Invalid expected deposit bytes")
        if not isinstance(request["source"], str) or not Path(request["source"]).is_absolute():
            raise ValueError("Source must be absolute")
        if not isinstance(request["forbidden"], list) or any(not isinstance(path, str) or not Path(path).is_absolute() for path in request["forbidden"]):
            raise ValueError("Invalid forbidden roots")
        name = object_name(request["name"], expected["sha256"])
        receipt = execute_deposit(resource, request["source"], name, expected, request["forbidden"], request["timeout"])
        encoded = json.dumps(receipt, ensure_ascii=True, allow_nan=False).encode("ascii")
        if len(encoded) > MAX_OUTPUT_BYTES:
            raise ValueError("Receipt exceeds output limit")
        sys.stdout.buffer.write(encoded)
        sys.stdout.buffer.flush()
        return 0
    except BaseException as error:
        # No traceback, remote response, request headers or exception message.
        encoded = json.dumps({"status": "FAILED", "error_type": type(error).__name__}).encode("ascii")
        sys.stdout.buffer.write(encoded)
        sys.stdout.buffer.flush()
        return 2


if __name__ == "__main__":
    raise SystemExit(_main())
