"""Tone / color adjustments useful for e-paper portraits."""

from __future__ import annotations

from PIL import Image, ImageEnhance, ImageFilter, ImageOps


def apply_adjustments(
    image: Image.Image,
    *,
    brightness: float = 1.0,
    contrast: float = 1.0,
    saturation: float = 1.0,
    gamma: float = 1.0,
    sharpen: float = 0.0,
    shadow_lift: float = 0.0,
    warmth: float = 0.0,
    edge_prep: bool = False,
    invert: bool = False,
) -> Image.Image:
    img = image.convert("RGB")

    if invert:
        img = ImageOps.invert(img)

    if abs(brightness - 1.0) > 1e-3:
        img = ImageEnhance.Brightness(img).enhance(brightness)
    if abs(contrast - 1.0) > 1e-3:
        img = ImageEnhance.Contrast(img).enhance(contrast)
    if abs(saturation - 1.0) > 1e-3:
        img = ImageEnhance.Color(img).enhance(saturation)

    if abs(gamma - 1.0) > 1e-3:
        g = max(0.1, min(3.0, gamma))
        lut = [min(255, int(round(255 * ((i / 255) ** (1.0 / g))))) for i in range(256)]
        img = img.point(lut * 3)

    if shadow_lift > 0:
        # Lift crushed shadows (E6 panels go muddy in darks).
        amount = max(0.0, min(1.0, shadow_lift))
        lut = []
        for i in range(256):
            t = i / 255.0
            lifted = t + amount * (1.0 - t) * (1.0 - t) * 0.85
            lut.append(min(255, int(round(lifted * 255))))
        img = img.point(lut * 3)

    if abs(warmth) > 1e-3:
        # Paper-ish white: nudge red/yellow, ease blue.
        w = max(-0.25, min(0.25, warmth))
        r_lut = [min(255, max(0, int(i * (1.0 + w)))) for i in range(256)]
        g_lut = [min(255, max(0, int(i * (1.0 + w * 0.35)))) for i in range(256)]
        b_lut = [min(255, max(0, int(i * (1.0 - w * 0.55)))) for i in range(256)]
        img = img.point(r_lut + g_lut + b_lut)

    if edge_prep:
        # Community Spectra6 converters: EDGE_ENHANCE → SMOOTH → SHARPEN chain.
        img = img.filter(ImageFilter.EDGE_ENHANCE)
        img = img.filter(ImageFilter.SMOOTH)

    if sharpen > 0:
        sharp = img.filter(ImageFilter.UnsharpMask(radius=1.5, percent=150, threshold=2))
        img = Image.blend(img, sharp, min(1.0, sharpen))

    return img


def apply_color_grade(
    image: Image.Image,
    *,
    warmth: float = 0.0,
    skin_tint: float = 0.0,
) -> Image.Image:
    """Farbgrade vor dem Dither.

    warmth: -1 Kühl … 0 neutral … +1 Warm (global spürbar)
    skin_tint: -1 Rosa/Rot … 0 neutral … +1 Gelb/Bräune (v. a. warme Mitteltöne)
    """
    import numpy as np

    warmth = max(-1.0, min(1.0, float(warmth)))
    skin_tint = max(-1.0, min(1.0, float(skin_tint)))

    arr = np.asarray(image.convert("RGB"), dtype=np.float32)
    r = arr[:, :, 0]
    g = arr[:, :, 1]
    b = arr[:, :, 2]
    luma = 0.299 * r + 0.587 * g + 0.114 * b

    did = False
    if abs(warmth) > 0.02:
        t = warmth * 0.55
        r = r + 38 * t
        g = g + 16 * t
        b = b - 42 * t
        did = True

    # Starke Orange-Kontamination (Hemd-Reflex / Kunstlicht) vor Dither etwas kühlen,
    # ohne Pastell-Himmel (kühl/blau) oder neutrale Cristina-Haut anzufassen.
    chroma = np.maximum(np.maximum(r, g), b) - np.minimum(np.minimum(r, g), b)
    orange_cast = np.clip((chroma - 70.0) / 100.0, 0.0, 1.0) * np.clip(
        (r - b - 45.0) / 110.0, 0.0, 1.0
    )
    mid_l = np.clip(1.0 - np.abs(luma - 150.0) / 100.0, 0.0, 1.0)
    cool_gate = orange_cast * mid_l * 0.38
    if float(cool_gate.max()) > 0.02:
        r = r - 36 * cool_gate
        g = g - 8 * cool_gate
        b = b + 28 * cool_gate
        did = True

    if abs(skin_tint) > 0.02:
        mid = np.clip(1.0 - np.abs(luma - 145.0) / 110.0, 0.0, 1.0)
        warmish = np.clip((r - b) / 255.0, 0.0, 1.0)
        # Gold/Ocker (R≈G ≫ B) nicht als Haut einfärben
        ochre = np.clip((np.minimum(r, g) - b) / 70.0, 0.0, 1.0) * np.clip(
            1.0 - np.abs(r - g) / 90.0, 0.0, 1.0
        )
        gate = mid * (0.35 + 0.65 * np.clip(warmish * 2.5, 0.0, 1.0))
        gate = gate * (1.0 - 0.95 * ochre)
        s = skin_tint * gate
        rosa = np.minimum(s, 0.0)  # ≤0
        gelb = np.maximum(s, 0.0)  # ≥0
        # Rosa: mehr Rot / weniger Grün; Gelb: mehr R+G, weniger Blau
        r = r - 42 * rosa + 16 * gelb
        g = g + 32 * rosa + 26 * gelb
        b = b - 10 * rosa - 22 * gelb
        did = True

    if not did:
        return image.convert("RGB")

    out = np.stack([r, g, b], axis=-1)
    np.clip(out, 0, 255, out=out)
    return Image.fromarray(out.astype(np.uint8), mode="RGB")


def fit_portrait(
    image: Image.Image,
    width: int = 480,
    height: int = 800,
    *,
    mode: str = "cover",
    focus_x: float = 0.5,
    focus_y: float = 0.5,
    zoom: float = 1.0,
) -> Image.Image:
    """Fit image into portrait canvas.

    mode=cover → crop to fill (default for photos)
    mode=contain → letterbox with white
    mode=stretch → distort to exact size
    zoom: 1.0 = minimal cover, >1 = weiter reinzoomen
    """
    img = image.convert("RGB")
    tw, th = width, height

    if mode == "stretch":
        return img.resize((tw, th), Image.Resampling.LANCZOS)

    sw, sh = img.size
    scale_w = tw / sw
    scale_h = th / sh

    if mode == "contain":
        scale = min(scale_w, scale_h)
        nw, nh = max(1, int(round(sw * scale))), max(1, int(round(sh * scale)))
        resized = img.resize((nw, nh), Image.Resampling.LANCZOS)
        canvas = Image.new("RGB", (tw, th), (255, 255, 255))
        canvas.paste(resized, ((tw - nw) // 2, (th - nh) // 2))
        return canvas

    # cover (+ optional zoom)
    z = max(1.0, min(4.0, float(zoom)))
    scale = max(scale_w, scale_h) * z
    nw, nh = max(1, int(round(sw * scale))), max(1, int(round(sh * scale)))
    resized = img.resize((nw, nh), Image.Resampling.LANCZOS)
    fx = max(0.0, min(1.0, focus_x))
    fy = max(0.0, min(1.0, focus_y))
    left = int(round((nw - tw) * fx))
    top = int(round((nh - th) * fy))
    left = max(0, min(max(0, nw - tw), left))
    top = max(0, min(max(0, nh - th), top))
    return resized.crop((left, top, left + tw, top + th))
