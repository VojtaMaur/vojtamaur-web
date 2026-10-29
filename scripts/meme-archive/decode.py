#!/usr/bin/env python3
"""Recover ALL_POSTS.txt from Meme Archive QR images or optional raw .ma packets."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile

from protocol import (Backend, HEADER_BYTES, MAX_OUTPUT_BYTES, MAX_TRANSFER_BYTES, b64decode,
                      b64encode, parse_packet, unpack_object)


IMAGE_SUFFIXES = frozenset((".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"))


class InsufficientPackets(ValueError):
    pass


class DecodeSession:
    """Validate a single edition before forwarding its symbols to RaptorQ."""

    def __init__(self, backend, edition: bytes | None = None,
                 max_output: int = MAX_OUTPUT_BYTES, max_transfer: int = MAX_TRANSFER_BYTES):
        self.backend = backend
        self.selected = edition
        self.edition = None
        self.oti = None
        self.max_output = max_output
        self.max_transfer = max_transfer
        self.seen = {}
        self.decoded = None
        self.filtered = 0
        self.duplicates = 0

    def add(self, data: bytes) -> bool:
        record = parse_packet(data, max_transfer=self.max_transfer)
        if self.selected is not None and record.edition != self.selected:
            self.filtered += 1
            return False
        if self.edition is None:
            self.edition, self.oti = record.edition, record.oti
            self.backend.request("init_decoder", oti=b64encode(record.oti))
        elif record.edition != self.edition:
            raise ValueError(f"Mixed editions: {self.edition.hex()} and {record.edition.hex()}. "
                             "Decode separately or select --edition HEX.")
        elif record.oti != self.oti:
            raise ValueError("Conflicting RFC 6330 OTI for the same edition.")
        key = (record.sbn, record.esi)
        digest = hashlib.sha256(record.packet).digest()
        if key in self.seen:
            if self.seen[key] != digest:
                raise ValueError("Conflicting payloads for the same RaptorQ symbol identifier.")
            self.duplicates += 1
            return False
        self.seen[key] = digest
        if self.decoded is None:
            result = self.backend.request("decode", packet=b64encode(record.packet))
            if result.get("data") is not None:
                self.decoded = unpack_object(b64decode(result["data"]), self.max_output)
        return True

    def finish(self) -> bytes:
        if self.decoded is None:
            selection = " for the selected edition" if self.selected else ""
            raise InsufficientPackets(f"Archive is incomplete{selection}: {len(self.seen)} distinct symbols. "
                                      "Collect more memes from that edition and try again.")
        return self.decoded


def iter_files(inputs):
    """Walk lazily in stable order without materializing an entire edition."""
    for value in inputs:
        path = Path(value)
        if not path.exists():
            raise ValueError(f"Input does not exist: {path}")
        if path.is_dir():
            for directory, children, files in os.walk(path):
                children.sort()
                for name in sorted(files):
                    candidate = Path(directory) / name
                    if candidate.suffix.lower() in IMAGE_SUFFIXES or candidate.suffix.lower() == ".ma":
                        yield candidate
        elif path.suffix.lower() in IMAGE_SUFFIXES or path.suffix.lower() == ".ma":
            yield path
        else:
            raise ValueError(f"Unsupported input type: {path.name}; use images, directories or .ma packets.")


def edition_arg(value):
    try:
        edition = bytes.fromhex(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Edition must contain exactly 32 hexadecimal characters.") from exc
    if len(edition) != 16 or len(value) != 32:
        raise argparse.ArgumentTypeError("Edition must contain exactly 32 hexadecimal characters.")
    return edition


def positive_int(value):
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("Value must be positive.")
    return number


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inputs", nargs="+", help="Images, edition directories, or raw .ma packets.")
    parser.add_argument("--output", required=True, type=Path, help="Destination ALL_POSTS.txt, written after verification.")
    parser.add_argument("--edition", type=edition_arg, help="Select one edition if inputs contain several editions.")
    parser.add_argument("--force", action="store_true", help="Replace an existing output file.")
    parser.add_argument("--node", default="node", help="Node executable (default: node).")
    parser.add_argument("--max-output-bytes", type=positive_int, default=MAX_OUTPUT_BYTES)
    parser.add_argument("--max-transfer-bytes", type=positive_int, default=MAX_TRANSFER_BYTES)
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    if args.output.exists() and not args.force:
        print(f"Error: output already exists: {args.output}; use --force to replace it.", file=sys.stderr)
        return 1
    files = scanned = damaged = unrelated = 0
    try:
        with Backend(node=args.node) as backend:
            session = DecodeSession(backend, args.edition, args.max_output_bytes, args.max_transfer_bytes)
            scanner = None
            for path in iter_files(args.inputs):
                files += 1
                if path.suffix.lower() == ".ma":
                    if path.stat().st_size > HEADER_BYTES + 65535:
                        raise ValueError(f"Raw packet exceeds the maximum RFC 6330 symbol size: {path.name}")
                    packets = [path.read_bytes()]
                else:
                    if scanner is None:
                        from render import scan_packets
                        scanner = scan_packets
                    packets = scanner(path)
                    scanned += 1
                for data in packets:
                    if not data.startswith(b"MA"):
                        if path.suffix.lower() == ".ma":
                            raise ValueError(f"Raw packet does not contain the Meme Archive magic: {path.name}")
                        unrelated += 1
                        continue
                    try:
                        # CRC/header errors from damaged scans are discarded. Mixed
                        # editions and conflicting valid symbols remain hard errors.
                        parse_packet(data, max_transfer=args.max_transfer_bytes)
                    except ValueError as exc:
                        if path.suffix.lower() == ".ma":
                            raise
                        damaged += 1
                        print(f"Warning: discarding damaged QR in {path.name}: {exc}", file=sys.stderr)
                        continue
                    session.add(data)
                if path.suffix.lower() != ".ma" and scanned and scanned % 50 == 0:
                    print(f"Scanned {scanned} images; {len(session.seen)} distinct symbols.", file=sys.stderr)
            raw = session.finish()
            edition = session.edition.hex()
            stats = {"edition": edition, "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
                     "files": files, "images_scanned": scanned, "symbols": len(session.seen),
                     "duplicates": session.duplicates, "filtered": session.filtered,
                     "damaged": damaged, "unrelated_qr": unrelated}
        args.output.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(prefix=f".{args.output.name}.", suffix=".tmp", dir=args.output.parent)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(raw)
                handle.flush()
                os.fsync(handle.fileno())
            if args.output.exists() and not args.force:
                raise ValueError(f"Output appeared while decoding: {args.output}; use --force to replace it.")
            os.replace(temporary, args.output)
        finally:
            Path(temporary).unlink(missing_ok=True)
        print(json.dumps({"output": str(args.output.resolve()), **stats}, ensure_ascii=False))
        return 0
    except InsufficientPackets as exc:
        print(f"Incomplete: {exc} (scanned {scanned} images; damaged QR: {damaged}).", file=sys.stderr)
        return 2
    except (OSError, ValueError, RuntimeError, ImportError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
