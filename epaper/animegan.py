"""AnimeGANv3 ONNX — echte Comic/Anime-Stufe 1 (lokal)."""

from __future__ import annotations

import urllib.request
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
MODELS_DIR = ROOT / "models"

MODEL_URLS: dict[str, str] = {
    "hayao": "https://github.com/TachibanaYoshino/AnimeGANv3/releases/download/v1.1.0/AnimeGANv3_Hayao_36.onnx",
    "shinkai": "https://github.com/TachibanaYoshino/AnimeGANv3/releases/download/v1.1.0/AnimeGANv3_Shinkai_37.onnx",
}

MODEL_FILES: dict[str, str] = {
    "hayao": "AnimeGANv3_Hayao_36.onnx",
    "shinkai": "AnimeGANv3_Shinkai_37.onnx",
}

_sessions: dict[str, object] = {}


def _to_multiple(x: int, m: int = 8, minimum: int = 256) -> int:
    if x < minimum:
        return minimum
    return x - (x % m)


def ensure_model(style: str = "hayao") -> Path:
    style = style if style in MODEL_FILES else "hayao"
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    path = MODELS_DIR / MODEL_FILES[style]
    if path.is_file() and path.stat().st_size > 1_000_000:
        return path
    url = MODEL_URLS[style]
    print(f"Loading AnimeGANv3 model ({style}) …")
    urllib.request.urlretrieve(url, path)
    return path


def _get_session(style: str = "hayao"):
    import onnxruntime as ort

    style = style if style in MODEL_FILES else "hayao"
    if style not in _sessions:
        path = ensure_model(style)
        _sessions[style] = ort.InferenceSession(
            str(path), providers=["CPUExecutionProvider"]
        )
    return _sessions[style]


def apply_animegan(image: Image.Image, style: str = "hayao") -> Image.Image:
    """Foto → Anime/Comic via AnimeGANv3. Behält Ausgabegröße = Eingabegröße."""
    session = _get_session(style)
    inp = session.get_inputs()[0]
    out_name = session.get_outputs()[0].name

    rgb = np.asarray(image.convert("RGB"))
    h0, w0 = rgb.shape[:2]
    tw = _to_multiple(w0)
    th = _to_multiple(h0)

    # cv2-kompatibel: BGR lesen → RGB float wie test_by_onnx
    import cv2

    bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    resized = cv2.resize(bgr, (tw, th))
    tensor = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB).astype(np.float32) / 127.5 - 1.0
    batch = np.expand_dims(tensor, axis=0)

    fake = session.run([out_name], {inp.name: batch})[0]
    out = np.squeeze(fake)
    out = ((out + 1.0) / 2.0 * 255.0).clip(0, 255).astype(np.uint8)
    if out.shape[0] != h0 or out.shape[1] != w0:
        out = cv2.resize(out, (w0, h0), interpolation=cv2.INTER_CUBIC)
    return Image.fromarray(out)


def available_styles() -> list[str]:
    return list(MODEL_FILES.keys())
