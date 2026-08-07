"""Export device-ready 24-bit BMP files (typically into pic/)."""

from __future__ import annotations

import re
from pathlib import Path

from PIL import Image


PORTRAIT_SIZE = (480, 800)
LANDSCAPE_SIZE = (800, 480)


def _safe_stem(name: str) -> str:
    stem = Path(name).stem
    stem = re.sub(r"[^\w\-]+", "_", stem, flags=re.UNICODE).strip("_")
    return (stem or "photo")[:48]


def export_bmp(
    image: Image.Image,
    pic_dir: Path,
    filename: str,
    *,
    portrait: bool = True,
    overwrite: bool = False,
) -> Path:
    """Write a 24-bit BMP at the exact PhotoPainter resolution into pic_dir."""
    pic_dir.mkdir(parents=True, exist_ok=True)
    target = PORTRAIT_SIZE if portrait else LANDSCAPE_SIZE
    rgb = image.convert("RGB").resize(target, Image.Resampling.NEAREST)

    # Erlaubt direkten Dateinamen inkl. .bmp
    raw = Path(filename).name
    if raw.lower().endswith(".bmp"):
        out_path = pic_dir / raw
    else:
        out_path = pic_dir / f"{_safe_stem(filename)}.bmp"

    if out_path.parent.resolve() != pic_dir.resolve():
        raise ValueError("invalid export path")

    if not overwrite and out_path.exists():
        stem = _safe_stem(out_path.stem)
        n = 2
        while True:
            candidate = pic_dir / f"{stem}_{n}.bmp"
            if not candidate.exists():
                out_path = candidate
                break
            n += 1

    # Waveshare requires classic 24-bit BMP (no compression).
    rgb.save(out_path, format="BMP")
    return out_path
