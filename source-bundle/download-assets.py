#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Iterable


MIN_PYTHON = (3, 9)
USER_AGENT = "vojtamaur-source-bundle-downloader/1.0"


@dataclass
class BadCandidate:
    kind: str
    source: str
    got_sha256: str
    local_path: Path | None = None
    temp_path: Path | None = None


@dataclass
class Result:
    status: str
    message: str = ""


def fail(message: str, code: int = 1) -> None:
    print(f"[assets] ERROR: {message}", file=sys.stderr)
    raise SystemExit(code)


def safe_manifest_path(value: str) -> Path:
    pure = PurePosixPath(value)

    if pure.is_absolute() or any(part in ("", ".", "..") for part in pure.parts):
        raise ValueError(f"Unsafe manifest path: {value!r}")

    return Path(*pure.parts)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()

    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)

    return h.hexdigest()


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def atomic_copy(source: Path, target: Path) -> None:
    ensure_parent(target)

    fd, temp_name = tempfile.mkstemp(
        prefix=f"{target.name}.",
        suffix=".part",
        dir=str(target.parent),
    )
    os.close(fd)

    temp_path = Path(temp_name)

    try:
        shutil.copy2(source, temp_path)
        os.replace(temp_path, target)
    finally:
        if temp_path.exists():
            temp_path.unlink()


def atomic_move(source: Path, target: Path) -> None:
    ensure_parent(target)
    os.replace(source, target)


def load_manifest(path: Path) -> list[dict[str, Any]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        fail(f"Manifest not found: {path}")
    except json.JSONDecodeError as error:
        fail(f"Manifest is not valid JSON: {path}: {error}")

    if isinstance(data, dict):
        files = data.get("files")
    else:
        files = data

    if not isinstance(files, list):
        fail("Manifest must contain a files list.")

    for index, item in enumerate(files):
        if not isinstance(item, dict):
            fail(f"Manifest item #{index + 1} is not an object.")
        for key in ("path", "web_path", "sha256", "urls"):
            if key not in item:
                fail(f"Manifest item #{index + 1} is missing {key!r}.")

    return files


def local_candidate_paths(root: Path, web_path: str, target: Path) -> list[Path]:
    web_rel = safe_manifest_path(web_path.lstrip("/"))

    candidate_roots = [
        root,
        root / "dist",
        root.parent,
        root.parent / "dist",
        root.parent.parent,
        root.parent.parent / "dist",
    ]

    candidates: list[Path] = []
    seen: set[Path] = set()

    for candidate_root in candidate_roots:
        candidate = (candidate_root / web_rel).resolve(strict=False)
        target_resolved = target.resolve(strict=False)

        if candidate == target_resolved:
            continue

        if candidate in seen:
            continue

        seen.add(candidate)
        candidates.append(candidate)

    return candidates


def rejected_path(root: Path, item_path: str, got_sha256: str) -> Path:
    rel = safe_manifest_path(item_path)
    target = root / "_rejected-assets" / rel
    suffix = "".join(target.suffixes)
    stem = target.name[:-len(suffix)] if suffix else target.name
    rejected_name = f"{stem}.{got_sha256[:12]}.bad-sha256{suffix}"
    return target.with_name(rejected_name)


def save_rejected(candidate: BadCandidate, root: Path, item_path: str) -> Path | None:
    destination = rejected_path(root, item_path, candidate.got_sha256)
    ensure_parent(destination)

    if candidate.temp_path and candidate.temp_path.exists():
        shutil.move(str(candidate.temp_path), destination)
        return destination

    if candidate.local_path and candidate.local_path.exists():
        shutil.copy2(candidate.local_path, destination)
        return destination

    return None


def prompt_yes_no(message: str) -> bool:
    if not sys.stdin.isatty():
        return False

    answer = input(f"{message} [y/N] ").strip().lower()
    return answer in {"y", "yes", "a", "ano"}


def download_to_temp(url: str, target: Path, timeout: float) -> tuple[Path, str]:
    ensure_parent(target)

    fd, temp_name = tempfile.mkstemp(
        prefix=f"{target.name}.",
        suffix=".download.part",
        dir=str(target.parent),
    )
    os.close(fd)

    temp_path = Path(temp_name)
    h = hashlib.sha256()

    request = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT},
        method="GET",
    )

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            with temp_path.open("wb") as handle:
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    h.update(chunk)
                    handle.write(chunk)
    except Exception:
        if temp_path.exists():
            temp_path.unlink()
        raise

    return temp_path, h.hexdigest()


def accept_bad_candidate(candidate: BadCandidate, target: Path) -> None:
    if candidate.temp_path and candidate.temp_path.exists():
        atomic_move(candidate.temp_path, target)
        return

    if candidate.local_path and candidate.local_path.exists():
        atomic_copy(candidate.local_path, target)
        return

    raise RuntimeError("Bad candidate no longer exists.")


def verify_existing(target: Path, expected: str) -> Result | None:
    if not target.exists():
        return None

    got = sha256_file(target)

    if got == expected:
        return Result("ok-existing", "already valid")

    return Result(
        "bad-existing",
        f"existing file has wrong SHA-256: got {got}, expected {expected}",
    )


def try_local_candidates(
    root: Path,
    item: dict[str, Any],
    target: Path,
    expected: str,
) -> tuple[Result | None, list[BadCandidate]]:
    bad_candidates: list[BadCandidate] = []

    for candidate in local_candidate_paths(root, str(item["web_path"]), target):
        if not candidate.is_file():
            continue

        got = sha256_file(candidate)

        if got == expected:
            atomic_copy(candidate, target)
            return Result("copied-local", f"copied from {candidate}"), bad_candidates

        bad_candidates.append(
            BadCandidate(
                kind="local",
                source=str(candidate),
                got_sha256=got,
                local_path=candidate,
            )
        )

        print(
            "[assets] local hash mismatch:",
            candidate,
            f"got={got}",
            f"expected={expected}",
        )

    return None, bad_candidates


def try_downloads(
    item: dict[str, Any],
    target: Path,
    expected: str,
    timeout: float,
) -> tuple[Result | None, list[BadCandidate]]:
    bad_candidates: list[BadCandidate] = []
    urls = item.get("urls") or []

    if not isinstance(urls, list):
        return None, bad_candidates

    for url in urls:
        if not isinstance(url, str):
            continue

        try:
            temp_path, got = download_to_temp(url, target, timeout)
        except urllib.error.HTTPError as error:
            print(f"[assets] HTTP {error.code}: {url}")
            continue
        except urllib.error.URLError as error:
            print(f"[assets] URL error: {url}: {error.reason}")
            continue
        except Exception as error:
            print(f"[assets] download failed: {url}: {error}")
            continue

        if got == expected:
            atomic_move(temp_path, target)
            return Result("downloaded", f"downloaded from {url}"), bad_candidates

        bad_candidates.append(
            BadCandidate(
                kind="download",
                source=url,
                got_sha256=got,
                temp_path=temp_path,
            )
        )

        print(
            "[assets] downloaded hash mismatch:",
            url,
            f"got={got}",
            f"expected={expected}",
        )

    return None, bad_candidates


def process_item(root: Path, item: dict[str, Any], args: argparse.Namespace) -> Result:
    item_path = str(item["path"])
    expected = str(item["sha256"]).lower()
    target = root / safe_manifest_path(item_path)

    existing = verify_existing(target, expected)

    if existing and existing.status == "ok-existing":
        return existing

    if args.verify:
        if existing:
            return existing
        return Result("missing", "missing")

    if existing and existing.status == "bad-existing":
        print(f"[assets] {item_path}: {existing.message}")

    local_result, bad_local = try_local_candidates(root, item, target, expected)

    if local_result:
        return local_result

    download_result, bad_downloads = try_downloads(item, target, expected, args.timeout)

    if download_result:
        for candidate in bad_downloads:
            if candidate.temp_path and candidate.temp_path.exists():
                candidate.temp_path.unlink()
        return download_result

    bad_candidates = bad_local + bad_downloads

    if bad_candidates:
        candidate = bad_candidates[-1]
        should_accept = args.accept_bad_hash

        if not should_accept and args.interactive:
            should_accept = prompt_yes_no(
                f"[assets] {item_path}: use {candidate.kind} candidate despite bad SHA-256 from {candidate.source}?"
            )

        if should_accept:
            accept_bad_candidate(candidate, target)

            for other in bad_candidates:
                if other is not candidate and other.temp_path and other.temp_path.exists():
                    other.temp_path.unlink()

            return Result(
                "accepted-bad-hash",
                f"accepted bad SHA-256 from {candidate.source}; got {candidate.got_sha256}, expected {expected}",
            )

        if args.keep_rejected:
            saved = save_rejected(candidate, root, item_path)

            for other in bad_candidates:
                if other is not candidate and other.temp_path and other.temp_path.exists():
                    other.temp_path.unlink()

            if saved:
                return Result(
                    "rejected-bad-hash",
                    f"rejected bad SHA-256 from {candidate.source}; saved as {saved}",
                )

    for candidate in bad_candidates:
        if candidate.temp_path and candidate.temp_path.exists():
            candidate.temp_path.unlink()

    return Result("failed", "no valid source found")


def parse_args(argv: Iterable[str]) -> argparse.Namespace:
    script_dir = Path(__file__).resolve().parent

    parser = argparse.ArgumentParser(
        description="Download or verify public assets for a vojtamaur.cz source bundle.",
    )

    parser.add_argument(
        "--root",
        default=str(script_dir),
        help="Directory where the reconstructed source tree lives. Default: directory of this script.",
    )
    parser.add_argument(
        "--manifest",
        default=None,
        help="Path to MEDIA_MANIFEST.json. Default: <root>/MEDIA_MANIFEST.json.",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Only verify existing files; do not copy or download anything.",
    )
    parser.add_argument(
        "--interactive",
        action="store_true",
        help="Ask before accepting a file with a bad SHA-256 hash.",
    )
    parser.add_argument(
        "--accept-bad-hash",
        action="store_true",
        help="Emergency mode: accept the last available bad-hash candidate. This is not a clean reconstruction.",
    )
    parser.add_argument(
        "--keep-rejected",
        action="store_true",
        help="Keep one rejected bad-hash candidate under _rejected-assets/ for inspection.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=20.0,
        help="Network timeout in seconds. Default: 20.",
    )

    return parser.parse_args(list(argv))


def main(argv: Iterable[str] = sys.argv[1:]) -> int:
    if sys.version_info < MIN_PYTHON:
        fail("Python 3.9 or newer is required.")

    args = parse_args(argv)
    root = Path(args.root).resolve()
    manifest_path = Path(args.manifest).resolve() if args.manifest else root / "MEDIA_MANIFEST.json"
    files = load_manifest(manifest_path)

    print(f"[assets] root: {root}")
    print(f"[assets] manifest: {manifest_path}")
    print(f"[assets] files: {len(files)}")

    counts: dict[str, int] = {}

    for index, item in enumerate(files, start=1):
        item_path = str(item["path"])
        print(f"[assets] {index}/{len(files)} {item_path}")

        try:
            result = process_item(root, item, args)
        except KeyboardInterrupt:
            raise
        except Exception as error:
            result = Result("failed", str(error))

        counts[result.status] = counts.get(result.status, 0) + 1

        if result.message:
            print(f"[assets]   {result.status}: {result.message}")
        else:
            print(f"[assets]   {result.status}")

    print("[assets] summary:")
    for key in sorted(counts):
        print(f"[assets]   {key}: {counts[key]}")

    clean_statuses = {"ok-existing", "copied-local", "downloaded"}
    if set(counts).issubset(clean_statuses):
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
