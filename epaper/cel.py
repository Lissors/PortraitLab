"""Softer comic/cel prep that still leaves room for 6-color dithering.

Hard luminance banding + no dither collapses portraits to yellow/black.
This version keeps more midtones so Spectra6 can mix skin with Y/W/R.
"""

from __future__ import annotations

from PIL import Image, ImageEnhance, ImageFilter, ImageOps


def apply_cel_shade(
    image: Image.Image,
    *,
    levels: int = 5,
    outline: float = 0.35,
    flatten: float = 0.55,
    sat_boost: float = 1.35,
) -> Image.Image:
    levels = max(3, min(8, int(levels)))
    outline = max(0.0, min(1.0, float(outline)))
    flatten = max(0.0, min(1.0, float(flatten)))

    src = image.convert("RGB")
    smooth = src.filter(ImageFilter.MedianFilter(size=3))
    smooth = smooth.filter(ImageFilter.GaussianBlur(radius=0.7))

    # Mild posterize (RGB) — keeps hue variety for later e-paper dither.
    step = max(8, 256 // max(4, levels + 1))
    poster = smooth.point(lambda p: min(255, (p // step) * step + step // 2))
    mixed = Image.blend(smooth, poster, flatten)
    mixed = ImageEnhance.Color(mixed).enhance(sat_boost)
    mixed = ImageEnhance.Contrast(mixed).enhance(1.18)

    if outline <= 0.05:
        return mixed

    gray = ImageOps.grayscale(smooth)
    edges = gray.filter(ImageFilter.FIND_EDGES)
    edges = ImageEnhance.Contrast(edges).enhance(1.6)
    # Higher threshold = fewer, cleaner lines (portraits hate thick ink blobs).
    thr = int(70 + (1.0 - outline) * 90)
    line = edges.point(lambda p: 255 if p > thr else 0)
    if outline > 0.55:
        line = line.filter(ImageFilter.MaxFilter(size=3))

    out = mixed.copy()
    # Soft ink: darken rather than hard paste pure black everywhere.
    ink_strength = 0.55 + 0.4 * outline
    darkened = ImageEnhance.Brightness(mixed).enhance(max(0.15, 1.0 - ink_strength))
    out.paste(darkened, mask=line)
    return out
