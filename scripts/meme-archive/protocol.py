"""Meme Archive v1 binary transport and bounded RFC 6330 backend bridge.

Transport details are specified in FORMAT.md. No image library is imported here.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass
import gzip
import hashlib
import json
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import zlib


MAGIC = b"MA"
VERSION = 1
FEC_ID = 6
COMPRESSION_ID = 1
HEADER_BYTES = 41  # Includes FEC Payload ID and trailing CRC, excludes symbol.
MAX_TRANSFER_BYTES = 64 * 1024 * 1024
MAX_OUTPUT_BYTES = 64 * 1024 * 1024
OBJECT_MAGIC = b"MAO1"


def make_object(raw: bytes) -> bytes:
    """Wrap a deterministic gzip member and its uncompressed SHA-256."""
    member = bytearray(gzip.compress(raw, compresslevel=9, mtime=0))
    # Python versions differ here when delegating mtime=0 directly to zlib.
    member[9] = 255
    return OBJECT_MAGIC + hashlib.sha256(raw).digest() + bytes(member)


def unpack_object(data: bytes, max_output: int = MAX_OUTPUT_BYTES) -> bytes:
    if max_output < 1:
        raise ValueError("Maximum output size must be positive.")
    if len(data) < 54 or data[:4] != OBJECT_MAGIC:
        raise ValueError("Unsupported or truncated Meme Archive object.")
    digest, compressed = data[4:36], data[36:]
    decoder = zlib.decompressobj(16 + zlib.MAX_WBITS)
    try:
        raw = decoder.decompress(compressed, max_output + 1)
    except zlib.error as exc:
        raise ValueError("Invalid gzip object (including its CRC32/size).") from exc
    if len(raw) > max_output or decoder.unconsumed_tail:
        raise ValueError(f"Decompressed archive exceeds the {max_output}-byte limit.")
    if not decoder.eof or decoder.unused_data:
        raise ValueError("Truncated gzip object or trailing/multiple gzip members.")
    if hashlib.sha256(raw).digest() != digest:
        raise ValueError("Reconstructed ALL_POSTS.txt SHA-256 does not match.")
    return raw


@dataclass(frozen=True)
class OTI:
    transfer_length: int
    symbol_size: int
    source_blocks: int
    sub_blocks: int
    alignment: int


def parse_oti(data: bytes, max_transfer: int = MAX_TRANSFER_BYTES) -> OTI:
    if len(data) != 12:
        raise ValueError("RFC 6330 OTI must contain exactly 12 bytes.")
    length = int.from_bytes(data[:5], "big")
    symbol_size = int.from_bytes(data[6:8], "big")
    blocks = data[8]
    sub_blocks = int.from_bytes(data[9:11], "big")
    alignment = data[11]
    if data[5] != 0:
        raise ValueError("RFC 6330 OTI reserved byte must be zero.")
    if not 1 <= length <= min(max_transfer, 946270874880):
        raise ValueError(f"RFC 6330 transfer length is outside the {max_transfer}-byte limit.")
    if symbol_size == 0 or blocks == 0:
        raise ValueError("RFC 6330 symbol size and source block count must be positive.")
    if sub_blocks != 1 or alignment != 1:
        raise ValueError("Meme Archive v1 supports RFC 6330 profile N=1 and Al=1 only.")
    source_symbols = (length + symbol_size - 1) // symbol_size
    if blocks > source_symbols or (source_symbols + blocks - 1) // blocks > 56403:
        raise ValueError("RFC 6330 source block partition exceeds the permitted K range.")
    return OTI(length, symbol_size, blocks, sub_blocks, alignment)


@dataclass(frozen=True)
class Packet:
    edition: bytes
    oti: bytes
    packet: bytes
    sbn: int
    esi: int
    symbol_size: int

    @property
    def edition_hex(self) -> str:
        return self.edition.hex()


def wrap_packet(edition: bytes, oti: bytes, packet: bytes) -> bytes:
    if len(edition) != 16:
        raise ValueError("Edition identifier must contain exactly 16 bytes.")
    config = parse_oti(oti)
    if len(packet) != config.symbol_size + 4 or packet[0] >= config.source_blocks:
        raise ValueError("RFC 6330 packet size or source block number is invalid.")
    body = MAGIC + bytes((VERSION, FEC_ID, COMPRESSION_ID)) + edition + oti + packet
    return body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)


def parse_packet(data: bytes, max_transfer: int = MAX_TRANSFER_BYTES) -> Packet:
    if len(data) < HEADER_BYTES + 1:
        raise ValueError("Meme Archive packet is truncated.")
    if data[:2] != MAGIC or data[2:5] != bytes((VERSION, FEC_ID, COMPRESSION_ID)):
        raise ValueError("Unsupported Meme Archive magic/version/FEC/compression identifiers.")
    if zlib.crc32(data[:-4]) & 0xFFFFFFFF != int.from_bytes(data[-4:], "big"):
        raise ValueError("Meme Archive packet CRC32 mismatch.")
    oti = data[21:33]
    config = parse_oti(oti, max_transfer=max_transfer)
    if len(data) != HEADER_BYTES + config.symbol_size:
        raise ValueError("Meme Archive packet must contain exactly one complete RaptorQ symbol.")
    packet = data[33:-4]
    sbn, esi = packet[0], int.from_bytes(packet[1:4], "big")
    if sbn >= config.source_blocks:
        raise ValueError("RFC 6330 source block number is outside the OTI partition.")
    return Packet(data[5:21], oti, packet, sbn, esi, config.symbol_size)


def b64encode(value: bytes) -> str:
    return base64.b64encode(value).decode("ascii")


def b64decode(value: str) -> bytes:
    try:
        return base64.b64decode(value, validate=True)
    except (ValueError, TypeError) as exc:
        raise ValueError("Backend returned invalid base64 data.") from exc


class Backend:
    """One long-lived Node/WASM process; stderr cannot block its JSON stream."""

    def __init__(self, node: str = "node", backend_path: Path | None = None):
        executable = shutil.which(node)
        if not executable:
            raise RuntimeError("Node.js is required for the RFC 6330 backend; install Node or use --node.")
        self.stderr = tempfile.TemporaryFile(mode="w+b")
        path = backend_path or Path(__file__).with_name("backend.mjs")
        try:
            self.process = subprocess.Popen(
                [executable, str(path)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=self.stderr, text=True, encoding="utf-8", bufsize=1,
            )
        except OSError:
            self.stderr.close()
            raise

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def request(self, op: str, **kwargs) -> dict:
        try:
            if self.process.poll() is not None:
                raise RuntimeError("RFC 6330 backend process exited.")
            self.process.stdin.write(json.dumps({"op": op, **kwargs}, separators=(",", ":")) + "\n")
            self.process.stdin.flush()
            response = self.process.stdout.readline()
            if not response:
                raise RuntimeError("RFC 6330 backend did not return a response.")
            result = json.loads(response)
        except (BrokenPipeError, OSError, json.JSONDecodeError, RuntimeError) as exc:
            self.stderr.flush()
            self.stderr.seek(0)
            detail = self.stderr.read(4096).decode("utf-8", errors="replace").strip()
            raise RuntimeError(f"RFC 6330 backend failed: {exc}" + (f"\n{detail}" if detail else "")) from exc
        if not isinstance(result, dict):
            raise RuntimeError("RFC 6330 backend returned a non-object response.")
        if result.get("error"):
            raise RuntimeError(f"RFC 6330 backend: {result['error']}")
        return result

    def close(self):
        if self.process.poll() is None:
            try:
                self.process.stdin.close()
                self.process.wait(timeout=3)
            except (OSError, subprocess.TimeoutExpired):
                self.process.kill()
                self.process.wait(timeout=3)
        if self.process.stdout:
            self.process.stdout.close()
        self.stderr.close()
