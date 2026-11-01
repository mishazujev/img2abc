"""Score2ABC web app: upload sheet music, get ABC notation back."""
from __future__ import annotations

import os
import re
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import omr
from .jobs import JobQueue
from .mxl2abc import convert

MAX_UPLOAD_MB = int(os.environ.get("MAX_UPLOAD_MB", "30"))
STATIC = Path(__file__).resolve().parent.parent / "static"
MUSICXML_EXT = {".mxl", ".musicxml", ".xml"}

app = FastAPI(title="Score2ABC", docs_url="/api/docs", openapi_url="/api/openapi.json")
jobs = JobQueue()


def client_id(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for", "")
    return fwd.split(",")[0].strip() or (request.client.host if request.client else "unknown")


def safe_name(name: str, index: int) -> str:
    stem, ext = os.path.splitext(os.path.basename(name or "upload"))
    stem = re.sub(r"[^A-Za-z0-9_-]+", "_", stem)[:40] or "page"
    return f"{index:03d}_{stem}{ext.lower()}"


async def save_uploads(files: list[UploadFile], dest: Path, allowed: set[str]) -> list[Path]:
    total = 0
    saved = []
    for i, up in enumerate(files):
        ext = os.path.splitext(up.filename or "")[1].lower()
        if ext not in allowed:
            raise HTTPException(400, f"Unsupported file type: {up.filename}")
        path = dest / safe_name(up.filename or "", i)
        with path.open("wb") as fh:
            while chunk := await up.read(1 << 20):
                total += len(chunk)
                if total > MAX_UPLOAD_MB * 1024 * 1024:
                    raise HTTPException(413, f"Upload is larger than {MAX_UPLOAD_MB} MB.")
                fh.write(chunk)
        saved.append(path)
    return saved


@app.get("/api/health")
def health():
    return {"ok": True, "omr": omr.audiveris_available(), "max_pages": omr.MAX_PAGES,
            "max_upload_mb": MAX_UPLOAD_MB}


@app.post("/api/jobs")
async def create_job(request: Request, files: list[UploadFile] = File(...)):
    if not files:
        raise HTTPException(400, "No files uploaded.")
    if len(files) > omr.MAX_PAGES:
        raise HTTPException(400, f"At most {omr.MAX_PAGES} files per score.")
    job_id, workdir = jobs.new_workdir()
    saved = await save_uploads(files, workdir / "in", omr.IMAGE_EXT | omr.PDF_EXT)
    try:
        job = jobs.submit(job_id, workdir, saved, client_id(request))
    except RuntimeError as exc:
        raise HTTPException(429, str(exc)) from exc
    _, pos = jobs.get(job.id)
    return job.public(pos)


@app.get("/api/jobs/{job_id}")
def job_status(job_id: str):
    job, pos = jobs.get(job_id)
    if not job:
        raise HTTPException(404, "Job not found or expired.")
    return job.public(pos)


@app.get("/api/jobs/{job_id}/musicxml/{index}")
def job_musicxml(job_id: str, index: int):
    job, _ = jobs.get(job_id)
    if not job or index < 0 or index >= len(job.musicxml):
        raise HTTPException(404, "File not found.")
    path = job.musicxml[index]
    return FileResponse(path, filename=path.name,
                        media_type="application/vnd.recordare.musicxml")


@app.post("/api/musicxml")
async def from_musicxml(file: UploadFile = File(...)):
    """Convert an existing MusicXML file straight to ABC (no OMR needed)."""
    data = await file.read(MAX_UPLOAD_MB * 1024 * 1024 + 1)
    if len(data) > MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(413, f"Upload is larger than {MAX_UPLOAD_MB} MB.")
    if os.path.splitext(file.filename or "")[1].lower() not in MUSICXML_EXT:
        raise HTTPException(400, "Please upload a .mxl, .musicxml or .xml file.")
    try:
        return {"abc": convert(data)}
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(422, f"Could not read this MusicXML file: {exc}") from exc


@app.exception_handler(HTTPException)
async def http_error(_, exc: HTTPException):
    return JSONResponse({"error": exc.detail}, status_code=exc.status_code)


app.mount("/", StaticFiles(directory=STATIC, html=True), name="static")
