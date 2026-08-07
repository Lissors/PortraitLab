# Portrait Lab

**Local prep tool for Spectra 6 (E6) e-paper portraits.**

Portrait Lab turns a photo into a device-ready **24-bit BMP** for a **Waveshare ESP32-S3 PhotoPainter** (Amazon PhotoPainter E6 family): six inks only — black, white, green, blue, red, yellow. You style and crop on the PC; you copy the BMP to the TF/microSD card for the display.

> **Privacy & rights:** Do not commit private or modern copyrighted photos. Put your own images in `original/` locally. Model weights stay in `models/` (gitignored).  
> **Public-domain demo (Da Vinci):** [`original/mona_lisa.png`](original/mona_lisa.png) → [`pic/mona_lisa_auto_at.bmp`](pic/mona_lisa_auto_at.bmp) — Leonardo’s *Mona Lisa* is **public domain**; reproduction from Wikimedia Commons (PD). See [`original/mona_lisa.SOURCE.md`](original/mona_lisa.SOURCE.md).  
> **Synthetic demo (CC0):** [`examples/demo_portrait.png`](examples/demo_portrait.png) — not a real person ([`examples/LICENSE`](examples/LICENSE)).

**Deutsch:** [README.de.md](README.de.md)

---

## Why this exists

E-paper Spectra 6 is not a normal RGB screen. It can only show **six solid colors**. Photos look muddy or posterized if you just resize and save them.

Portrait Lab is the **prep desk** before the frame:

1. Choose framing (portrait or landscape) and crop.
2. Run a **Stage 1 style** so faces/edges read better on sparse ink.
3. Run **Stage 2 dithering** into the Spectra 6 palette (preview on screen ≈ what the panel can do).
4. Export a classic BMP + settings JSON into `pic/` for the TF card.

Nothing is uploaded. The server binds to `127.0.0.1` only.

---

## Pipeline (two stages)

```text
Photo → crop / orientation → Stage 1 (style) → Stage 2 (E6 dither) → BMP in pic/
```

| Stage | Role | Output |
|-------|------|--------|
| **Crop** | Cover-fit to 480×800 or 800×480; focus + zoom | Framed RGB |
| **Stage 1** | Style / prep (AnimeGANv3, oil, forum look, full auto) | “Comic” preview (memory only) |
| **Stage 2** | Tone grade + Spectra 6 dither | Monitor simulation + device BMP |

- **Portrait canvas:** 480×800  
- **Landscape canvas:** 800×480  
- **Export:** uncompressed **24-bit BMP** (Waveshare requirement)  
- **Palette:** Spectra 6 — Black, White, Green, Blue, Red, Yellow  

Folders:

| Folder | Purpose |
|--------|---------|
| `original/` | Your source images (local only — gitignored) |
| `pic/` | Finished BMPs + `*_settings.json` (local only — gitignored) |
| `models/` | ONNX weights (local only — gitignored) |
| `epaper/` | Pipeline code |
| `static/` | Web UI |

---

## Quick start

**Requirements:** Python 3.10+ recommended, Windows OK (`start.bat`).

1. Double-click `start.bat`  
   - creates `.venv`  
   - installs `requirements.txt`  
   - starts the app on **http://127.0.0.1:8765**
2. Place ONNX models under `models/` (see [Models](#models)).
3. Open a photo → set crop → render → **Save to /pic**.
4. Copy the BMP from `pic/` to the PhotoPainter TF card.

Or:

```bat
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python server.py
```

---

## Stage 1 — styles (modes)

Pick one style card, then **Confirm position · render**.

| Mode | ID | What it does |
|------|-----|----------------|
| **Full Auto** | `auto` | Recommended path: slightly cool flash/cast → **AnimeGANv3 Hayao** → light contrast + less saturation. **Does not** auto-crop; framing stays yours. |
| **Portrait (Forum)** | `portrait` | Classical “forum / Toon-nooT” prep for faces: stronger contrast, mild saturation, sharpen, shadow lift, light edge prep. **No** neural style network. |
| **Anime Comic** | `anime` | **AnimeGANv3 Hayao** only — clear comic / anime look. |
| **Oil painting** | `oil` | OpenCV oil-painting brush look (`cv2.xphoto.oilPainting`), not a neural style model. |
| **Shinkai** | `shinkai` | **AnimeGANv3 Shinkai** — softer, more atmospheric anime look. |

---

## Stage 2 — e-paper controls

Applied after Stage 1. Preview uses **perceived** colors (what you see in the browser). Export writes **device** RGB (pure 0/255 channel values the panel expects).

| Control | Meaning |
|---------|---------|
| **Brightness / Contrast** | Tone before dither (slider mid = neutral). |
| **Warmth** | Global cool ↔ warm. |
| **Skin** | Skin-biased tint: pink ↔ yellow (helps Spectra peach mixes of white/yellow/red). |
| **Dither strength** | How strongly error diffusion / blue noise is applied (0 = weak, 100 = full). |
| **Algorithm** | See dither modes below. |
| **Color distance** | How colors are matched to the 6 inks. |
| **Convert to B&W** | Dither on black + white only. |
| **Re-run E-Paper** | Re-dither without re-running Stage 1. |

### Dither algorithms

| Algorithm | ID | Use when |
|-----------|-----|----------|
| **Atkinson (Portrait)** | `atkinson` | Default for faces — cleaner midtones, less muddy skin. |
| **Floyd–Steinberg** | `floyd` | Classic error diffusion; often grainier. |
| **Blue Noise** | `bluenoise` | Ordered blue-noise thresholds — stable grain, less directional worms. |
| **No dither** | `none` | Hard nearest-color quantize only (poster look). |

### Color distance

| Mode | ID | Meaning |
|------|-----|---------|
| **Toon-nooT (Default)** | `toon` | Semantic / hue-priority matching tuned for this Spectra pipeline (skin, sky, neutrals). |
| **CIE L\*a\*b\*** | `lab` | Perceptual Lab distance (CIE76-style) for palette pick. |

---

## Crop & orientation

- Toggle **Portrait (480×800)** or **Landscape (800×480)**.
- **Cover** fit: image fills the canvas; edges may be cropped.
- **Zoom 100%** = minimal cover. Higher zoom = tighter crop (cuts borders).
- **Focus X / Y** = crop anchor.
- Drag to pan, scroll to zoom; double-click for fullscreen crop overlay.
- **Confirm position · render** runs Stage 1 (and Stage 2 for the pair preview).
- EXIF orientation is applied when the file loads.

---

## Intensive search & Auto-Tune

### Intensive search (one photo)

Requires a loaded photo and crop. Does **not** save automatically.

1. Builds a **BiSeNet** skin mask when available (else a color heuristic).
2. **Phase A:** tries all five Stage-1 styles × a coarse Stage-2 grid.  
3. **Phase B:** refines the top styles with a denser grid (tone, dither algo, color distance).  
4. Applies the best preview in the UI. Use **Save to /pic** to keep it.

Typical runtime: about **3–8 minutes** on CPU (machine-dependent). Cancellable.

### Auto-Tune all originals

Batch job over files in `original/` (server limit typically **50** per run). For each image it searches Stage-2 settings (with Stage 1), then **writes** `{name}_{style}_at.bmp` + settings into `pic/`. Skips pairs that already exist. Can take several minutes.

---

## Gallery (`/pic`)

- **Click** a thumbnail: load monitor **simulation** of the device BMP; rebuild Stage-1 comic from `original/` + settings when possible.
- **Right-click:** delete BMP + settings (and known companion files).
- **Save to /pic** while a gallery item is open: confirm overwrite of that BMP.
- New exports get a new name (or `_2`, `_3`, … on collision).
- Stage-1 comic PNGs are **not** stored on disk under `pic/`.

---

## Models

Place these under `models/` (not in git):

| File | Used by |
|------|---------|
| `AnimeGANv3_Hayao_36.onnx` | Full Auto, Anime Comic |
| `AnimeGANv3_Shinkai_37.onnx` | Shinkai |
| `bisenet_face_parsing_resnet18.onnx` | Intensive search skin mask |

Also used from the repo (small binary): `epaper/bluenoise64.bin` for blue-noise dither.  
**Oil painting** needs OpenCV contrib (`opencv-contrib-python-headless` in `requirements.txt`), not an ONNX file.

Some models may download on first use if missing and the network is available; prefer placing them yourself.

---

## Typical workflow (PhotoPainter)

1. Put personal photos you own the rights to in `original/` (optional) or open any image in the UI.  
2. Set orientation and crop so the face/subject fills the panel well.  
3. Prefer **Full Auto** or **Portrait (Forum)** for people; try Anime / Shinkai / Oil for a look.  
4. Tune Stage 2 (warmth / skin / Atkinson) until the right preview looks good.  
5. Optional: **Intensive search** for a slow automatic Stage-1+2 pick.  
6. **Save to /pic** → copy the BMP to the TF card → insert into the PhotoPainter.

---

## API (local)

FastAPI app (`server.py`), default **http://127.0.0.1:8765**.

Useful endpoints: `/api/meta`, `/api/render`, `/api/dither`, `/api/export`, `/api/gallery`, `/api/autotune`, `/api/autotune-one` (+ status/cancel).

---

## Project layout

```text
PortraitLab/
  start.bat          # Windows launcher
  server.py          # FastAPI + Uvicorn
  requirements.txt
  examples/          # CC0 demo sample (safe to ship)
  static/            # Web UI
  epaper/            # Style, dither, export, autotune
  models/            # ONNX (gitignored) + .gitkeep
  original/          # Sources (gitignored) + .gitkeep
  pic/               # Exports (gitignored) + .gitkeep
```

---

## License

**Application code & UI:** see [`LICENSE`](LICENSE).

| Allowed | Not allowed |
|---------|-------------|
| Download | Modify / create derivatives |
| Make and share **exact unmodified** copies | **Use / run** the software (any purpose) |
| | Relicense, sell, or remove notices |

Demo assets only where marked otherwise (e.g. CC0 synthetic sample, public-domain Mona Lisa — see their `SOURCE` / `LICENSE` files).

### Content policy (contributors / maintainers)

- Do **not** commit private photos or modern copyrighted images.  
- Do **not** commit ONNX weights unless you have redistribution rights.  
- Third-party models (AnimeGANv3, BiSeNet, …) keep their own upstream licenses.
