# -*- coding: utf-8 -*-
"""Vektorová vizualizace velikostí souborů a adresářů do SVG.

Přepracováno z původního run.py. Výpočet délek a úhlů větví zůstává stejný.
Nepotřebuje matplotlib ani žádné externí knihovny.
"""

import math
import os
import re


# =========================
# KONFIGURACE (uprav tady)
# =========================
ROOT_PATH = r"E:\Creative Cloud Files  grafik@ateliermaur.cz D487509762985A5F0A495E69@d486509762985a5f495e69.e\ATELIER MAUR\15_MĚSTA"           # Kořen vizualizovaného stromu (např. r"D:\\")
OUT_DIR = "."               # Kam ukládat SVG (např. r"D:\exports")
INDEX_WIDTH = 4             # 0001, 0002, ...
LINEWIDTH = 0.01            # Tloušťka čar v bodech (jako v původním matplotlib)
RELATIVE_SCALE = 2          # Relativní škála

SCALE_MODE = "linear"       # "linear" | "sqrt" | "log"
MAX_SPAN_DEG = 140.0
SPAN_DECAY = 1              # Jak rychle se s hloubkou zužuje úhlový rozptyl větvení

FOLLOW_SYMLINKS = False
START_X, START_Y = 0.0, -0.9
START_ANGLE_DEG = 90.0
RADIUS = 0.95
SORT_CHILDREN = True

DRAW_NODE_TICKS = False     # Debug: křížky v místech návaznosti větví
TICK_LEN = 0.006

# SVG
SVG_VIEWBOX_SIZE = 2000    # Jen souřadnicová škála, nikoliv počet pixelů bitmapy
SVG_DECIMALS = 3           # Přesnost souřadnic (3 stačí i pro vysoké přiblížení)
SEGMENTS_PER_PATH = 20000  # Seskupení čar do SVG <path>, úspora dat a paměti
BACKGROUND = "white"      # "white" nebo "none" pro průhledné pozadí
# =========================


def sanitize_for_windows_filename(s: str, max_len: int = 180) -> str:
    """Z cesty udělá bezpečný název souboru na Windows."""
    s = s.strip().replace("/", "\\").replace("\\", "__")
    s = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", s)
    s = re.sub(r"_+", "_", s)
    s = s.rstrip(" .") or "root"
    return s[:max_len].rstrip(" .") or "root"


def next_index(out_dir: str, width: int) -> int:
    """Naváže na indexy starých PNG i nových SVG."""
    os.makedirs(out_dir, exist_ok=True)
    pat = re.compile(rf"^(\d{{{width}}})__.*\.(?:png|svg)$", re.IGNORECASE)
    mx = 0
    for fn in os.listdir(out_dir):
        match = pat.match(fn)
        if match:
            mx = max(mx, int(match.group(1)))
    return mx + 1


def build_output_path(root_abs: str) -> str:
    slug = sanitize_for_windows_filename(root_abs)
    idx = next_index(OUT_DIR, INDEX_WIDTH)
    return os.path.join(OUT_DIR, f"{idx:0{INDEX_WIDTH}d}__{slug}.svg")


def weight(size: int) -> float:
    s = max(int(size), 0)
    if SCALE_MODE == "linear":
        return float(s)
    if SCALE_MODE == "sqrt":
        return math.sqrt(float(s))
    return math.log1p(float(s))


def safe_stat_size(path: str) -> int:
    try:
        return os.stat(path, follow_symlinks=FOLLOW_SYMLINKS).st_size
    except Exception:
        return 0


def normalized(path: str) -> str:
    return os.path.normcase(os.path.abspath(path))


def compute_dir_totals(root: str, excluded: str) -> dict:
    dir_totals = {}
    for dirpath, dirnames, filenames in os.walk(root, followlinks=FOLLOW_SYMLINKS):
        total_here = 0
        for fn in filenames:
            fp = os.path.join(dirpath, fn)
            if normalized(fp) != excluded:
                total_here += safe_stat_size(fp)
        dir_totals[dirpath] = total_here

    # Stejně jako v originálu: součty od nejhlubších adresářů ke kořeni.
    for d in sorted(dir_totals, key=lambda p: p.count(os.sep), reverse=True):
        parent = os.path.dirname(d)
        if parent in dir_totals:
            dir_totals[parent] += dir_totals[d]
    return dir_totals


def iter_children(path: str, dir_totals: dict, excluded: str):
    """Přímí potomci a jejich velikosti; žádné následování symlinků dle nastavení."""
    try:
        with os.scandir(path) as it:
            for entry in it:
                p = entry.path
                if normalized(p) == excluded:
                    continue
                try:
                    is_dir = entry.is_dir(follow_symlinks=FOLLOW_SYMLINKS)
                except Exception:
                    is_dir = False
                if is_dir:
                    sz = dir_totals.get(p, 0)
                else:
                    try:
                        sz = entry.stat(follow_symlinks=FOLLOW_SYMLINKS).st_size
                    except Exception:
                        sz = 0
                yield p, sz
    except OSError:
        return


def compute_max_path(root: str, dir_totals: dict, excluded: str) -> float:
    root_w = weight(dir_totals.get(root, 0) if os.path.isdir(root) else safe_stat_size(root))
    maxp = root_w
    stack = [(root, root_w)]
    while stack:
        path, cum = stack.pop()
        maxp = max(maxp, cum)
        if not os.path.isdir(path):
            continue
        for p, size in iter_children(path, dir_totals, excluded):
            stack.append((p, cum + weight(size)))
    return maxp


def polar_step(x: float, y: float, angle_deg: float, length: float):
    angle_rad = math.radians(angle_deg)
    return x + length * math.cos(angle_rad), y + length * math.sin(angle_rad)


def draw_svg(root: str, dir_totals: dict, scale_factor: float, out_svg: str, excluded: str) -> int:
    """Streamovaný SVG export. Větve jsou podcesty M...L... společného <path>."""
    size = SVG_VIEWBOX_SIZE
    half = size / 2.0
    # Matplotlib měl obrázek široký 1 palec s osou x v rozsahu [-1, 1].
    # Převedení původních linewidth bodů do souřadnic SVG proto zachová tloušťku.
    stroke_width = LINEWIDTH * size / 72.0

    def fmt(value: float) -> str:
        return f"{value:.{SVG_DECIMALS}f}".rstrip("0").rstrip(".") or "0"

    def xy(x: float, y: float) -> str:
        return f"{fmt((x + 1.0) * half)} {fmt((1.0 - y) * half)}"

    count = 0
    pieces = []

    with open(out_svg, "w", encoding="utf-8", newline="\n") as svg:
        svg.write(
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" '
            f'viewBox="0 0 {size} {size}" role="img">\n'
            '  <title>Strom souborů a adresářů</title>\n'
        )
        if BACKGROUND != "none":
            if BACKGROUND not in {"white", "black"}:
                raise ValueError("BACKGROUND musí být 'white', 'black' nebo 'none'.")
            svg.write(f'  <rect width="{size}" height="{size}" fill="{BACKGROUND}"/>\n')
        svg.write(
            f'  <defs><clipPath id="frame"><rect width="{size}" height="{size}"/></clipPath></defs>\n'
            f'  <g clip-path="url(#frame)" fill="none" stroke="black" '
            f'stroke-width="{stroke_width:.8g}" stroke-linecap="butt">\n'
        )

        def flush():
            if pieces:
                svg.write('    <path d="' + " ".join(pieces) + '"/>\n')
                pieces.clear()

        def segment(x1, y1, x2, y2):
            nonlocal count
            pieces.append(f"M{xy(x1, y1)}L{xy(x2, y2)}")
            count += 1
            if len(pieces) >= SEGMENTS_PER_PATH:
                flush()

        stack = [(root, START_X, START_Y, START_ANGLE_DEG, 0)]
        while stack:
            path, x, y, angle, depth = stack.pop()
            sz = dir_totals.get(path, 0) if os.path.isdir(path) else safe_stat_size(path)
            length = weight(sz) * scale_factor
            x2, y2 = polar_step(x, y, angle, length)
            segment(x, y, x2, y2)

            if DRAW_NODE_TICKS:
                a = math.radians(angle)
                nx, ny = -math.sin(a), math.cos(a)
                segment(x2 - TICK_LEN * nx, y2 - TICK_LEN * ny,
                        x2 + TICK_LEN * nx, y2 + TICK_LEN * ny)

            if not os.path.isdir(path):
                continue

            children = list(iter_children(path, dir_totals, excluded))
            if not children:
                continue
            if SORT_CHILDREN:
                children.sort(key=lambda t: (-t[1], t[0].lower()))

            span = MAX_SPAN_DEG * (SPAN_DECAY ** depth)
            ws = [weight(csz) for _, csz in children]
            total_w = sum(ws)
            start = angle - span / 2.0
            if total_w == 0:
                portion = span / len(children)
                angles = [start + (i + 0.5) * portion for i in range(len(children))]
            else:
                angles = []
                cur = start
                for w in ws:
                    portion = span * (w / total_w)
                    angles.append(cur + portion / 2.0)
                    cur += portion

            # Zásobník je LIFO; záměrně obráceně jako v původním skriptu.
            for (child_path, _), child_angle in reversed(list(zip(children, angles))):
                stack.append((child_path, x2, y2, child_angle, depth + 1))

        flush()
        svg.write('  </g>\n</svg>\n')

    return count


def main():
    root = os.path.abspath(ROOT_PATH)
    if not os.path.exists(root):
        raise FileNotFoundError(f"ROOT_PATH neexistuje: {root}")

    out_svg = build_output_path(root)
    excluded = normalized(out_svg)  # Pokud exportuješ přímo do skenovaného stromu.

    dir_totals = compute_dir_totals(root, excluded)
    max_path = compute_max_path(root, dir_totals, excluded)
    if max_path == 0:
        max_path = 1.0

    scale_factor = (RADIUS / max_path) * RELATIVE_SCALE
    segments = draw_svg(root, dir_totals, scale_factor, out_svg, excluded)

    print(f"Saved: {out_svg}")
    print(f"Segments: {segments:,}; SVG size: {os.path.getsize(out_svg):,} bytes")


if __name__ == "__main__":
    main()
