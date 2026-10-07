"""Filesystem boundaries, independent project copies, and optional Docker experiments.

This module does not import the SDK, run repository programs, or apply patches.  A
workspace is a convenience boundary for file tools.  Arbitrary code requires the
separate DockerExecutor boundary; it must never be run directly on the host.
"""

from __future__ import annotations

import difflib
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
import threading
import uuid
from pathlib import Path
from typing import Any


class SecurityError(ValueError):
    """A path or filesystem entry would cross an isolation boundary."""


class SnapshotLimitError(ValueError):
    """The complete snapshot cannot fit the configured size budget."""


_REPARSE_POINT = 0x400
_EXCLUDED_DIRS = {
    ".git", ".hg", ".svn", "node_modules", ".venv", "venv", "env",
    "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".cache",
    ".tox", ".nox", ".next", ".nuxt", ".aws", ".azure", ".gcloud",
    ".ssh", ".gnupg", ".codex", "credentials", "secrets", "exports",
    ".source-bundle-staging", "source-bundle-staging", "source_bundle_staging",
    "source-snapshot", "source_snapshot",
    "swarm-runs", "swarm_runs", ".packages",
}
_SECRET_SUFFIXES = {".key", ".pem", ".p12", ".pfx", ".kdbx", ".keystore"}
_ARCHIVE_SUFFIXES = {".zip", ".7z", ".rar", ".tar", ".tgz", ".gz", ".bz2", ".xz"}
_SECRET_NAMES = {
    "credentials.json", "credentials", "secrets.json", "secrets.toml",
    "service-account.json", "service_account.json", "id_rsa", "id_ed25519",
    ".netrc", ".npmrc", ".pypirc", "authorized_keys", "known_hosts",
}
_WINDOWS_RESERVED = re.compile(r"^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?$", re.I)
_WORKSPACE_MARKER = ".metaweb-workspace.json"
_CREDENTIAL_CONTENT = re.compile(
    rb"-----BEGIN (?:RSA |DSA |EC |OPENSSH |ENCRYPTED )?PRIVATE KEY-----"
    rb"|\bsk-[A-Za-z0-9_-]{20,}\b"
    rb"|\bgh[pousr]_[A-Za-z0-9]{20,}\b"
    rb"|\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"
)


def _linked(info: os.stat_result) -> bool:
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & _REPARSE_POINT)


def _plain_absolute(path: Path | str) -> Path:
    """Resolve lexical components only, then reject links in every existing parent."""
    absolute = Path(os.path.abspath(os.fspath(path)))
    for part in [*reversed(absolute.parents), absolute]:
        try:
            info = part.lstat()
        except FileNotFoundError:
            continue
        if _linked(info):
            raise SecurityError(f"Symlink or reparse point is forbidden: {part}")
    return absolute


def _relative(relative: str | Path, *, allow_dot: bool = False) -> Path:
    value = os.fspath(relative)
    if not isinstance(value, str) or not value or "\x00" in value or ":" in value:
        raise SecurityError("Expected a relative path without a drive or alternate data stream")
    value = value.replace("\\", "/")
    if value.startswith("/"):
        raise SecurityError("Absolute paths are forbidden")
    if value == "." and allow_dot:
        return Path()
    parts = value.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise SecurityError("Empty components and path traversal are forbidden")
    if any(part.endswith((".", " ")) or _WINDOWS_RESERVED.match(part) for part in parts):
        raise SecurityError("Ambiguous or reserved Windows path is forbidden")
    return Path(*parts)


def _confined(root: Path, relative: str | Path, *, allow_dot: bool = False) -> Path:
    base = _plain_absolute(root)
    target = _plain_absolute(base / _relative(relative, allow_dot=allow_dot))
    try:
        target.relative_to(base)
    except ValueError as exc:
        raise SecurityError("Path leaves its workspace") from exc
    return target


def _overlap(first: Path, second: Path) -> bool:
    return first == second or first in second.parents or second in first.parents


def _excluded(relative: Path, *, directory: bool = False) -> str | None:
    parts = [part.casefold() for part in relative.parts]
    dirs = parts if directory else parts[:-1]
    if any(part in _EXCLUDED_DIRS or part.startswith("dist") for part in dirs):
        return "excluded directory"
    name = parts[-1] if parts else ""
    if name == ".env" or name.startswith(".env.") or name in _SECRET_NAMES:
        return "potential credential"
    if name.startswith(("service-account-", "service_account_", "credentials-", "secrets-")):
        return "potential credential"
    if Path(name).suffix in _SECRET_SUFFIXES:
        return "potential credential"
    if Path(name).suffix in _ARCHIVE_SUFFIXES:
        return "archive/container excluded to avoid nested secrets and source bundles"
    return None


def _inventory(root: Path, *, exclude: bool = True, reject_links: bool = False) -> tuple[list[Path], list[dict[str, str]]]:
    files: list[Path] = []
    skipped: list[dict[str, str]] = []
    pending = [root]
    while pending:
        directory = pending.pop()
        _plain_absolute(directory)
        with os.scandir(directory) as entries:
            for entry in sorted(entries, key=lambda item: item.name):
                path = Path(entry.path)
                relative = path.relative_to(root)
                info = entry.stat(follow_symlinks=False)
                if _linked(info):
                    if reject_links:
                        raise SecurityError(f"Symlink or reparse point is forbidden: {relative}")
                    skipped.append({"path": relative.as_posix(), "reason": "symlink or reparse point"})
                    continue
                is_directory = stat.S_ISDIR(info.st_mode)
                reason = _excluded(relative, directory=is_directory) if exclude else None
                if reason:
                    skipped.append({"path": relative.as_posix(), "reason": reason})
                elif is_directory:
                    pending.append(path)
                elif stat.S_ISREG(info.st_mode):
                    _relative(relative.as_posix())
                    files.append(relative)
                elif reject_links:
                    raise SecurityError(f"Special filesystem entry is forbidden: {relative}")
                else:
                    skipped.append({"path": relative.as_posix(), "reason": "special filesystem entry"})
        if len(files) > 100_000:
            raise SnapshotLimitError("File count exceeds the snapshot safety limit")
    return sorted(files, key=lambda path: path.as_posix()), skipped


def _read_bytes(root: Path, relative: Path, limit: int = 64_000_000) -> bytes:
    path = _confined(root, relative)
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode) or _linked(before):
        raise SecurityError(f"Expected a regular file: {relative}")
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    with os.fdopen(descriptor, "rb") as handle:
        opened = os.fstat(handle.fileno())
        if not stat.S_ISREG(opened.st_mode) or (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
            raise SecurityError(f"File changed identity while opening: {relative}")
        data = handle.read(limit + 1)
    _confined(root, relative)
    if len(data) > limit:
        raise SnapshotLimitError(f"File exceeds {limit} bytes: {relative}")
    return data


def _atomic_write(path: Path, content: bytes) -> None:
    _plain_absolute(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    _plain_absolute(path.parent)
    temporary = path.parent / f".swarm-{uuid.uuid4().hex}.tmp"
    try:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
        with os.fdopen(os.open(temporary, flags, 0o600), "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        _plain_absolute(path)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _digest(files: dict[str, dict[str, Any]]) -> str:
    value = json.dumps(files, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(value).hexdigest()


def create_snapshot(project: Path, destination: Path, max_file_bytes: int = 20_000_000,
                    max_total_bytes: int = 500_000_000) -> dict[str, Any]:
    """Atomically snapshot tracked working-tree contents, or safely walk a non-Git tree.

    Git is used only to enumerate tracked names. Uncommitted modifications are read
    from the working tree. Missing tracked files, credentials, archives, caches,
    links, reparse points, and special files are recorded as exclusions. Any size
    limit failure removes the staging copy and leaves no successful destination.
    """
    if max_file_bytes <= 0 or max_total_bytes <= 0:
        raise ValueError("Snapshot limits must be positive")
    project = _plain_absolute(project)
    destination = _plain_absolute(destination)
    if not project.is_dir():
        raise ValueError("Project must be an existing directory")
    if _overlap(project, destination):
        raise SecurityError("Snapshot must be outside the project tree")
    if destination.exists():
        raise FileExistsError(destination)
    skipped: list[dict[str, str]] = []
    mode = "safe-walk"
    if (project / ".git").exists():
        git_env = {key: value for key, value in os.environ.items() if not key.upper().startswith("GIT_")}
        try:
            result = subprocess.run(
                ["git", "--no-optional-locks", "--no-pager", "-c", "core.fsmonitor=false",
                 "-c", "core.hooksPath=" + os.devnull, "-C", str(project), "ls-files", "--cached", "-z"],
                env=git_env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True, timeout=30,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise RuntimeError("Git tracked-file enumeration failed; refusing an untracked fallback") from exc
        if len(result.stdout) > 32_000_000:
            raise SnapshotLimitError("Tracked-file inventory exceeds its safety limit")
        files = sorted({_relative(os.fsdecode(name)) for name in result.stdout.split(b"\x00") if name}, key=lambda path: path.as_posix())
        if len(files) > 100_000:
            raise SnapshotLimitError("File count exceeds the snapshot safety limit")
        mode = "git-tracked"
    else:
        files, skipped = _inventory(project)
    destination.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=".swarm-snapshot-", dir=destination.parent))
    records: dict[str, dict[str, Any]] = {}
    total = 0
    try:
        for relative in files:
            name = relative.as_posix()
            reason = _excluded(relative)
            if reason:
                skipped.append({"path": name, "reason": reason})
                continue
            try:
                source = _confined(project, relative)
                info = source.lstat()
            except FileNotFoundError:
                skipped.append({"path": name, "reason": "missing tracked working-tree file"})
                continue
            except SecurityError:
                skipped.append({"path": name, "reason": "symlink or reparse point"})
                continue
            if _linked(info) or not stat.S_ISREG(info.st_mode):
                skipped.append({"path": name, "reason": "symlink, reparse point, or special file"})
                continue
            data = _read_bytes(project, relative, max_file_bytes)
            if _CREDENTIAL_CONTENT.search(data):
                skipped.append({"path": name, "reason": "potential credential detected in file content"})
                continue
            total += len(data)
            if total > max_total_bytes:
                raise SnapshotLimitError(f"Snapshot exceeds {max_total_bytes} bytes")
            target = stage / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("xb") as handle:
                handle.write(data)
            # Copies are new files, never hard links; preserve only executable intent.
            os.chmod(target, 0o755 if info.st_mode & stat.S_IXUSR else 0o644)
            records[name] = {"sha256": hashlib.sha256(data).hexdigest(), "size": len(data),
                             "executable": bool(info.st_mode & stat.S_IXUSR)}
        _plain_absolute(destination)
        if destination.exists():
            raise FileExistsError(destination)
        os.replace(stage, destination)
    finally:
        if stage.exists():
            shutil.rmtree(stage)
    digest = _digest(records)
    return {"path": str(destination), "files": records, "hash": digest, "sha256": digest,
            "skipped": skipped, "total_bytes": total, "mode": mode}


class Workspace:
    """An independent editable source copy plus work/context directories.

    Reopening a Workspace-created directory preserves changes for resume. Paths
    accepted by file tools are relative to ``root`` (for example
    ``source/vojtamaur-web/index.html``). The marker is an integrity aid, not an OS
    security boundary. Do not expose arbitrary host execution as a file tool.
    """

    def __init__(self, snapshot: Path, root: Path, max_file_bytes: int = 64_000_000,
                 max_total_bytes: int = 1_500_000_000):
        self.snapshot = _plain_absolute(snapshot)
        self.root = _plain_absolute(root)
        if not self.snapshot.is_dir() or _overlap(self.snapshot, self.root):
            raise SecurityError("Workspace must be separate from an existing snapshot")
        self.source = self.root / "source" / "vojtamaur-web"
        self.work = self.root / "work"
        self.context = self.root / "context"
        if self.root.exists() and any(self.root.iterdir()):
            marker = _confined(self.root, _WORKSPACE_MARKER)
            if not marker.is_file():
                raise SecurityError("Refusing an existing directory without a workspace marker")
            metadata = json.loads(_read_bytes(self.root, Path(_WORKSPACE_MARKER), 65_536))
            if metadata.get("snapshot") != str(self.snapshot) or metadata.get("root") != str(self.root):
                raise SecurityError("Workspace marker belongs to another snapshot or directory")
            if not all(path.is_dir() for path in (self.source, self.work, self.context)):
                raise SecurityError("Workspace is incomplete")
            _inventory(self.root, exclude=False, reject_links=True)
            return
        if max_file_bytes <= 0 or max_total_bytes <= 0:
            raise ValueError("Workspace copy limits must be positive")
        files, _ = _inventory(self.snapshot, exclude=True, reject_links=True)
        self.root.mkdir(parents=True, exist_ok=True)
        try:
            self.source.mkdir(parents=True)
            self.work.mkdir()
            self.context.mkdir()
            copied = 0
            for relative in files:
                data = _read_bytes(self.snapshot, relative, max_file_bytes)
                if _CREDENTIAL_CONTENT.search(data):
                    # Defence in depth if a caller supplies an unsanitized tree.
                    continue
                copied += len(data)
                if copied > max_total_bytes:
                    raise SnapshotLimitError("Workspace copy exceeds its total byte limit")
                target = self.source / relative
                _atomic_write(target, data)
                info = (self.snapshot / relative).lstat()
                os.chmod(target, 0o755 if info.st_mode & stat.S_IXUSR else 0o644)
            _atomic_write(self.root / _WORKSPACE_MARKER, json.dumps(
                {"schema": 1, "snapshot": str(self.snapshot), "root": str(self.root)},
                indent=2, ensure_ascii=False,
            ).encode("utf-8"))
        except BaseException:
            shutil.rmtree(self.root)
            raise

    def read_file(self, relative: str | Path) -> str:
        data = _read_bytes(self.root, _relative(relative), 2_000_000)
        try:
            if b"\x00" in data:
                raise UnicodeDecodeError("utf-8", data, 0, 1, "NUL byte")
            return data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError("read_file supports UTF-8 text; binary files remain available in the workspace and patch artifacts") from exc

    def write_file(self, relative: str | Path, content: str | bytes) -> None:
        path = _confined(self.root, relative)
        if path == self.root / _WORKSPACE_MARKER:
            raise SecurityError("Workspace metadata is protected")
        data = content.encode("utf-8") if isinstance(content, str) else content
        if not isinstance(data, bytes):
            raise TypeError("File contents must be text or bytes")
        if len(data) > 20_000_000:
            raise SnapshotLimitError("Workspace file exceeds 20000000 bytes")
        _atomic_write(path, data)

    def file_info(self, relative: str | Path) -> dict[str, Any]:
        """Validate and hash exact artifact bytes without decoding binary output."""
        data = _read_bytes(self.root, _relative(relative))
        if _CREDENTIAL_CONTENT.search(data):
            raise SecurityError("Artifact contains a potential credential")
        return {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data), "binary": _text(data) is None}

    def import_public_export(self, source: Path, relative: str, expected: dict, maximum: int) -> None:
        """Host-selected, captured public build bytes; no extraction or path delegation."""
        target = _confined(self.root, relative)
        if target == self.root / _WORKSPACE_MARKER:
            raise SecurityError("Workspace metadata is protected")
        _plain_absolute(source)
        if source.stat().st_size != expected["bytes"] or expected["bytes"] > maximum:
            raise SnapshotLimitError("Captured export exceeds its declared limit")
        target.parent.mkdir(parents=True, exist_ok=True)
        _plain_absolute(target.parent)
        temporary = target.parent / (".swarm-" + uuid.uuid4().hex + ".tmp")
        digest, size = hashlib.sha256(), 0
        try:
            with source.open("rb") as inp, temporary.open("xb") as out:
                while chunk := inp.read(65536):
                    size += len(chunk)
                    if size > maximum:
                        raise SnapshotLimitError("Captured export grew beyond its limit")
                    digest.update(chunk)
                    out.write(chunk)
                out.flush()
                os.fsync(out.fileno())
            if size != expected["bytes"] or digest.hexdigest() != expected["sha256"]:
                raise SecurityError("Captured export changed during copy")
            _confined(self.root, relative)
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)

    def list_files(self, relative: str | Path = ".") -> list[str]:
        directory = _confined(self.root, relative, allow_dot=True)
        if not directory.is_dir():
            raise ValueError("Expected a workspace directory")
        files, _ = _inventory(directory, exclude=False, reject_links=True)
        return [(directory / path).relative_to(self.root).as_posix() for path in files]


def _git_path(prefix: str, relative: str) -> str:
    value = prefix + relative
    if all(32 < ord(char) < 127 and char not in {'"', "\\"} for char in value):
        return value
    escaped = "".join(
        chr(byte) if 32 < byte < 127 and byte not in {34, 92} else f"\\{byte:03o}"
        for byte in value.encode("utf-8")
    )
    return '"' + escaped + '"'


def _text(data: bytes | None) -> str | None:
    if data is None:
        return ""
    if b"\x00" in data:
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


def export_patch(snapshot: Path, workspace_source: Path, destination: Path) -> dict[str, Any]:
    """Export reviewable text changes and exact before/after binary artifacts.

    ``destination`` is a directory. No patch is applied to the project. Links,
    credentials, caches and archives are omitted and listed in ``skipped``.
    Binary-manifest records include replacement content and original content so
    additions, replacements and deletions can be reviewed and reproduced.
    """
    snapshot, workspace_source, destination = map(_plain_absolute, (snapshot, workspace_source, destination))
    if not snapshot.is_dir() or not workspace_source.is_dir():
        raise ValueError("Snapshot and workspace source must exist")
    if _overlap(snapshot, destination) or _overlap(workspace_source, destination):
        raise SecurityError("Patch output must be outside both source trees")
    before_files, before_skipped = _inventory(snapshot)
    after_files, after_skipped = _inventory(workspace_source)
    before_names = {relative.as_posix() for relative in before_files}
    after_names = {relative.as_posix() for relative in after_files}
    patch_parts: list[str] = []
    changed: list[dict[str, Any]] = []
    binary_records: list[dict[str, Any]] = []
    content_skipped: list[dict[str, str]] = []
    destination.mkdir(parents=True, exist_ok=True)
    for name in sorted(before_names | after_names):
        relative = _relative(name)
        old = _read_bytes(snapshot, relative) if name in before_names else None
        new = _read_bytes(workspace_source, relative) if name in after_names else None
        if any(data is not None and _CREDENTIAL_CONTENT.search(data) for data in (old, new)):
            content_skipped.append({"path": name, "reason": "potential credential detected in file content", "tree": "comparison"})
            continue
        old_mode = "100755" if old is not None and (snapshot / relative).stat().st_mode & stat.S_IXUSR else "100644"
        new_mode = "100755" if new is not None and (workspace_source / relative).stat().st_mode & stat.S_IXUSR else "100644"
        if old == new and old_mode == new_mode:
            continue
        operation = "added" if old is None else "deleted" if new is None else "modified"
        old_text, new_text = _text(old), _text(new)
        record: dict[str, Any] = {"path": name, "operation": operation,
                                  "binary": old_text is None or new_text is None,
                                  "before_sha256": hashlib.sha256(old).hexdigest() if old is not None else None,
                                  "after_sha256": hashlib.sha256(new).hexdigest() if new is not None else None,
                                  "before_mode": old_mode if old is not None else None,
                                  "after_mode": new_mode if new is not None else None}
        changed.append(record)
        a_name, b_name = _git_path("a/", name), _git_path("b/", name)
        patch_parts.append(f"diff --git {a_name} {b_name}\n")
        if old is None:
            patch_parts.append(f"new file mode {new_mode}\n")
        elif new is None:
            patch_parts.append(f"deleted file mode {old_mode}\n")
        elif old_mode != new_mode:
            patch_parts.extend([f"old mode {old_mode}\n", f"new mode {new_mode}\n"])
        if record["binary"]:
            artifact = dict(record)
            for label, data in (("before", old), ("after", new)):
                if data is not None:
                    artifact_path = Path("binaries") / (hashlib.sha256(data).hexdigest() + ".bin")
                    _atomic_write(_confined(destination, artifact_path), data)
                    artifact[label + "_artifact"] = artifact_path.as_posix()
            binary_records.append(artifact)
            patch_parts.append(f"Binary files {a_name if old is not None else '/dev/null'} and {b_name if new is not None else '/dev/null'} differ\n")
        elif old != new:
            for line in difflib.unified_diff(
                old_text.splitlines(keepends=True), new_text.splitlines(keepends=True),
                fromfile=a_name if old is not None else "/dev/null",
                tofile=b_name if new is not None else "/dev/null", n=3, lineterm="\n",
            ):
                patch_parts.append(line)
                if not line.endswith("\n"):
                    patch_parts.append("\n\\ No newline at end of file\n")
    patch_path = destination / "changes.patch"
    manifest_path = destination / "binary-manifest.json"
    skipped = [{**entry, "tree": "snapshot"} for entry in before_skipped] + [
        {**entry, "tree": "workspace"} for entry in after_skipped
    ] + content_skipped
    _atomic_write(patch_path, "".join(patch_parts).encode("utf-8"))
    _atomic_write(manifest_path, json.dumps({"schema": 1, "files": binary_records, "skipped": skipped},
                                         indent=2, ensure_ascii=False).encode("utf-8"))
    return {"path": str(destination), "patch": str(patch_path), "binary_manifest": str(manifest_path),
            "files": changed, "changed": len(changed), "skipped": skipped}


class DockerExecutor:
    @staticmethod
    def executable():
        found = shutil.which("docker")
        if found:
            return found
        if os.name == "nt":
            candidates = [Path(os.environ.get("LOCALAPPDATA", "")) / "Programs/DockerDesktop/resources/bin/docker.exe",
                          Path(os.environ.get("PROGRAMFILES", "")) / "Docker/Docker/resources/bin/docker.exe"]
            for path in candidates:
                if path.is_absolute() and path.is_file():
                    return str(path)
        return None

    """Run a command in a local Linux image with only one workspace mounted.

    No host command fallback exists. Docker is optional and images must be built
    explicitly by a human. Container cleanup is attempted in ``finally``, even
    after an attach-client failure or timeout. An independent in-container
    watchdog bounds experiments even after the host runner dies. Docker remains
    a privileged host service; use a dedicated machine/VM for hostile code.
    """

    def __init__(self, image: str = "metaweb-swarm-experiment:local", timeout_seconds: int = 60):
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/:@-]{0,255}", image):
            raise ValueError("Invalid Docker image reference")
        if not 1 <= timeout_seconds <= 3600:
            raise ValueError("Timeout must be between 1 and 3600 seconds")
        self.image, self.timeout_seconds = image, timeout_seconds
        self.output_limit = 100_000

    @staticmethod
    def _environment(config: Path) -> dict[str, str]:
        allowed = {"PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "PATHEXT"}
        environment = {key: value for key, value in os.environ.items() if key.upper() in allowed}
        environment["DOCKER_CONFIG"] = str(config)
        return environment

    def _call(self, argv: list[str], environment: dict[str, str], timeout: int) -> dict[str, Any]:
        """Drain stdout without accumulating unlimited experiment output."""
        output = bytearray()
        truncated = False
        if argv and argv[0] == "docker":
            argv = [self.executable() or "docker", *argv[1:]]
        process = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                   stdin=subprocess.DEVNULL, env=environment, shell=False)

        def drain() -> None:
            nonlocal truncated
            assert process.stdout is not None
            try:
                while chunk := process.stdout.read(65_536):
                    room = self.output_limit - len(output)
                    output.extend(chunk[:max(0, room)])
                    if len(chunk) > room:
                        truncated = True
            except (OSError, ValueError):
                pass

        reader = threading.Thread(target=drain, daemon=True)
        reader.start()
        timed_out = False
        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            process.kill()
            process.wait(timeout=5)
        except BaseException:
            process.kill()
            process.wait(timeout=5)
            raise
        finally:
            reader.join(timeout=2)
            if process.stdout is not None:
                process.stdout.close()
        return {"returncode": process.returncode, "output": output.decode("utf-8", errors="replace"),
                "timed_out": timed_out, "output_truncated": truncated}

    def check_ready(self) -> dict[str, Any]:
        """No pull, build, container creation, workspace mount or experiment."""
        with tempfile.TemporaryDirectory(prefix="metaweb-docker-check-") as temporary:
            environment = self._environment(Path(temporary))
            try:
                engine = self._call(["docker", "info", "--format", "{{.OSType}}"], environment, 15)
                if engine["returncode"] != 0 or engine.get("timed_out") or engine["output"].strip() != "linux":
                    return {"ready": False, "reason": "LINUX_DAEMON_UNAVAILABLE", "output": engine["output"]}
                image = self._call(["docker", "image", "inspect", self.image], environment, 15)
                if image["returncode"] != 0 or image.get("timed_out"):
                    return {"ready": False, "reason": "LOCAL_IMAGE_MISSING", "image": self.image}
                return {"ready": True, "image": self.image, "experiment_executed": False}
            except OSError as error:
                return {"ready": False, "reason": "DOCKER_UNAVAILABLE", "error": str(error)}

    def run(self, workspace_root: Path, argv: list[str]) -> dict[str, Any]:
        return self._run(workspace_root, argv)

    def fetch_packages(self, build_root: Path, packages: list[str]) -> dict[str, Any]:
        # Only an empty, host-created staging directory is mounted online.
        from .packages import requirements, PACKAGE_DRIVER
        specs = requirements(packages)
        return self._run(build_root, ["python", "-I", "-c", PACKAGE_DRIVER, "fetch", json.dumps(specs)],
            package_fetch=True)

    def install_packages(self, workspace_root: Path, wheelhouse: Path, packages: list[str]) -> dict[str, Any]:
        from .packages import requirements, PACKAGE_DRIVER
        specs = requirements(packages)
        return self._run(workspace_root, ["python", "-I", "-c", PACKAGE_DRIVER, "install", json.dumps(specs)], wheelhouse=wheelhouse)

    def _run(self, workspace_root: Path, argv: list[str], *, package_fetch=False, wheelhouse=None) -> dict[str, Any]:
        root = _plain_absolute(workspace_root)
        if not root.is_dir() or "," in str(root):
            raise SecurityError("Expected a workspace directory usable as a single Docker mount")
        marker = _read_bytes(root, Path(_WORKSPACE_MARKER), 65_536)
        if json.loads(marker).get("root") != str(root):
            raise SecurityError("Expected a Workspace-created directory")
        _inventory(root, exclude=False, reject_links=True)
        if not argv or not all(isinstance(arg, str) and "\x00" not in arg for arg in argv):
            raise ValueError("Expected a non-empty command argument list")
        if sum(len(arg) for arg in argv) > 100_000:
            raise ValueError("Command arguments exceed the safety limit")
        extra = ["--env", "PIP_CONFIG_FILE=/dev/null"]
        if package_fetch or wheelhouse is not None:
            extra += ["--tmpfs", "/package-tmp:rw,nosuid,nodev,size=512m,mode=1777", "--env", "TMPDIR=/package-tmp"]
        if not package_fetch:
            extra += ["--env", "PYTHONPATH=/workspace/.packages",
                      "--env", "PATH=/workspace/.packages/bin:/usr/local/bin:/usr/local/sbin:/usr/sbin:/usr/bin:/sbin:/bin"]
        if wheelhouse is not None:
            wheels = _plain_absolute(wheelhouse)
            if not wheels.is_dir() or "," in str(wheels):
                raise SecurityError("Invalid wheelhouse mount")
            _inventory(wheels, exclude=False, reject_links=True)
            extra += ["--mount", f"type=bind,src={wheels},dst=/wheels,readonly"]
        name = "metaweb-swarm-" + uuid.uuid4().hex
        user = "65534:65534"
        if os.name == "posix" and os.getuid() != 0:
            # The host user's IDs make its bind-mounted files writable without
            # broadening permissions for other host users.
            user = f"{os.getuid()}:{os.getgid()}"
        create = [
            "docker", "create", "--name", name, "--pull=never", "--network", "bridge" if package_fetch else "none",
            "--cap-drop", "ALL", "--security-opt", "no-new-privileges", "--read-only",
            "--pids-limit", "64", "--memory", "512m", "--cpus", "1", "--user", user,
            "--stop-timeout", "2", "--tmpfs", "/tmp:rw,noexec,nosuid,size=64m",
            "--mount", f"type=bind,src={root},dst=/workspace", "--workdir", "/workspace",
            "--env", "HOME=/tmp", "--env", "TMPDIR=/tmp", *extra, "--entrypoint", "/usr/bin/timeout",
            self.image, "--signal=TERM", "--kill-after=5", "--", f"{self.timeout_seconds}s", *argv,
        ]
        result: dict[str, Any] = {"status": "BLOCKED", "output": "", "returncode": None,
                                  "timed_out": False, "output_truncated": False,
                                  "container": name, "cleanup_ok": False}
        with tempfile.TemporaryDirectory(prefix="metaweb-docker-config-") as temporary:
            environment = self._environment(Path(temporary))
            try:
                engine = self._call(["docker", "info", "--format", "{{.OSType}}"], environment, 15)
                if engine["returncode"] != 0 or engine["output"].strip() != "linux":
                    result["output"] = "A reachable Linux Docker engine is required. " + engine["output"]
                    return result
                inspect = self._call(["docker", "image", "inspect", self.image], environment, 15)
                if inspect["returncode"] != 0:
                    result["output"] = "Local experiment image is missing; image pulls are disabled. " + inspect["output"]
                    return result
                created = self._call(create, environment, 15)
                if created["returncode"] != 0 or created["timed_out"]:
                    result.update(created)
                    return result
                attached = self._call(["docker", "start", "--attach", name], environment, self.timeout_seconds)
                result.update(attached)
                result["status"] = "LIMIT_REACHED" if attached["timed_out"] else "BLOCKED"
                if not attached["timed_out"]:
                    # Docker client success alone is not proof that the command
                    # finished successfully; inspect the actual container state.
                    inspected = self._call(["docker", "inspect", "--format", "{{json .State}}", name], environment, 10)
                    try:
                        state = json.loads(inspected["output"])
                        if inspected["returncode"] != 0 or state.get("Running") is not False:
                            raise ValueError("Container completion state unavailable")
                        exit_code = state.get("ExitCode")
                        if type(exit_code) is not int:
                            raise ValueError("Container exit code unavailable")
                        result["returncode"] = exit_code
                        result["timed_out"] = exit_code in (124, 137)
                        result["status"] = "LIMIT_REACHED" if result["timed_out"] else "COMPLETED" if exit_code == 0 else "BLOCKED"
                        if state.get("OOMKilled") is True:
                            result["status"] = "LIMIT_REACHED"
                            result["limit_reason"] = "CONTAINER_MEMORY"
                        if exit_code == 127:
                            result["reason"] = "The local image must contain /usr/bin/timeout and the requested command"
                    except (TypeError, ValueError) as exc:
                        result["status"] = "BLOCKED"
                        result["reason"] = str(exc)
            except OSError as exc:
                result["output"] = f"Docker is unavailable: {exc}"
            finally:
                # The attach client may disappear while the container survives.
                # Address the independently named container rather than its PID.
                try:
                    self._call(["docker", "kill", name], environment, 10)
                    cleanup = self._call(["docker", "rm", "--force", name], environment, 10)
                    result["cleanup_ok"] = cleanup["returncode"] == 0 or "No such container" in cleanup["output"]
                    if not result["cleanup_ok"]:
                        result["status"] = "BLOCKED"
                        result["cleanup_error"] = cleanup["output"]
                except OSError as exc:
                    result["cleanup_error"] = str(exc)
        return result
