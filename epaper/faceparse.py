"""BiSeNet Face-Parsing (ResNet18 ONNX) — Hautmaske für Intensiv-Suche.

Modell (MIT): yakhyo/face-parsing ResNet18 ONNX (~43–51 MB).
Download-URL (GitHub Release ``weights``):
  https://github.com/yakhyo/face-parsing/releases/download/weights/resnet18.onnx
Repo: https://github.com/yakhyo/face-parsing
"""

from __future__ import annotations

import urllib.request
from pathlib import Path

import numpy as np
from PIL import Image

from .paths import MODELS_DIR

# BiSeNet Face-Parsing ResNet18 ONNX — MIT, yakhyo/face-parsing @ release ``weights``
MODEL_URL = (
    "https://github.com/yakhyo/face-parsing/releases/download/weights/resnet18.onnx"
)
MODEL_FILE = "bisenet_face_parsing_resnet18.onnx"
# Mindestens ~40 MB — kleinere Dateien = Abbruch/HTML-Fehlerseite
_MIN_BYTES = 40_000_000

# CelebAMask-HQ Klassen (0 = Hintergrund). Haut-ROI für Peach-Scoring.
_SKIN_CLASSES = frozenset(
    {
        1,  # skin
        10,  # nose
        14,  # neck
    }
)

_session = None


def model_path() -> Path:
    return MODELS_DIR / MODEL_FILE


def ensure_model(*, download: bool = True) -> Path | None:
    """Pfad zum ONNX, oder None wenn fehlend und download=False / Download scheitert."""
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    path = model_path()
    if path.is_file() and path.stat().st_size >= _MIN_BYTES:
        return path
    if not download:
        return None
    print(f"Loading BiSeNet face parsing ({MODEL_FILE}) …")
    tmp = path.with_suffix(".onnx.part")
    try:
        urllib.request.urlretrieve(MODEL_URL, tmp)
        if not tmp.is_file() or tmp.stat().st_size < _MIN_BYTES:
            tmp.unlink(missing_ok=True)
            print("BiSeNet download incomplete — fallback without skin mask.")
            return None
        tmp.replace(path)
    except Exception as exc:  # noqa: BLE001
        tmp.unlink(missing_ok=True)
        print(f"BiSeNet download failed: {exc}")
        return None
    return path


def _get_session():
    global _session
    import onnxruntime as ort

    if _session is not None:
        return _session
    path = ensure_model(download=True)
    if path is None:
        return None
    _session = ort.InferenceSession(str(path), providers=["CPUExecutionProvider"])
    return _session


def skin_mask_from_rgb(
    image: Image.Image,
    *,
    download: bool = True,
) -> np.ndarray | None:
    """Bool-Maske (H, W) für Haut/Nase/Hals. None bei fehlendem Modell oder leerer Maske."""
    path = ensure_model(download=download)
    if path is None:
        return None
    try:
        session = _get_session()
    except Exception as exc:  # noqa: BLE001
        print(f"BiSeNet-Session: {exc}")
        return None
    if session is None:
        return None

    import cv2

    rgb = np.asarray(image.convert("RGB"), dtype=np.uint8)
    h0, w0 = rgb.shape[:2]
    # yakhyo onnx_inference: BGR rein → RGB, 512×512, ImageNet-Norm, NCHW
    bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    resized = cv2.resize(bgr, (512, 512), interpolation=cv2.INTER_LINEAR)
    rgb_in = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
    mean = np.array([0.485, 0.456, 0.406], dtype=np.float32)
    std = np.array([0.229, 0.224, 0.225], dtype=np.float32)
    tensor = (rgb_in - mean) / std
    batch = np.transpose(tensor, (2, 0, 1))[None, ...].astype(np.float32)

    inp = session.get_inputs()[0]
    out_name = session.get_outputs()[0].name
    try:
        logits = session.run([out_name], {inp.name: batch})[0]
    except Exception as exc:  # noqa: BLE001
        print(f"BiSeNet-Inferenz: {exc}")
        return None

    pred = np.asarray(logits).squeeze(0).argmax(0).astype(np.uint8)
    mask_small = np.isin(pred, list(_SKIN_CLASSES))
    mask = cv2.resize(
        mask_small.astype(np.uint8),
        (w0, h0),
        interpolation=cv2.INTER_NEAREST,
    ).astype(bool)
    if not bool(mask.any()):
        return None
    # Zu wenig Fläche → eher Fehltreffer bei Gemälden ohne klares Gesicht
    if float(mask.mean()) < 0.004:
        return None
    return mask
