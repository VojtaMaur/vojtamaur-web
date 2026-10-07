"""Copy owner-prepared public exports, separately from the sanitized source tree.

ZIP/EPUB containers remain opaque and are never extracted or executed. This is
an explicit owner-publication scope, not a guarantee that an archive is secret
free. Only direct allowlisted export files, or explicit relative selections,
are considered; irrelevant repository backups are never scanned.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import tempfile

from .workspace import (SecurityError, SnapshotLimitError, _CREDENTIAL_CONTENT,
                        _atomic_write, _confined, _linked, _overlap, _plain_absolute, _relative)

ALLOWED_SUFFIXES = {".zip", ".pdf", ".epub", ".txt"}
SCOPE_NOTICE = ("Owner-prepared public export payloads, copied independently from production. "
                "No archive extraction or execution; upload requires the run's configured external-action policy. "
                "Only selected TXT/manifests receive bounded credential-pattern screening; binary containers are opaque.")


def allowed_export(relative):
    relative = _relative(relative)
    name = relative.name.casefold()
    if name.startswith(".") or name.startswith(("credentials", "secrets", "service-account", "service_account")):
        return False
    return relative.suffix.casefold() in ALLOWED_SUFFIXES or name.endswith(".manifest.json")


def _copy_export(source_root, relative, target, limit, text_scan_limit):
    source = _confined(source_root, relative)
    before = source.lstat()
    if _linked(before) or not stat.S_ISREG(before.st_mode):
        raise SecurityError("Export must be a regular file")
    if before.st_size > limit:
        raise SnapshotLimitError(f"Export exceeds {limit} bytes: {relative.as_posix()}")
    screening = relative.suffix.casefold() == ".txt" or relative.name.casefold().endswith(".manifest.json")
    if screening and before.st_size > text_scan_limit:
        raise SnapshotLimitError(f"Text/manifest export exceeds credential-screening limit: {relative.as_posix()}")
    target.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    digest, size, chunks = hashlib.sha256(), 0, []
    with os.fdopen(os.open(source, flags), "rb") as incoming, target.open("xb") as outgoing:
        opened = os.fstat(incoming.fileno())
        if not stat.S_ISREG(opened.st_mode) or (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
            raise SecurityError("Export changed identity while opening")
        while chunk := incoming.read(1024 * 1024):
            size += len(chunk)
            if size > limit:
                raise SnapshotLimitError(f"Export exceeds {limit} bytes: {relative.as_posix()}")
            if screening:
                if size > text_scan_limit:
                    raise SnapshotLimitError(f"Text export grew beyond credential-screening limit: {relative.as_posix()}")
                chunks.append(chunk)
            digest.update(chunk)
            outgoing.write(chunk)
        outgoing.flush()
        os.fsync(outgoing.fileno())
    _confined(source_root, relative)
    if screening and _CREDENTIAL_CONTENT.search(b"".join(chunks)):
        raise SecurityError("Potential credential detected in selected text export")
    os.chmod(target, 0o644)
    return {"path": relative.as_posix(), "bytes": size, "sha256": digest.hexdigest(),
            "credential_screening": "bounded_pattern_screen" if screening else "opaque_owner_public_export"}


def intake_exports(project, run_dir, filenames=None, *, max_file_bytes=128 * 1024 * 1024,
                   max_total_bytes=512 * 1024 * 1024, max_files=100,
                   max_text_scan_bytes=8 * 1024 * 1024):
    """Atomically publish independent payload copies under run/input_exports.

    filenames=None selects direct files with the fixed public-export allowlist.
    Explicit filenames are export-relative paths; all must be allowed, regular,
    non-linked files. Existing intake is never overwritten on resume.
    """
    if any(type(value) is not int or value < 1 for value in
           (max_file_bytes, max_total_bytes, max_files, max_text_scan_bytes)):
        raise ValueError("Export limits must be positive integers")
    project, run_dir = _plain_absolute(project), _plain_absolute(run_dir)
    if _overlap(project, run_dir):
        raise SecurityError("Export intake must be outside production")
    if not project.is_dir() or not run_dir.is_dir():
        raise ValueError("Project and run must be existing directories")
    source_root = _confined(project, "exports")
    destination = _confined(run_dir, "input_exports")
    if destination.exists():
        raise FileExistsError("Export intake already exists; do not overwrite historical inputs")
    manifest = {"schema_version": 1, "scope": SCOPE_NOTICE, "files": [], "skipped": [], "total_bytes": 0}
    if filenames is not None and (not isinstance(filenames, (list, tuple)) or any(not isinstance(item, str) for item in filenames)):
        raise ValueError("Export filenames must be a list of relative strings or null")
    if not source_root.exists():
        if filenames:
            raise FileNotFoundError("Project exports directory does not exist")
        manifest["skipped"].append({"path": "exports", "reason": "exports directory missing"})
        selections = []
    elif filenames is not None:
        selections = sorted({_relative(name) for name in filenames}, key=lambda path: path.as_posix())
        if any(not allowed_export(name) for name in selections):
            raise ValueError("Explicit selection contains a disallowed public export type/name")
    else:
        selections = []
        with os.scandir(source_root) as entries:
            for number, entry in enumerate(entries, 1):
                if number > max(1000, max_files * 20):
                    raise SnapshotLimitError("Public export directory entry count exceeds scan limit")
                relative = Path(entry.name)
                info = entry.stat(follow_symlinks=False)
                if _linked(info):
                    manifest["skipped"].append({"path": entry.name, "reason": "symlink or reparse point"})
                elif stat.S_ISREG(info.st_mode) and allowed_export(relative):
                    selections.append(relative)
                else:
                    manifest["skipped"].append({"path": entry.name, "reason": "not an allowlisted direct public export file"})
        selections.sort(key=lambda path: path.as_posix())
    if len(selections) > max_files:
        raise SnapshotLimitError("Public export file count exceeds limit")
    stage = Path(tempfile.mkdtemp(prefix=".swarm-exports-", dir=run_dir))
    try:
        for relative in selections:
            receipt = _copy_export(source_root, relative, stage / relative, max_file_bytes, max_text_scan_bytes)
            manifest["total_bytes"] += receipt["bytes"]
            if manifest["total_bytes"] > max_total_bytes:
                raise SnapshotLimitError("Public exports exceed total byte limit")
            manifest["files"].append(receipt)
        manifest["sha256"] = hashlib.sha256(json.dumps(manifest["files"], sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        _atomic_write(stage / "manifest.json", (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
        _plain_absolute(destination)
        if destination.exists():
            raise FileExistsError(destination)
        os.replace(stage, destination)
        return manifest
    except BaseException:
        # Only remove our verified, randomly named staging directory.
        _plain_absolute(stage)
        if stage.parent != run_dir or not stage.name.startswith(".swarm-exports-"):
            raise SecurityError("Unexpected export staging path")
        shutil.rmtree(stage)
        raise
