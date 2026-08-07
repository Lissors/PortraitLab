"""CIE L*a*b* helpers for Spectra-6 palette matching."""

from __future__ import annotations


def srgb_to_linear(c: float) -> float:
    """Channel 0..255 → linear light."""
    v = c / 255.0
    if v <= 0.04045:
        return v / 12.92
    return ((v + 0.055) / 1.055) ** 2.4


def rgb_to_xyz(r: float, g: float, b: float) -> tuple[float, float, float]:
    """sRGB 0..255 → CIE XYZ (D65)."""
    rl = srgb_to_linear(r)
    gl = srgb_to_linear(g)
    bl = srgb_to_linear(b)
    x = rl * 0.4124564 + gl * 0.3575761 + bl * 0.1804375
    y = rl * 0.2126729 + gl * 0.7151522 + bl * 0.0721750
    z = rl * 0.0193339 + gl * 0.1191920 + bl * 0.9503041
    return x, y, z


def _lab_f(t: float) -> float:
    delta = 6.0 / 29.0
    if t > delta**3:
        return t ** (1.0 / 3.0)
    return t / (3.0 * delta * delta) + 4.0 / 29.0


def xyz_to_lab(x: float, y: float, z: float) -> tuple[float, float, float]:
    """XYZ → CIE L*a*b* (D65 white)."""
    # D65
    xn, yn, zn = 0.95047, 1.00000, 1.08883
    fx = _lab_f(x / xn)
    fy = _lab_f(y / yn)
    fz = _lab_f(z / zn)
    L = 116.0 * fy - 16.0
    a = 500.0 * (fx - fy)
    b = 200.0 * (fy - fz)
    return L, a, b


def rgb_to_lab(r: float, g: float, b: float) -> tuple[float, float, float]:
    return xyz_to_lab(*rgb_to_xyz(r, g, b))


def delta_e76_sq(
    lab1: tuple[float, float, float],
    lab2: tuple[float, float, float],
) -> float:
    """Squared CIE76 ΔE (faster, order-preserving)."""
    dL = lab1[0] - lab2[0]
    da = lab1[1] - lab2[1]
    db = lab1[2] - lab2[2]
    return dL * dL + da * da + db * db


def palette_labs(colors: list[tuple[int, int, int]]) -> list[tuple[float, float, float]]:
    return [rgb_to_lab(float(c[0]), float(c[1]), float(c[2])) for c in colors]
