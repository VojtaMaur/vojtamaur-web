"""Timestamped names for manual exports, independent of rendering libraries."""
from __future__ import annotations

import argparse
from datetime import datetime
import os
from pathlib import Path
import re

TIMESTAMP_FORMAT = "%Y-%m-%d_%H-%M-%S-%f"
TIMESTAMP_ENV = "VOJTAMAUR_EXPORT_TIMESTAMP"
TIMESTAMP_PATTERN = r"\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}-\d{6}"


def validate_timestamp(value: str) -> str:
    if not re.fullmatch(TIMESTAMP_PATTERN, value):
        raise argparse.ArgumentTypeError("Timestamp must use YYYY-MM-DD_HH-MM-SS-ffffff.")
    try:
        datetime.strptime(value, TIMESTAMP_FORMAT)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"Invalid export timestamp: {value}") from exc
    return value


def new_timestamp() -> str:
    """Use local time, or the shared timestamp selected by export-all.bat."""
    value = os.environ.get(TIMESTAMP_ENV)
    return validate_timestamp(value) if value is not None else datetime.now().strftime(TIMESTAMP_FORMAT)


def add_arguments(parser: argparse.ArgumentParser) -> None:
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--timestamp", type=validate_timestamp, metavar="YYYY-MM-DD_HH-MM-SS-ffffff",
                       help="Timestamp for automatically generated names; default: local export start time. Explicit --output names are unchanged.")
    group.add_argument("--no-timestamp", action="store_true",
                       help="Use legacy names for automatic outputs, replacing previous exports at those paths.")


def timestamp_for(args: argparse.Namespace) -> str | None:
    """Cache one timestamp per invocation, including bilingual and separate output."""
    if not hasattr(args, "_export_timestamp"):
        args._export_timestamp = (None if args.no_timestamp else args.timestamp or new_timestamp())
    return args._export_timestamp


def stamped_path(path: Path, stamp: str | None) -> Path:
    if stamp is None:
        return path
    # Keep compound sidecar extensions together, so PDF/TXT/manifest stems match.
    extension = next((suffix for suffix in (".manifest.json", ".failures.jsonl")
                      if path.name.endswith(suffix)), path.suffix)
    stem = path.name[:-len(extension)] if extension else path.name
    return path.with_name(f"{stem}-{stamp}{extension}")


def variant_path(path: Path, marker: str) -> Path:
    """Keep the timestamp last when PDF processing adds a derivative label."""
    match = re.search(rf"-({TIMESTAMP_PATTERN})$", path.stem)
    if match:
        return path.with_name(f"{path.stem[:match.start()]}-{marker}-{match[1]}{path.suffix}")
    return path.with_name(f"{path.stem}-{marker}{path.suffix}")


if __name__ == "__main__":
    # Each full batch always starts a fresh edition, even in an inherited shell.
    print(datetime.now().strftime(TIMESTAMP_FORMAT))
