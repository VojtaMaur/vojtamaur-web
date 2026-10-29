"""Pillow meme composition and binary QR rendering; scanner dependency is optional."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path


def find_font(explicit=None):
    from PIL import ImageFont

    if explicit:
        path = Path(explicit).expanduser().resolve()
        if not path.is_file():
            raise ValueError(f"Font does not exist: {path}")
        ImageFont.truetype(str(path), 20)
        return str(path)
    candidates = [Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / "impact.ttf",
                  Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
                  Path("/System/Library/Fonts/Supplemental/Impact.ttf")]
    for path in candidates:
        if path.is_file():
            return str(path.resolve())
    # Pillow resolves installed font names; preserve the resolved source for manifests.
    for name in ("DejaVuSans-Bold.ttf", "Arial Bold.ttf", "arialbd.ttf"):
        try:
            font = ImageFont.truetype(name, 20)
            return str(Path(font.path).resolve())
        except OSError:
            pass
    raise RuntimeError("No bold TrueType font found. Supply --font with an Impact/DejaVu Sans Bold font.")


def _wrap(draw, text, font, width, stroke=0):
    words = text.split()
    lines, line = [], ""
    for word in words:
        # Break exceptionally long tokens so captions cannot escape the picture.
        tokens = []
        token = ""
        for char in word:
            if token and draw.textbbox((0, 0), token + char, font=font, stroke_width=stroke)[2] > width:
                tokens.append(token)
                token = char
            else:
                token += char
        tokens.append(token)
        for token in tokens:
            trial = (line + " " + token).strip()
            if line and draw.textbbox((0, 0), trial, font=font, stroke_width=stroke)[2] > width:
                lines.append(line)
                line = token
            else:
                line = trial
    if line:
        lines.append(line)
    return "\n".join(lines)


def _caption(canvas, text, font_path, top, max_height):
    from PIL import ImageDraw, ImageFont

    draw = ImageDraw.Draw(canvas)
    margin = max(18, canvas.width // 35)
    for size in range(max(22, canvas.width // 16), 13, -1):
        font = ImageFont.truetype(font_path, size=size)
        stroke = max(2, size // 15)
        wrapped = _wrap(draw, text.upper(), font, canvas.width - 2 * margin, stroke)
        box = draw.multiline_textbbox((0, 0), wrapped, font=font, spacing=5, stroke_width=stroke, align="center")
        if box[3] - box[1] <= max_height and box[2] - box[0] <= canvas.width - 2 * margin:
            break
    else:
        raise ValueError("Caption cannot fit at a readable size; reduce --max-text-chars")
    left = (canvas.width - (box[2] - box[0])) // 2 - box[0]
    y = margin - box[1] if top else canvas.height - margin - (box[3] - box[1]) - box[1]
    draw.multiline_text((left, y), wrapped, font=font, fill="white", stroke_width=stroke,
                        stroke_fill="black", spacing=5, align="center")


FOUNTAIN_COPY = {
    "en": ("Fountain code: this QR holds an archive fragment.\n"
           "Collect enough memes from this edition to reconstruct the full text archive (ALL_POSTS.txt)."),
    "cs": ("Fountain kód: tento QR nese fragment archivu.\n"
           "Nasbírej dost memů z této edice a obnov celý textový archiv (ALL_POSTS.txt)."),
}


def _localized_footer(qr_image, font_path, width, edition, index, language, recovery=None):
    """Fit all footer text beside the QR, or below it on narrow images."""
    from PIL import Image, ImageDraw, ImageFont

    if language not in {"en", "cs", "en+cs"}:
        raise ValueError("Footer language must be en, cs or en+cs")
    title, edition_label, meme_label = {
        "en": ("MEME ARCHIVE", "Edition", "Meme"),
        "cs": ("ARCHIV MEMŮ", "Edice", "Mem"),
        "en+cs": ("MEME ARCHIVE / ARCHIV MEMŮ", "Edition / Edice", "Meme / Mem"),
    }[language]
    qr_x, qr_y = width - qr_image.width - 16, 16
    beside = qr_x - 36 >= 180
    text_width = qr_x - 36 if beside else width - 44
    text_top = 26 if beside else qr_image.height + 48
    title_font = ImageFont.truetype(font_path, max(14, min(24, width // 45)))
    note_font = ImageFont.truetype(font_path, max(12, min(18, width // 60)))
    body_font = ImageFont.truetype(font_path, max(14, min(20, width // 54)))
    measure = ImageDraw.Draw(Image.new("RGB", (1, 1)))

    def block(text, font, y, color):
        wrapped = "\n".join(_wrap(measure, line, font, text_width) for line in text.splitlines())
        box = measure.multiline_textbbox((0, 0), wrapped, font=font, spacing=5)
        return dict(text=wrapped, font=font, x=22, y=y, box=box,
                    height=box[3] - box[1], color=color)

    blocks = []
    y = text_top
    notes = [(title, title_font), ("MA1 / RaptorQ / RFC 6330", note_font)]
    if edition:
        notes.append((f"{edition_label} {edition}", note_font))
    notes.extend(((f"{meme_label} {index + 1:06d}", note_font), ("vojtamaur.cz", note_font)))
    for text, font in notes:
        item = block(text, font, y, "#171717")
        blocks.append(item)
        y += item["height"] + 12
    copies = dict(FOUNTAIN_COPY)
    if recovery is not None:
        minimum, recommended, block_count = (recovery[key] for key in ("minimum", "recommended", "blocks"))
        if not all(isinstance(value, int) for value in (minimum, recommended, block_count)) or not 1 <= block_count <= minimum <= recommended:
            raise ValueError("Invalid reconstruction estimate")
        copies = {
            "en": ("Fountain code: this QR holds an archive fragment.\n"
                   f"Rebuild the full text archive (ALL_POSTS.txt) with ~{recommended}+ different memes "
                   f"from this edition (minimum {minimum})."),
            "cs": ("Fountain kód: tento QR nese fragment archivu.\n"
                   f"Celý textový archiv (ALL_POSTS.txt) obnovíš z ~{recommended}+ různých memů "
                   f"této edice (minimum {minimum})."),
        }
        if block_count > 1:
            copies["en"] += f" Fragments from all {block_count} source blocks are needed."
            copies["cs"] += f" Je potřeba zastoupit všech {block_count} zdrojových bloků."
    explanation = (copies[language] if language != "en+cs" else
                   copies["en"] + "\n\n" + copies["cs"])
    body = block(explanation, body_font, 0, "#333333")
    footer_height = max(qr_image.height + 32, y + 18 + body["height"] + 22)
    body["y"] = max(y + 18, footer_height - body["height"] - 22)
    blocks.append(body)
    footer = Image.new("RGB", (width, footer_height), "white")
    footer.paste(qr_image, (qr_x, qr_y))
    draw = ImageDraw.Draw(footer)
    for item in blocks:
        box = item["box"]
        draw.multiline_text((item["x"] - box[0], item["y"] - box[1]), item["text"],
                            font=item["font"], fill=item["color"], spacing=5)
    metadata = {"footer_language": language, "footer_explanation": explanation,
                "footer_text_box": [22, text_top, 22 + text_width,
                                    body["y"] + body["height"]]}
    if recovery is not None:
        metadata["footer_recovery"] = recovery
    return footer, metadata


def render_meme(root, choice, packet: bytes, destination, settings=None):
    """Write a lossless PNG with an unscaled, integer-module binary QR in its footer.

    settings: width=1080, photo_height=810, qr_scale=4, ecc='M', font=None,
    edition='', index=choice['index'], language='en' for new editions.
    Missing language preserves the exact legacy 1.0 footer for resume.
    """
    from PIL import Image, ImageDraw, ImageFont, ImageOps
    import segno

    settings = settings or {}
    width = int(settings.get("width", 1080))
    photo_height = int(settings.get("photo_height", settings.get("image_height", 810)))
    scale = int(settings.get("qr_scale", 4))
    if width < 512 or photo_height < 320 or scale < 4:
        raise ValueError("width >=512, photo_height >=320 and qr_scale >=4 are required")
    font_path = find_font(settings.get("font"))
    image_path = Path(root) / choice["image"]["path"]
    if hashlib.sha256(image_path.read_bytes()).hexdigest() != choice["image"]["sha256"]:
        raise ValueError(f"Source image changed since edition creation: {image_path}")
    with Image.open(image_path) as image:
        image.seek(0)
        image = ImageOps.exif_transpose(image).convert("RGBA")
        flattened = Image.new("RGBA", image.size, "white")
        flattened.alpha_composite(image)
        # Contain avoids destroying the subject in extreme portrait/panorama sources.
        photo = ImageOps.pad(flattened.convert("RGB"), (width, photo_height), color="#151515",
                             method=Image.Resampling.LANCZOS)
    for top, key in ((True, "top"), (False, "bottom")):
        record = choice.get(key)
        if record:
            _caption(photo, record["text"], font_path, top, int(photo_height * 0.37))
    qr = segno.make(packet, mode="byte", error=str(settings.get("ecc", "M")).lower(),
                    micro=False, boost_error=False)
    modules = len(qr.matrix)
    qr_edge = (modules + 8) * scale
    if qr_edge + 32 > width:
        raise ValueError("QR exceeds image width; increase --width or decrease --symbol-size")
    qr_image = Image.new("RGB", (modules + 8, modules + 8), "white")
    pixels = qr_image.load()
    for y, row in enumerate(qr.matrix):
        for x, dark in enumerate(row):
            if dark:
                pixels[x + 4, y + 4] = (0, 0, 0)
    qr_image = qr_image.resize((qr_edge, qr_edge), Image.Resampling.NEAREST)
    language = settings.get("language")
    if language is not None:
        footer, footer_metadata = _localized_footer(qr_image, font_path, width,
            str(settings.get("edition", "")), settings.get("index", choice.get("index", 0)), language,
            settings.get("recovery"))
        canvas = Image.new("RGB", (width, photo_height + footer.height), "white")
        canvas.paste(photo, (0, 0))
        canvas.paste(footer, (0, photo_height))
        qr_x, qr_y = width - qr_edge - 16, photo_height + 16
        footer_metadata["footer_text_box"][1] += photo_height
        footer_metadata["footer_text_box"][3] += photo_height
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        canvas.save(destination, format="PNG", optimize=False, compress_level=6)
        return {"width": width, "height": canvas.height, "photo_height": photo_height,
                "qr_box": [qr_x, qr_y, qr_x + qr_edge, qr_y + qr_edge],
                "qr_version": qr.version, "qr_modules": modules, "qr_scale": scale,
                "qr_ecc": qr.error.upper(), "quiet_zone_modules": 4,
                "font": font_path, "font_sha256": hashlib.sha256(Path(font_path).read_bytes()).hexdigest(),
                **footer_metadata}
    # Existing 1.0 editions retain their original pixels and random sequence.
    footer_height = qr_edge + 32
    canvas = Image.new("RGB", (width, photo_height + footer_height), "white")
    canvas.paste(photo, (0, 0))
    qr_x, qr_y = width - qr_edge - 16, photo_height + 16
    canvas.paste(qr_image, (qr_x, qr_y))
    draw = ImageDraw.Draw(canvas)
    footer_font = ImageFont.truetype(font_path, max(14, min(24, width // 45)))
    small_font = ImageFont.truetype(font_path, max(12, min(18, width // 60)))
    text_width = qr_x - 36
    edition = str(settings.get("edition", ""))
    index = settings.get("index", choice.get("index", 0))
    if text_width >= 130:
        title = _wrap(draw, "MEME ARCHIVE", footer_font, text_width)
        draw.multiline_text((22, photo_height + 27), title, font=footer_font, fill="#171717", spacing=6)
        title_box = draw.multiline_textbbox((0, 0), title, font=footer_font, spacing=6)
        note = ("MA1 / RaptorQ / RFC 6330\n"
                + ("Edition " + edition + "\n" if edition else "")
                + f"Meme {index + 1:06d}\nvojtamaur.cz")
        y = photo_height + 45 + title_box[3] - title_box[1]
        for paragraph in note.splitlines():
            wrapped = _wrap(draw, paragraph, small_font, text_width)
            draw.multiline_text((22, y), wrapped, font=small_font, fill="#333333", spacing=4)
            box = draw.multiline_textbbox((0, 0), wrapped, font=small_font, spacing=4)
            y += box[3] - box[1] + 14
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(destination, format="PNG", optimize=False, compress_level=6)
    return {"width": width, "height": canvas.height, "photo_height": photo_height,
            "qr_box": [qr_x, qr_y, qr_x + qr_edge, qr_y + qr_edge],
            "qr_version": qr.version, "qr_modules": modules, "qr_scale": scale,
            "qr_ecc": qr.error.upper(), "quiet_zone_modules": 4,
            "font": font_path, "font_sha256": hashlib.sha256(Path(font_path).read_bytes()).hexdigest()}


def scan_qr(path_or_image):
    """Return exact raw byte payloads, including arbitrary non-UTF8 data, from a PNG/JPEG.

    zxing-cpp is optional and imported only for scanning. Passing a Pillow image
    supports direct tests of resized/recompressed final memes.
    """
    from PIL import Image
    try:
        import zxingcpp
    except ImportError as exc:
        raise RuntimeError("QR scanning needs optional zxing-cpp: python -m pip install zxing-cpp") from exc
    image = path_or_image
    owned = not isinstance(image, Image.Image)
    if owned:
        image = Image.open(path_or_image)
    try:
        # QR only; ignore incidental codes in the source photograph.
        results = zxingcpp.read_barcodes(image, formats=zxingcpp.BarcodeFormat.QRCode)
        return [bytes(result.bytes) for result in results if result.valid]
    finally:
        if owned:
            image.close()


def scan_packets(path):
    """Decoder-facing alias for scanning exact binary packet bytes."""
    return scan_qr(path)
