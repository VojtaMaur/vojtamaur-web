"""Small GUI-only tasks that preserve the website's original export scripts."""
from __future__ import annotations

import argparse
from datetime import datetime
import os
from pathlib import Path
import shutil
import tempfile


def snapshot(project_root: Path, kind: str, output: str | None = None) -> Path:
    """Copy one exact built archive into a separate file; never rewrite dist/."""
    if kind not in ("txt", "json"):
        raise ValueError("Formát musí být txt nebo json.")
    root = Path(project_root).resolve()
    source = root / "dist" / ("ALL_POSTS." + kind)
    if not source.is_file():
        raise ValueError("Chybí " + str(source) + ". Nejprve vytvořte aktuální web.")
    if output:
        destination = Path(output).expanduser()
        if not destination.is_absolute():
            destination = root / destination
        destination = destination.resolve()
    else:
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S-%f")
        destination = root / "exports" / ("ALL_POSTS-" + timestamp + "." + kind)
    dist = (root / "dist").resolve()
    if destination == dist or dist in destination.parents:
        raise ValueError("Výstup musí být mimo dist/, aby se nezměnil hotový web a jeho podpis.")
    if destination.suffix.lower() != "." + kind:
        raise ValueError("Výstup musí mít příponu ." + kind + ".")
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=".export-manager-", suffix=".tmp", dir=destination.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as target, source.open("rb") as origin:
            shutil.copyfileobj(origin, target)
            target.flush()
            os.fsync(target.fileno())
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    return destination


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="task", required=True)
    command = commands.add_parser("snapshot", help="Samostatná kopie ALL_POSTS.txt nebo ALL_POSTS.json z hotového webu.")
    command.add_argument("--kind", choices=("txt", "json"), required=True)
    command.add_argument("--project-root", type=Path, required=True)
    command.add_argument("--output", help="Volitelný cílový soubor mimo dist/.")
    args = parser.parse_args(argv)
    try:
        destination = snapshot(args.project_root, args.kind, args.output)
    except (OSError, ValueError) as error:
        parser.exit(1, "Export se nezdařil: " + str(error) + "\n")
    print("Vytvořeno: " + str(destination))


if __name__ == "__main__":
    main()
