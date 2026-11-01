---
title: Score2ABC
emoji: 🎼
colorFrom: indigo
colorTo: blue
sdk: docker
app_port: 7860
pinned: false
short_description: Convert piano sheet music images and PDFs to ABC notation
---

# Score2ABC

Convert piano sheet music from a photo, scan or PDF into editable [ABC notation](https://abcnotation.com/).

Upload pages → [Audiveris](https://github.com/Audiveris/audiveris) recognises the music and writes MusicXML → a built-in converter turns it into ABC → the result is drawn, played and edited in the browser with [abcjs](https://www.abcjs.net/).

Features:

- PDF or multi-page image upload (PNG, JPG, TIFF, WebP), with page reordering
- Direct MusicXML (`.mxl`, `.musicxml`) to ABC conversion
- Live ABC editor with score preview and audio playback
- Downloads: `.abc`, MIDI, and the intermediate MusicXML
- Piano-aware output: one ABC voice per staff/voice, braced grand staff via `%%score`, key/meter changes, ties, tuplets, grace notes, repeats and endings, dynamics and articulations

## Project layout

```
app/
  main.py      FastAPI app: upload, job status, downloads, static site
  jobs.py      in-memory job queue (one OMR run at a time, results kept 1 h)
  omr.py       input preparation (images → PDF) and the Audiveris CLI call
  mxl2abc.py   MusicXML → ABC converter (also usable on its own)
static/        the website (plain HTML/CSS/JS, abcjs vendored)
tests/         pytest suite; uses a fake Audiveris so it runs anywhere
docs/PLAN.md   roadmap
Dockerfile     production image (Ubuntu 24.04 + Audiveris .deb + Python)
```

## Run locally

With Docker (includes Audiveris):

```bash
docker build -t score2abc .
docker run -p 7860:7860 score2abc
# open http://localhost:7860
```

Without Docker (MusicXML conversion works; image/PDF recognition needs Audiveris installed at `/opt/audiveris/bin/Audiveris` or `AUDIVERIS_BIN`):

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 7860
```

Converter only:

```bash
python -m app.mxl2abc score.mxl > score.abc
```

## Tests

```bash
pip install pytest httpx music21   # music21 is optional (corpus tests)
pytest
```

## Deploy to Hugging Face Spaces (free)

1. Create a Space at <https://huggingface.co/new-space>: SDK **Docker**, template **Blank**, hardware **CPU basic (free)**.
2. Create a Hugging Face access token with **write** permission (Settings → Access Tokens).
3. In this GitHub repo: Settings → Secrets and variables → Actions →
   - secret `HF_TOKEN` = the token
   - variable `HF_SPACE` = `your-hf-username/your-space-name`
4. Push to `main` (or run the *Deploy to Hugging Face* workflow by hand). The Space builds the Docker image (≈5–10 min the first time) and goes live at `https://huggingface.co/spaces/<user>/<space>`.

Free Spaces sleep after 48 h without visitors and wake on the next visit (about a minute).

## Configuration

Environment variables (all optional):

| Variable | Default | Meaning |
|---|---|---|
| `AUDIVERIS_BIN` | `/opt/audiveris/bin/Audiveris` | Audiveris launcher |
| `OMR_TIMEOUT` | `900` | seconds before a recognition run is stopped |
| `OMR_WORKERS` | `1` | parallel recognitions (each needs ~1–2 GB RAM) |
| `MAX_PAGES` | `20` | pages per score |
| `MAX_UPLOAD_MB` | `30` | upload size limit |
| `MAX_QUEUE` | `20` | waiting jobs before new ones are refused |
| `MAX_JOBS_PER_CLIENT` | `2` | active jobs per IP address |
| `JOB_TTL` | `3600` | seconds results are kept |

## API

- `POST /api/jobs` — multipart `files` (one PDF or images in page order) → job
- `GET /api/jobs/{id}` — `status` (`queued` / `running` / `done` / `error`), `position`, `abc`, `error`
- `GET /api/jobs/{id}/musicxml/{n}` — recognised MusicXML
- `POST /api/musicxml` — multipart `file` (MusicXML) → `{ "abc": ... }`
- Interactive docs at `/api/docs`

## Licences

This project: MIT. Audiveris (AGPL-3.0) runs as a separate program inside the container; abcjs is MIT.
