# Portrait Lab

**Lokales Vorbereitungswerkzeug für Spectra-6-(E6)-E-Paper-Porträts.**

Portrait Lab macht aus einem Foto ein gerätefertiges **24-Bit-BMP** für den **Waveshare ESP32-S3 PhotoPainter** (Amazon PhotoPainter E6): nur sechs Farben — Schwarz, Weiß, Grün, Blau, Rot, Gelb. Stil und Zuschnitt am PC; das BMP kommt auf die TF-/microSD-Karte fürs Display.

> **Datenschutz & Rechte:** Keine privaten oder modern urheberrechtlich geschützten Fotos committen. Eigene Bilder lokal in `original/`. Modellgewichte in `models/` (gitignored).  
> **Gemeinfreies Demo (Da Vinci):** [`original/mona_lisa.png`](original/mona_lisa.png) → [`pic/mona_lisa_auto_at.bmp`](pic/mona_lisa_auto_at.bmp) — Leonardos *Mona Lisa* ist **gemeinfrei**; Reproduktion von Wikimedia Commons (PD). Siehe [`original/mona_lisa.SOURCE.md`](original/mona_lisa.SOURCE.md).  
> **Synthetisches Demo (CC0):** [`examples/demo_portrait.png`](examples/demo_portrait.png) — keine echte Person ([`examples/LICENSE`](examples/LICENSE)).

**English:** [README.md](README.md)

---

## Wozu das Programm?

E-Paper Spectra 6 ist **kein normales RGB-Display**. Es kann nur **sechs feste Farben** zeigen. Ein Foto einfach zu verkleinern und zu speichern wirkt auf dem Panel oft matschig, fleckig oder „posterartig“.

Portrait Lab ist die **Vorbereitung am PC**, bevor das Bild auf den Rahmen kommt:

1. Hoch-/Querformat und Ausschnitt festlegen.
2. **Stufe 1 – Stil**, damit Gesichter und Kanten mit wenigen Farben lesbar bleiben.
3. **Stufe 2 – Dithering** in die Spectra-6-Palette (Vorschau ≈ Panel).
4. Klassisches BMP + Settings-JSON nach `pic/` exportieren → auf die TF-Karte → in den PhotoPainter.

Nichts wird hochgeladen. Der Server lauscht nur auf `127.0.0.1`.

---

## Pipeline (zwei Stufen)

```text
Foto → Zuschnitt / Ausrichtung → Stufe 1 (Stil) → Stufe 2 (E6-Dither) → BMP in pic/
```

| Stufe | Aufgabe | Ergebnis |
|-------|---------|----------|
| **Zuschnitt** | Cover-Fit auf 480×800 oder 800×480; Fokus + Zoom | gerahmtes RGB |
| **Stufe 1** | Stil / Prep (AnimeGANv3, Ölbild, Forum-Look, Full Auto) | „Comic“-Vorschau (nur im Speicher) |
| **Stufe 2** | Tonwerte + Spectra-6-Dither | Monitor-Simulation + Geräte-BMP |

- **Hochformat:** 480×800  
- **Querformat:** 800×480  
- **Export:** unkomprimiertes **24-Bit-BMP** (Waveshare-Anforderung)  
- **Palette:** Spectra 6 — Schwarz, Weiß, Grün, Blau, Rot, Gelb  

Ordner:

| Ordner | Zweck |
|--------|--------|
| `original/` | Quellbilder (nur lokal — gitignored) |
| `pic/` | fertige BMPs + `*_settings.json` (nur lokal — gitignored) |
| `models/` | ONNX-Gewichte (nur lokal — gitignored) |
| `epaper/` | Pipeline-Code |
| `static/` | Web-UI |

---

## Schnellstart

**Voraussetzung:** Python 3.10+ empfohlen, Windows OK (`start.bat`).

1. Doppelklick auf `start.bat`  
   - legt `.venv` an  
   - installiert `requirements.txt`  
   - startet die App unter **http://127.0.0.1:8765**
2. ONNX-Modelle nach `models/` legen (siehe [Modelle](#modelle)).
3. Foto öffnen → Zuschnitt → berechnen → **Save to /pic**.
4. BMP aus `pic/` auf die PhotoPainter-TF-Karte kopieren.

Oder:

```bat
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python server.py
```

---

## Stufe 1 — Stile (Modi)

Stil wählen, dann **Confirm position · render**.

| Modus | ID | Bedeutung |
|-------|-----|-----------|
| **Full Auto** | `auto` | Empfohlener Weg: Blitz/Cast leicht kühlen → **AnimeGANv3 Hayao** → leichter Kontrast, etwas weniger Sättigung. **Kein** Auto-Zuschnitt; Framing bleibt bei dir. |
| **Portrait (Forum)** | `portrait` | Klassische Gesichts-Aufbereitung (Toon-nooT-Nähe): mehr Kontrast, leichte Sättigung, Schärfe, Schatten anheben, Edge-Prep. **Kein** neuronales Stilnetz. |
| **Anime Comic** | `anime` | Nur **AnimeGANv3 Hayao** — klarer Comic-/Anime-Look. |
| **Oil painting** | `oil` | Ölbild-Look per OpenCV (`cv2.xphoto.oilPainting`), kein Neural-Style-Modell. |
| **Shinkai** | `shinkai` | **AnimeGANv3 Shinkai** — weicherer, atmosphärischer Anime-Look. |

---

## Stufe 2 — E-Paper-Regler

Nach Stufe 1. Die Vorschau nutzt **wahrgenommene** Farben (Monitor). Der Export schreibt **Geräte-RGB** (reine 0/255-Kanäle fürs Panel).

| Regler | Bedeutung |
|--------|-----------|
| **Brightness / Contrast** | Tonwerte vor dem Dither (Mitte = neutral). |
| **Warmth** | Global kühl ↔ warm. |
| **Skin** | Hautton rosa ↔ gelb (hilft bei Spectra-„Pfirsich“ aus Weiß/Gelb/Rot). |
| **Dither strength** | Stärke von Error-Diffusion / Blue Noise (0 = schwach, 100 = voll). |
| **Algorithm** | Siehe Dither-Modi unten. |
| **Color distance** | Wie Farben auf die 6 Tinten gematcht werden. |
| **Convert to B&W** | Nur Schwarz + Weiß. |
| **Re-run E-Paper** | Neu dithern ohne Stufe 1 erneut. |

### Dither-Algorithmen

| Algorithmus | ID | Wann |
|-------------|-----|------|
| **Atkinson (Portrait)** | `atkinson` | Standard für Gesichter — sauberere Mitttöne, weniger matschige Haut. |
| **Floyd–Steinberg** | `floyd` | Klassische Error-Diffusion; oft körniger. |
| **Blue Noise** | `bluenoise` | Geordnetes Blue-Noise — stabiles Korn, weniger Richtungsartefakte. |
| **No dither** | `none` | Harte Quantisierung (Poster-Look). |

### Farbabstand

| Modus | ID | Bedeutung |
|-------|-----|-----------|
| **Toon-nooT (Default)** | `toon` | Semantisches / hue-priorisiertes Matching für diese Spectra-Pipeline (Haut, Himmel, Neutrale). |
| **CIE L\*a\*b\*** | `lab` | Perzeptueller Lab-Abstand (CIE76-ähnlich). |

---

## Zuschnitt & Ausrichtung

- **Portrait (480×800)** oder **Landscape (800×480)**.
- **Cover**-Fit: Bild füllt die Fläche; Ränder können abgeschnitten werden.
- **Zoom 100 %** = minimaler Cover. Höher = engerer Ausschnitt.
- **Focus X / Y** = Ankerpunkt.
- Ziehen = Pan, Mausrad = Zoom; Doppelklick = Vollbild-Zuschnitt.
- **Confirm position · render** startet Stufe 1 (und Stufe 2 für die Paar-Vorschau).
- EXIF-Ausrichtung wird beim Laden angewendet.

---

## Intensiv-Suche & Auto-Tune

### Intensiv-Suche (ein Foto)

Braucht geladenes Foto + Zuschnitt. Speichert **nicht** automatisch.

1. Baut eine **BiSeNet**-Hautmaske (sonst Farb-Heuristik).
2. **Phase A:** alle fünf Stufe-1-Stile × grobes Stufe-2-Raster.  
3. **Phase B:** Top-Stile mit feinerem Raster (Ton, Dither, Farbabstand).  
4. Beste Vorschau in der UI. Mit **Save to /pic** behalten.

Typisch **ca. 3–8 Minuten** auf CPU (je nach Rechner). Abbrechbar.

### Auto-Tune alle Originale

Batch über `original/` (Server-Limit typisch **50** pro Lauf). Pro Bild Stufe-2-Suche (mit Stufe 1), dann **Schreiben** von `{name}_{style}_at.bmp` + Settings nach `pic/`. Vorhandene Paare werden übersprungen. Kann mehrere Minuten dauern.

---

## Galerie (`/pic`)

- **Klick:** Monitor-**Simulation** des Geräte-BMPs; Stufe-1-Comic aus `original/` + Settings, falls möglich.
- **Rechtsklick:** BMP + Settings löschen (inkl. bekannter Companion-Dateien).
- **Save to /pic** bei geöffnetem Galerie-Eintrag: Überschreiben bestätigen.
- Neue Exporte bekommen einen neuen Namen (bei Kollision `_2`, `_3`, …).
- Stufe-1-Comic-PNGs liegen **nicht** unter `pic/` auf der Platte.

---

## Modelle

Unter `models/` ablegen (nicht im Git):

| Datei | Verwendung |
|-------|------------|
| `AnimeGANv3_Hayao_36.onnx` | Full Auto, Anime Comic |
| `AnimeGANv3_Shinkai_37.onnx` | Shinkai |
| `bisenet_face_parsing_resnet18.onnx` | Hautmaske Intensiv-Suche |

Aus dem Repo (kleine Binärdatei): `epaper/bluenoise64.bin` für Blue-Noise-Dither.  
**Oil painting** braucht OpenCV Contrib (`opencv-contrib-python-headless` in `requirements.txt`), kein ONNX.

Manche Modelle können beim ersten Start fehlen und ggf. heruntergeladen werden — besser selbst ablegen.

---

## Typischer Ablauf (PhotoPainter)

1. Eigene Fotos mit Nutzungsrechten in `original/` (optional) oder Datei in der UI öffnen.  
2. Ausrichtung und Zuschnitt so setzen, dass Motiv/Gesicht gut füllt.  
3. Für Personen oft **Full Auto** oder **Portrait (Forum)**; Anime / Shinkai / Oil für einen Look.  
4. Stufe 2 (Wärme / Haut / Atkinson) feinjustieren, bis die rechte Vorschau passt.  
5. Optional: **Intensive search**.  
6. **Save to /pic** → BMP auf die TF-Karte → in den PhotoPainter.

---

## API (lokal)

FastAPI-App (`server.py`), Standard **http://127.0.0.1:8765**.

Nützliche Endpunkte: `/api/meta`, `/api/render`, `/api/dither`, `/api/export`, `/api/gallery`, `/api/autotune`, `/api/autotune-one` (+ Status/Cancel).

---

## Projektstruktur

```text
PortraitLab/
  start.bat          # Windows-Starter
  server.py          # FastAPI + Uvicorn
  requirements.txt
  examples/          # CC0-Demo (darf ins Repo)
  static/            # Web-UI
  epaper/            # Stil, Dither, Export, Autotune
  models/            # ONNX (gitignored) + .gitkeep
  original/          # Quellen (gitignored) + .gitkeep
  pic/               # Exporte (gitignored) + .gitkeep
```

---

## Lizenz

**Anwendungscode & UI:** siehe [`LICENSE`](LICENSE) — **nicht-kommerziell**.

| Erlaubt | Nicht erlaubt |
|---------|----------------|
| Herunterladen; exakte unveränderte Kopien | **Kommerzielle Nutzung** (Verkauf, bezahlter Dienst, Produkt) |
| Private, persönliche, nicht-kommerzielle Nutzung | Kommerzielles Produkt auf Basis dieses Codes |
| | Veränderte Versionen verbreiten; neu lizenzieren; Hinweise entfernen |

Ziel: Andere dürfen anschauen, kopieren und privat nutzen — aber **nicht kommerzialisieren**.

Demo-Assets nur dort anders, wo gekennzeichnet (z. B. CC0-Demo, gemeinfreie Mona Lisa — siehe deren `SOURCE` / `LICENSE`).

### Inhaltsregeln (für Pflege des Repos)

- Keine privaten oder modern urheberrechtlich geschützten Fotos committen.  
- Keine ONNX-Gewichte committen ohne Weitergaberechte.  
- Drittanbieter-Modelle (AnimeGANv3, BiSeNet, …) behalten ihre Upstream-Lizenzen.
