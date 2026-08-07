"""Portrait Lab — AnimeGANv3 Comic + Spectra 6 Dither → pic/."""

from __future__ import annotations

import base64
import io
import json
import os
import threading
import time
import uuid
import webbrowser
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from PIL import Image, ImageOps

from epaper.adjust import fit_portrait
from epaper.export import LANDSCAPE_SIZE, PORTRAIT_SIZE, export_bmp
from epaper.paths import (
    PIC_DIR,
    ROOT,
    STATIC_DIR,
    ensure_dirs,
    gallery_export_files,
    is_gallery_bmp,
    resolve_original,
)
from epaper.styles import COLORS, PALETTE_ID, INTENSIVE_STYLE_IDS, STYLES, stage1_comic, stage2_epaper
from epaper.palette import get_palette, device_to_simulated


ensure_dirs()

APP_VERSION = "3.16.4"

# Intensiv-Suche: Hintergrund-Job + Polling (kein Lang-POST / kein Disconnect-Cancel)
_intensive_lock = threading.Lock()
_intensive_cancel = threading.Event()
_intensive_job: dict | None = None


def _canvas_size(*, portrait: bool) -> tuple[int, int]:
    return PORTRAIT_SIZE if portrait else LANDSCAPE_SIZE


def _is_portrait_flag(value: object, *, default: bool = True) -> bool:
    """Form/JSON: portrait=1|true|portrait / landscape|0|false."""
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    s = str(value).strip().lower()
    if s in {"0", "false", "no", "off", "landscape", "quer", "querformat"}:
        return False
    if s in {"1", "true", "yes", "on", "portrait", "hoch", "hochformat"}:
        return True
    return default


def _open_image(data: bytes) -> Image.Image:
    """Laden inkl. EXIF-Ausrichtung (sonst Querformat-Pixel bei Hochkant-Fotos)."""
    img = Image.open(io.BytesIO(data))
    img.load()
    try:
        img = ImageOps.exif_transpose(img)
    except Exception:  # noqa: BLE001
        pass
    return img.convert("RGB")


def _bmp_size(path: Path) -> tuple[int, int] | None:
    try:
        with Image.open(path) as im:
            return im.size
    except Exception:  # noqa: BLE001
        return None

app = FastAPI(title="Portrait Lab", version=APP_VERSION)


def _truthy(value: str | bool | int | None) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


class NoCacheStaticMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        path = request.url.path
        if path.endswith((".js", ".css", ".html")) or path == "/":
            response.headers["Cache-Control"] = "no-store, max-age=0"
        return response


app.add_middleware(NoCacheStaticMiddleware)


def _png_b64(img: Image.Image) -> str:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii")


def _png_bytes(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


@app.get("/api/meta")
def meta() -> dict:
    pal = get_palette(PALETTE_ID)
    return {
        "version": APP_VERSION,
        "pipeline": [
            {"stage": 1, "name": "Style (Anime / Oil)", "standalone": True},
            {"stage": 2, "name": "Spectra 6 E-Paper", "standalone": False},
        ],
        "device": "Waveshare ESP32-S3-PhotoPainter · E6",
        "colors": COLORS,
        "paletteId": PALETTE_ID,
        "portrait": {"width": PORTRAIT_SIZE[0], "height": PORTRAIT_SIZE[1]},
        "landscape": {"width": LANDSCAPE_SIZE[0], "height": LANDSCAPE_SIZE[1]},
        "format": "24-bit BMP",
        "picDir": str(PIC_DIR),
        "styles": list(STYLES.values()),
        "intensiveStyleIds": list(INTENSIVE_STYLE_IDS),
        "defaultStyle": "auto",
        "ditherAlgorithms": [
            {"id": "atkinson", "label": "Atkinson (Portrait)"},
            {"id": "floyd", "label": "Floyd–Steinberg"},
            {"id": "bluenoise", "label": "Blue Noise"},
            {"id": "none", "label": "No dither"},
        ],
        "colorDistances": [
            {"id": "toon", "label": "Toon-nooT (Default)"},
            {"id": "lab", "label": "CIE L*a*b*"},
        ],
        "swatches": [
            {"label": c["label"], "perceived": list(c["perceived"]), "device": list(c["device"])}
            for c in pal["colors"]
        ],
    }


@app.get("/api/gallery")
def gallery() -> dict:
    """Nur fertige Exporte (BMP + Settings) — keine Comic-PNGs auf Disk."""
    files = sorted(
        (f for f in PIC_DIR.glob("*.bmp") if is_gallery_bmp(f)),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    items = []
    for f in files:
        stem = f.stem
        settings = PIC_DIR / f"{stem}_settings.json"
        size = _bmp_size(f)
        w, h = size if size else (PORTRAIT_SIZE[0], PORTRAIT_SIZE[1])
        orient = "landscape" if w > h else "portrait"
        has_settings = settings.is_file()
        meta: dict = {}
        if has_settings:
            try:
                loaded = json.loads(settings.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    meta = loaded
            except Exception:  # noqa: BLE001
                meta = {}
        src_path = resolve_original(meta, stem) if has_settings else resolve_original({}, stem)
        items.append(
            {
                "name": f.name,
                "url": f"/pic/{f.name}",
                "simUrl": f"/api/sim/{f.name}",
                # Comic wird on-demand aus Original+Settings neu berechnet (nicht in pic/)
                "comicUrl": f"/api/gallery/{f.name}/comic" if has_settings else None,
                "settingsUrl": f"/pic/{settings.name}" if has_settings else None,
                "originalUrl": f"/api/gallery/{f.name}/original" if src_path else None,
                "originalName": src_path.name if src_path else None,
                "bytes": f.stat().st_size,
                "width": w,
                "height": h,
                "orientation": orient,
                "portrait": orient == "portrait",
                "autotune": (
                    "autotune" in f.name.lower()
                    or f.name.lower().endswith("_at.bmp")
                    or "_at." in f.name.lower()
                ),
            }
        )
    return {"items": items}


@app.get("/api/sim/{name}")
def simulate_bmp(name: str) -> Response:
    """Geräte-BMP als E6-Monitor-Simulation (perceived)."""
    safe = Path(name).name
    if not safe.lower().endswith(".bmp"):
        raise HTTPException(400, "BMP only")
    path = (PIC_DIR / safe).resolve()
    if path.parent != PIC_DIR.resolve() or not path.is_file():
        raise HTTPException(404, "BMP not found")
    if not is_gallery_bmp(path):
        raise HTTPException(404, "BMP not in gallery")
    try:
        img = Image.open(path)
        img.load()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, f"BMP unreadable: {exc}") from exc
    sim = device_to_simulated(img, PALETTE_ID)
    return Response(content=_png_bytes(sim), media_type="image/png")


def _gallery_bmp_and_meta(name: str) -> tuple[Path, dict]:
    safe = Path(name).name
    if not safe.lower().endswith(".bmp"):
        raise HTTPException(400, "BMP only")
    path = (PIC_DIR / safe).resolve()
    if path.parent != PIC_DIR.resolve() or not path.is_file():
        raise HTTPException(404, "BMP not found")
    if not is_gallery_bmp(path):
        raise HTTPException(404, "BMP not in gallery")
    meta_path = PIC_DIR / f"{path.stem}_settings.json"
    meta: dict = {}
    if meta_path.is_file():
        try:
            loaded = json.loads(meta_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                meta = loaded
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(400, f"Settings unreadable: {exc}") from exc
    return path, meta


@app.get("/api/gallery/{name}/original")
def gallery_original(name: str) -> Response:
    """Quellbild aus original/ für Re-Crop nach Galerie-Öffnen."""
    path, meta = _gallery_bmp_and_meta(name)
    src_path = resolve_original(meta, path.stem)
    if src_path is None:
        raise HTTPException(404, "Original not in original/")
    data = src_path.read_bytes()
    suf = src_path.suffix.lower()
    mime = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
        ".bmp": "image/bmp",
    }.get(suf, "application/octet-stream")
    return Response(
        content=data,
        media_type=mime,
        headers={
            "Content-Disposition": f'inline; filename="{src_path.name}"',
            "Cache-Control": "no-store",
            "X-Original-Name": src_path.name,
        },
    )


@app.get("/api/gallery/{name}/comic")
def gallery_comic(name: str) -> Response:
    """Stufe-1-Comic on-demand aus Original + Settings — ohne Disk-Schreiben."""
    path, meta = _gallery_bmp_and_meta(name)
    meta_path = PIC_DIR / f"{path.stem}_settings.json"
    if not meta_path.is_file():
        raise HTTPException(404, "No settings for this BMP")

    src_path = resolve_original(meta, path.stem)
    if src_path is None:
        raise HTTPException(
            404,
            "Original not in original/ — comic not rebuildable",
        )

    st = meta.get("settings") if isinstance(meta, dict) else {}
    if not isinstance(st, dict):
        st = {}
    size = _bmp_size(path)
    is_portrait = True
    if size:
        is_portrait = size[0] <= size[1]
    if "portrait" in st or "orientation" in st:
        is_portrait = _is_portrait_flag(
            st.get("portrait", st.get("orientation")),
            default=is_portrait,
        )
    tw, th = _canvas_size(portrait=is_portrait)
    style_id = str(st.get("style_id") or st.get("styleId") or "auto")

    try:
        src = _open_image(src_path.read_bytes())
        fitted = fit_portrait(
            src,
            tw,
            th,
            mode="cover",
            focus_x=float(st.get("focus_x", st.get("focusX", 0.5))),
            focus_y=float(st.get("focus_y", st.get("focusY", 0.5))),
            zoom=float(st.get("zoom", 1.0)),
        )
        comic = stage1_comic(fitted, style_id)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, f"Comic rebuild failed: {exc}") from exc

    return Response(content=_png_bytes(comic), media_type="image/png")


@app.delete("/api/gallery/{name}")
def delete_gallery_item(name: str) -> JSONResponse:
    """Galerie-BMP + Settings (+ ggf. Legacy-Sidecars) aus pic/ löschen."""
    safe = Path(name).name
    if not safe.lower().endswith(".bmp"):
        raise HTTPException(400, "BMP only")
    path = (PIC_DIR / safe).resolve()
    pic = PIC_DIR.resolve()
    if path.parent != pic or not path.is_file():
        raise HTTPException(404, "BMP not found")
    if not is_gallery_bmp(path):
        raise HTTPException(400, "Not a gallery file (finished exports only)")
    removed: list[str] = []
    for candidate in gallery_export_files(path):
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        if resolved.parent != pic or not resolved.is_file():
            continue
        resolved.unlink()
        removed.append(resolved.name)
    return JSONResponse({"ok": True, "removed": removed, "stem": path.stem})


@app.post("/api/render")
async def render_stages(
    file: UploadFile = File(...),
    style_id: str = Form("auto"),
    focus_x: float = Form(0.5),
    focus_y: float = Form(0.5),
    zoom: float = Form(1.0),
    stage: str = Form("pair"),
    dither_strength: float = Form(1.0),
    dither_algo: str = Form("atkinson"),
    color_distance: str = Form("toon"),
    skin_warmth: float = Form(0.5),
    warmth: float | None = Form(None),
    skin_tint: float | None = Form(None),
    brightness: float = Form(1.0),
    contrast: float = Form(1.0),
    grayscale: str = Form("0"),
    portrait: str = Form("1"),
) -> Response:
    raw = await file.read()
    try:
        src = _open_image(raw)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, f"Image unreadable: {exc}") from exc

    is_portrait = _is_portrait_flag(portrait, default=True)
    tw, th = _canvas_size(portrait=is_portrait)
    fitted = fit_portrait(
        src,
        tw,
        th,
        mode="cover",
        focus_x=focus_x,
        focus_y=focus_y,
        zoom=zoom,
    )
    try:
        comic = stage1_comic(fitted, style_id)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, f"Comic AI failed: {exc}") from exc

    if stage == "comic":
        return Response(content=_png_bytes(comic), media_type="image/png")

    epaper = stage2_epaper(
        comic,
        output="perceived",
        dither_strength=dither_strength,
        algorithm=dither_algo,
        distance_mode=color_distance,
        skin_warmth=skin_warmth,
        brightness=brightness,
        contrast=contrast,
        style_id=style_id,
        grayscale=_truthy(grayscale),
        warmth=warmth,
        skin_tint=skin_tint,
    )
    if stage == "epaper":
        return Response(content=_png_bytes(epaper), media_type="image/png")

    return JSONResponse(
        {
            "ok": True,
            "comic": _png_b64(comic),
            "epaper": _png_b64(epaper),
            "size": [tw, th],
            "portrait": is_portrait,
            "orientation": "portrait" if is_portrait else "landscape",
            "styleId": style_id,
        }
    )


@app.post("/api/dither")
async def dither_only(
    file: UploadFile = File(...),
    dither_strength: float = Form(1.0),
    dither_algo: str = Form("atkinson"),
    color_distance: str = Form("toon"),
    skin_warmth: float = Form(0.5),
    warmth: float | None = Form(None),
    skin_tint: float | None = Form(None),
    brightness: float = Form(1.0),
    contrast: float = Form(1.0),
    style_id: str = Form("auto"),
    grayscale: str = Form("0"),
) -> Response:
    """Nur Stufe 2 — Comic-PNG rein, E6 raus (schnell bei Farbe/Dither)."""
    raw = await file.read()
    try:
        comic = _open_image(raw)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, f"Comic unreadable: {exc}") from exc

    epaper = stage2_epaper(
        comic,
        output="perceived",
        dither_strength=dither_strength,
        algorithm=dither_algo,
        distance_mode=color_distance,
        skin_warmth=skin_warmth,
        brightness=brightness,
        contrast=contrast,
        style_id=style_id,
        grayscale=_truthy(grayscale),
        warmth=warmth,
        skin_tint=skin_tint,
    )
    return Response(content=_png_bytes(epaper), media_type="image/png")


@app.post("/api/export")
async def export_endpoint(
    file: UploadFile = File(...),
    meta_json: str = Form("{}"),
) -> JSONResponse:
    try:
        settings = json.loads(meta_json or "{}")
    except json.JSONDecodeError as exc:
        raise HTTPException(400, f"meta_json invalid: {exc}") from exc

    raw = await file.read()
    try:
        src = _open_image(raw)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, f"Image unreadable: {exc}") from exc

    filename = settings.get("filename", "portrait")
    style_id = settings.get("styleId", "auto")
    dither_strength = float(settings.get("ditherStrength", 1.0))
    dither_algo = settings.get("ditherAlgo", "atkinson")
    color_distance = settings.get("colorDistance", settings.get("color_distance", "toon"))
    skin_warmth = float(settings.get("skinWarmth", 0.5))
    warmth = settings.get("warmth")
    skin_tint = settings.get("skinTint")
    brightness = float(settings.get("brightness", 1.0))
    contrast = float(settings.get("contrast", 1.0))
    grayscale = bool(settings.get("grayscale", False))
    is_portrait = _is_portrait_flag(
        settings.get("portrait", settings.get("orientation")),
        default=True,
    )
    tw, th = _canvas_size(portrait=is_portrait)

    fitted = fit_portrait(
        src,
        tw,
        th,
        mode=settings.get("fitMode", "cover"),
        focus_x=float(settings.get("focusX", 0.5)),
        focus_y=float(settings.get("focusY", 0.5)),
        zoom=float(settings.get("zoom", 1.0)),
    )
    comic = stage1_comic(fitted, style_id)
    img = stage2_epaper(
        comic,
        output="device",
        dither_strength=dither_strength,
        algorithm=dither_algo,
        distance_mode=color_distance,
        skin_warmth=skin_warmth,
        brightness=brightness,
        contrast=contrast,
        style_id=style_id,
        grayscale=grayscale,
        warmth=float(warmth) if warmth is not None else None,
        skin_tint=float(skin_tint) if skin_tint is not None else None,
    )

    out = export_bmp(
        img,
        PIC_DIR,
        filename,
        portrait=is_portrait,
        overwrite=bool(settings.get("overwrite")),
    )
    # Comic bleibt nur im Speicher der UI — pic/ nur BMP + Settings
    for suffix in ("_stufe1_comic.png", "_comic.png", "_epaper_preview.png", "_preview.png"):
        leftover = PIC_DIR / f"{out.stem}{suffix}"
        leftover.unlink(missing_ok=True)

    meta_path = PIC_DIR / f"{out.stem}_settings.json"
    meta_path.write_text(
        json.dumps(
            {
                "source": settings.get("source"),
                "settings": {
                    "brightness": brightness,
                    "contrast": contrast,
                    "warmth": warmth,
                    "skin_tint": skin_tint,
                    "dither_strength": dither_strength,
                    "algorithm": dither_algo,
                    "color_distance": color_distance,
                    "style_id": style_id,
                    "focus_x": float(settings.get("focusX", 0.5)),
                    "focus_y": float(settings.get("focusY", 0.5)),
                    "zoom": float(settings.get("zoom", 1.0)),
                    "grayscale": grayscale,
                    "portrait": is_portrait,
                    "orientation": "portrait" if is_portrait else "landscape",
                },
                "bmp": out.name,
                "size": [tw, th],
                "orientation": "portrait" if is_portrait else "landscape",
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    return JSONResponse(
        {
            "ok": True,
            "path": str(out),
            "name": out.name,
            "url": f"/pic/{out.name}",
            "size": [tw, th],
            "portrait": is_portrait,
            "orientation": "portrait" if is_portrait else "landscape",
            "colors": COLORS,
            "styleId": style_id,
        }
    )


@app.post("/api/export-comic")
async def export_comic_endpoint(
    file: UploadFile = File(...),
    meta_json: str = Form("{}"),
) -> JSONResponse:
    """Stufe-2-Export aus vorhandenem Comic (ohne Stil neu zu rechnen)."""
    try:
        settings = json.loads(meta_json or "{}")
    except json.JSONDecodeError as exc:
        raise HTTPException(400, f"meta_json invalid: {exc}") from exc

    raw = await file.read()
    try:
        comic = _open_image(raw)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, f"Comic unreadable: {exc}") from exc

    filename = settings.get("filename") or settings.get("overwriteName") or "portrait"
    style_id = settings.get("styleId", "auto")
    dither_strength = float(settings.get("ditherStrength", 1.0))
    dither_algo = settings.get("ditherAlgo", "atkinson")
    color_distance = settings.get("colorDistance", settings.get("color_distance", "toon"))
    skin_warmth = float(settings.get("skinWarmth", 0.5))
    warmth = settings.get("warmth")
    skin_tint = settings.get("skinTint")
    brightness = float(settings.get("brightness", 1.0))
    contrast = float(settings.get("contrast", 1.0))
    grayscale = bool(settings.get("grayscale", False))
    overwrite = bool(settings.get("overwrite", True))
    # Comic-Abmessungen oder explizites Flag → Orientation
    cw, ch = comic.size
    default_portrait = cw <= ch
    is_portrait = _is_portrait_flag(
        settings.get("portrait", settings.get("orientation")),
        default=default_portrait,
    )
    tw, th = _canvas_size(portrait=is_portrait)
    if comic.size != (tw, th):
        comic = comic.resize((tw, th), Image.Resampling.LANCZOS)

    img = stage2_epaper(
        comic,
        output="device",
        dither_strength=dither_strength,
        algorithm=dither_algo,
        distance_mode=color_distance,
        skin_warmth=skin_warmth,
        brightness=brightness,
        contrast=contrast,
        style_id=style_id,
        grayscale=grayscale,
        warmth=float(warmth) if warmth is not None else None,
        skin_tint=float(skin_tint) if skin_tint is not None else None,
    )

    out = export_bmp(img, PIC_DIR, filename, portrait=is_portrait, overwrite=overwrite)
    for suffix in ("_stufe1_comic.png", "_comic.png", "_epaper_preview.png", "_preview.png"):
        leftover = PIC_DIR / f"{out.stem}{suffix}"
        leftover.unlink(missing_ok=True)
    meta_path = PIC_DIR / f"{out.stem}_settings.json"
    meta_path.write_text(
        json.dumps(
            {
                "source": settings.get("source"),
                "settings": {
                    "brightness": brightness,
                    "contrast": contrast,
                    "warmth": warmth,
                    "skin_tint": skin_tint,
                    "dither_strength": dither_strength,
                    "algorithm": dither_algo,
                    "color_distance": color_distance,
                    "style_id": style_id,
                    "focus_x": float(settings.get("focusX", settings.get("focus_x", 0.5))),
                    "focus_y": float(settings.get("focusY", settings.get("focus_y", 0.5))),
                    "zoom": float(settings.get("zoom", 1.0)),
                    "grayscale": grayscale,
                    "portrait": is_portrait,
                    "orientation": "portrait" if is_portrait else "landscape",
                },
                "bmp": out.name,
                "size": [tw, th],
                "orientation": "portrait" if is_portrait else "landscape",
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return JSONResponse(
        {
            "ok": True,
            "path": str(out),
            "name": out.name,
            "url": f"/pic/{out.name}",
            "size": [tw, th],
            "portrait": is_portrait,
            "orientation": "portrait" if is_portrait else "landscape",
            "colors": COLORS,
            "styleId": style_id,
        }
    )


@app.post("/api/autotune")
async def autotune_endpoint(
    style_id: str = Form("auto"),
    limit: int = Form(50),
) -> JSONResponse:
    """Lädt original/, sucht optimale E6-Settings, speichert BMP+Settings in pic/."""
    from epaper.autotune import run_autotune

    try:
        items = run_autotune(
            style_id=style_id or "auto",
            limit=limit if limit and limit > 0 else 50,
            skip_done=True,
            min_aspect=1.05,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, f"Auto-Tune failed: {exc}") from exc
    return JSONResponse(
        {
            "ok": True,
            "count": len(items),
            "styleId": style_id or "auto",
            "items": items,
        }
    )


def _intensive_snapshot(job: dict) -> dict:
    """Status-Payload für Polling (ohne große Bilder, außer status=done)."""
    out = {
        "ok": True,
        "jobId": job["id"],
        "status": job["status"],
        "phase": job.get("phase"),
        "current": job.get("current", 0),
        "total": job.get("total", 0),
        "message": job.get("message") or "",
        "startedAt": job.get("startedAt"),
        "elapsedSec": round(time.time() - job["startedAt"], 1)
        if job.get("startedAt")
        else None,
        "error": job.get("error"),
        "busy": job["status"] == "running",
    }
    if job["status"] == "done" and job.get("result"):
        out["result"] = job["result"]
        # elapsed aus Worker bevorzugen
        if job["result"].get("elapsedSec") is not None:
            out["elapsedSec"] = job["result"]["elapsedSec"]
    return out


def _intensive_set_progress(
    job_id: str, phase: str, current: int, total: int, message: str
) -> None:
    with _intensive_lock:
        job = _intensive_job
        if not job or job["id"] != job_id or job["status"] != "running":
            return
        job["phase"] = phase
        job["current"] = int(current)
        job["total"] = int(total)
        job["message"] = message


def _intensive_worker(
    job_id: str,
    fitted: Image.Image,
    *,
    focus_x: float,
    focus_y: float,
    zoom: float,
    quick: bool,
    tw: int,
    th: int,
    is_portrait: bool,
) -> None:
    from epaper.autotune import intensive_tune

    def _progress(phase: str, current: int, total: int, message: str) -> None:
        _intensive_set_progress(job_id, phase, current, total, message)

    try:
        result = intensive_tune(
            fitted,
            focus_x=focus_x,
            focus_y=focus_y,
            zoom=zoom,
            quick=quick,
            progress=_progress,
            cancel_check=_intensive_cancel.is_set,
        )
        payload = {
            "ok": True,
            "settings": result["settings"],
            "score": result["score"],
            "styleId": result["styleId"],
            "comic": _png_b64(result["comic"]),
            "epaper": _png_b64(result["epaper"]),
            "skinMaskUsed": result["skinMaskUsed"],
            "elapsedSec": result["elapsedSec"],
            "stylesTried": result.get("stylesTried"),
            "topStyles": result.get("topStyles"),
            "quick": result.get("quick", False),
            "size": [tw, th],
            "portrait": is_portrait,
            "orientation": "portrait" if is_portrait else "landscape",
            "focusX": focus_x,
            "focusY": focus_y,
            "zoom": zoom,
        }
        with _intensive_lock:
            job = _intensive_job
            if job and job["id"] == job_id:
                job["status"] = "done"
                job["phase"] = "done"
                job["message"] = "Done"
                job["current"] = job.get("total") or 1
                job["result"] = payload
                job["error"] = None
    except RuntimeError as exc:
        cancelled = "cancelled" in str(exc).lower() or "abgebrochen" in str(exc).lower() or _intensive_cancel.is_set()
        with _intensive_lock:
            job = _intensive_job
            if job and job["id"] == job_id:
                job["status"] = "cancelled" if cancelled else "error"
                job["message"] = (
                    "Intensive search cancelled"
                    if cancelled
                    else f"Intensive search failed: {exc}"
                )
                job["error"] = None if cancelled else str(exc)
                job["result"] = None
    except Exception as exc:  # noqa: BLE001
        with _intensive_lock:
            job = _intensive_job
            if job and job["id"] == job_id:
                job["status"] = "error"
                job["message"] = f"Intensive search failed: {exc}"
                job["error"] = str(exc)
                job["result"] = None


@app.post("/api/autotune-one/cancel")
async def autotune_one_cancel() -> JSONResponse:
    """Aktive Intensiv-Suche kooperativ abbrechen (nur explizit — kein Disconnect)."""
    _intensive_cancel.set()
    with _intensive_lock:
        busy = bool(_intensive_job and _intensive_job["status"] == "running")
        job_id = _intensive_job["id"] if _intensive_job else None
        if _intensive_job and _intensive_job["status"] == "running":
            _intensive_job["message"] = "Cancel requested…"
    return JSONResponse(
        {
            "ok": True,
            "cancelled": True,
            "busy": busy,
            "jobId": job_id,
        }
    )


@app.get("/api/autotune-one/status")
async def autotune_one_status(job_id: str | None = None) -> JSONResponse:
    """Fortschritt / Ergebnis der Intensiv-Suche (Polling)."""
    with _intensive_lock:
        job = _intensive_job
        if not job:
            return JSONResponse(
                {
                    "ok": True,
                    "status": "idle",
                    "busy": False,
                    "message": "No job",
                }
            )
        if job_id and job["id"] != job_id:
            raise HTTPException(404, "Unknown job ID (other/older run)")
        return JSONResponse(_intensive_snapshot(job))


@app.post("/api/autotune-one")
async def autotune_one_endpoint(
    file: UploadFile = File(...),
    focus_x: float = Form(0.5),
    focus_y: float = Form(0.5),
    zoom: float = Form(1.0),
    portrait: str = Form("1"),
    quick: str = Form("0"),
) -> JSONResponse:
    """Intensiv-Suche starten → jobId; Client pollt /api/autotune-one/status."""
    global _intensive_job

    with _intensive_lock:
        if _intensive_job and _intensive_job["status"] == "running":
            raise HTTPException(
                409,
                "Intensive search already running — cancel or wait",
            )

    raw = await file.read()
    try:
        src = _open_image(raw)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, f"Image unreadable: {exc}") from exc

    is_portrait = _is_portrait_flag(portrait, default=True)
    tw, th = _canvas_size(portrait=is_portrait)
    fitted = fit_portrait(
        src,
        tw,
        th,
        mode="cover",
        focus_x=focus_x,
        focus_y=focus_y,
        zoom=zoom,
    )

    job_id = uuid.uuid4().hex
    job = {
        "id": job_id,
        "status": "running",
        "phase": "start",
        "current": 0,
        "total": 0,
        "message": "Starting intensive search…",
        "startedAt": time.time(),
        "error": None,
        "result": None,
    }
    with _intensive_lock:
        _intensive_cancel.clear()
        _intensive_job = job

    threading.Thread(
        target=_intensive_worker,
        args=(job_id, fitted),
        kwargs={
            "focus_x": focus_x,
            "focus_y": focus_y,
            "zoom": zoom,
            "quick": _truthy(quick),
            "tw": tw,
            "th": th,
            "is_portrait": is_portrait,
        },
        name=f"intensive-{job_id[:8]}",
        daemon=True,
    ).start()

    return JSONResponse(
        {
            "ok": True,
            "jobId": job_id,
            "status": "running",
            "message": job["message"],
        }
    )


app.mount("/pic", StaticFiles(directory=str(PIC_DIR)), name="pic")
app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")


def _already_running(url: str) -> bool:
    try:
        from urllib.request import urlopen

        with urlopen(f"{url}/api/meta", timeout=0.8) as resp:
            body = resp.read().decode("utf-8", errors="ignore")
            return '"colors": 6' in body
    except Exception:  # noqa: BLE001
        return False


def _free_port(port: int) -> None:
    """Kill whatever listens on port (Windows). DE-Locale: ABHÖREN ≠ LISTENING."""
    if os.name != "nt":
        return
    try:
        import subprocess

        out = subprocess.check_output(["netstat", "-ano"], text=True, errors="ignore")
    except Exception:  # noqa: BLE001
        return
    for line in out.splitlines():
        if f":{port}" not in line:
            continue
        low = line.lower()
        # EN LISTENING / DE ABHÖREN (auch als abh?ren bei kaputtem Encoding)
        if "listen" not in low and "abh" not in low:
            continue
        if "127.0.0.1" not in line and "0.0.0.0" not in line:
            continue
        parts = line.split()
        if len(parts) < 5:
            continue
        try:
            pid = int(parts[-1])
        except ValueError:
            continue
        if pid <= 0:
            continue
        try:
            subprocess.run(["taskkill", "/PID", str(pid), "/F"], check=False, capture_output=True)
            print(f"Port {port}: stopped old process PID {pid}.")
        except Exception:  # noqa: BLE001
            pass


def _port_listening(port: int) -> bool:
    """True wenn bereits etwas auf port lauscht (vor _free_port)."""
    if os.name != "nt":
        return False
    try:
        import subprocess

        out = subprocess.check_output(["netstat", "-ano"], text=True, errors="ignore")
    except Exception:  # noqa: BLE001
        return False
    for line in out.splitlines():
        if f":{port}" not in line:
            continue
        low = line.lower()
        if "listen" not in low and "abh" not in low:
            continue
        if "127.0.0.1" not in line and "0.0.0.0" not in line:
            continue
        return True
    return False


def _touch_open_marker() -> None:
    marker = ROOT / ".portrait_lab_open.lock"
    try:
        marker.write_text(f"{time.time()}\nv{APP_VERSION}\n", encoding="utf-8")
    except OSError:
        pass


def _recent_open_marker(*, max_age_s: float = 180.0) -> bool:
    """True wenn kürzlich schon ein Lab-Start den Marker gesetzt hat."""
    marker = ROOT / ".portrait_lab_open.lock"
    try:
        return (time.time() - marker.stat().st_mtime) < max_age_s
    except OSError:
        return False


def _should_open_browser(*, was_running: bool) -> bool:
    """Browser nur bei kaltem Erststart öffnen — nicht bei Neustarts.

    - Port schon belegt (was_running): nie öffnen — sonst lädt der bestehende
      Tab (/?v=…) neu und löscht die Zuschnitt-Session.
    - PORTRAIT_LAB_OPEN_BROWSER=1 (start.bat): öffnen, sofern nicht was_running.
    - PORTRAIT_LAB_OPEN_BROWSER=0: nie öffnen (Agents/Neustarts).
    - Ohne Flag (python server.py): Marker < 3 Min → unterdrücken; sonst öffnen.
    """
    flag = os.environ.get("PORTRAIT_LAB_OPEN_BROWSER", "").strip().lower()
    if flag in {"0", "false", "no"}:
        _touch_open_marker()
        return False
    # Bestehende Lab-Instanz → Tab nicht force-reloaden
    if was_running:
        _touch_open_marker()
        return False
    if flag in {"1", "true", "yes"}:
        _touch_open_marker()
        return True

    # Default: konservativ — frischer Marker = Neustart (Port oft schon freigegeben)
    recent = _recent_open_marker()
    _touch_open_marker()
    return not recent


def main() -> None:
    import uvicorn

    url = "http://127.0.0.1:8765"
    # Vor _free_port prüfen: läuft schon etwas → Neustart, kein Browser-Reload
    was_running = _port_listening(8765) or _already_running(url)
    open_browser = _should_open_browser(was_running=was_running)
    # Immer neu starten — alter Prozess liefert sonst veraltetes JS/API
    _free_port(8765)
    time.sleep(0.4)
    try:
        from epaper.animegan import ensure_model

        ensure_model("hayao")
    except Exception as exc:  # noqa: BLE001
        print(f"Model note: {exc}")
    print(f"Portrait Lab v{APP_VERSION} -> {url}", flush=True)
    print(f"Stage 1: Style AI | Stage 2: E6 {COLORS} colors | {PIC_DIR}", flush=True)
    if open_browser:
        print("Opening browser …", flush=True)
        threading.Timer(1.0, lambda: webbrowser.open(f"{url}/?v={APP_VERSION}")).start()
    else:
        print("Restart — browser tab kept (no auto-reload of session).", flush=True)
    uvicorn.run(app, host="127.0.0.1", port=8765, log_level="info")


if __name__ == "__main__":
    main()
