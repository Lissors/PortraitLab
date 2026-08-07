"""Error-diffusion / blue-noise dithering with semantic Spectra-6 mapping."""

from __future__ import annotations

from PIL import Image

from .bluenoise import blue_noise_at
from .lab import delta_e76_sq, palette_labs, rgb_to_lab
from .palette import Palette, perceived_list

# Spectra6 indices: 0 Schwarz, 1 Weiss, 2 Gruen, 3 Blau, 4 Rot, 5 Gelb
_IDX_BLACK = 0
_IDX_WHITE = 1
_IDX_GREEN = 2
_IDX_BLUE = 3
_IDX_RED = 4
_IDX_YELLOW = 5

# Farbabstand: toon = Toon-nooT hue-priority (Default), lab = CIE76 ΔE², rgb = raw RGB
DISTANCE_MODES = ("toon", "lab", "rgb")


def _dist_rgb(r: float, g: float, b: float, c: tuple[int, int, int]) -> float:
    dr = r - c[0]
    dg = g - c[1]
    db = b - c[2]
    return dr * dr + dg * dg + db * db


def _dist_hue_priority(r: float, g: float, b: float, c: tuple[int, int, int]) -> float:
    """Toon-nooT: Hue errors weigh more than luma errors (Default)."""
    cr, cg, cb = c
    diff_r = r - cr
    diff_g = g - cg
    diff_b = b - cb
    rgb_dist = (
        (diff_r * diff_r * 0.250 + diff_g * diff_g * 0.350 + diff_b * diff_b * 0.400)
        * 0.75
        / (255.0 * 255.0)
    )
    luma1 = (r * 250 + g * 350 + b * 400) / (255.0 * 1000)
    luma2 = (cr * 250 + cg * 350 + cb * 400) / (255.0 * 1000)
    return 1.5 * rgb_dist + 0.60 * ((luma1 - luma2) ** 2)


def _normalize_distance_mode(distance_mode: str | None, *, hue_priority: bool) -> str:
    mode = (distance_mode or "").strip().lower()
    if mode in ("cie", "cielab", "deltae", "de76"):
        mode = "lab"
    if mode in DISTANCE_MODES:
        return mode
    return "toon" if hue_priority else "rgb"

def _luma(r: float, g: float, b: float) -> float:
    return 0.299 * r + 0.587 * g + 0.114 * b


def _chroma(r: float, g: float, b: float) -> float:
    return max(r, g, b) - min(r, g, b)


def _ochre_likelihood(r: float, g: float, b: float) -> float:
    """Goldgrund / Ocker / warmes Gelb."""
    if r < 55 or g < 45:
        return 0.0
    cy = min(r, g) - b
    if cy < 22:
        return 0.0
    bal = max(0.0, min(1.0, 1.0 - abs(r - g) / 90.0))
    if bal < 0.25:
        return 0.0
    luma = _luma(r, g, b)
    dark = 1.0 - min(1.0, max(0.0, (luma - 90.0) / 120.0))
    return min(1.0, (cy / 70.0) * (0.35 + 0.65 * bal) * (0.55 + 0.45 * dark))


def _skin_likelihood(r: float, g: float, b: float) -> float:
    """Haut — nicht Gold, nicht Grün, nicht Blau."""
    if r < 55 or r > 250:
        return 0.0
    if r < g - 8 or b > g + 25:
        return 0.0
    if g > r + 5 and g > b + 20:
        return 0.0
    luma = _luma(r, g, b)
    if luma < 50 or luma > 235:
        return 0.0
    if (r - b) / 255.0 < 0.05:
        return 0.0
    if _ochre_likelihood(r, g, b) > 0.35:
        return 0.0
    if _blue_likelihood(r, g, b) > 0.25:
        return 0.0
    rg = abs(r - g) / 255.0
    if rg < 0.04 and (min(r, g) - b) > 35:
        return 0.0
    score = min(1.0, ((r - b) / 255.0) * 2.2) * (1.0 - min(1.0, max(0.0, rg - 0.25) * 2))
    mid = max(0.0, min(1.0, 1.0 - abs(luma - 150.0) / 120.0))
    return max(0.0, min(1.0, score * (0.45 + 0.55 * mid)))


def _neutral_wall_likelihood(r: float, g: float, b: float) -> float:
    """Dunkle/mittlere Neutrale (Wand/Säule)."""
    luma = _luma(r, g, b)
    if luma < 18 or luma > 195:
        return 0.0
    ch = _chroma(r, g, b)
    if ch > 24:
        return 0.0
    if g > r + 22 and g > b + 18:
        return 0.0
    if _blue_likelihood(r, g, b) > 0.2:
        return 0.0
    flat = 1.0 - ch / 24.0
    dark = 1.0 - min(1.0, max(0.0, (luma - 30.0) / 140.0))
    return max(0.0, min(1.0, flat * (0.35 + 0.65 * dark)))


def _blue_likelihood(r: float, g: float, b: float) -> float:
    """Himmel / Cobalt / Pastellblau — B führend (auch bei hellen Himmeln)."""
    if b < 40:
        return 0.0
    luma = _luma(r, g, b)
    if luma < 25:
        return 0.0
    ch = _chroma(r, g, b)
    # Klassisches Cobalt: B klar dominant
    lead = min(b - r, b - g)
    classic = 0.0
    if b >= r + 8 and b >= g + 4 and ch >= 16 and lead >= 6:
        classic = min(1.0, (lead / 50.0) * (0.35 + 0.65 * min(1.0, ch / 65.0)))
    # Pastell-Himmel: hell, kühl, B > R (auch wenn G nah an B)
    pastel = 0.0
    if luma > 125 and b > r + 3 and b >= g - 6 and ch >= 8:
        cool = max(0.0, (b - r) / 40.0)
        not_warm = max(0.0, 1.0 - max(0.0, (r - g) / 30.0))
        soft = min(1.0, max(0.25, ch / 35.0))
        pastel = min(1.0, cool * (0.5 + 0.5 * soft) * not_warm)
        pastel *= 0.8 + 0.35 * min(1.0, max(0.0, (luma - 125.0) / 85.0))
    return min(1.0, max(classic, pastel))


def _cool_neutral_likelihood(r: float, g: float, b: float) -> float:
    """Kühles Schatten-Grau (bläulich) — Spur Blau, kein Grün."""
    luma = _luma(r, g, b)
    if luma < 22 or luma > 170:
        return 0.0
    ch = _chroma(r, g, b)
    if ch > 28:
        return 0.0
    if b < g - 2 and b < r - 2:
        return 0.0  # warm
    if g > r + 18 and g > b + 10:
        return 0.0  # grün
    cool = max(0.0, (b - min(r, g)) / 30.0)
    flat = 1.0 - ch / 28.0
    return max(0.0, min(1.0, flat * (0.35 + 0.65 * cool)))


def _green_likelihood(r: float, g: float, b: float) -> float:
    """Blattgrün / Mantel — G dominant."""
    if g < 40:
        return 0.0
    if g < r + 8 or g < b + 6:
        return 0.0
    ch = _chroma(r, g, b)
    if ch < 18:
        return 0.0
    lead = min(g - r, g - b)
    return min(1.0, (lead / 50.0) * (0.4 + 0.6 * min(1.0, ch / 60.0)))


def _red_likelihood(r: float, g: float, b: float) -> float:
    """Karmin / Scharlach — R klar dominant, nicht Ocker."""
    if r < 60:
        return 0.0
    if r < g + 12 or r < b + 15:
        return 0.0
    if _ochre_likelihood(r, g, b) > 0.4:
        return 0.0
    ch = _chroma(r, g, b)
    if ch < 25:
        return 0.0
    lead = min(r - g, r - b)
    return min(1.0, (lead / 55.0) * (0.35 + 0.65 * min(1.0, ch / 70.0)))


def _nearest_index(
    r: float,
    g: float,
    b: float,
    colors: list[tuple[int, int, int]],
    *,
    hue_priority: bool = True,
    distance_mode: str = "toon",
    color_labs: list[tuple[float, float, float]] | None = None,
    pixel_lab: tuple[float, float, float] | None = None,
    skin_bias: float = 0.0,
    yellow_in_skin: float = 0.25,
) -> int:
    """Semantische Gates → erlaubte Farben, dann Distanz (toon/lab/rgb)."""
    mode = _normalize_distance_mode(distance_mode, hue_priority=hue_priority)
    skin = _skin_likelihood(r, g, b) * max(0.0, min(1.0, skin_bias))
    ochre = _ochre_likelihood(r, g, b)
    neutral = _neutral_wall_likelihood(r, g, b)
    cool = _cool_neutral_likelihood(r, g, b)
    blue = _blue_likelihood(r, g, b)
    green = _green_likelihood(r, g, b)
    red = _red_likelihood(r, g, b)
    y_allow = max(0.0, min(1.0, yellow_in_skin))
    luma = _luma(r, g, b)

    if ochre > 0.25:
        skin *= max(0.0, 1.0 - ochre * 1.5)
    if neutral > 0.2:
        skin *= max(0.0, 1.0 - neutral)
    if blue > 0.25:
        skin *= max(0.0, 1.0 - blue)
    if green > 0.3:
        skin *= max(0.0, 1.0 - green * 0.8)

    lab_px = pixel_lab
    if mode == "lab" and lab_px is None:
        lab_px = rgb_to_lab(r, g, b)

    best_i = 0
    best_d = 1e18
    for i, c in enumerate(colors):
        if mode == "lab" and color_labs is not None and lab_px is not None:
            d = delta_e76_sq(lab_px, color_labs[i])
        elif mode == "toon":
            d = _dist_hue_priority(r, g, b, c)
        else:
            d = _dist_rgb(r, g, b, c)

        # --- Haut: Peach = W + dosiertes Y; R nur in Schatten; kein G/B ---
        if skin > 0.05:
            light = min(1.0, max(0.0, (luma - 90.0) / 120.0))
            mid = 1.0 - abs(luma - 155.0) / 100.0
            mid = max(0.0, min(1.0, mid))
            # Orange-Hemd / warmes Indoor: Hautchroma hoch → sonst R+Y-Stipple
            ch = _chroma(r, g, b)
            orange_cast = min(1.0, max(0.0, (ch - 55.0) / 90.0)) * min(
                1.0, max(0.0, (r - b - 40.0) / 100.0)
            )
            if i == _IDX_GREEN:
                d *= 1.0 + 6.0 * skin
            elif i == _IDX_BLUE:
                d *= 1.0 + 3.2 * skin
            elif i == _IDX_RED:
                # hellere Haut: Rot hart weg (Error-Diffusion sonst → Rosa-Stipple)
                d *= 1.0 + (0.4 + 2.8 * light + 3.0 * orange_cast) * skin
            elif i == _IDX_WHITE:
                d *= 1.0 - (0.42 + 0.12 * light + 0.48 * orange_cast) * skin
            elif i == _IDX_BLACK:
                d *= 1.0 + 0.1 * skin
            elif i == _IDX_YELLOW:
                # y_allow hoch → Gelb belohnen (Peach), sonst bestrafen
                # bei starkem Orange-Cast weniger Y (sonst „Käsegesicht“)
                y_bias = (0.85 - 1.65 * y_allow) * skin
                y_bias -= 0.45 * y_allow * mid * skin
                y_bias += 1.15 * orange_cast * skin
                d *= 1.0 + y_bias

        # --- Gold/Ocker: Y+K/W; Rot verboten ---
        if ochre > 0.08:
            dark = 1.0 - min(1.0, max(0.0, luma / 210.0))
            if i == _IDX_YELLOW:
                d *= 1.0 - (0.82 + 0.35 * dark) * ochre
            elif i == _IDX_RED:
                d *= 1.0 + (1.8 + 1.4 * dark) * ochre
            elif i == _IDX_WHITE:
                d *= 1.0 - 0.2 * ochre * (1.0 - dark)
            elif i == _IDX_BLACK:
                d *= 1.0 - 0.28 * ochre * dark
            elif i == _IDX_GREEN:
                d *= 1.0 + 1.1 * ochre
            elif i == _IDX_BLUE:
                d *= 1.0 + 0.9 * ochre

        # --- Neutrale Wand: K/W; Grün/Gelb/Rot hart weg ---
        if neutral > 0.08:
            if i == _IDX_GREEN:
                d *= 1.0 + 16.0 * neutral
            elif i == _IDX_YELLOW:
                d *= 1.0 + 2.4 * neutral
            elif i == _IDX_RED:
                d *= 1.0 + 1.6 * neutral
            elif i == _IDX_BLUE:
                d *= 1.0 + 0.35 * neutral  # Spur Blau ok für kühle Neutrale
            elif i == _IDX_BLACK:
                d *= 1.0 - 0.58 * neutral
            elif i == _IDX_WHITE:
                d *= 1.0 - 0.28 * neutral

        # --- Kühles Neutral: K/W + Spur B; kein G ---
        if cool > 0.08 and ochre < 0.15:
            if i == _IDX_GREEN:
                d *= 1.0 + 8.0 * cool
            elif i == _IDX_BLUE:
                d *= 1.0 - 0.45 * cool
            elif i == _IDX_BLACK:
                d *= 1.0 - 0.35 * cool
            elif i == _IDX_WHITE:
                d *= 1.0 - 0.2 * cool
            elif i == _IDX_RED:
                d *= 1.0 + 1.2 * cool
            elif i == _IDX_YELLOW:
                d *= 1.0 + 1.5 * cool

        # --- Echtes Blau / Pastell-Himmel: B belohnen, Weiss nicht stehlen ---
        if blue > 0.08:
            light = min(1.0, max(0.0, (luma - 120.0) / 90.0))
            if i == _IDX_BLUE:
                d *= 1.0 - (0.82 + 0.35 * light) * blue
            elif i == _IDX_GREEN:
                d *= 1.0 + 2.0 * blue
            elif i == _IDX_RED:
                d *= 1.0 + 1.7 * blue
            elif i == _IDX_YELLOW:
                d *= 1.0 + 1.5 * blue
            elif i == _IDX_WHITE:
                # Pastell: Weiss nur als Dither-Partner, nie Alleinherrscher
                d *= 1.0 + (0.35 + 0.45 * light) * blue
            elif i == _IDX_BLACK:
                d *= 1.0 - 0.22 * blue * (1.0 - light)

        # --- Blattgrün / Mantel ---
        if green > 0.1 and blue < 0.25 and ochre < 0.2:
            if i == _IDX_GREEN:
                d *= 1.0 - 0.55 * green
            elif i == _IDX_BLUE:
                # petrol/teal: etwas Blau erlauben
                teal = max(0.0, min(1.0, (b - r) / 40.0))
                d *= 1.0 - 0.25 * green * teal
            elif i == _IDX_RED:
                d *= 1.0 + 1.2 * green
            elif i == _IDX_YELLOW:
                d *= 1.0 + 0.35 * green

        # --- Karmin/Scharlach ---
        if red > 0.12 and ochre < 0.25 and skin < 0.2:
            if i == _IDX_RED:
                d *= 1.0 - 0.55 * red
            elif i == _IDX_YELLOW:
                d *= 1.0 + 0.9 * red
            elif i == _IDX_GREEN:
                d *= 1.0 + 1.4 * red
            elif i == _IDX_BLUE:
                d *= 1.0 + 0.8 * red
            elif i == _IDX_BLACK:
                d *= 1.0 - 0.15 * red * (1.0 - min(1.0, luma / 120.0))

        # --- Staubiges Warmgrau ohne Gate: trotzdem Grün vermeiden ---
        elif (
            neutral < 0.08
            and _chroma(r, g, b) < 45
            and 25 < luma < 160
            and blue < 0.1
            and green < 0.15
        ):
            if i == _IDX_GREEN:
                d *= 2.6
            elif i == _IDX_BLACK:
                d *= 0.84

        if d < best_d:
            best_d = d
            best_i = i
    return best_i


def natural_skin_prep(image: Image.Image, amount: float = 0.4) -> Image.Image:
    """Haut Richtung Peach/Rosa: weniger Gelbgrün, etwas mehr Rot."""
    amount = max(0.0, min(1.0, float(amount)))
    if amount < 0.01:
        return image
    rgb = image.convert("RGB")
    px = rgb.load()
    w, h = rgb.size
    out = Image.new("RGB", (w, h))
    out_px = out.load()
    for y in range(h):
        for x in range(w):
            r, g, b = px[x, y]
            s = _skin_likelihood(float(r), float(g), float(b)) * amount
            if s > 0.02:
                r = min(255, int(r + 3 * s))
                g = max(0, int(g - 10 * s))
                b = max(0, int(b - 4 * s))
                if g > r * 0.95:
                    g = max(0, int(g - 5 * s))
            out_px[x, y] = (r, g, b)
    return out


def neutral_wall_prep(image: Image.Image, amount: float = 0.65) -> Image.Image:
    """Dunkle/mittlere Fast-Neutrale → Grau (sonst Spectra-Grün als Olivwand)."""
    import numpy as np

    amount = max(0.0, min(1.0, float(amount)))
    if amount < 0.01:
        return image.convert("RGB")
    arr = np.asarray(image.convert("RGB"), dtype=np.float32)
    r, g, b = arr[:, :, 0], arr[:, :, 1], arr[:, :, 2]
    luma = 0.299 * r + 0.587 * g + 0.114 * b
    chroma = np.maximum(np.maximum(r, g), b) - np.minimum(np.minimum(r, g), b)
    # echtes Blau/Grün nicht entsättigen
    real_green = (g > r + 16) & (g > b + 12)
    # Pastell-Himmel nicht entsättigen
    real_blue = ((b > r + 8) & (b > g + 2) & (chroma > 14)) | (
        (luma > 135) & (b > r + 4) & (b >= g - 3) & (chroma > 10)
    )
    gate = (chroma < 32) & (luma > 22) & (luma < 175) & ~real_green & ~real_blue
    w = amount * np.clip(1.0 - chroma / 32.0, 0.0, 1.0) * np.clip(
        1.0 - (luma - 40.0) / 150.0, 0.35, 1.0
    )
    w = np.where(gate, w, 0.0)[..., None]
    grey = np.stack([luma, luma, luma], axis=-1) * 0.92
    out = arr * (1.0 - w) + grey * w
    np.clip(out, 0, 255, out=out)
    return Image.fromarray(out.astype(np.uint8), mode="RGB")


warm_skin_prep = natural_skin_prep


def pastel_sky_prep(image: Image.Image, amount: float = 0.55) -> Image.Image:
    """Helle kühle Flächen leicht blauer machen — sonst → reines Weiss."""
    import numpy as np

    amount = max(0.0, min(1.0, float(amount)))
    if amount < 0.01:
        return image.convert("RGB")
    arr = np.asarray(image.convert("RGB"), dtype=np.float32)
    r, g, b = arr[:, :, 0], arr[:, :, 1], arr[:, :, 2]
    luma = 0.299 * r + 0.587 * g + 0.114 * b
    chroma = np.maximum(np.maximum(r, g), b) - np.minimum(np.minimum(r, g), b)
    cool = (b > r + 2) & (b >= g - 8) & (luma > 125) & (chroma > 6) & (chroma < 90)
    # kein warmes Peach
    cool &= ~((r > g + 8) & (r > b + 5))
    w = amount * np.clip((b - r) / 35.0, 0.15, 1.0) * np.clip((luma - 120.0) / 80.0, 0.2, 1.0)
    w = np.where(cool, w, 0.0)
    b2 = np.clip(b + 28.0 * w, 0, 255)
    g2 = np.clip(g - 6.0 * w, 0, 255)
    r2 = np.clip(r - 10.0 * w, 0, 255)
    out = np.stack([r2, g2, b2], axis=-1)
    return Image.fromarray(out.astype(np.uint8), mode="RGB")


def dither_image(
    image: Image.Image,
    palette: Palette,
    *,
    strength: float = 1.0,
    algorithm: str = "floyd",
    match: str = "perceived",
    output: str = "device",
    hue_priority: bool = True,
    distance_mode: str | None = None,
    skin_bias: float = 0.85,
    warm_prep: float = 0.4,
    yellow_in_skin: float = 0.25,
) -> Image.Image:
    """Dither onto the e-paper palette with semantic color gates.

    ``distance_mode``: ``toon`` (Default, Toon-nooT), ``lab`` (CIE76), ``rgb``.
    ``algorithm``: ``atkinson``, ``floyd``, ``bluenoise``, ``none``.
    """
    strength = max(0.0, min(1.0, float(strength)))
    mode = _normalize_distance_mode(distance_mode, hue_priority=hue_priority)
    if warm_prep > 0.01:
        image = natural_skin_prep(image, warm_prep)
    image = pastel_sky_prep(image, 0.55)
    image = neutral_wall_prep(image, 0.72)
    rgb = image.convert("RGB")
    w, h = rgb.size
    px = rgb.load()

    match_colors = perceived_list(palette) if match == "perceived" else [c["device"] for c in palette["colors"]]
    out_colors = (
        [c["device"] for c in palette["colors"]]
        if output == "device"
        else perceived_list(palette)
    )
    err_colors = match_colors
    color_labs = palette_labs(match_colors) if mode == "lab" else None

    bias = max(0.0, min(1.0, float(skin_bias)))
    y_skin = max(0.0, min(1.0, float(yellow_in_skin)))

    buf = [[list(map(float, px[x, y])) for x in range(w)] for y in range(h)]
    # Skin-Maske vom Original (vor Error-Diffusion), sonst greift Override nicht
    skin_mask = [
        [
            _skin_likelihood(float(px[x, y][0]), float(px[x, y][1]), float(px[x, y][2]))
            * bias
            for x in range(w)
        ]
        for y in range(h)
    ]
    luma_mask = [
        [_luma(float(px[x, y][0]), float(px[x, y][1]), float(px[x, y][2])) for x in range(w)]
        for y in range(h)
    ]
    out = Image.new("RGB", (w, h))
    out_px = out.load()

    algo = (algorithm or "floyd").lower().replace("_", "").replace("-", "")
    if algo in ("bn", "blue", "voidandcluster", "vac"):
        algo = "bluenoise"
    use_bn = algo == "bluenoise"
    # Blue-Noise: ordered threshold — Amplitude skaliert mit strength
    bn_amp = 52.0 * strength

    for y in range(h):
        for x in range(w):
            old = buf[y][x]
            sr, sg, sb = old[0], old[1], old[2]
            if use_bn and strength > 0:
                # Dekorrelierte Phasen → weniger monochromes Korn
                t0 = (blue_noise_at(x, y) / 255.0 - 0.5) * 2.0 * bn_amp
                t1 = (blue_noise_at(x + 17, y + 23) / 255.0 - 0.5) * 2.0 * bn_amp
                t2 = (blue_noise_at(x + 7, y + 41) / 255.0 - 0.5) * 2.0 * bn_amp
                sr = old[0] + t0
                sg = old[1] + t1
                sb = old[2] + t2

            pixel_lab = rgb_to_lab(sr, sg, sb) if mode == "lab" else None
            idx = _nearest_index(
                sr,
                sg,
                sb,
                match_colors,
                hue_priority=hue_priority,
                distance_mode=mode,
                color_labs=color_labs,
                pixel_lab=pixel_lab,
                skin_bias=bias,
                yellow_in_skin=y_skin,
            )
            # Hellere Haut: reines Rot unterdrücken (Peach = W/Y)
            if idx == _IDX_RED and skin_mask[y][x] > 0.1 and luma_mask[y][x] > 120:
                idx = _IDX_YELLOW if y_skin > 0.4 else _IDX_WHITE
            matched = err_colors[idx]
            out_px[x, y] = out_colors[idx]

            if use_bn or algo == "none" or strength <= 0:
                continue

            err = [(old[i] - matched[i]) * strength for i in range(3)]

            def add(nx: int, ny: int, factor: float) -> None:
                if 0 <= nx < w and 0 <= ny < h:
                    p = buf[ny][nx]
                    for i in range(3):
                        p[i] += err[i] * factor

            if algo == "atkinson":
                add(x + 1, y, 1 / 8)
                add(x + 2, y, 1 / 8)
                add(x - 1, y + 1, 1 / 8)
                add(x, y + 1, 1 / 8)
                add(x + 1, y + 1, 1 / 8)
                add(x, y + 2, 1 / 8)
            else:
                add(x + 1, y, 7 / 16)
                add(x - 1, y + 1, 3 / 16)
                add(x, y + 1, 5 / 16)
                add(x + 1, y + 1, 1 / 16)

    return out
