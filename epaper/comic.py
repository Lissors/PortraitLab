"""Stufe 1: Foto → Vollfarb-Comic (Mitte der Orientierungs-Grafik).

Ziel: flache Farbflächen + kräftige schwarze Tusche-Konturen.
"""

from __future__ import annotations

import numpy as np
from PIL import Image
import cv2


def _odd(n: int, minimum: int = 3) -> int:
    n = max(minimum, int(n))
    return n if n % 2 else n + 1


def _ink_edges(bgr: np.ndarray, quantized: np.ndarray, line_size: int) -> np.ndarray:
    """Dicke Tusche-Konturen: Canny + Flächengrenzen, ohne Adaptive-Speckles."""
    h, w = bgr.shape[:2]
    line_size = max(3, int(line_size))

    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    soft = gray.copy()
    for _ in range(3):
        soft = cv2.bilateralFilter(soft, d=9, sigmaColor=80, sigmaSpace=80)
    soft = cv2.medianBlur(soft, _odd(line_size, 5))

    # Multi-Scale Canny → lange Konturen um Augen/Nase/Mund/Kiefer
    e_fine = cv2.Canny(soft, 45, 130)
    e_coarse = cv2.Canny(cv2.GaussianBlur(soft, (0, 0), 1.6), 30, 100)
    edges = cv2.bitwise_or(e_fine, e_coarse)

    # Grenzen der Cel-Flächen
    qgray = cv2.cvtColor(quantized, cv2.COLOR_BGR2GRAY)
    qgray = cv2.medianBlur(qgray, 5)
    region = cv2.Canny(qgray, 18, 55)
    edges = cv2.bitwise_or(edges, region)

    # Schließen und kräftig verdicken (Comic-Strich)
    k3 = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    edges = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, k3, iterations=2)
    thick = _odd(max(3, line_size // 2))
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (thick, thick))
    edges = cv2.dilate(edges, k, iterations=1)

    # Nur echte Mini-Punkte weg; Hauptlinien behalten
    num, labels, stats, _ = cv2.connectedComponentsWithStats(edges, connectivity=8)
    cleaned = np.zeros_like(edges)
    min_area = max(18, (h * w) // 60000)
    for i in range(1, num):
        if stats[i, cv2.CC_STAT_AREA] >= min_area:
            cleaned[labels == i] = 255
    return cleaned


def apply_comic(
    image: Image.Image,
    *,
    colors: int = 8,
    line_size: int = 7,
    blur: int = 9,
    bilateral: int = 9,
) -> Image.Image:
    colors = max(4, min(16, int(colors)))
    blur = _odd(blur, 5)
    bilateral = max(5, int(bilateral))
    line_size = max(3, int(line_size))

    rgb = np.array(image.convert("RGB"))
    bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)

    # --- Flache Cel-Farben ---
    color = bgr.copy()
    for _ in range(5):
        color = cv2.bilateralFilter(color, d=bilateral, sigmaColor=100, sigmaSpace=100)
    color = cv2.medianBlur(color, blur)

    h, w = color.shape[:2]
    data = color.reshape((-1, 3)).astype(np.float32)
    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 40, 0.4)
    _, labels, centers = cv2.kmeans(
        data, colors, None, criteria, 5, cv2.KMEANS_PP_CENTERS
    )
    quantized = np.uint8(centers)[labels.flatten()].reshape((h, w, 3))
    quantized = cv2.medianBlur(quantized, 5)

    # Leicht mehr Kontrast in den Flächen (Comic-Punch)
    lab = cv2.cvtColor(quantized, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)
    clahe = cv2.createCLAHE(clipLimit=1.4, tileGridSize=(8, 8))
    l = clahe.apply(l)
    quantized = cv2.cvtColor(cv2.merge([l, a, b]), cv2.COLOR_LAB2BGR)

    edges = _ink_edges(bgr, quantized, line_size)

    comic = quantized.copy()
    comic[edges > 0] = (0, 0, 0)

    return Image.fromarray(cv2.cvtColor(comic, cv2.COLOR_BGR2RGB))


def apply_comic_fill(image: Image.Image, **kwargs) -> Image.Image:
    return apply_comic(image, **kwargs)


def ink_mask(image: Image.Image, line_size: int = 7, **kwargs) -> Image.Image:
    rgb = np.array(image.convert("RGB"))
    bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    color = bgr.copy()
    for _ in range(3):
        color = cv2.bilateralFilter(color, d=9, sigmaColor=90, sigmaSpace=90)
    edges = _ink_edges(bgr, color, line_size)
    return Image.fromarray(edges)


def ink_mask_from_fill(fill: Image.Image, **kwargs) -> Image.Image:
    return ink_mask(fill, **kwargs)


def apply_ink(image: Image.Image, mask: Image.Image, color=(0, 0, 0)) -> Image.Image:
    out = image.convert("RGB").copy()
    out.paste(color, mask=mask)
    return out
