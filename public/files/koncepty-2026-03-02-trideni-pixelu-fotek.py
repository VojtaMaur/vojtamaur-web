from PIL import Image, ImageOps
import numpy as np
import time

def hue_np(rgb_u8: np.ndarray) -> np.ndarray:
    """
    Vectorized hue for RGB uint8 array shape (N, 3) or (W, 3).
    Returns hue in [0, 1).
    """
    rgb = rgb_u8.astype(np.float32) / 255.0
    r = rgb[..., 0]
    g = rgb[..., 1]
    b = rgb[..., 2]

    maxc = np.maximum(np.maximum(r, g), b)
    minc = np.minimum(np.minimum(r, g), b)
    delta = maxc - minc

    h = np.zeros_like(maxc)

    # Avoid division by zero
    nonzero = delta > 1e-12

    # Masks for which channel is max
    is_r = (maxc == r) & nonzero
    is_g = (maxc == g) & nonzero
    is_b = (maxc == b) & nonzero

    h[is_r] = ((g[is_r] - b[is_r]) / delta[is_r]) % 6.0
    h[is_g] = ((b[is_g] - r[is_g]) / delta[is_g]) + 2.0
    h[is_b] = ((r[is_b] - g[is_b]) / delta[is_b]) + 4.0

    h = (h / 6.0) % 1.0
    return h

def sort_image_lumY_hueX(input_path: str, output_path: str, progress: bool = True) -> None:
    t0 = time.time()

    # 1) Load with EXIF orientation fixed, preserve original W/H after that
    img = ImageOps.exif_transpose(Image.open(input_path)).convert("RGB")
    arr = np.array(img)  # (H, W, 3)
    h, w, _ = arr.shape

    if progress:
        print(f"[1/3] Loaded {w}x{h} ({w*h:,} px).")

    # 2) Global sort by luminance so TOP = bright, BOTTOM = dark
    pixels = arr.reshape(-1, 3)
    # Perceptual-ish luminance
    lum = 0.2126 * pixels[:, 0] + 0.7152 * pixels[:, 1] + 0.0722 * pixels[:, 2]
    order = np.argsort(-lum, kind="stable")  # minus => descending (bright first)
    sorted_pixels = pixels[order].astype(np.uint8)
    grid = sorted_pixels.reshape(h, w, 3)

    if progress:
        print(f"[2/3] Sorted globally by luminance (top bright).")

    # 3) For each row, sort by hue (left -> right)
    if progress:
        print(f"[3/3] Sorting rows by HUE...")
    last_print = time.time()

    for y in range(h):
        row = grid[y]  # (W, 3)
        keys = hue_np(row)  # (W,)
        idx = np.argsort(keys, kind="stable")
        grid[y] = row[idx]

        if progress:
            # update at most ~20x/sec so console doesn't melt
            now = time.time()
            if now - last_print > 0.05 or y == h - 1:
                pct = (y + 1) * 100.0 / h
                print(f"\r    {y+1}/{h} rows  ({pct:5.1f}%)", end="")
                last_print = now

    if progress:
        print()  # newline

    Image.fromarray(grid, mode="RGB").save(output_path)

    if progress:
        dt = time.time() - t0
        print(f"Done. Saved: {output_path}  |  time: {dt:.2f}s")

if __name__ == "__main__":
    sort_image_lumY_hueX("in.jpg", "out_lumY_hueX.png", progress=True)