"""Auto-Tune: Originale laden, E6-Parameter suchen, fertige BMPs nach pic/.

Batch: ``run_autotune`` → pic/
Einzelbild Intensiv-Suche: ``intensive_tune`` (kein Disk-Schreiben).
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Sequence

from PIL import Image, ImageOps

from .adjust import fit_portrait
from .export import PORTRAIT_SIZE, export_bmp
from .paths import ORIGINAL_DIR, PIC_DIR
from .styles import INTENSIVE_STYLE_IDS, stage1_comic, stage2_epaper


def _open_oriented(path: Path) -> Image.Image:
    """JPEG laden und EXIF-Orientation in Pixel backen (Canon oft Tag 6)."""
    im = Image.open(path)
    im.load()
    try:
        im = ImageOps.exif_transpose(im)
    except Exception:  # noqa: BLE001
        pass
    return im.convert("RGB")

# Spectra-6 perceived (Nähe) für Scoring
_GREEN = (53, 86, 58)
_RED = (150, 68, 58)
_YELLOW = (205, 180, 55)
_WHITE = (205, 200, 195)
_BLACK = (31, 34, 38)
_BLUE = (78, 112, 178)


@dataclass
class TuneSettings:
    brightness: float = 1.0
    contrast: float = 1.0
    warmth: float = 0.0
    skin_tint: float = -0.25
    dither_strength: float = 1.0
    algorithm: str = "atkinson"
    color_distance: str = "toon"  # toon (Default) | lab (CIE76) — Phase B sucht beides
    style_id: str = "auto"
    focus_x: float = 0.5
    focus_y: float = 0.5
    zoom: float = 1.0


def _nearest_label(rgb: tuple[int, int, int]) -> str:
    cands = {
        "K": _BLACK,
        "W": _WHITE,
        "G": _GREEN,
        "B": _BLUE,
        "R": _RED,
        "Y": _YELLOW,
    }
    best, best_d = "K", 1e18
    r, g, b = rgb
    for name, (pr, pg, pb) in cands.items():
        d = (r - pr) ** 2 + (g - pg) ** 2 + (b - pb) ** 2
        if d < best_d:
            best, best_d = name, d
    return best


def score_epaper(
    comic: Image.Image,
    epaper: Image.Image,
    step: int = 4,
    skin_mask=None,
) -> float:
    """Semantischer Score: Neutral/Ochre/Haut/Blau-Gates.

    ``skin_mask``: optionale Bool-Maske in Comic-Auflösung (BiSeNet).
    Gewichtet Peach (W/Y) in der Haut-ROI und bestraft Grün + starkes Rot-Stipple.
    Fehlt die Maske → bestehende Farb-Heuristik (warm_skin).
    """
    import numpy as np

    c = comic.convert("RGB").resize(
        (max(1, comic.width // step), max(1, comic.height // step)),
        Image.Resampling.BILINEAR,
    )
    e = epaper.convert("RGB").resize(c.size, Image.Resampling.NEAREST)
    mask_s = None
    if skin_mask is not None:
        try:
            m = np.asarray(skin_mask, dtype=bool)
            if m.shape[:2] == (comic.height, comic.width):
                mask_img = Image.fromarray(m.astype(np.uint8) * 255, mode="L")
            else:
                mask_img = Image.fromarray(
                    (m.astype(np.uint8) * 255), mode="L"
                ).resize((comic.width, comic.height), Image.Resampling.NEAREST)
            mask_s = np.asarray(
                mask_img.resize(c.size, Image.Resampling.NEAREST), dtype=np.uint8
            ) > 127
            if not bool(mask_s.any()):
                mask_s = None
        except Exception:  # noqa: BLE001
            mask_s = None

    cp, ep = c.load(), e.load()
    w, h = c.size
    score = 0.0
    n_skin = n_green_skin = n_red_skin = n_peach_skin = 0
    n_ochre = n_red_ochre = 0
    n_neutral = n_green_neutral = 0
    n_blue = n_blue_hit = 0
    n_roi = n_roi_green = n_roi_red = n_roi_peach = 0
    for y in range(h):
        for x in range(w):
            r, g, b = cp[x, y]
            luma = 0.299 * r + 0.587 * g + 0.114 * b
            chroma = max(r, g, b) - min(r, g, b)
            chroma_y = min(r, g) - b
            ochre = chroma_y > 28 and abs(r - g) < 55 and luma > 55
            blueish = (b > r + 12 and b > g + 6 and chroma > 22) or (
                luma > 130 and b > r + 4 and b >= g - 4 and chroma > 10
            )
            neutral = chroma < 26 and 25 < luma < 170 and not ochre and not blueish
            warm_skin = (
                r > b + 8 and r >= g - 5 and 40 < luma < 220 and not ochre and not blueish
            )
            in_roi = bool(mask_s is not None and mask_s[y, x])
            lab = _nearest_label(ep[x, y])
            if in_roi:
                n_roi += 1
                if lab == "G":
                    score -= 5.5
                    n_roi_green += 1
                elif lab == "R":
                    score -= 1.8  # schweres Rot-Stipple in Haut
                    n_roi_red += 1
                elif lab == "Y":
                    score += 2.4  # Peach
                    n_roi_peach += 1
                elif lab == "W":
                    score += 1.8
                    n_roi_peach += 1
                elif lab == "B":
                    score -= 1.4
                elif lab == "K":
                    score += 0.15
            if ochre:
                n_ochre += 1
                if lab == "R":
                    score -= 3.5
                    n_red_ochre += 1
                elif lab == "Y":
                    score += 1.8
                elif lab == "W":
                    score += 0.7
                elif lab == "G":
                    score -= 0.8
            elif blueish:
                n_blue += 1
                if lab == "B":
                    score += 2.2
                    n_blue_hit += 1
                elif lab == "W":
                    # Pastell-Himmel darf Weiss mischen, aber nicht nur Weiss
                    score += 0.15 if luma > 150 else 0.4
                elif lab == "G":
                    score -= 1.5
                elif lab == "R":
                    score -= 1.2
                elif lab == "Y":
                    score -= 0.8
            elif neutral:
                n_neutral += 1
                if lab == "G":
                    score -= 3.0
                    n_green_neutral += 1
                elif lab == "K":
                    score += 0.6
                elif lab == "W":
                    score += 0.5
                elif lab == "R":
                    score -= 0.6
            elif warm_skin and not in_roi:
                n_skin += 1
                if lab == "G":
                    score -= 4.0
                    n_green_skin += 1
                elif lab == "R":
                    score += 0.35  # weniger Rosa-Stipple belohnen
                    n_red_skin += 1
                elif lab == "W":
                    score += 1.2
                    n_peach_skin += 1
                elif lab == "Y":
                    score += 0.85  # Peach
                    n_peach_skin += 1
                elif lab == "B":
                    score -= 1.0
                elif lab == "K":
                    score += 0.2
            elif not in_roi:
                if lab == "G" and r > g:
                    score -= 0.4
    if n_skin:
        score -= 2.0 * (n_green_skin / n_skin)
    if n_roi:
        score -= 3.0 * (n_roi_green / n_roi)
        score -= 1.2 * (n_roi_red / n_roi)
        score += 2.0 * (n_roi_peach / n_roi)
    if n_ochre:
        score -= 3.0 * (n_red_ochre / n_ochre)
    if n_neutral:
        score -= 2.5 * (n_green_neutral / n_neutral)
    if n_blue:
        score += 1.5 * (n_blue_hit / n_blue)

    arr = np.asarray(e, dtype=np.float32)
    lum = 0.299 * arr[:, :, 0] + 0.587 * arr[:, :, 1] + 0.114 * arr[:, :, 2]
    # leichter Kontrast, aber Crush bestrafen
    k_frac = float((lum < 40).mean())
    score += min(6.0, float(lum.std()) / 14.0)
    if k_frac > 0.72:
        score -= 6.0 * (k_frac - 0.72)
    return score


def _grid() -> list[TuneSettings]:
    """Eng um die Mitte — keine Extrem-Rosa/Kontrast-Autotune."""
    out: list[TuneSettings] = []
    for brightness in (0.95, 1.02):
        for contrast in (0.92, 1.0):
            for warmth in (-0.1, 0.05, 0.2):
                for skin_tint in (-0.15, 0.05, 0.25):
                    out.append(
                        TuneSettings(
                            brightness=brightness,
                            contrast=contrast,
                            warmth=warmth,
                            skin_tint=skin_tint,
                            dither_strength=0.95,
                        )
                    )
    return out


def _coarse_grid(*, quick: bool = False) -> list[TuneSettings]:
    """Phase A — Tonwerte, festes Dither."""
    out: list[TuneSettings] = []
    if quick:
        brights = (0.95, 1.05)
        contrasts = (0.95,)
        warmths = (-0.1, 0.15)
        tints = (0.05,)
    else:
        brights = (0.9, 1.0, 1.1)
        contrasts = (0.88, 1.0, 1.1)
        warmths = (-0.2, 0.0, 0.2)
        tints = (-0.25, 0.0, 0.25)
    for brightness in brights:
        for contrast in contrasts:
            for warmth in warmths:
                for skin_tint in tints:
                    out.append(
                        TuneSettings(
                            brightness=brightness,
                            contrast=contrast,
                            warmth=warmth,
                            skin_tint=skin_tint,
                            dither_strength=0.95,
                            algorithm="atkinson",
                        )
                    )
    return out


def _dense_grid(base: TuneSettings, *, quick: bool = False) -> list[TuneSettings]:
    """Phase B — um den Winner, inkl. Dither-Stärke, Algorithmus und Farbabstand.

    Choice: Phase A bleibt toon+atkinson (schnell, kompatibel).
    Phase B sucht algorithm ∈ {atkinson, floyd, bluenoise} und
    color_distance ∈ {toon, lab} (quick: nur toon).
    """
    out: list[TuneSettings] = []
    if quick:
        brights = (base.brightness,)
        contrasts = (base.contrast,)
        warmths = (base.warmth, base.warmth + 0.1)
        tints = (base.skin_tint,)
        strengths = (0.85, 1.0)
        algos = ("atkinson", "floyd", "bluenoise")
        distances = ("toon",)
    else:
        brights = (
            round(base.brightness - 0.05, 3),
            base.brightness,
            round(base.brightness + 0.05, 3),
        )
        contrasts = (
            round(base.contrast - 0.06, 3),
            base.contrast,
            round(base.contrast + 0.06, 3),
        )
        warmths = (
            round(base.warmth - 0.1, 3),
            base.warmth,
            round(base.warmth + 0.1, 3),
        )
        tints = (
            round(base.skin_tint - 0.12, 3),
            base.skin_tint,
            round(base.skin_tint + 0.12, 3),
        )
        strengths = (0.75, 0.9, 1.0)
        algos = ("atkinson", "floyd", "bluenoise")
        distances = ("toon", "lab")
    for brightness in brights:
        for contrast in contrasts:
            for warmth in warmths:
                for skin_tint in tints:
                    for dither_strength in strengths:
                        for algorithm in algos:
                            for color_distance in distances:
                                out.append(
                                    TuneSettings(
                                        brightness=max(0.5, min(1.5, brightness)),
                                        contrast=max(0.5, min(1.5, contrast)),
                                        warmth=max(-1.0, min(1.0, warmth)),
                                        skin_tint=max(-1.0, min(1.0, skin_tint)),
                                        dither_strength=dither_strength,
                                        algorithm=algorithm,
                                        color_distance=color_distance,
                                        style_id=base.style_id,
                                        focus_x=base.focus_x,
                                        focus_y=base.focus_y,
                                        zoom=base.zoom,
                                    )
                                )
    return out


def _eval_candidate(
    small: Image.Image,
    cand: TuneSettings,
    *,
    style_id: str,
    skin_mask_small=None,
) -> float:
    ep = stage2_epaper(
        small,
        output="perceived",
        dither_strength=cand.dither_strength,
        algorithm=cand.algorithm,
        distance_mode=cand.color_distance,
        brightness=cand.brightness,
        contrast=cand.contrast,
        style_id=style_id,
        warmth=cand.warmth,
        skin_tint=cand.skin_tint,
    )
    return score_epaper(small, ep, step=2, skin_mask=skin_mask_small)


def _resize_mask(mask, size: tuple[int, int]):
    import numpy as np

    if mask is None:
        return None
    m = np.asarray(mask, dtype=bool)
    if m.shape[:2] == (size[1], size[0]):
        return m
    img = Image.fromarray(m.astype(np.uint8) * 255, mode="L")
    return np.asarray(img.resize(size, Image.Resampling.NEAREST), dtype=np.uint8) > 127


def tune_comic(
    comic: Image.Image,
    *,
    style_id: str = "auto",
    preview_scale: float = 0.4,
    skin_mask=None,
) -> tuple[TuneSettings, float, Image.Image]:
    """Sucht beste Stufe-2-Settings für ein Comic-Bild."""
    pw = max(120, int(comic.width * preview_scale))
    ph = max(200, int(comic.height * preview_scale))
    small = comic.resize((pw, ph), Image.Resampling.LANCZOS)
    mask_small = _resize_mask(skin_mask, (pw, ph))
    best: TuneSettings | None = None
    best_score = -1e18
    for cand in _grid():
        cand.style_id = style_id
        s = _eval_candidate(
            small, cand, style_id=style_id, skin_mask_small=mask_small
        )
        if s > best_score:
            best_score = s
            best = cand
    assert best is not None
    full = stage2_epaper(
        comic,
        output="device",
        dither_strength=best.dither_strength,
        algorithm=best.algorithm,
        distance_mode=best.color_distance,
        brightness=best.brightness,
        contrast=best.contrast,
        style_id=style_id,
        warmth=best.warmth,
        skin_tint=best.skin_tint,
    )
    return best, best_score, full


def intensive_tune(
    fitted: Image.Image,
    *,
    style_ids: Sequence[str] | None = None,
    focus_x: float = 0.5,
    focus_y: float = 0.5,
    zoom: float = 1.0,
    quick: bool = False,
    progress: Callable[..., None] | None = None,
    cancel_check: Callable[[], bool] | None = None,
) -> dict:
    """Zwei-Phasen Intensiv-Suche für ein zugeschnittenes RGB-Bild.

    Speichert nichts auf Disk. BiSeNet-Hautmaske einmal pro Suche;
    Fallback auf Farb-Heuristik wenn Modell fehlt oder Maske leer.
    """
    from .faceparse import skin_mask_from_rgb

    t0 = time.time()
    ids = list(style_ids) if style_ids else list(INTENSIVE_STYLE_IDS)
    if quick:
        ids = ids[:2]

    def _cancelled() -> bool:
        return bool(cancel_check and cancel_check())

    def _prog(phase: str, current: int, total: int, message: str) -> None:
        if progress:
            progress(phase, current, total, message)

    if _cancelled():
        raise RuntimeError("cancelled")

    _prog("skin", 0, 1, "Skin mask…")
    skin_mask = skin_mask_from_rgb(fitted, download=True)
    skin_used = skin_mask is not None
    _prog(
        "skin",
        1,
        1,
        "Skin mask ready" if skin_used else "No skin mask (color heuristic)",
    )

    comics: dict[str, Image.Image] = {}
    style_best: dict[str, tuple[TuneSettings, float]] = {}

    coarse = _coarse_grid(quick=quick)
    total_a = len(ids) * (1 + len(coarse))  # stil + kandidaten
    done_a = 0

    for sid in ids:
        if _cancelled():
            raise RuntimeError("cancelled")
        _prog("A", done_a, total_a, f"Style {sid}…")
        comics[sid] = stage1_comic(fitted, sid)
        done_a += 1
        comic = comics[sid]
        pw = max(100, int(comic.width * (0.28 if quick else 0.35)))
        ph = max(160, int(comic.height * (0.28 if quick else 0.35)))
        small = comic.resize((pw, ph), Image.Resampling.LANCZOS)
        mask_small = _resize_mask(skin_mask, (pw, ph))
        best_s: TuneSettings | None = None
        best_score = -1e18
        for cand in coarse:
            if _cancelled():
                raise RuntimeError("cancelled")
            cand = TuneSettings(
                brightness=cand.brightness,
                contrast=cand.contrast,
                warmth=cand.warmth,
                skin_tint=cand.skin_tint,
                dither_strength=cand.dither_strength,
                algorithm=cand.algorithm,
                color_distance=cand.color_distance,
                style_id=sid,
                focus_x=focus_x,
                focus_y=focus_y,
                zoom=zoom,
            )
            s = _eval_candidate(
                small, cand, style_id=sid, skin_mask_small=mask_small
            )
            if s > best_score:
                best_score = s
                best_s = cand
            done_a += 1
            if done_a % 4 == 0 or done_a == total_a:
                _prog("A", done_a, total_a, f"Phase A · {sid}")
        assert best_s is not None
        style_best[sid] = (best_s, best_score)

    ranked = sorted(style_best.items(), key=lambda kv: kv[1][1], reverse=True)
    top_n = 1 if quick else 2
    top = ranked[:top_n]

    # Phase B
    phase_b_jobs: list[tuple[str, TuneSettings, Image.Image]] = []
    for sid, (base, _) in top:
        for cand in _dense_grid(base, quick=quick):
            cand.style_id = sid
            cand.focus_x = focus_x
            cand.focus_y = focus_y
            cand.zoom = zoom
            phase_b_jobs.append((sid, cand, comics[sid]))

    total_b = len(phase_b_jobs)
    best: TuneSettings | None = None
    best_score = -1e18
    best_sid = top[0][0]
    small = None
    mask_small = None
    last_sid: str | None = None
    for i, (sid, cand, comic) in enumerate(phase_b_jobs):
        if _cancelled():
            raise RuntimeError("cancelled")
        if sid != last_sid:
            pw = max(120, int(comic.width * (0.35 if quick else 0.45)))
            ph = max(200, int(comic.height * (0.35 if quick else 0.45)))
            small = comic.resize((pw, ph), Image.Resampling.LANCZOS)
            mask_small = _resize_mask(skin_mask, (pw, ph))
            last_sid = sid
        assert small is not None
        s = _eval_candidate(small, cand, style_id=sid, skin_mask_small=mask_small)
        if s > best_score:
            best_score = s
            best = cand
            best_sid = sid
        if i % 6 == 0 or i + 1 == total_b:
            _prog("B", i + 1, total_b, f"Phase B · {sid}")

    assert best is not None
    best.style_id = best_sid
    best.focus_x = focus_x
    best.focus_y = focus_y
    best.zoom = zoom

    _prog("final", 0, 1, "Full resolution…")
    if _cancelled():
        raise RuntimeError("cancelled")
    comic_full = comics[best_sid]
    epaper_full = stage2_epaper(
        comic_full,
        output="perceived",
        dither_strength=best.dither_strength,
        algorithm=best.algorithm,
        distance_mode=best.color_distance,
        brightness=best.brightness,
        contrast=best.contrast,
        style_id=best_sid,
        warmth=best.warmth,
        skin_tint=best.skin_tint,
    )
    _prog("final", 1, 1, "Done")

    return {
        "settings": asdict(best),
        "score": round(float(best_score), 3),
        "styleId": best_sid,
        "comic": comic_full,
        "epaper": epaper_full,
        "skinMaskUsed": skin_used,
        "elapsedSec": round(time.time() - t0, 1),
        "stylesTried": ids,
        "topStyles": [s for s, _ in top],
        "quick": quick,
    }


def list_originals(
    *,
    min_w: int = 480,
    min_h: int = 800,
    min_aspect: float = 1.05,
    prefer: list[str] | None = None,
) -> list[Path]:
    """Portrait-taugliche Originale (ohne Upscale für 480×800)."""
    if prefer is None:
        prefer = [
            "mona_lisa",
            "vermeer_pearl",
            "sargent_madame_x",
            "american_gothic",
            "van_gogh_self",
            "rembrandt_self",
            "davinci_ermine",
            "davinci_salvator",
            "davinci_ginevra",
            "frida_kahlo",
            "el_greco_cardinal",
            "velazquez_juan",
            "velazquez_infanta",
            "goya_don_manuel",
            "holbein_erasmus",
            "memling_young",
            "bronzzino",
            "modigliani",
            "munch_madonna",
            "munch_scream",
            "botticelli_simonetta",
            "titian_man",
            "titian_portrait",
            "raphael",
            "ingres",
            "hals_yonker",
            "otto_dix",
            "klimt",
            "whistler_mother",
            "copley",
            "gilbert_stuart",
            "caravaggio_boy",
            "caravaggio_medusa",
            "leonardo_musician",
            "parmigianino",
            "duccio",
            "giotto_madonna",
            "bellini_madonna",
            "vermeer_water",
            "vermeer_study",
            "rembrandt_aristotle",
            "david_lavoisier",
            "fragonard",
            "millet_shepherdess",
            "cezanne_uncle",
            "manet_boy",
            "rubens_venus",
            "bosch_adoration",
            "van_eyck",
            "greuze",
        ]
    exclude = (
        "maj_nude",
        "toilet_venus",
        "turner_fort",
        "christ_carrying",  # extreme strip crop
        "woman_parrot",
        "venus_adonis",
        "love_letter",  # genre scene
        "broken_eggs",
        "fresh_air",
        "thinker",
        "musicians",
        "corot_",
        "delacroix_orphan",
        "wyndham",
        "white_girl",  # landscape-ish crop
        "_fetch",
    )
    exts = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
    scored: list[tuple[float, Path]] = []
    for p in ORIGINAL_DIR.iterdir():
        if not p.is_file() or p.suffix.lower() not in exts:
            continue
        if p.name.startswith(".") or p.name.startswith("_"):
            continue
        low = p.name.lower()
        if any(x in low for x in exclude):
            continue
        try:
            im = _open_oriented(p)
            w, h = im.size
        except Exception:  # noqa: BLE001
            continue
        if w < min_w or h < min_h:
            continue
        aspect = h / max(1, w)
        if aspect < min_aspect:
            continue
        bonus = 0.0
        stem = p.stem.lower()
        for i, key in enumerate(prefer):
            if key in stem:
                bonus = 2000 - i * 10
                break
        scored.append((bonus + aspect, p))
    scored.sort(key=lambda t: (-t[0], t[1].name))
    return [p for _, p in scored]


def _out_stem(source: Path, style_id: str) -> str:
    stem = source.stem.replace("_original", "")
    # kurz halten (export truncated auf 48)
    base = f"{stem}_{style_id}_at"
    if len(base) > 48:
        base = f"{stem[: 48 - len(style_id) - 4]}_{style_id}_at"
    return base


def run_autotune(
    *,
    style_id: str = "auto",
    limit: int | None = 50,
    skip_done: bool = True,
    min_aspect: float = 1.0,
    progress=None,
) -> list[dict]:
    """Originale: Stil → Auto-Tune → BMP + JSON in pic/."""
    PIC_DIR.mkdir(exist_ok=True)
    files = list_originals(min_aspect=min_aspect)
    if limit is not None:
        files = files[: max(0, limit)]
    results: list[dict] = []
    t0 = time.time()
    total = len(files)
    for i, path in enumerate(files):
        base = _out_stem(path, style_id)
        meta_path = PIC_DIR / f"{base}_settings.json"
        bmp_path = PIC_DIR / f"{base}.bmp"
        if skip_done and meta_path.exists() and bmp_path.exists():
            if progress:
                progress(i, total, path.name, "skip")
            try:
                results.append(json.loads(meta_path.read_text(encoding="utf-8")))
            except Exception:  # noqa: BLE001
                pass
            continue
        if progress:
            progress(i, total, path.name, "style")
        src = _open_oriented(path)
        fitted = fit_portrait(
            src,
            PORTRAIT_SIZE[0],
            PORTRAIT_SIZE[1],
            mode="cover",
            # Batch ohne UI: leichter Portrait-Bias (Gesicht oft im oberen Drittel)
            focus_x=0.5,
            focus_y=0.35,
            zoom=1.0,
        )
        comic = stage1_comic(fitted, style_id)
        if progress:
            progress(i, total, path.name, "tune")
        settings, score, epaper = tune_comic(comic, style_id=style_id)
        # alte Versionen gleichen Stems überschreiben (inkl. Legacy-Comic-PNGs)
        for old in PIC_DIR.glob(f"{base}*"):
            if old.suffix.lower() in {".bmp", ".png", ".json"}:
                try:
                    old.unlink()
                except Exception:  # noqa: BLE001
                    pass
        out = export_bmp(epaper, PIC_DIR, base, portrait=True)
        meta = {
            "source": path.name,
            "score": round(score, 3),
            "settings": asdict(settings),
            "bmp": out.name,
        }
        meta_path = PIC_DIR / f"{out.stem}_settings.json"
        meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
        results.append(meta)
        if progress:
            progress(i, total, path.name, "done")
    elapsed = time.time() - t0
    summary = {
        "ok": True,
        "count": len(results),
        "elapsedSec": round(elapsed, 1),
        "styleId": style_id,
        "items": results,
    }
    # Summary nur stdout — kein tmp/-Ordner
    print(json.dumps({k: summary[k] for k in ("ok", "count", "elapsedSec", "styleId")}, indent=2), flush=True)
    return results


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="Portrait Lab Auto-Tune")
    ap.add_argument("--style", default="auto")
    ap.add_argument("--limit", type=int, default=50)
    ap.add_argument("--min-aspect", type=float, default=1.05)
    ap.add_argument("--force", action="store_true", help="Auch bestehende neu rechnen")
    args = ap.parse_args()

    def _p(i, n, name, phase):
        print(f"[{i + 1}/{n}] {name} - {phase}", flush=True)

    items = run_autotune(
        style_id=args.style,
        limit=args.limit,
        skip_done=not args.force,
        min_aspect=args.min_aspect,
        progress=_p,
    )
    print(f"Done: {len(items)} files -> {PIC_DIR}", flush=True)
