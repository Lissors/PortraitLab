"""Blue-noise threshold map for Spectra-6 ordered dithering."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

_SIZE = 64
_BIN = Path(__file__).with_name("bluenoise64.bin")


@lru_cache(maxsize=1)
def blue_noise_map() -> list[list[int]]:
    """64×64 void-and-cluster threshold map (0..255), row-major."""
    raw = _BIN.read_bytes()
    if len(raw) != _SIZE * _SIZE:
        raise RuntimeError(f"bluenoise64.bin erwartet {_SIZE * _SIZE} Bytes, got {len(raw)}")
    rows: list[list[int]] = []
    for y in range(_SIZE):
        base = y * _SIZE
        rows.append([raw[base + x] for x in range(_SIZE)])
    return rows


def blue_noise_at(x: int, y: int) -> int:
    m = blue_noise_map()
    return m[y % _SIZE][x % _SIZE]
