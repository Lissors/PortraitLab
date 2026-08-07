"""Device color palette — nur Spectra 6 (Amazon PhotoPainter E6)."""

from __future__ import annotations

from typing import TypedDict


class PaletteColor(TypedDict):
    label: str
    perceived: tuple[int, int, int]
    device: tuple[int, int, int]


class Palette(TypedDict):
    id: str
    name: str
    colors: list[PaletteColor]


# E Ink Spectra 6 — perceived für semantisches Matching (nicht Geräte-Neon)
SPECTRA6: Palette = {
    "id": "spectra6",
    "name": "Spectra 6 (E6) · 6 colors",
    "colors": [
        # Neutraleres Schwarz (kein Oliv-/Blaustich)
        {"label": "Black", "perceived": (28, 28, 28), "device": (0, 0, 0)},
        # Leicht warmes Weiss für Haut-Highlights
        {"label": "White", "perceived": (210, 204, 196), "device": (255, 255, 255)},
        # Blattgrün — weiter weg von Grau
        {"label": "Green", "perceived": (48, 98, 52), "device": (0, 255, 0)},
        # Helleres Blau — sonst wandert Pastell-Himmel komplett nach Weiss
        {"label": "Blue", "perceived": (78, 112, 178), "device": (0, 0, 255)},
        # Klareres Pigmentrot (Haut eher über W+Y+leicht R)
        {"label": "Red", "perceived": (168, 58, 48), "device": (255, 0, 0)},
        # Peach-taugliches Ockergelb (Haut-Mitttöne)
        {"label": "Yellow", "perceived": (188, 152, 42), "device": (255, 255, 0)},
    ],
}

# Nur Schwarz + Weiss (für SW-Modus) — neutrale perceived-Werte,
# sonst wirkt das kalibrierte E6-Schwarz (G>R) auf dem Monitor grünlich.
SPECTRA6_BW: Palette = {
    "id": "spectra6_bw",
    "name": "Spectra 6 · Black & white",
    "colors": [
        {"label": "Black", "perceived": (18, 18, 18), "device": (0, 0, 0)},
        {"label": "White", "perceived": (245, 245, 245), "device": (255, 255, 255)},
    ],
}

PALETTES: dict[str, Palette] = {
    SPECTRA6["id"]: SPECTRA6,
    SPECTRA6_BW["id"]: SPECTRA6_BW,
}


def get_palette(palette_id: str = "spectra6") -> Palette:
    return PALETTES.get(palette_id, SPECTRA6)


def perceived_list(palette: Palette) -> list[tuple[int, int, int]]:
    return [c["perceived"] for c in palette["colors"]]


def device_list(palette: Palette) -> list[tuple[int, int, int]]:
    return [c["device"] for c in palette["colors"]]


def device_to_simulated(image, palette_id: str = "spectra6"):
    """Geräte-BMP (reine R/G/B/…) → Monitor-Simulation mit perceived-Farben."""
    from PIL import Image
    import numpy as np

    palette = get_palette(palette_id)
    # BW-BMP hat nur K/W — Spectra6-Map würde Grün etc. nie treffen, passt trotzdem
    arr = np.asarray(image.convert("RGB"), dtype=np.uint8)
    out = arr.copy()
    for c in palette["colors"]:
        d = c["device"]
        p = c["perceived"]
        mask = (arr[:, :, 0] == d[0]) & (arr[:, :, 1] == d[1]) & (arr[:, :, 2] == d[2])
        if mask.any():
            out[mask] = p
    # Unbekannte Pixel: nächster Geräte-Farbton
    known = {(c["device"][0], c["device"][1], c["device"][2]) for c in palette["colors"]}
    # Schnellpfad: wenn alles gemappt, fertig
    flat = arr.reshape(-1, 3)
    # Nur wenn es ungemappte gibt — selten bei Export
    uniq = {tuple(map(int, t)) for t in np.unique(flat, axis=0)}
    unknown = uniq - known
    if unknown:
        devices = [c["device"] for c in palette["colors"]]
        perceived = [c["perceived"] for c in palette["colors"]]
        for uy in unknown:
            best_i = 0
            best_d = 1e18
            for i, d in enumerate(devices):
                dist = (uy[0] - d[0]) ** 2 + (uy[1] - d[1]) ** 2 + (uy[2] - d[2]) ** 2
                if dist < best_d:
                    best_d = dist
                    best_i = i
            mask = (arr[:, :, 0] == uy[0]) & (arr[:, :, 1] == uy[1]) & (arr[:, :, 2] == uy[2])
            out[mask] = perceived[best_i]
    return Image.fromarray(out, mode="RGB")
