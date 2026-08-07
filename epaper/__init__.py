"""E-paper engine — 2-Stufen Comic → E6."""

from .palette import PALETTES, get_palette
from .dither import dither_image
from .export import export_bmp
from .styles import (
    STYLES,
    LEGACY_STYLES,
    ALL_STYLES,
    INTENSIVE_STYLE_IDS,
    COLORS,
    PALETTE_ID,
    stage1_comic,
    stage2_epaper,
    apply_style,
    style_to_epaper,
)
from .comic import apply_comic

__all__ = [
    "PALETTES",
    "STYLES",
    "LEGACY_STYLES",
    "ALL_STYLES",
    "INTENSIVE_STYLE_IDS",
    "COLORS",
    "PALETTE_ID",
    "get_palette",
    "dither_image",
    "export_bmp",
    "stage1_comic",
    "stage2_epaper",
    "apply_style",
    "style_to_epaper",
    "apply_comic",
]
