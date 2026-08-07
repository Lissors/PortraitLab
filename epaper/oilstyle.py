"""Ölbild / Neural Style für Stufe 1.

- oil: echtes Oil-Painting (OpenCV xphoto) — Pinselkleckse, kein Aquarell
- princess / udnie: Fast Neural Style (ONNX)
"""

from __future__ import annotations

import urllib.request
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
MODELS_DIR = ROOT / "models"

MODEL_URLS: dict[str, str] = {
    "princess": "https://media.githubusercontent.com/media/onnx/models/main/validated/vision/style_transfer/fast_neural_style/model/rain-princess-9.onnx",
    "udnie": "https://media.githubusercontent.com/media/onnx/models/main/validated/vision/style_transfer/fast_neural_style/model/udnie-9.onnx",
}

MODEL_FILES: dict[str, str] = {
    "princess": "rain-princess-9.onnx",
    "udnie": "udnie-9.onnx",
}

_sessions: dict[str, object] = {}


def apply_oil_cv(image: Image.Image, *, strength: float = 0.45) -> Image.Image:
    """Echtes Ölbild via cv2.xphoto.oilPainting — feine Pinselstriche."""
    strength = max(0.2, min(1.0, float(strength)))
    bgr = cv2.cvtColor(np.asarray(image.convert("RGB")), cv2.COLOR_RGB2BGR)

    base = cv2.edgePreservingFilter(bgr, flags=2, sigma_s=20, sigma_r=0.28)

    # Feiner Pinsel (1–3); 1 = sehr fein, noch erkennbar als Öl
    brush = 1 if strength < 0.55 else 3
    dyn = 1

    painted = cv2.xphoto.oilPainting(base, brush, dyn)

    blur = cv2.GaussianBlur(painted, (0, 0), 0.5)
    painted = cv2.addWeighted(painted, 1.12, blur, -0.12, 0)

    out = cv2.addWeighted(painted, 0.9, base, 0.1, 0)
    return Image.fromarray(cv2.cvtColor(out, cv2.COLOR_BGR2RGB))


def ensure_model(style: str = "princess") -> Path:
    style = style if style in MODEL_FILES else "princess"
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    path = MODELS_DIR / MODEL_FILES[style]
    if path.is_file() and path.stat().st_size > 1_000_000:
        return path
    print(f"Lade Neural-Style-Modell ({style}) …")
    urllib.request.urlretrieve(MODEL_URLS[style], path)
    return path


def _get_session(style: str = "princess"):
    import onnxruntime as ort

    style = style if style in MODEL_FILES else "princess"
    if style not in _sessions:
        path = ensure_model(style)
        _sessions[style] = ort.InferenceSession(
            str(path), providers=["CPUExecutionProvider"]
        )
    return _sessions[style]


def apply_fnst(image: Image.Image, style: str = "princess") -> Image.Image:
    """Fast Neural Style Transfer (fest 224×224, danach hochskalieren)."""
    session = _get_session(style if style in MODEL_FILES else "princess")
    inputs = session.get_inputs()
    img_inp = next(
        (i for i in inputs if "weight" not in i.name.lower() and "bias" not in i.name.lower()),
        inputs[0],
    )
    out_name = session.get_outputs()[0].name
    shape = img_inp.shape
    th = int(shape[2]) if isinstance(shape[2], int) else 224
    tw = int(shape[3]) if isinstance(shape[3], int) else 224

    rgb = image.convert("RGB")
    w0, h0 = rgb.size
    small = rgb.resize((tw, th), Image.Resampling.LANCZOS)
    x = np.asarray(small, dtype=np.float32)
    x = np.transpose(x, (2, 0, 1))[None, ...]

    out = session.run([out_name], {img_inp.name: x})[0]
    out = np.squeeze(out)
    if out.ndim == 3 and out.shape[0] == 3:
        out = np.transpose(out, (1, 2, 0))
    out = np.clip(out, 0, 255).astype(np.uint8)
    result = Image.fromarray(out)
    if result.size != (w0, h0):
        result = result.resize((w0, h0), Image.Resampling.LANCZOS)
    return result


def apply_oil_style(image: Image.Image, style: str = "oil") -> Image.Image:
    if style in ("princess", "udnie"):
        return apply_fnst(image, style)
    return apply_oil_cv(image)
