"""Project directories.



- ``original/`` — Quellbilder only (``*_original.*``, Fotos)

- ``pic/`` — fertige ESP32-Exporte only (BMP + optional ``*_settings.json``)



Kein ``tmp/`` — Previews/Reports bleiben im Speicher bzw. stdout.

Originale gehören nie nach ``pic/``.

"""



from __future__ import annotations



from pathlib import Path



ROOT = Path(__file__).resolve().parent.parent

PIC_DIR = ROOT / "pic"

ORIGINAL_DIR = ROOT / "original"

STATIC_DIR = ROOT / "static"

MODELS_DIR = ROOT / "models"





def ensure_dirs() -> None:

    """Create standard project folders (no content). Never creates tmp/."""

    PIC_DIR.mkdir(parents=True, exist_ok=True)

    ORIGINAL_DIR.mkdir(parents=True, exist_ok=True)





# Sidecars next to a fertigen Export (stem.bmp). Comic-PNGs werden nicht mehr geschrieben.

GALLERY_COMPANION_SUFFIXES: tuple[str, ...] = (

    "_settings.json",

)





def is_gallery_bmp(path: Path) -> bool:

    """Nur fertige Geräte-BMPs — keine Underscore-/Preview-/Quell-/Debug-Dateien."""

    if path.suffix.lower() != ".bmp":

        return False

    name = path.name

    if name.startswith("_") or name.startswith("."):

        return False

    low = name.lower()

    for marker in (

        "_preview",

        "_bad_",

        "_src",

        "_original",

        "_inspect",

        "_fix",

        "_diag",

    ):

        if marker in low:

            return False

    # Export/Autotune schreibt immer Settings; nackte Agent-BMPs ausfiltern

    if not (path.parent / f"{path.stem}_settings.json").is_file():

        return False

    return True





def gallery_export_files(bmp_path: Path) -> list[Path]:

    """BMP + paired companions for one gallery export (same stem), only under pic/.



    Matches known sidecars and any other ``{stem}_*`` non-BMP artifact (legacy

    comic PNGs etc.). Never includes a different gallery BMP (e.g. ``stem_1.bmp``)

    or that export's own sidecars (e.g. ``stem_1_settings.json``).

    """

    bmp_path = Path(bmp_path)

    if not is_gallery_bmp(bmp_path):

        return []

    pic = PIC_DIR.resolve()

    try:

        resolved = bmp_path.resolve()

        if resolved.parent != pic:

            return []

    except OSError:

        return []



    stem = resolved.stem

    found: list[Path] = [resolved]

    seen = {resolved.name.lower()}



    for suffix in GALLERY_COMPANION_SUFFIXES:

        candidate = (PIC_DIR / f"{stem}{suffix}").resolve()

        key = candidate.name.lower()

        if key in seen:

            continue

        if candidate.is_file() and candidate.parent == pic:

            found.append(candidate)

            seen.add(key)



    # Longer gallery stems under this prefix (stem_1, stem_2, …) keep their own files.

    sibling_stems = [

        p.stem

        for p in PIC_DIR.glob("*.bmp")

        if p.stem.startswith(f"{stem}_") and is_gallery_bmp(p)

    ]



    prefix = f"{stem}_"

    try:

        entries = list(PIC_DIR.iterdir())

    except OSError:

        entries = []

    for entry in entries:

        if not entry.is_file():

            continue

        key = entry.name.lower()

        if key in seen or not entry.name.startswith(prefix):

            continue

        # Other numbered/variant BMPs are separate exports — leave them alone.

        if entry.suffix.lower() == ".bmp":

            continue

        if any(

            entry.name.startswith(f"{sib}_") or entry.stem == sib for sib in sibling_stems

        ):

            continue

        try:

            candidate = entry.resolve()

        except OSError:

            continue

        if candidate.parent != pic:

            continue

        found.append(candidate)

        seen.add(key)



    return found





_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}





_EXPORT_STEM_SUFFIXES = ("_auto_at", "_auto_autotune", "_autotune", "_at")


def strip_export_stem_suffix(stem: str) -> str:
    """vermeer_pearl_auto_at → vermeer_pearl (Export-/Autotune-Suffixe)."""
    low = stem.lower()
    for suffix in _EXPORT_STEM_SUFFIXES:
        if low.endswith(suffix):
            return stem[: -len(suffix)]
    return stem


def resolve_original(settings: dict, bmp_stem: str) -> Path | None:

    """Find source image under original/ from settings or BMP stem."""

    candidates: list[Path] = []

    def add_slug(slug: str) -> None:
        slug = strip_export_stem_suffix(Path(slug).stem if Path(slug).suffix else slug)
        if not slug:
            return
        for ext in (".png", ".jpg", ".jpeg", ".webp"):
            candidates.append(ORIGINAL_DIR / f"{slug}_original{ext}")
            candidates.append(ORIGINAL_DIR / f"{slug}{ext}")

    for key in ("original", "source"):

        raw = settings.get(key)

        if not raw:

            continue

        name = Path(str(raw)).name

        suf = Path(name).suffix.lower()

        if suf in _IMAGE_EXTS:

            candidates.append(ORIGINAL_DIR / name)
            add_slug(name)

        else:

            add_slug(name)

    add_slug(bmp_stem)

    seen: set[str] = set()

    for path in candidates:

        key = str(path.resolve()) if path.exists() else str(path)

        if key in seen:

            continue

        seen.add(key)

        if path.is_file():

            return path

    return None


