"""Generate Grok-styled tray icons with usage percentage."""

from __future__ import annotations

from PIL import Image, ImageDraw, ImageFont

# xAI / Grok monochrome + violet
COLOR_OK = (167, 139, 250)       # violet healthy
COLOR_MID = (134, 239, 172)      # soft mint mid
COLOR_WARN = (252, 211, 77)      # amber
COLOR_CRIT = (248, 113, 113)     # soft red
COLOR_UNKNOWN = (82, 82, 82)
COLOR_BG = (12, 12, 12)
COLOR_RING = (34, 34, 34)
COLOR_TEXT = (245, 245, 245)


def color_for_usage(percent: float | None) -> tuple[int, int, int]:
    if percent is None:
        return COLOR_UNKNOWN
    if percent >= 90:
        return COLOR_CRIT
    if percent >= 70:
        return COLOR_WARN
    if percent < 40:
        return COLOR_OK
    return COLOR_MID


def _load_font(size: int) -> ImageFont.ImageFont | ImageFont.FreeTypeFont:
    candidates = [
        "C:/Windows/Fonts/segoeuib.ttf",
        "C:/Windows/Fonts/segoeui.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
        "C:/Windows/Fonts/arial.ttf",
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size=size)
        except OSError:
            continue
    return ImageFont.load_default()


def make_usage_icon(
    percent: float | None,
    *,
    size: int = 64,
    label: str | None = None,
) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    color = color_for_usage(percent)
    pad = max(1, size // 14)
    bbox = (pad, pad, size - pad - 1, size - pad - 1)
    stroke = max(3, size // 9)

    # Track
    draw.ellipse(bbox, outline=(*COLOR_RING, 255), width=stroke)

    used = 0.0 if percent is None else max(0.0, min(100.0, float(percent)))
    if used > 0:
        start = -90
        end = start + (used / 100.0) * 360.0
        draw.arc(bbox, start=start, end=end, fill=(*color, 255), width=stroke)

    # Center disc (black hole core)
    inner = pad + stroke + 1
    draw.ellipse(
        (inner, inner, size - inner - 1, size - inner - 1),
        fill=(*COLOR_BG, 245),
    )

    if label is None:
        if percent is None:
            label = "?"
        else:
            rounded = int(round(percent))
            label = f"{rounded}" if rounded < 100 else "99+"

    font_size = size // 2 if len(label) <= 2 else max(10, size // 3)
    font = _load_font(font_size)
    _draw_centered_label(draw, label, font, size, COLOR_TEXT)
    return img


def make_error_icon(size: int = 64) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    pad = max(1, size // 14)
    bbox = (pad, pad, size - pad - 1, size - pad - 1)
    draw.ellipse(bbox, fill=(*COLOR_CRIT, 230))
    font = _load_font(size // 2)
    _draw_centered_label(draw, "!", font, size, COLOR_TEXT)
    return img


def _draw_centered_label(
    draw: ImageDraw.ImageDraw,
    label: str,
    font: ImageFont.ImageFont | ImageFont.FreeTypeFont,
    size: int,
    color: tuple[int, int, int],
) -> None:
    """Center text using ink bounding box (not font em-box)."""
    # getbbox: (left, top, right, bottom) relative to origin including bearings.
    try:
        left, top, right, bottom = font.getbbox(label)
    except Exception:  # noqa: BLE001
        left, top, right, bottom = draw.textbbox((0, 0), label, font=font)
    tw = right - left
    th = bottom - top
    x = (size - tw) / 2 - left
    y = (size - th) / 2 - top
    # Tiny optical lift for digits in the tray (Windows scales icons down).
    y -= size * 0.03
    draw.text((x, y), label, font=font, fill=(*color, 255))
