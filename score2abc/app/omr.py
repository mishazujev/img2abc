"""Optical music recognition with Audiveris, run as a command-line batch job."""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from PIL import Image, ImageOps

IMAGE_EXT = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".gif", ".webp"}
PDF_EXT = {".pdf"}

AUDIVERIS = os.environ.get("AUDIVERIS_BIN", "/opt/audiveris/bin/Audiveris")
TIMEOUT = int(os.environ.get("OMR_TIMEOUT", "900"))
MAX_PAGES = int(os.environ.get("MAX_PAGES", "20"))
# Audiveris works best when a staff line gap is ~20px: roughly 300 DPI scans.
MIN_WIDTH = 2000


class OmrError(Exception):
    def __init__(self, message: str, log: str = ""):
        super().__init__(message)
        self.log = log


def audiveris_available() -> bool:
    return Path(AUDIVERIS).exists() or shutil.which(AUDIVERIS) is not None


def prepare_input(files: list[Path], workdir: Path) -> Path:
    """Turn the uploaded files into a single Audiveris input (one 'book').

    A single PDF is passed through. Images are cleaned up (orientation from
    EXIF, grayscale, upscaled when small) and bundled into one PDF so a
    multi-page score stays one piece of music.
    """
    pdfs = [f for f in files if f.suffix.lower() in PDF_EXT]
    images = [f for f in files if f.suffix.lower() in IMAGE_EXT]
    if pdfs and images:
        raise OmrError("Please upload either one PDF or a set of images, not both.")
    if len(pdfs) > 1:
        raise OmrError("Please upload one PDF at a time.")
    if pdfs:
        return pdfs[0]
    if not images:
        raise OmrError("No supported files. Use PDF, PNG, JPG or TIFF.")
    if len(images) > MAX_PAGES:
        raise OmrError(f"At most {MAX_PAGES} pages per score.")

    pages = []
    for f in images:
        try:
            img = Image.open(f)
            img = ImageOps.exif_transpose(img)
        except Exception as exc:  # noqa: BLE001 - report any decoding problem
            raise OmrError(f"Could not read image {f.name}: {exc}") from exc
        if img.mode in ("RGBA", "LA", "P"):
            bg = Image.new("RGB", img.size, "white")
            bg.paste(img.convert("RGBA"), mask=img.convert("RGBA").split()[-1])
            img = bg
        img = img.convert("L")
        if img.width < MIN_WIDTH:
            scale = MIN_WIDTH / img.width
            img = img.resize((MIN_WIDTH, round(img.height * scale)), Image.LANCZOS)
        pages.append(img)

    out = workdir / "score.pdf"
    pages[0].save(out, "PDF", resolution=300.0, save_all=True, append_images=pages[1:])
    return out


def run_audiveris(source: Path, outdir: Path) -> tuple[list[Path], str]:
    """Run Audiveris; return the exported MusicXML files and the log."""
    if not audiveris_available():
        raise OmrError("The Audiveris OMR engine is not installed on this server. "
                       "You can still convert MusicXML files to ABC.")
    outdir.mkdir(parents=True, exist_ok=True)
    cmd = [AUDIVERIS, "-batch", "-transcribe", "-export",
           "-output", str(outdir), "-sheets", f"1-{MAX_PAGES}", "--", str(source)]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=TIMEOUT)
    except subprocess.TimeoutExpired as exc:
        raise OmrError(f"Recognition took longer than {TIMEOUT // 60} minutes and was stopped.",
                       (exc.stdout or "") if isinstance(exc.stdout, str) else "") from exc
    log = (proc.stdout or "") + (proc.stderr or "")
    results = sorted(outdir.rglob("*.mxl"), key=_movement_order)
    if not results:
        hint = "No music was recognised."
        low = log.lower()
        if "interline" in low or "too low resolution" in low:
            hint += " The image resolution looks too low; try a 300 DPI scan."
        elif "no staves" in low or "no staff" in low:
            hint += " No staves were found; make sure the page shows printed sheet music."
        raise OmrError(hint, log)
    return results, log


def _movement_order(path: Path):
    stem = path.stem  # name or name.mvt2
    if ".mvt" in stem:
        try:
            return (1, int(stem.rsplit(".mvt", 1)[1]))
        except ValueError:
            pass
    return (0, 0)
