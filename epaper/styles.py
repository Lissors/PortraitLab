"""Zwei Stufen: AnimeGAN / Ölbild-KI → Spectra 6 E-Paper."""

from __future__ import annotations

from typing import TypedDict

from PIL import Image

from .animegan import apply_animegan
from .dither import dither_image
from .oilstyle import apply_oil_style
from .palette import get_palette

PALETTE_ID = "spectra6"
COLORS = 6


class Style(TypedDict):
    id: str
    name: str
    blurb: str


STYLES: dict[str, Style] = {
    "auto": {
        "id": "auto",
        "name": "Full Auto",
        "blurb": "Best path: cool flash → Anime → Atkinson. Crop stays yours.",
    },
    "portrait": {
        "id": "portrait",
        "name": "Portrait (Forum)",
        "blurb": "Toon-nooT: contrast/saturation + Atkinson.",
    },
    "anime": {
        "id": "anime",
        "name": "Anime Comic",
        "blurb": "AnimeGANv3 Hayao — Comic/Anime.",
    },
    "oil": {
        "id": "oil",
        "name": "Oil painting",
        "blurb": "Real oil painting (brush dabs).",
    },
    "shinkai": {
        "id": "shinkai",
        "name": "Shinkai",
        "blurb": "AnimeGANv3 Shinkai — softer anime.",
    },
}

# Aus dem Picker entfernt, aber noch verarbeitbar (alte Settings / API).
LEGACY_STYLES: dict[str, Style] = {
    "princess": {
        "id": "princess",
        "name": "Rain Princess",
        "blurb": "Neural Style — impressionist (legacy).",
    },
    "udnie": {
        "id": "udnie",
        "name": "Udnie",
        "blurb": "Neural Style — abstract art look (legacy).",
    },
}

ALL_STYLES: dict[str, Style] = {**STYLES, **LEGACY_STYLES}

# Intensive Autotune / Multi-Style-Suche: nur sichtbare Stile, ohne Legacy.
INTENSIVE_STYLE_IDS: tuple[str, ...] = tuple(STYLES.keys())

# Alte Galerie-Settings → UI-Picker (keine Karten mehr für Neural Style).
LEGACY_STYLE_FALLBACK: dict[str, str] = {
    "princess": "auto",
    "udnie": "auto",
}


def resolve_style_id(style_id: str | None, *, for_picker: bool = False) -> str:
    """Unbekannte IDs → auto; Legacy wahlweise auf Picker-Fallback mappen."""
    sid = (style_id or "auto").strip().lower() or "auto"
    if for_picker and sid in LEGACY_STYLE_FALLBACK:
        return LEGACY_STYLE_FALLBACK[sid]
    if sid in ALL_STYLES:
        return sid
    return "auto"


def apply_forum_portrait(image: Image.Image) -> Image.Image:
    """Foren-Prep für Portraits (Toon-nooT / epdoptimize-Nähe).

    Kontrast ~1.4, Sättigung ~1.08 (nicht zu hoch → Haut nicht orange),
    leichte Helligkeit, Schatten anheben, dezente Schärfe.
    """
    from .adjust import apply_adjustments

    return apply_adjustments(
        image,
        brightness=1.06,
        contrast=1.4,
        saturation=1.08,
        gamma=1.02,
        sharpen=0.35,
        shadow_lift=0.1,
        warmth=0.02,
        edge_prep=True,
    )


def apply_auto_king(image: Image.Image) -> Image.Image:
    """Vollautomatik / Königslösung — nur Stil, kein Auto-Zuschnitt.

    Blitz-Röte etwas kühlen → AnimeGANv3 Hayao → leichter Kontrast,
    etwas weniger Sättigung. Framing bleibt Fokus X/Y des Users.
    """
    from PIL import ImageEnhance

    img = image.convert("RGB")
    r, g, b = img.split()
    cooled = Image.merge(
        "RGB",
        (
            r.point(lambda i: max(0, int(i * 0.96))),
            g,
            b.point(lambda i: min(255, int(i * 1.03))),
        ),
    )
    out = apply_animegan(cooled, "hayao")
    out = ImageEnhance.Contrast(out).enhance(1.06)
    out = ImageEnhance.Color(out).enhance(0.95)
    return out


def stage1_comic(
    image: Image.Image,
    style_id: str = "auto",
    **_ignored,
) -> Image.Image:
    """Stufe 1 — Stilisierung / Forum-Prep / Vollautomatik."""
    style_id = resolve_style_id(style_id)
    if style_id == "auto":
        return apply_auto_king(image)
    if style_id == "portrait":
        return apply_forum_portrait(image)
    if style_id in ("oil", "princess", "udnie"):
        return apply_oil_style(image, style_id)
    if style_id == "shinkai":
        return apply_animegan(image, "shinkai")
    return apply_animegan(image, "hayao")


def stage2_epaper(
    comic: Image.Image,
    *,
    output: str = "device",
    dither_strength: float = 1.0,
    algorithm: str = "atkinson",
    distance_mode: str = "toon",
    skin_warmth: float = 0.4,
    brightness: float = 1.0,
    contrast: float = 1.0,
    style_id: str | None = None,
    grayscale: bool = False,
    warmth: float | None = None,
    skin_tint: float | None = None,
) -> Image.Image:
    """Stufe 2 — Spectra 6.

    brightness/contrast: 1.0 = neutral.
    warmth: -1..+1 (None → aus skin_warmth abgeleitet, 0.5→0)
    skin_tint: -1 Rosa .. +1 Gelb (None → aus skin_warmth)
    skin_warmth 0..1: Kompatibilität (0.5 ≈ Mitte)
    distance_mode: ``toon`` (Default) oder ``lab`` (CIE L*a*b*).
    """
    from PIL import ImageEnhance, ImageOps

    from .adjust import apply_color_grade

    img = comic.convert("RGB")
    b = max(0.4, min(1.8, float(brightness)))
    c = max(0.4, min(1.8, float(contrast)))
    if abs(b - 1.0) > 1e-3:
        img = ImageEnhance.Brightness(img).enhance(b)
    if abs(c - 1.0) > 1e-3:
        img = ImageEnhance.Contrast(img).enhance(c)

    # Slider-Mitte: skin_warmth 0.5 → warmth/tint 0
    sw = max(0.0, min(1.0, float(skin_warmth)))
    if warmth is None:
        warmth = (sw - 0.5) * 2.0
    if skin_tint is None:
        skin_tint = (sw - 0.5) * 2.0
    warmth = max(-1.0, min(1.0, float(warmth)))
    skin_tint = max(-1.0, min(1.0, float(skin_tint)))

    dist = (distance_mode or "toon").strip().lower()
    if dist in ("cie", "cielab", "deltae", "de76"):
        dist = "lab"
    if dist not in ("toon", "lab", "rgb"):
        dist = "toon"

    if grayscale:
        img = ImageOps.grayscale(img).convert("RGB")
        palette = get_palette("spectra6_bw")
        return dither_image(
            img,
            palette,
            strength=max(0.0, min(1.0, float(dither_strength))),
            algorithm=algorithm or "atkinson",
            match="perceived",
            output=output,
            hue_priority=False,
            distance_mode="rgb",
            skin_bias=0.0,
            warm_prep=0.0,
            yellow_in_skin=0.0,
        )

    img = apply_color_grade(img, warmth=warmth, skin_tint=skin_tint)

    # Mapping-Politik: Peach-Haut (W+Y), Pastell-Himmel behalten
    y_skin = 0.55 + 0.30 * skin_tint
    warm_prep = 0.04 + 0.22 * max(0.0, -skin_tint)
    if style_id in ("portrait", "auto"):
        skin_bias = 0.48
    else:
        skin_bias = 0.45

    palette = get_palette(PALETTE_ID)
    return dither_image(
        img,
        palette,
        strength=max(0.0, min(1.0, float(dither_strength))),
        algorithm=algorithm or "atkinson",
        match="perceived",
        output=output,
        hue_priority=(dist == "toon"),
        distance_mode=dist,
        skin_bias=skin_bias,
        warm_prep=warm_prep,
        yellow_in_skin=y_skin,
    )


def apply_style(image: Image.Image, style_id: str) -> Image.Image:
    return stage1_comic(image, style_id)


def style_to_epaper(
    image: Image.Image,
    style_id: str = "auto",
    *,
    output: str = "perceived",
    dither_strength: float = 1.0,
    skin_warmth: float = 0.28,
) -> Image.Image:
    comic = stage1_comic(image, style_id)
    return stage2_epaper(
        comic,
        output=output,
        dither_strength=dither_strength,
        skin_warmth=skin_warmth,
        style_id=style_id,
    )
