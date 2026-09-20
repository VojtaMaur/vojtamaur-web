"""Render complete DNA text files as absolute cardinal walks.

A = north (+Y), T = south (-Y), C = east (+X), G = west (-X).
Only these four uppercase ASCII characters move the pen. All other bytes,
including whitespace, ambiguous bases, lowercase letters and U, are ignored.
Inputs must be plain sequence text (not FASTA headers or annotated records).

Install: python -m pip install numpy matplotlib pillow
Run:     python run.py
Optional: python run.py --input-dir PATH --output-dir PATH --size 1800
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

import numpy as np
from matplotlib.backends.backend_agg import RendererAgg
from matplotlib.path import Path as PlotPath
from matplotlib.transforms import Affine2D
from PIL import Image


CHUNK_BYTES = 65_536
MAPPING = {"A": (0, 1), "T": (0, -1), "C": (1, 0), "G": (-1, 0)}
DX = np.zeros(256, dtype=np.int8)
DY = np.zeros(256, dtype=np.int8)
for _base, (_x, _y) in MAPPING.items():
    DX[ord(_base)], DY[ord(_base)] = _x, _y
VALID = (DX != 0) | (DY != 0)


def path_chunks(source: Path, chunk_bytes: int = CHUNK_BYTES):
    """Yield exact int64 vertices, including the previous chunk's endpoint.

    Every accepted base contributes exactly one unit segment. No sampling,
    path simplification, randomization, or per-chunk position resets occur.
    Memory usage is bounded by chunk size, not by total sequence length.
    """
    if chunk_bytes < 1:
        raise ValueError("chunk_bytes must be positive")
    x = y = 0
    with source.open("rb") as handle:
        while raw := handle.read(chunk_bytes):
            codes = np.frombuffer(raw, dtype=np.uint8)
            bases = codes[VALID[codes]]
            vertices = np.empty((len(bases) + 1, 2), dtype=np.int64)
            vertices[0] = (x, y)
            vertices[1:, 0] = np.cumsum(DX[bases], dtype=np.int64) + x
            vertices[1:, 1] = np.cumsum(DY[bases], dtype=np.int64) + y
            x, y = map(int, vertices[-1])
            yield raw, codes, vertices


def scan(source: Path) -> dict:
    """First pass: count all bytes and find exact bounds of the whole path."""
    histogram = np.zeros(256, dtype=np.int64)
    digest = hashlib.sha256()
    xmin = xmax = ymin = ymax = 0
    endpoint = [0, 0]
    for raw, codes, vertices in path_chunks(source):
        digest.update(raw)
        histogram += np.bincount(codes, minlength=256)
        xmin = min(xmin, int(vertices[:, 0].min()))
        xmax = max(xmax, int(vertices[:, 0].max()))
        ymin = min(ymin, int(vertices[:, 1].min()))
        ymax = max(ymax, int(vertices[:, 1].max()))
        endpoint = vertices[-1].tolist()
    counts = {base: int(histogram[ord(base)]) for base in MAPPING}
    # Independent invariant: endpoint equals the difference in base counts.
    assert endpoint == [counts["C"] - counts["G"], counts["A"] - counts["T"]]
    accepted = sum(counts.values())
    return {
        "input": source.name,
        "input_sha256": digest.hexdigest(),
        "input_bytes": int(histogram.sum()),
        "base_counts": counts,
        "accepted_bases": accepted,
        "ignored_bytes": int(histogram.sum()) - accepted,
        "ignored_symbols": {
            repr(chr(i)): int(histogram[i])
            for i in range(256) if histogram[i] and not VALID[i]
        },
        "start": [0, 0],
        "endpoint": endpoint,
        "bounds": [xmin, xmax, ymin, ymax],
    }


def render(source: Path, destination: Path, stats: dict, size: int = 1800) -> dict:
    """Second pass: draw every segment with the SAME scale for X and Y.

    Antialiasing keeps subpixel lines legible. Lossless WebP preserves the
    rendered pixels exactly, avoiding JPEG artifacts on thin black lines.
    """
    xmin, xmax, ymin, ymax = stats["bounds"]
    span_x, span_y = xmax - xmin, ymax - ymin
    margin = max(16, round(size * 0.032))
    scale = (size - 2 * margin) / max(span_x, span_y, 1)
    width = min(size, max(2 * margin + 1, math.ceil(span_x * scale) + 2 * margin))
    height = min(size, max(2 * margin + 1, math.ceil(span_y * scale) + 2 * margin))
    transform = Affine2D().scale(scale).translate(
        (width - span_x * scale) / 2 - xmin * scale,
        (height - span_y * scale) / 2 - ymin * scale,
    )
    renderer = RendererAgg(width, height, 100)
    renderer.clear()
    gc = renderer.new_gc()
    gc.set_foreground("#000000")
    gc.set_linewidth(0.85 * 72 / 100)  # 0.85 output pixels at 100 dpi
    gc.set_antialiased(True)
    gc.set_capstyle("round")
    gc.set_joinstyle("round")
    gc.set_snap(False)  # do not shift individual edges onto pixel centers
    digest = hashlib.sha256()
    segments = 0
    for raw, _, vertices in path_chunks(source):
        digest.update(raw)
        segments += len(vertices) - 1
        if len(vertices) > 1:
            path = PlotPath(vertices)
            path.should_simplify = False
            renderer.draw_path(gc, path, transform)
    gc.restore()
    if digest.hexdigest() != stats["input_sha256"]:
        raise RuntimeError(f"Input changed while rendering: {source}")
    assert segments == stats["accepted_bases"]
    rgba = Image.fromarray(np.asarray(renderer.buffer_rgba()).copy())
    white = Image.new("RGBA", rgba.size, "white")
    bitmap = Image.alpha_composite(white, rgba).convert("RGB")
    destination.parent.mkdir(parents=True, exist_ok=True)
    bitmap.save(destination, "WEBP", lossless=True, method=6)
    # Decode every output and confirm lossless preservation and dimensions.
    with Image.open(destination) as decoded:
        decoded.load()
        assert decoded.size == bitmap.size
        assert decoded.convert("RGB").tobytes() == bitmap.tobytes()
    return {
        **stats,
        "output": destination.name,
        "width": width,
        "height": height,
        "output_bytes": destination.stat().st_size,
        "output_sha256": hashlib.sha256(destination.read_bytes()).hexdigest(),
        "segments_rendered": segments,
        "pixels_per_unit_x": scale,
        "pixels_per_unit_y": scale,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--size", type=int, default=1800, help="Longest image edge in pixels")
    args = parser.parse_args()
    if not 256 <= args.size <= 8192:
        parser.error("--size must be between 256 and 8192")
    output_dir = args.output_dir or args.input_dir
    sources = sorted(
        (p for p in args.input_dir.iterdir() if p.is_file() and p.suffix.lower() == ".txt"),
        key=lambda p: p.name,
    )
    if not sources:
        parser.error(f"No TXT inputs in {args.input_dir}")
    results = []
    for source in sources:
        stats = scan(source)
        if not stats["accepted_bases"]:
            print(f"SKIP {source.name}: no A/T/C/G", flush=True)
            results.append({**stats, "status": "skipped_no_bases"})
            continue
        result = render(source, output_dir / f"{source.stem}.webp", stats, args.size)
        results.append(result)
        print(
            f'{source.name}: {result["accepted_bases"]:,} bases; '
            f'{result["width"]}x{result["height"]}; '
            f'{result["output_bytes"] / 1024:.1f} KiB', flush=True,
        )
    output_dir.mkdir(parents=True, exist_ok=True)
    report = {
        "mapping": {k: list(v) for k, v in MAPPING.items()},
        "format": "WebP lossless", "color": "#000000", "background": "#ffffff",
        "max_edge_px": args.size, "sampling": "none", "simplification": False,
        "files": results,
    }
    (output_dir / "export-report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
