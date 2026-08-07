const STYLES = {
  auto: {
    id: "auto",
    name: "Full Auto",
    blurb: "Best path: cool flash → Anime → Atkinson. Crop stays yours.",
  },
  portrait: {
    id: "portrait",
    name: "Portrait (Forum)",
    blurb: "Toon-nooT: contrast/saturation + Atkinson.",
  },
  anime: { id: "anime", name: "Anime Comic", blurb: "AnimeGANv3 Hayao — comic/anime." },
  oil: { id: "oil", name: "Oil painting", blurb: "Real oil painting (brush dabs)." },
  shinkai: { id: "shinkai", name: "Shinkai", blurb: "AnimeGANv3 Shinkai — softer anime." },
};

/** Aus dem Picker entfernt; alte Settings/Dateinamen → auto. */
const LEGACY_STYLE_FALLBACK = { princess: "auto", udnie: "auto" };
const STEM_STYLE_IDS = [...Object.keys(STYLES), ...Object.keys(LEGACY_STYLE_FALLBACK)];

const PALETTE = [
  { label: "Black", perceived: [28, 28, 28] },
  { label: "White", perceived: [210, 204, 196] },
  { label: "Green", perceived: [48, 98, 52] },
  { label: "Blue", perceived: [52, 78, 168] },
  { label: "Red", perceived: [168, 58, 48] },
  { label: "Yellow", perceived: [188, 152, 42] },
];

const viewComic = document.getElementById("viewComic");
const viewEpaper = document.getElementById("viewEpaper");
const emptyComic = document.getElementById("emptyComic");
const emptyEpaper = document.getElementById("emptyEpaper");
const labelComic = document.getElementById("labelComic");
const labelEpaper = document.getElementById("labelEpaper");
const statusLine = document.getElementById("statusLine");
const styleGrid = document.getElementById("styleGrid");
const swatches = document.getElementById("swatches");
const galleryEl = document.getElementById("gallery");
const focusX = document.getElementById("focusX");
const focusY = document.getElementById("focusY");
const zoomEl = document.getElementById("zoom");
const dither = document.getElementById("dither");
const ditherAlgo = document.getElementById("ditherAlgo");
const colorDistance = document.getElementById("colorDistance");
const warmthEl = document.getElementById("warmth");
const skinTint = document.getElementById("skinTint");
const brightness = document.getElementById("brightness");
const contrast = document.getElementById("contrast");
const btnExport = document.getElementById("btnExport");
const btnSw = document.getElementById("btnSw");
const btnApplyStyle = document.getElementById("btnApplyStyle");
const btnApplyEpaper = document.getElementById("btnApplyEpaper");
const comicPanel = document.getElementById("comicPanel");
const cropCanvas = document.getElementById("cropCanvas");
const cropHint = document.getElementById("cropHint");
const cropCtx = cropCanvas?.getContext("2d");
const cropOverlay = document.getElementById("cropOverlay");
const cropOverlayCanvas = document.getElementById("cropOverlayCanvas");
const overlayCtx = cropOverlayCanvas?.getContext("2d");

const PORTRAIT_W = 480;
const PORTRAIT_H = 800;
const LANDSCAPE_W = 800;
const LANDSCAPE_H = 480;

/** Aktuelles Ziel-Canvas (PhotoPainter). */
let targetW = PORTRAIT_W;
let targetH = PORTRAIT_H;
let isPortrait = true;

function canvasSize() {
  return { w: targetW, h: targetH };
}

function syncFormatToggle() {
  for (const btn of document.querySelectorAll(".format-btn[data-format]")) {
    const wantPortrait = btn.dataset.format === "portrait";
    const on = wantPortrait === isPortrait;
    btn.classList.toggle("active", on);
    btn.setAttribute("aria-pressed", on ? "true" : "false");
  }
}

/** Format aus Breite/Höhe setzen — Rahmen 1+2 und Crop-Ziel. */
function setOrientationFromSize(w, h, { announce = true } = {}) {
  const nw = Number(w) || 0;
  const nh = Number(h) || 0;
  // Nur bei klarer Differenz umschalten (Quadrat → Hochformat)
  const nextPortrait = !(nw > nh * 1.02);
  const changed = nextPortrait !== isPortrait;
  isPortrait = nextPortrait;
  targetW = isPortrait ? PORTRAIT_W : LANDSCAPE_W;
  targetH = isPortrait ? PORTRAIT_H : LANDSCAPE_H;
  document.documentElement.classList.toggle("landscape", !isPortrait);
  document.documentElement.classList.toggle("portrait", isPortrait);
  syncFormatToggle();
  if (changed && announce && statusLine) {
    statusLine.textContent = isPortrait
      ? `Portrait ${targetW}×${targetH}`
      : `Landscape ${targetW}×${targetH}`;
  }
  return { w: targetW, h: targetH, portrait: isPortrait, changed };
}

function setOrientationFromFlag(portraitFlag, { announce = false } = {}) {
  // Explizit landscape/0/false → Quer; alles andere mit true-Werten → Hoch
  if (
    portraitFlag === false ||
    portraitFlag === 0 ||
    portraitFlag === "0" ||
    portraitFlag === "false" ||
    portraitFlag === "landscape" ||
    portraitFlag === "quer" ||
    portraitFlag === "querformat"
  ) {
    return setOrientationFromSize(LANDSCAPE_W, LANDSCAPE_H, { announce });
  }
  if (
    portraitFlag === true ||
    portraitFlag === 1 ||
    portraitFlag === "1" ||
    portraitFlag === "true" ||
    portraitFlag === "portrait" ||
    portraitFlag === "hoch" ||
    portraitFlag === "hochformat"
  ) {
    return setOrientationFromSize(PORTRAIT_W, PORTRAIT_H, { announce });
  }
  // Unbekannt → Hochformat (sicherer Default)
  return setOrientationFromSize(PORTRAIT_W, PORTRAIT_H, { announce });
}

/** Nutzer wählt Hoch-/Querformat im Zuschnitt — Rahmen + Crop-Ziel sofort. */
function setOutputFormat(portraitFlag, { announce = true } = {}) {
  const prev = isPortrait;
  const result = setOrientationFromFlag(portraitFlag, { announce });
  if (result.portrait === prev) return result;
  if (sourceFile && sourceImg) {
    enterCropEdit();
    // Aspect-Ratio-CSS braucht einen Frame, bevor die Vorschau neu skaliert
    requestAnimationFrame(() => {
      drawCropPreview();
      if (!cropOverlay?.hidden) drawCropOverlay();
    });
  }
  return result;
}

let styleId = "auto";
let sourceFile = null;
let sourceImg = null;
let lastFilename = "portrait";
let lastComicBlob = null;
let grayscaleOn = false;
/** Aktuell aus Galerie geöffnetes BMP — Export überschreibt diese Datei. */
let galleryTarget = null;
/** true = Live-Zuschnitt (Original), false = fertiger Stil in Rahmen 1 */
let cropEditing = true;

let ditherTimer = 0;
let renderGen = 0;
let abortCtrl = null;
let ditherAbort = null;
/** Intensiv-Suche: nur explizites Abbrechen (kein Fetch-Abort auf Lang-POST). */
let intensiveRunning = false;
let intensiveJobId = null;
let intensiveWantCancel = false;

let comicUrl = null;
let epaperUrl = null;

let drag = null;

function zoomFactor() {
  return Math.max(1, Number(zoomEl?.value || 100) / 100);
}

function cropParams() {
  return {
    focusX: Number(focusX.value) / 100,
    focusY: Number(focusY.value) / 100,
    zoom: zoomFactor(),
  };
}

function setImg(imgEl, emptyEl, blob, which) {
  const clean = URL.createObjectURL(blob);
  const prev = which === "comic" ? comicUrl : epaperUrl;
  if (which === "comic") comicUrl = clean;
  else epaperUrl = clean;

  emptyEl.classList.add("hidden");
  imgEl.removeAttribute("hidden");
  imgEl.hidden = false;
  imgEl.style.display = "block";
  imgEl.style.visibility = "visible";
  imgEl.style.opacity = "1";
  imgEl.src = clean;

  if (prev) {
    try {
      URL.revokeObjectURL(prev);
    } catch (_) {
      /* ignore */
    }
  }
}

function markFrameLoading(which) {
  if (which === "comic" || which === "both") {
    emptyComic.classList.remove("hidden");
    emptyComic.querySelector(".empty-copy").textContent = "Updating…";
    viewComic.hidden = true;
    if (cropCanvas) cropCanvas.style.display = "none";
  }
  if (which === "epaper" || which === "both") {
    emptyEpaper.classList.remove("hidden");
    emptyEpaper.querySelector(".empty-copy").textContent = "Rendering E-Paper…";
    viewEpaper.hidden = true;
  }
}

function b64ToBlob(b64, type = "image/png") {
  const bin = atob(b64);
  const arr = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) arr[i] = bin.charCodeAt(i);
  return new Blob([arr], { type });
}

/** Slider 0..100 → -1..+1 (50 = neutral) */
function midFactor(sliderVal) {
  return (Number(sliderVal) - 50) / 50;
}

function warmthLabel(v) {
  const n = Number(v);
  if (n < 30) return "cool";
  if (n < 45) return "slightly cool";
  if (n <= 55) return "Mid";
  if (n < 70) return "warm";
  return "very warm";
}

function tintLabel(v) {
  const n = Number(v);
  if (n < 25) return "strong pink";
  if (n < 40) return "pink";
  if (n <= 55) return "Mid";
  if (n < 70) return "yellow";
  return "strong yellow";
}

/** Slider 0..100 → Faktor 0.5..1.5 (50 = neutral 1.0) */
function toneFactor(sliderVal) {
  return 0.5 + Number(sliderVal) / 100;
}

function toneSliderFromFactor(factor) {
  const f = Math.max(0.5, Math.min(1.5, Number(factor) || 1));
  return String(Math.round((f - 0.5) * 100));
}

function midSliderFromFactor(factor) {
  const f = Math.max(-1, Math.min(1, Number(factor) || 0));
  return String(Math.round(50 + f * 50));
}

function applyEpaperSettings(st) {
  if (!st || typeof st !== "object") return;
  if (brightness && st.brightness != null) brightness.value = toneSliderFromFactor(st.brightness);
  if (contrast && st.contrast != null) contrast.value = toneSliderFromFactor(st.contrast);
  if (warmthEl && st.warmth != null) warmthEl.value = midSliderFromFactor(st.warmth);
  if (skinTint && (st.skin_tint != null || st.skinTint != null)) {
    skinTint.value = midSliderFromFactor(st.skin_tint ?? st.skinTint);
  }
  if (dither && st.dither_strength != null) {
    dither.value = String(Math.round(Number(st.dither_strength) * 100));
  }
  if (ditherAlgo && st.algorithm) ditherAlgo.value = st.algorithm;
  if (colorDistance && (st.color_distance != null || st.colorDistance != null)) {
    colorDistance.value = st.color_distance ?? st.colorDistance;
  }
  if (st.grayscale != null) {
    grayscaleOn = Boolean(st.grayscale);
    syncSwButton();
  }
  const fx = st.focus_x ?? st.focusX;
  const fy = st.focus_y ?? st.focusY;
  if (focusX && fx != null) focusX.value = String(Math.round(Number(fx) * 1000) / 10);
  if (focusY && fy != null) focusY.value = String(Math.round(Number(fy) * 1000) / 10);
  if (zoomEl && st.zoom != null) {
    zoomEl.value = String(Math.round(Number(st.zoom) * 1000) / 10);
  }
  const rawSid = st.style_id || st.styleId;
  if (rawSid) {
    const sid = LEGACY_STYLE_FALLBACK[rawSid] || rawSid;
    if (STYLES[sid]) {
      styleId = sid;
      highlightStyles();
      updateStyleHeading();
    }
  }
  updateSliderLabels();
}

function currentEpaperMeta(extra = {}) {
  const p = cropParams();
  return {
    styleId,
    ditherStrength: Number(dither.value) / 100,
    ditherAlgo: ditherAlgo.value,
    colorDistance: colorDistance?.value || "toon",
    warmth: midFactor(warmthEl?.value ?? 50),
    skinTint: midFactor(skinTint?.value ?? 50),
    brightness: toneFactor(brightness.value),
    contrast: toneFactor(contrast.value),
    grayscale: grayscaleOn,
    portrait: isPortrait,
    orientation: isPortrait ? "portrait" : "landscape",
    focusX: p.focusX,
    focusY: p.focusY,
    zoom: p.zoom,
    ...extra,
  };
}

/** Basis-Stem: Dateiname ohne Ext, _original, Export-Suffix (_auto_at …) und Stil-Id. */
function baseStemFromName(name) {
  let stem = String(name || "").replace(/\.[^.]+$/, "");
  stem = stem.replace(/_original$/i, "");
  for (const suf of ["_auto_at", "_auto_autotune", "_autotune", "_at"]) {
    if (stem.toLowerCase().endsWith(suf)) {
      stem = stem.slice(0, -suf.length);
      break;
    }
  }
  for (const sid of STEM_STYLE_IDS) {
    const tail = `_${sid}`;
    if (stem.toLowerCase().endsWith(tail.toLowerCase())) {
      stem = stem.slice(0, -tail.length);
      break;
    }
  }
  return stem.toLowerCase();
}

/** true wenn geladenes Foto zum aktuellen Galerie-Export gehört (Re-Crop → Überschreiben). */
function fileMatchesGalleryTarget(file) {
  if (!galleryTarget || !file) return false;
  const fileBase = baseStemFromName(file.name);
  if (!fileBase) return false;
  const candidates = [galleryTarget.name, galleryTarget.source].filter(Boolean);
  for (const c of candidates) {
    if (baseStemFromName(c) === fileBase) return true;
  }
  const bmpStem = String(galleryTarget.name || "")
    .replace(/\.bmp$/i, "")
    .toLowerCase();
  return bmpStem === fileBase || bmpStem.startsWith(`${fileBase}_`);
}

function updateExportHint() {
  if (!btnExport) return;
  if (galleryTarget?.name) {
    btnExport.title = `Overwrites ${galleryTarget.name}`;
  } else {
    btnExport.title = "Save as BMP to /pic";
  }
}

function updateSliderLabels() {
  const dv = document.getElementById("ditherVal");
  const sv = document.getElementById("skinVal");
  const wv = document.getElementById("warmthVal");
  const bv = document.getElementById("brightVal");
  const cv = document.getElementById("contrastVal");
  const xv = document.getElementById("focusXVal");
  const yv = document.getElementById("focusYVal");
  const zv = document.getElementById("zoomVal");
  if (dv && dither) dv.textContent = `${dither.value}%`;
  if (wv && warmthEl) wv.textContent = warmthLabel(warmthEl.value);
  if (sv && skinTint) sv.textContent = tintLabel(skinTint.value);
  if (bv && brightness) bv.textContent = `${Math.round(toneFactor(brightness.value) * 100)}%`;
  if (cv && contrast) cv.textContent = `${Math.round(toneFactor(contrast.value) * 100)}%`;
  if (xv && focusX) {
    const x = Number(focusX.value);
    let label = `${x % 1 === 0 ? x : x.toFixed(1)}%`;
    if (sourceImg) {
      try {
        const { sw, srcW } = sourceCropRect();
        if (sw - srcW < 2) label += " · voll";
      } catch (_) {
        /* ignore */
      }
    }
    xv.textContent = label;
  }
  if (yv && focusY) {
    const y = Number(focusY.value);
    let label = `${y % 1 === 0 ? y : y.toFixed(1)}%`;
    if (sourceImg) {
      try {
        const { sh, srcH } = sourceCropRect();
        if (sh - srcH < 2) label += " · voll";
      } catch (_) {
        /* ignore */
      }
    }
    yv.textContent = label;
  }
  if (zv && zoomEl) {
    const z = Number(zoomEl.value);
    const pct = Math.abs(z - Math.round(z)) < 1e-6 ? `${Math.round(z)}%` : `${z.toFixed(1)}%`;
    // 100% = Cover/Ausfüllen; darüber = Reinzoomen (Ränder abschneiden)
    zv.textContent = z <= 100.01 ? `${pct} · cover` : `${pct} · zoom in`;
  }
}

function updateStyleHeading() {
  const name = STYLES[styleId]?.name || styleId;
  if (labelComic) labelComic.textContent = `1 · ${name}`;
  if (labelEpaper) labelEpaper.textContent = `2 · E6 · ${name}`;
  if (statusLine && !sourceFile) statusLine.textContent = `Style: ${name}`;
}

function styleBusyLabel() {
  return `${STYLES[styleId]?.name || styleId}…`;
}

function syncActionButtons() {
  const hasSrc = Boolean(sourceFile && sourceImg);
  if (btnApplyStyle) btnApplyStyle.disabled = !hasSrc || intensiveRunning;
  if (btnApplyEpaper) btnApplyEpaper.disabled = !lastComicBlob || intensiveRunning;
  if (btnExport) btnExport.disabled = !lastComicBlob || intensiveRunning;
  const btnInt = document.getElementById("btnIntensive");
  const hint = document.getElementById("intensiveHint");
  if (btnInt && !intensiveRunning) {
    btnInt.disabled = !hasSrc;
    btnInt.textContent = "Intensive search";
    btnInt.title = hasSrc
      ? "Intensive search: all styles + fine grid (~3–8 min)"
      : "Load a photo and set the crop first";
  }
  if (hint) {
    hint.textContent = hasSrc
      ? "After crop: all styles + fine grid (~3–8 min). Does not save automatically."
      : "Open a photo and set the crop first.";
  }
  updateExportHint();
}

function enterCropEdit() {
  cropEditing = true;
  lastComicBlob = null;
  syncActionButtons();
  if (comicPanel) {
    comicPanel.classList.add("has-preview", "editing");
    comicPanel.classList.remove("has-result");
  }
  if (cropHint) cropHint.hidden = false;
  if (viewComic) {
    viewComic.hidden = true;
    viewComic.style.display = "none";
  }
  // E-Paper veraltet
  if (viewEpaper) {
    viewEpaper.hidden = true;
  }
  if (emptyEpaper) {
    emptyEpaper.classList.remove("hidden");
    emptyEpaper.querySelector(".empty-copy").textContent = "Crop changed — re-render style.";
  }
  drawCropPreview();
  // Overlay nur per Doppelklick — nicht als erste Seite nach Laden
  if (!cropOverlay?.hidden) drawCropOverlay();
  if (statusLine && sourceFile) {
    statusLine.textContent = "Crop · style not rendered yet";
  }
}

function showComicResult(blob) {
  cropEditing = false;
  closeCropOverlay();
  if (comicPanel) {
    comicPanel.classList.add("has-result");
    comicPanel.classList.remove("editing", "has-preview");
  }
  if (cropHint) cropHint.hidden = true;
  if (cropCanvas) cropCanvas.style.display = "none";
  setImg(viewComic, emptyComic, blob, "comic");
}

/** Crop-Fenster in Quellpixeln (wie fit_portrait cover+zoom). */
function sourceCropRect() {
  // natural* = Pixelraster, das drawImage nutzt (Browser + EXIF)
  const sw = sourceImg.naturalWidth;
  const sh = sourceImg.naturalHeight;
  const { focusX: fx, focusY: fy, zoom } = cropParams();
  const scale = Math.max(targetW / sw, targetH / sh) * zoom;
  const srcW = Math.min(sw, targetW / scale);
  const srcH = Math.min(sh, targetH / scale);
  const srcLeft = Math.max(0, (sw - srcW) * fx);
  const srcTop = Math.max(0, (sh - srcH) * fy);
  return { sw, sh, srcLeft, srcTop, srcW, srcH, scale, fx, fy, zoom };
}

function drawCropPreview() {
  if (!cropCanvas || !cropCtx || !sourceImg || !comicPanel) return;
  const rect = comicPanel.getBoundingClientRect();
  const cssW = Math.max(1, Math.round(rect.width));
  const cssH = Math.max(1, Math.round(rect.height));
  const dpr = Math.min(2, window.devicePixelRatio || 1);
  const tw = Math.round(cssW * dpr);
  const th = Math.round(cssH * dpr);
  if (cropCanvas.width !== tw || cropCanvas.height !== th) {
    cropCanvas.width = tw;
    cropCanvas.height = th;
  }
  cropCanvas.style.display = "block";

  // Immer denselben Ausschnitt wie der Server (targetW×targetH), nicht Panel-CSS
  const { srcLeft, srcTop, srcW, srcH } = sourceCropRect();

  cropCtx.fillStyle = "#f2efe8";
  cropCtx.fillRect(0, 0, tw, th);
  cropCtx.imageSmoothingEnabled = true;
  cropCtx.imageSmoothingQuality = "high";
  cropCtx.drawImage(sourceImg, srcLeft, srcTop, srcW, srcH, 0, 0, tw, th);

  emptyComic.classList.add("hidden");
  if (comicPanel) comicPanel.classList.add("has-preview");
}

function openCropOverlay() {
  if (!cropOverlay || !sourceImg) return;
  cropOverlay.hidden = false;
  document.body.style.overflow = "hidden";
  drawCropOverlay();
}

function closeCropOverlay() {
  if (!cropOverlay) return;
  cropOverlay.hidden = true;
  document.body.style.overflow = "";
  cropOverlay.classList.remove("dragging");
}

/** Fullscreen: ganzes Bild + heller Zuschnittsrahmen */
function drawCropOverlay() {
  if (!cropOverlayCanvas || !overlayCtx || !sourceImg || cropOverlay?.hidden) return;

  const cssW = Math.max(1, cropOverlayCanvas.clientWidth || window.innerWidth);
  const cssH = Math.max(
    1,
    cropOverlayCanvas.clientHeight || Math.max(200, window.innerHeight - 72),
  );
  const dpr = Math.min(2, window.devicePixelRatio || 1);
  const tw = Math.round(cssW * dpr);
  const th = Math.round(cssH * dpr);
  if (cropOverlayCanvas.width !== tw || cropOverlayCanvas.height !== th) {
    cropOverlayCanvas.width = tw;
    cropOverlayCanvas.height = th;
  }

  const { sw, sh, srcLeft, srcTop, srcW, srcH } = sourceCropRect();
  const padX = tw * 0.04;
  const padY = th * 0.04;
  const fit = Math.min((tw - padX * 2) / sw, (th - padY * 2) / sh);
  const iw = sw * fit;
  const ih = sh * fit;
  const ox = (tw - iw) / 2;
  const oy = (th - ih) / 2;

  // Layout für Drag/Zoom merken (CSS-Pixel)
  overlayLayout = {
    fit: fit / dpr,
    ox: ox / dpr,
    oy: oy / dpr,
    iw: iw / dpr,
    ih: ih / dpr,
    dpr,
  };

  overlayCtx.fillStyle = "#100e0c";
  overlayCtx.fillRect(0, 0, tw, th);
  overlayCtx.imageSmoothingEnabled = true;
  overlayCtx.imageSmoothingQuality = "high";
  overlayCtx.drawImage(sourceImg, ox, oy, iw, ih);

  const cx = ox + srcLeft * fit;
  const cy = oy + srcTop * fit;
  const cw = srcW * fit;
  const ch = srcH * fit;

  // Alles außer Crop abdunkeln
  overlayCtx.fillStyle = "rgba(6, 4, 3, 0.62)";
  overlayCtx.beginPath();
  overlayCtx.rect(0, 0, tw, th);
  overlayCtx.rect(cx, cy, cw, ch);
  overlayCtx.fill("evenodd");

  // Crop-Rahmen
  overlayCtx.strokeStyle = "rgba(255, 214, 150, 0.95)";
  overlayCtx.lineWidth = Math.max(2, Math.round(3 * dpr));
  overlayCtx.strokeRect(cx + 1, cy + 1, cw - 2, ch - 2);

  // Ecken
  const corner = Math.max(10, 18 * dpr);
  overlayCtx.strokeStyle = "#ffe2b0";
  overlayCtx.lineWidth = Math.max(2.5, 3.5 * dpr);
  const corners = [
    [cx, cy, 1, 1],
    [cx + cw, cy, -1, 1],
    [cx, cy + ch, 1, -1],
    [cx + cw, cy + ch, -1, -1],
  ];
  for (const [x, y, sx, sy] of corners) {
    overlayCtx.beginPath();
    overlayCtx.moveTo(x, y + sy * corner);
    overlayCtx.lineTo(x, y);
    overlayCtx.lineTo(x + sx * corner, y);
    overlayCtx.stroke();
  }

  overlayCtx.fillStyle = "rgba(255, 230, 200, 0.9)";
  overlayCtx.font = `${Math.round(13 * dpr)}px Manrope, sans-serif`;
  overlayCtx.fillText(
    `Zoom ${Number(zoomEl.value).toFixed(1)}% · crop ${targetW}×${targetH}`,
    ox,
    Math.max(oy - 8 * dpr, 18 * dpr),
  );
}

let overlayLayout = null;

function loadSourceImage(file) {
  // EXIF in Pixel backen → naturalWidth/Height = Anzeige = Server nach exif_transpose
  return (async () => {
    let bmp;
    try {
      bmp = await createImageBitmap(file, { imageOrientation: "from-image" });
    } catch (_) {
      bmp = await createImageBitmap(file);
    }
    const canvas = document.createElement("canvas");
    canvas.width = bmp.width;
    canvas.height = bmp.height;
    canvas.getContext("2d").drawImage(bmp, 0, 0);
    bmp.close();
    const blob = await new Promise((resolve, reject) => {
      canvas.toBlob(
        (b) => (b ? resolve(b) : reject(new Error("Image decode failed"))),
        "image/jpeg",
        0.92,
      );
    });
    return blobToImage(blob);
  })();
}

function blobToImage(blob) {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(blob);
    const img = new Image();
    img.onload = () => {
      URL.revokeObjectURL(url);
      resolve(img);
    };
    img.onerror = () => {
      URL.revokeObjectURL(url);
      reject(new Error("Could not load image"));
    };
    img.src = url;
  });
}

async function detectOrientedSize(file, img) {
  return { w: img.naturalWidth, h: img.naturalHeight };
}

function selectStyle(id) {
  if (!STYLES[id]) return;
  const prev = styleId;
  styleId = id;
  if (id === "auto" || id === "portrait") {
    if (ditherAlgo) ditherAlgo.value = "atkinson";
    if (warmthEl) warmthEl.value = "50";
    if (skinTint) skinTint.value = "50";
    if (dither) dither.value = "100";
    updateSliderLabels();
  }
  updateStyleHeading();
  highlightStyles();
  if (!sourceFile) {
    if (statusLine) statusLine.textContent = `Style: ${STYLES[id].name} — open a photo`;
    return;
  }
  // Zuschnitt behalten — nicht zurück in die Positionierung springen
  closeCropOverlay();
  if (statusLine) {
    statusLine.textContent =
      prev === id
        ? `Stil: ${STYLES[id].name}`
        : `Style → ${STYLES[id].name} · crop kept`;
  }
  void runStyleOnly();
}

function highlightStyles() {
  styleGrid.querySelectorAll(".style-card").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.style === styleId);
  });
}

function buildStyles() {
  styleGrid.innerHTML = "";
  Object.values(STYLES).forEach((s) => {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "style-card" + (s.id === styleId ? " active" : "");
    btn.dataset.style = s.id;
    btn.innerHTML = `<strong>${s.name}</strong><span>${s.blurb}</span>`;
    styleGrid.appendChild(btn);
  });
}

styleGrid.addEventListener("click", (e) => {
  const btn = e.target.closest(".style-card");
  if (!btn || !styleGrid.contains(btn)) return;
  e.preventDefault();
  selectStyle(btn.dataset.style);
});

function buildSwatches() {
  swatches.innerHTML = "";
  PALETTE.forEach((c) => {
    const d = document.createElement("div");
    d.className = "swatch";
    d.style.background = `rgb(${c.perceived.join(",")})`;
    d.title = c.label;
    swatches.appendChild(d);
  });
}

function cancelIntensiveServer() {
  // fire-and-forget: Server-Flag setzen, damit CPU-Worker stoppt
  void fetch("/api/autotune-one/cancel", {
    method: "POST",
    cache: "no-store",
  }).catch(() => {});
}

function cancelPending() {
  clearTimeout(ditherTimer);
  if (abortCtrl) {
    abortCtrl.abort();
    abortCtrl = null;
  }
  if (ditherAbort) {
    ditherAbort.abort();
    ditherAbort = null;
  }
  if (intensiveRunning) {
    intensiveWantCancel = true;
    cancelIntensiveServer();
  }
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function intensiveStatusLabel(data, elapsedSec) {
  const sec = Math.round(elapsedSec);
  const msg = (data?.message || "").trim();
  const cur = Number(data?.current) || 0;
  const tot = Number(data?.total) || 0;
  const frac = tot > 0 ? ` ${cur}/${tot}` : "";
  if (msg) return `Intensive… ${sec}s · ${msg}${frac}`;
  return `Intensive search… ${sec}s (style grid + skin mask)`;
}

function appendCropFields(form) {
  const p = cropParams();
  form.append("focus_x", String(p.focusX));
  form.append("focus_y", String(p.focusY));
  form.append("zoom", String(p.zoom));
  form.append("portrait", isPortrait ? "1" : "0");
}

/** Stufe 1 (Stil), danach automatisch Stufe 2 (E-Paper). */
async function runStyleOnly() {
  if (!sourceFile) return;
  cancelPending();
  updateSliderLabels();
  renderGen += 1;
  const myGen = renderGen;
  const wantedStyle = styleId;
  abortCtrl = new AbortController();

  if (statusLine) statusLine.textContent = styleBusyLabel();
  if (btnApplyStyle) btnApplyStyle.disabled = true;
  markFrameLoading("both");

  const form = new FormData();
  form.append("file", sourceFile);
  form.append("style_id", wantedStyle);
  appendCropFields(form);
  form.append("stage", "comic");

  try {
    const res = await fetch("/api/render", {
      method: "POST",
      body: form,
      signal: abortCtrl.signal,
      cache: "no-store",
    });
    if (myGen !== renderGen || wantedStyle !== styleId) return;
    if (!res.ok) {
      const t = await res.text();
      throw new Error(t || "Style failed");
    }
    const blob = await res.blob();
    if (myGen !== renderGen || wantedStyle !== styleId) return;

    lastComicBlob = blob;
    showComicResult(blob);
    updateStyleHeading();
    syncActionButtons();
    if (statusLine) {
      statusLine.textContent = `${lastFilename} · ${STYLES[wantedStyle]?.name || wantedStyle} · E-Paper…`;
    }
    // E-Paper direkt mitberechnen
    await runDitherOnly();
  } catch (err) {
    if (err?.name === "AbortError") return;
    if (myGen !== renderGen) return;
    enterCropEdit();
    if (statusLine) statusLine.textContent = String(err.message || err).slice(0, 120);
    console.error(err);
  } finally {
    syncActionButtons();
  }
}

async function runDitherOnly() {
  if (!lastComicBlob) {
    if (statusLine) statusLine.textContent = "Render style first";
    return;
  }
  const myGen = renderGen;
  if (ditherAbort) ditherAbort.abort();
  ditherAbort = new AbortController();

  const form = new FormData();
  form.append("file", lastComicBlob, "comic.png");
  form.append("dither_strength", String(Number(dither.value) / 100));
  form.append("dither_algo", ditherAlgo.value);
  form.append("color_distance", colorDistance?.value || "toon");
  form.append("warmth", String(midFactor(warmthEl?.value ?? 50)));
  form.append("skin_tint", String(midFactor(skinTint?.value ?? 50)));
  form.append("brightness", String(toneFactor(brightness.value)));
  form.append("contrast", String(toneFactor(contrast.value)));
  form.append("style_id", styleId);
  form.append("grayscale", grayscaleOn ? "1" : "0");

  try {
    if (statusLine) statusLine.textContent = "E-Paper…";
    markFrameLoading("epaper");
    const res = await fetch("/api/dither", {
      method: "POST",
      body: form,
      signal: ditherAbort.signal,
      cache: "no-store",
    });
    if (myGen !== renderGen) return;
    if (!res.ok) throw new Error("Dither failed");
    const blob = await res.blob();
    if (myGen !== renderGen) return;

    setImg(viewEpaper, emptyEpaper, blob, "epaper");
    emptyEpaper.classList.add("hidden");
    viewEpaper.hidden = false;
    viewEpaper.style.display = "block";
    if (labelEpaper) {
      labelEpaper.textContent = `2 · E6 · ${STYLES[styleId]?.name || styleId}`;
    }
    if (statusLine) {
      statusLine.textContent = `${lastFilename} · ${STYLES[styleId]?.name || styleId}`;
    }
    syncActionButtons();
  } catch (err) {
    if (err?.name === "AbortError") return;
    console.error(err);
    if (statusLine) statusLine.textContent = String(err.message || err).slice(0, 120);
  }
}

function scheduleDitherOnly() {
  clearTimeout(ditherTimer);
  updateSliderLabels();
  if (!lastComicBlob) return;
  if (statusLine) statusLine.textContent = "Dither…";
  ditherTimer = setTimeout(() => {
    void runDitherOnly();
  }, 100);
}

async function exportToPic() {
  if (!lastComicBlob && !sourceFile) return;

  if (galleryTarget?.name) {
    const short =
      galleryTarget.name.length > 48
        ? `${galleryTarget.name.slice(0, 46)}…`
        : galleryTarget.name;
    if (!window.confirm(`Save to /pic — overwrite "${short}"?`)) {
      if (statusLine) statusLine.textContent = "Export cancelled";
      return;
    }
  }

  statusLine.textContent = galleryTarget?.name
    ? `Exporting (overwrites ${galleryTarget.name})…`
    : "Exporting…";

  try {
    // Galerie-Ziel oder nur Comic: Stufe 2 speichern (überschreibt geöffnetes BMP)
    if (lastComicBlob && (galleryTarget || !sourceFile)) {
      const overwriteName = galleryTarget?.name || `${lastFilename}_${styleId}.bmp`;
      const form = new FormData();
      form.append("file", lastComicBlob, "comic.png");
      form.append(
        "meta_json",
        JSON.stringify(
          currentEpaperMeta({
            filename: overwriteName,
            overwrite: true,
            source: galleryTarget?.source || sourceFile?.name || lastFilename || null,
          }),
        ),
      );
      const res = await fetch("/api/export-comic", { method: "POST", body: form });
      const data = await res.json();
      if (!res.ok) throw new Error(data?.detail || "Export failed");
      galleryTarget = {
        name: data.name,
        source: galleryTarget?.source || sourceFile?.name || lastFilename || null,
      };
      statusLine.textContent = `Saved (overwritten): ${data.name}`;
      syncActionButtons();
      await refreshGallery();
      return;
    }

    // Neues Foto: voller Pipeline-Export (mit galleryTarget → gleicher Stem)
    const overwrite = Boolean(galleryTarget?.name);
    const form = new FormData();
    form.append("file", sourceFile);
    form.append(
      "meta_json",
      JSON.stringify(
        currentEpaperMeta({
          pipeline: "stage2",
          filename: galleryTarget?.name || `${lastFilename}_${styleId}`,
          overwrite,
          source: galleryTarget?.source || sourceFile?.name || lastFilename,
        }),
      ),
    );
    const res = await fetch("/api/export", { method: "POST", body: form });
    const data = await res.json();
    if (!res.ok) throw new Error(data?.detail || "Export failed");
    galleryTarget = {
      name: data.name,
      source: galleryTarget?.source || sourceFile?.name || lastFilename,
    };
    statusLine.textContent = overwrite
      ? `Saved (overwritten): ${data.name}`
      : `Saved: ${data.name}`;
    syncActionButtons();
    await refreshGallery();
  } catch (err) {
    console.error(err);
    statusLine.textContent = String(err.message || err).slice(0, 140);
  }
}

async function runAutotuneAll() {
  const btn = document.getElementById("btnAutotune");
  if (btn) btn.disabled = true;
  if (statusLine) {
    statusLine.textContent =
      "Auto-Tune running (style + grid) — may take several minutes…";
  }
  try {
    const form = new FormData();
    form.append("style_id", styleId || "auto");
    form.append("limit", "0");
    const res = await fetch("/api/autotune", { method: "POST", body: form });
    const data = await res.json();
    if (!res.ok) throw new Error(data?.detail || "Auto-Tune failed");
    if (statusLine) {
      statusLine.textContent = `Auto-Tune done: ${data.count} files in /pic`;
    }
    await refreshGallery();
  } catch (err) {
    console.error(err);
    if (statusLine) statusLine.textContent = String(err.message || err).slice(0, 140);
  } finally {
    if (btn) btn.disabled = false;
  }
}

async function runIntensiveSearch() {
  if (!sourceFile || !sourceImg) {
    if (statusLine) statusLine.textContent = "Load a photo and set the crop first";
    return;
  }
  if (intensiveRunning) {
    intensiveWantCancel = true;
    cancelIntensiveServer();
    if (statusLine) statusLine.textContent = "Cancelling intensive search…";
    return;
  }

  const btn = document.getElementById("btnIntensive");
  const keepGallery = galleryTarget ? { ...galleryTarget } : null;
  cancelPending();
  intensiveWantCancel = false;
  intensiveJobId = null;
  intensiveRunning = true;
  renderGen += 1;
  const myGen = renderGen;

  if (btn) {
    btn.disabled = false;
    btn.classList.add("running");
    btn.textContent = "Cancel…";
    btn.title = "Cancel intensive search";
  }
  syncActionButtons();
  closeCropOverlay();
  markFrameLoading("both");
  if (statusLine) {
    statusLine.textContent = "Starting intensive search…";
  }

  const form = new FormData();
  form.append("file", sourceFile);
  appendCropFields(form);
  form.append("quick", "0");

  const started = Date.now();

  try {
    const startRes = await fetch("/api/autotune-one", {
      method: "POST",
      body: form,
      cache: "no-store",
    });
    const startData = await startRes.json().catch(() => ({}));
    if (!startRes.ok) {
      const detail = startData?.detail;
      const msg =
        typeof detail === "string"
          ? detail
          : Array.isArray(detail)
            ? detail.map((d) => d.msg || d).join("; ")
            : "Intensive search failed";
      throw new Error(msg);
    }
    intensiveJobId = startData.jobId;
    if (!intensiveJobId) throw new Error("No job ID from server");

    let data = null;
    while (true) {
      if (myGen !== renderGen) return;
      if (intensiveWantCancel) {
        cancelIntensiveServer();
      }
      await sleep(1000);
      if (myGen !== renderGen) return;

      const stRes = await fetch(
        `/api/autotune-one/status?job_id=${encodeURIComponent(intensiveJobId)}`,
        { cache: "no-store" },
      );
      const st = await stRes.json().catch(() => ({}));
      if (!stRes.ok) {
        const detail = st?.detail;
        throw new Error(
          typeof detail === "string" ? detail : "Status poll failed",
        );
      }

      const elapsed = (Date.now() - started) / 1000;
      if (statusLine) {
        statusLine.textContent = intensiveStatusLabel(st, elapsed);
      }

      if (st.status === "done") {
        data = st.result;
        break;
      }
      if (st.status === "cancelled") {
        if (statusLine) statusLine.textContent = "Intensive search cancelled";
        return;
      }
      if (st.status === "error") {
        throw new Error(st.error || st.message || "Intensive search failed");
      }
      // running
    }

    if (myGen !== renderGen) return;
    if (!data?.settings) throw new Error("Empty result");

    // Galerie-Overwrite-Ziel behalten
    galleryTarget = keepGallery;

    applyEpaperSettings({
      ...data.settings,
      style_id: data.styleId || data.settings?.style_id,
      focus_x: data.focusX ?? data.settings?.focus_x,
      focus_y: data.focusY ?? data.settings?.focus_y,
      zoom: data.zoom ?? data.settings?.zoom,
    });
    highlightStyles();

    const comicBlob = b64ToBlob(data.comic);
    const epaperBlob = b64ToBlob(data.epaper);
    lastComicBlob = comicBlob;
    showComicResult(comicBlob);
    setImg(viewEpaper, emptyEpaper, epaperBlob, "epaper");
    emptyEpaper.classList.add("hidden");
    viewEpaper.hidden = false;
    viewEpaper.style.display = "block";
    updateStyleHeading();

    const skinNote = data.skinMaskUsed ? "skin mask" : "no face mask";
    if (statusLine) {
      statusLine.textContent =
        `Intensive done · ${STYLES[styleId]?.name || styleId} · score ${data.score} · ${data.elapsedSec}s · ${skinNote} — Save to /pic to keep`;
    }
  } catch (err) {
    console.error(err);
    if (statusLine) statusLine.textContent = String(err.message || err).slice(0, 140);
  } finally {
    intensiveRunning = false;
    intensiveJobId = null;
    intensiveWantCancel = false;
    if (btn) {
      btn.classList.remove("running");
      btn.textContent = "Intensive search";
      btn.title = "Intensive search: all styles + fine grid (~3–8 min)";
    }
    if (keepGallery && !galleryTarget) galleryTarget = keepGallery;
    syncActionButtons();
  }
}

async function refreshGallery() {
  const data = await (await fetch("/api/gallery")).json();
  galleryEl.innerHTML = "";
  if (!data.items.length) {
    const li = document.createElement("li");
    li.className = "empty";
    li.textContent = "No BMPs yet";
    galleryEl.appendChild(li);
    return;
  }
  for (const item of data.items) {
    const li = document.createElement("li");
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "gallery-thumb";
    if (item.orientation === "landscape" || item.portrait === false || (item.width && item.height && item.width > item.height)) {
      btn.classList.add("is-landscape");
    }
    btn.title = `${item.name} · Click = simulation · Right-click = delete`;
    const img = document.createElement("img");
    img.src = item.simUrl || item.url;
    img.alt = item.name;
    img.loading = "lazy";
    btn.appendChild(img);
    if (item.autotune) {
      const tag = document.createElement("span");
      tag.className = "gallery-tag";
      tag.textContent = "auto";
      btn.appendChild(tag);
    }
    btn.addEventListener("click", () => void openGalleryItem(item));
    btn.addEventListener("contextmenu", (e) => {
      e.preventDefault();
      void deleteGalleryItem(item, li);
    });
    li.appendChild(btn);
    galleryEl.appendChild(li);
  }
}

async function deleteGalleryItem(item, liEl) {
  const short = item.name.length > 42 ? `${item.name.slice(0, 40)}…` : item.name;
  if (!window.confirm(`Delete "${short}"?\n(BMP + settings)`)) return;
  try {
    const res = await fetch(`/api/gallery/${encodeURIComponent(item.name)}`, {
      method: "DELETE",
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data?.detail || "Delete failed");
    liEl?.remove();
    if (statusLine) {
      const n = Array.isArray(data?.removed) ? data.removed.length : 0;
      statusLine.textContent =
        n > 1 ? `Deleted: ${item.name} (+${n - 1} companion files)` : `Deleted: ${item.name}`;
    }
    if (!galleryEl.querySelector(".gallery-thumb")) {
      galleryEl.innerHTML = "";
      const empty = document.createElement("li");
      empty.className = "empty";
      empty.textContent = "No BMPs yet";
      galleryEl.appendChild(empty);
    }
  } catch (err) {
    console.error(err);
    if (statusLine) statusLine.textContent = String(err.message || err).slice(0, 140);
  }
}

async function openGalleryItem(item) {
  galleryTarget = { name: item.name, source: item.name };
  sourceFile = null;
  sourceImg = null;
  cropEditing = false;
  if (statusLine) statusLine.textContent = `Loading simulation: ${item.name}`;
  markFrameLoading(item.comicUrl ? "both" : "epaper");

  try {
    // Format aus BMP-Metadaten (nicht nochmal aus Sim raten)
    if (item.width && item.height) {
      setOrientationFromSize(item.width, item.height, { announce: false });
    } else if (typeof item.portrait === "boolean") {
      setOrientationFromFlag(item.portrait, { announce: false });
    } else if (item.orientation === "landscape" || item.orientation === "portrait") {
      setOrientationFromFlag(item.orientation, { announce: false });
    }

    let toneExtra = "";
    // Neutraler Cover-Start; gespeicherte Settings überschreiben ggf. Fokus/Zoom
    if (zoomEl) zoomEl.value = "100";
    if (focusX) focusX.value = "50";
    if (focusY) focusY.value = "50";
    if (item.settingsUrl) {
      try {
        const s = await (await fetch(item.settingsUrl, { cache: "no-store" })).json();
        applyEpaperSettings(s.settings || {});
        if (s.source) galleryTarget.source = s.source;
        const st = s.settings || {};
        if (typeof st.portrait === "boolean") {
          setOrientationFromFlag(st.portrait, { announce: false });
        } else if (st.orientation === "landscape" || st.orientation === "portrait") {
          setOrientationFromFlag(st.orientation, { announce: false });
        } else if (Array.isArray(s.size) && s.size.length === 2) {
          setOrientationFromSize(s.size[0], s.size[1], { announce: false });
        }
        toneExtra = ` · C ${Math.round((st.contrast ?? 1) * 100)}% · W ${st.warmth ?? "?"} · Skin ${st.skin_tint ?? "?"}`;
      } catch (_) {
        /* ignore */
      }
    }
    updateSliderLabels();

    const simRes = await fetch(item.simUrl, { cache: "no-store" });
    if (!simRes.ok) throw new Error("Simulation failed");
    const simBlob = await simRes.blob();
    setImg(viewEpaper, emptyEpaper, simBlob, "epaper");
    if (labelEpaper) {
      labelEpaper.textContent = item.autotune
        ? `2 · E6 Sim · Auto-Tune`
        : `2 · E6 Sim · ${item.name}`;
    }

    if (item.comicUrl) {
      if (statusLine) statusLine.textContent = `Loading comic (on demand): ${item.name}`;
      const comicRes = await fetch(item.comicUrl, { cache: "no-store" });
      if (comicRes.ok) {
        const comicBlob = await comicRes.blob();
        lastComicBlob = comicBlob;
        if (comicPanel) {
          comicPanel.classList.remove("editing");
          comicPanel.classList.add("has-result", "has-preview");
        }
        if (cropCanvas) cropCanvas.style.display = "none";
        setImg(viewComic, emptyComic, comicBlob, "comic");
        if (labelComic) {
          labelComic.textContent = `1 · ${STYLES[styleId]?.name || styleId}`;
        }
      } else {
        emptyComic.classList.remove("hidden");
        emptyComic.querySelector(".empty-copy").textContent =
          "Comic not rebuildable (original missing) — E6 sim only. Re-render style = load a photo.";
        viewComic.hidden = true;
        lastComicBlob = null;
      }
    } else {
      emptyComic.classList.remove("hidden");
      emptyComic.querySelector(".empty-copy").textContent =
        "No comic for this BMP — contrast export not available.";
      viewComic.hidden = true;
      lastComicBlob = null;
    }

    // Original für Re-Crop laden (Zoom > 100% = Ränder abschneiden)
    const origOk = await attachGalleryOriginal(item);
    const orientTag = isPortrait ? "Port" : "Land";
    if (statusLine) {
      statusLine.textContent = origOk
        ? `${item.name} · ${orientTag} ${targetW}×${targetH}${toneExtra} · Zoom >100% crops edges · Save to /pic overwrites`
        : `${item.name} · ${orientTag} ${targetW}×${targetH}${toneExtra} · No original — re-crop needs a file upload`;
    }
    syncActionButtons();
  } catch (err) {
    console.error(err);
    if (statusLine) statusLine.textContent = String(err.message || err).slice(0, 140);
  }
}

/** Original aus Galerie anhängen, ohne Comic-Ergebnis zu verwerfen. */
async function attachGalleryOriginal(item) {
  const url = item.originalUrl || (item.name ? `/api/gallery/${encodeURIComponent(item.name)}/original` : null);
  if (!url) return false;
  try {
    const res = await fetch(url, { cache: "no-store" });
    if (!res.ok) return false;
    const blob = await res.blob();
    const headerName = res.headers.get("X-Original-Name");
    const name = item.originalName || headerName || `${baseStemFromName(item.name) || "portrait"}_original.png`;
    const file = new File([blob], name, { type: blob.type || "image/png" });
    sourceFile = file;
    galleryTarget.source = name;
    sourceImg = await loadSourceImage(file);
    lastFilename = name.replace(/\.[^.]+$/, "") || "portrait";
    updateSliderLabels();
    return true;
  } catch (err) {
    console.warn("Original for re-crop not loaded", err);
    return false;
  }
}

async function loadFile(file) {
  const keepTarget = fileMatchesGalleryTarget(file) ? { ...galleryTarget } : null;
  sourceFile = file;
  galleryTarget = keepTarget;
  if (keepTarget) {
    galleryTarget.source = file.name;
  }
  lastFilename = file.name.replace(/\.[^.]+$/, "") || "portrait";
  lastComicBlob = null;
  cancelPending();
  try {
    sourceImg = await loadSourceImage(file);
  } catch (err) {
    if (statusLine) statusLine.textContent = String(err.message || err);
    return;
  }
  if (!keepTarget) {
    // Neues Foto: neutraler Cover-Zuschnitt (Mitte, Zoom 100%) — kein Portrait-Bias
    resetCropParams();
    // Default: Format aus Quell-Seitenverhältnis; Nutzer kann danach überschreiben
    const oz = await detectOrientedSize(file, sourceImg);
    setOrientationFromSize(oz.w, oz.h, { announce: true });
  } else {
    // Galerie-Re-Crop: gewähltes / gespeichertes Format + Crop behalten
    syncFormatToggle();
  }
  viewEpaper.hidden = true;
  emptyEpaper.classList.remove("hidden");
  emptyEpaper.querySelector(".empty-copy").textContent =
    "Set the crop in the overview, then Confirm position / style.";
  // Bleibt in der Übersicht — kein Vollbild-Crop als erste Seite
  closeCropOverlay();
  enterCropEdit();
  syncActionButtons();
  if (statusLine) {
    const fmt = isPortrait ? `Portrait ${targetW}×${targetH}` : `Landscape ${targetW}×${targetH}`;
    statusLine.textContent = keepTarget
      ? `Overview · ${fmt} · overwrites ${keepTarget.name}`
      : `Loaded: ${file.name} · ${fmt} · crop in overview`;
  }
}

/** Neutraler Cover-Zuschnitt: Fokus Mitte, Zoom 100% (ausfüllen). */
function resetCropParams() {
  if (focusX) focusX.value = "50";
  if (focusY) focusY.value = "50";
  if (zoomEl) zoomEl.value = "100";
  updateSliderLabels();
}

function resetCrop() {
  resetCropParams();
  if (sourceFile) enterCropEdit();
}

function onCropControlInput() {
  updateSliderLabels();
  if (!sourceFile || !sourceImg) return;
  // Slider/Zoom: Zuschnitt ändern (auch nach Galerie-Öffnen mit geladenem Original)
  if (!cropEditing || lastComicBlob) {
    enterCropEdit();
  } else {
    drawCropPreview();
    if (!cropOverlay?.hidden) drawCropOverlay();
    if (statusLine) statusLine.textContent = "Crop · style not rendered yet";
  }
}

document.getElementById("fileInput").addEventListener("change", (e) => {
  const f = e.target.files?.[0];
  if (f) void loadFile(f);
});

function syncSwButton() {
  if (!btnSw) return;
  btnSw.classList.toggle("active", grayscaleOn);
  btnSw.textContent = grayscaleOn ? "B&W on · back to color" : "Convert to B&W";
}

function resetEpaperControls() {
  if (brightness) brightness.value = "50";
  if (contrast) contrast.value = "50";
  if (warmthEl) warmthEl.value = "50";
  if (skinTint) skinTint.value = "50";
  if (dither) dither.value = "100";
  if (ditherAlgo) ditherAlgo.value = "atkinson";
  if (colorDistance) colorDistance.value = "toon";
  grayscaleOn = false;
  syncSwButton();
  updateSliderLabels();
  if (lastComicBlob) scheduleDitherOnly();
  else if (statusLine) statusLine.textContent = "E-Paper reset";
}

btnExport.addEventListener("click", exportToPic);
document.getElementById("btnRefreshGallery").addEventListener("click", refreshGallery);
document.getElementById("btnAutotune")?.addEventListener("click", () => void runAutotuneAll());
document.getElementById("btnIntensive")?.addEventListener("click", () => void runIntensiveSearch());
document.getElementById("btnResetEpaper")?.addEventListener("click", resetEpaperControls);
document.getElementById("btnResetCrop")?.addEventListener("click", resetCrop);
btnApplyStyle?.addEventListener("click", () => void runStyleOnly());
btnApplyEpaper?.addEventListener("click", () => void runDitherOnly());
btnSw?.addEventListener("click", () => {
  grayscaleOn = !grayscaleOn;
  syncSwButton();
  if (lastComicBlob) scheduleDitherOnly();
});
syncSwButton();

document.querySelectorAll(".format-btn[data-format]").forEach((btn) => {
  btn.addEventListener("click", () => {
    setOutputFormat(btn.dataset.format, { announce: true });
  });
});

focusX.addEventListener("input", onCropControlInput);
focusY.addEventListener("input", onCropControlInput);
zoomEl?.addEventListener("input", onCropControlInput);

dither.addEventListener("input", scheduleDitherOnly);
ditherAlgo.addEventListener("change", scheduleDitherOnly);
colorDistance?.addEventListener("change", scheduleDitherOnly);
warmthEl?.addEventListener("input", scheduleDitherOnly);
skinTint?.addEventListener("input", scheduleDitherOnly);
brightness.addEventListener("input", scheduleDitherOnly);
contrast.addEventListener("input", scheduleDitherOnly);

function panByPixels(dxCss, dyCss) {
  if (!sourceImg) return;
  const { sw, sh, srcW, srcH } = sourceCropRect();
  const spanX = Math.max(1e-6, sw - srcW);
  const spanY = Math.max(1e-6, sh - srcH);
  // Im Overlay: Bild fest, Rahmen bewegen — Drag nach rechts → Fokus runter
  // dx in Quellpixeln: wenn Overlay offen, über fit umrechnen
  let dxSrc = dxCss;
  let dySrc = dyCss;
  if (overlayLayout && !cropOverlay?.hidden) {
    dxSrc = dxCss / Math.max(1e-6, overlayLayout.fit);
    dySrc = dyCss / Math.max(1e-6, overlayLayout.fit);
  } else if (comicPanel) {
    const rect = comicPanel.getBoundingClientRect();
    const zoom = zoomFactor();
    const scale = Math.max(rect.width / sw, rect.height / sh) * zoom;
    dxSrc = dxCss / scale;
    dySrc = dyCss / scale;
  }
  let fx = Number(focusX.value) / 100 - dxSrc / spanX;
  let fy = Number(focusY.value) / 100 - dySrc / spanY;
  fx = Math.max(0, Math.min(1, fx));
  fy = Math.max(0, Math.min(1, fy));
  focusX.value = String(Math.round(fx * 1000) / 10); // 0.1 %
  focusY.value = String(Math.round(fy * 1000) / 10);
  onCropControlInput();
}

/** Zoom-Fenster bei zoom-Faktor (1..3) in Quellpixeln. */
function cropWindowAt(zoom, fx, fy) {
  const sw = sourceImg.naturalWidth;
  const sh = sourceImg.naturalHeight;
  const cover = Math.max(targetW / sw, targetH / sh);
  const srcW = Math.min(sw, targetW / (cover * zoom));
  const srcH = Math.min(sh, targetH / (cover * zoom));
  const srcLeft = Math.max(0, (sw - srcW) * fx);
  const srcTop = Math.max(0, (sh - srcH) * fy);
  return { sw, sh, srcW, srcH, srcLeft, srcTop };
}

/**
 * Fokus so anpassen, dass Quellpunkt (sx,sy) nach Zoom-Änderung
 * weiterhin bei relativer Position (nx,ny) im Ausschnitt liegt.
 */
function retainFocusAt(sx, sy, nx, ny, zoomNew) {
  const fx0 = Number(focusX.value) / 100;
  const fy0 = Number(focusY.value) / 100;
  const { sw, sh, srcW, srcH } = cropWindowAt(zoomNew, fx0, fy0);
  const spanX = sw - srcW;
  const spanY = sh - srcH;
  if (spanX > 1e-6) {
    const fx = (sx - nx * srcW) / spanX;
    focusX.value = String(Math.round(Math.max(0, Math.min(1, fx)) * 1000) / 10);
  }
  if (spanY > 1e-6) {
    const fy = (sy - ny * srcH) / spanY;
    focusY.value = String(Math.round(Math.max(0, Math.min(1, fy)) * 1000) / 10);
  }
}

/** Zoom Richtung Cursor: Vorschau (crop-Fenster) oder Overlay (Vollbild). */
function zoomTowardPointer(clientX, clientY, zoomOld, zoomNew, mode) {
  if (!sourceImg || !Number.isFinite(clientX) || !Number.isFinite(clientY)) return;
  if (Math.abs(zoomNew - zoomOld) < 1e-9) return;

  const fx = Number(focusX.value) / 100;
  const fy = Number(focusY.value) / 100;
  const oldWin = cropWindowAt(zoomOld, fx, fy);

  if (mode === "overlay" && overlayLayout && cropOverlayCanvas) {
    const rect = cropOverlayCanvas.getBoundingClientRect();
    const cx = clientX - rect.left;
    const cy = clientY - rect.top;
    const sx = (cx - overlayLayout.ox) / Math.max(1e-6, overlayLayout.fit);
    const sy = (cy - overlayLayout.oy) / Math.max(1e-6, overlayLayout.fit);
    if (sx < 0 || sy < 0 || sx > oldWin.sw || sy > oldWin.sh) return;
    const nx = (sx - oldWin.srcLeft) / Math.max(1e-6, oldWin.srcW);
    const ny = (sy - oldWin.srcTop) / Math.max(1e-6, oldWin.srcH);
    retainFocusAt(sx, sy, nx, ny, zoomNew);
    return;
  }

  // Stage-1-Vorschau: Panel zeigt den aktuellen Ausschnitt
  if (!comicPanel) return;
  const rect = comicPanel.getBoundingClientRect();
  const nx = (clientX - rect.left) / Math.max(1e-6, rect.width);
  const ny = (clientY - rect.top) / Math.max(1e-6, rect.height);
  if (nx < 0 || nx > 1 || ny < 0 || ny > 1) return;
  const sx = oldWin.srcLeft + nx * oldWin.srcW;
  const sy = oldWin.srcTop + ny * oldWin.srcH;
  retainFocusAt(sx, sy, nx, ny, zoomNew);
}

function pointerOverPanel(el, clientX, clientY) {
  if (!el) return false;
  const r = el.getBoundingClientRect();
  return clientX >= r.left && clientX <= r.right && clientY >= r.top && clientY <= r.bottom;
}

function applyWheelZoom(e, mode = "preview") {
  if (!sourceImg || !zoomEl) return false;
  // Overlay offen, oder Vorschau mit geladenem Original (auch nach Galerie)
  if (mode === "preview" && !cropEditing && cropOverlay?.hidden && !sourceFile) return false;
  e.preventDefault();
  let dy = e.deltaY;
  if (e.deltaMode === 1) dy *= 16; // lines → px
  if (e.deltaMode === 2) dy *= 400; // pages → px
  // ~3 % pro typischem Notch (deltaY ≈ 100); Trackpad-Schritte kleiner
  const step = Math.max(1.5, Math.min(5, Math.abs(dy) * 0.03));
  const dir = dy > 0 ? -1 : 1;
  const zoomOldPct = Number(zoomEl.value);
  const next = Math.max(100, Math.min(300, zoomOldPct + dir * step));
  const zoomNewPct = Math.round(next * 4) / 4;
  zoomEl.value = String(zoomNewPct);
  zoomTowardPointer(e.clientX, e.clientY, zoomOldPct / 100, zoomNewPct / 100, mode);
  onCropControlInput();
  return true;
}

function bindDragTarget(el) {
  if (!el) return;
  el.addEventListener("pointerdown", (e) => {
    if (!sourceImg) return;
    if (e.button !== 0) return;
    if (cropOverlay?.hidden) enterCropEdit();
    el.classList?.add?.("dragging");
    cropOverlay?.classList.add("dragging");
    comicPanel?.classList.add("dragging");
    try {
      el.setPointerCapture(e.pointerId);
    } catch (_) {
      /* ignore */
    }
    drag = { x: e.clientX, y: e.clientY, target: el };
  });
  el.addEventListener("pointermove", (e) => {
    if (!drag || drag.target !== el) return;
    const dx = e.clientX - drag.x;
    const dy = e.clientY - drag.y;
    drag = { x: e.clientX, y: e.clientY, target: el };
    panByPixels(dx, dy);
  });
  const end = (e) => {
    if (!drag || drag.target !== el) return;
    drag = null;
    el.classList?.remove?.("dragging");
    cropOverlay?.classList.remove("dragging");
    comicPanel?.classList.remove("dragging");
    try {
      el.releasePointerCapture(e.pointerId);
    } catch (_) {
      /* ignore */
    }
  };
  el.addEventListener("pointerup", end);
  el.addEventListener("pointercancel", end);
}

bindDragTarget(cropOverlayCanvas);
bindDragTarget(comicPanel);

// Mausrad-Zoom: Overlay oder Stage-1-Vorschau (gleiche Steuerung wie Zoom-Slider)
window.addEventListener(
  "wheel",
  (e) => {
    if (!sourceImg || !zoomEl) return;
    if (!cropOverlay?.hidden) {
      applyWheelZoom(e, "overlay");
      return;
    }
    if (!pointerOverPanel(comicPanel, e.clientX, e.clientY)) return;
    // Nach Galerie-Auto-Load: Original da → Rad startet Re-Crop
    if (!cropEditing && !sourceFile) return;
    applyWheelZoom(e, "preview");
  },
  { passive: false },
);

document.getElementById("btnCropDone")?.addEventListener("click", () => {
  closeCropOverlay();
  drawCropPreview();
  if (statusLine) statusLine.textContent = "Crop set · render style now";
});

document.getElementById("btnCropReset")?.addEventListener("click", () => {
  resetCrop();
});

comicPanel?.addEventListener("dblclick", () => {
  if (sourceImg) {
    cropEditing = true;
    openCropOverlay();
    drawCropPreview();
  }
});

window.addEventListener("resize", () => {
  if (cropEditing && sourceImg) {
    drawCropPreview();
    if (!cropOverlay?.hidden) drawCropOverlay();
  }
});

window.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && cropOverlay && !cropOverlay.hidden) {
    closeCropOverlay();
    drawCropPreview();
  }
});

window.addEventListener("dragover", (e) => e.preventDefault());
window.addEventListener("drop", (e) => {
  e.preventDefault();
  const f = e.dataTransfer?.files?.[0];
  if (f?.type.startsWith("image/")) void loadFile(f);
});

buildStyles();
buildSwatches();
updateSliderLabels();
updateStyleHeading();
syncActionButtons();
setOrientationFromFlag(true, { announce: false });
refreshGallery();

fetch("/api/meta")
  .then((r) => r.json())
  .then((m) => {
    if (statusLine && !sourceFile) {
      statusLine.textContent = `v${m.version || "?"} · Style: ${STYLES[styleId].name}`;
    }
    console.log("Portrait Lab", m.version, m.styles?.map((s) => s.id));
  })
  .catch((e) => console.error("meta", e));
