# Score2ABC — plan

## Goal

A public website where anyone can upload a piano score (photo, scan or PDF) and get ABC notation they can check, edit, play and download.

## Architecture

```
browser ──upload──▶ FastAPI ──▶ job queue ──▶ Audiveris (OMR, CLI batch)
   ▲                                              │ MusicXML (.mxl)
   │                                              ▼
   └──── ABC + MusicXML ◀──── mxl2abc converter ◀─┘
abcjs in the browser: render, play, MIDI export, live editing
```

- One Docker image (Ubuntu 24.04, Audiveris .deb with bundled Java, Python 3, Tesseract language data).
- Hosted on a Hugging Face Docker Space (free CPU tier: 2 vCPU, 16 GB RAM).
- GitHub is the source of truth; a GitHub Action runs tests and uploads to the Space.

## Milestones

### M1 — MVP (done in this first version)
- [x] MusicXML → ABC converter for piano (grand staff, multiple voices, chords, ties, tuplets, grace notes, repeats/endings, key/meter/clef changes, dynamics, articulations)
- [x] Audiveris wrapper: image clean-up (EXIF rotation, grayscale, upscaling), multi-image → one PDF, timeouts, helpful errors
- [x] Job queue with queue position, per-IP limits, auto-cleanup after 1 h
- [x] Web UI: drag-and-drop/paste upload, page reordering, progress, ABC editor with live preview and playback, downloads (ABC, MIDI, MusicXML), sample score, dark mode, mobile layout
- [x] Tests (converter fixtures, music21 corpus smoke tests, API with a fake Audiveris)
- [x] Dockerfile + GitHub Action deploying to Hugging Face

### M2 — Accuracy and trust
- [ ] Collect a small benchmark set of real piano scans and measure note accuracy per release
- [ ] Image pre-processing: deskew, crop margins, adaptive thresholding for phone photos
- [ ] Show the recognised page next to the rendered ABC (side-by-side check)
- [ ] Surface Audiveris' per-measure "abnormal" flags as warnings in the editor
- [ ] Lyrics (`w:` lines), pedal marks, ottava lines, chord symbols

### M3 — Editing comfort
- [ ] Click a note in the preview to jump to it in the editor
- [ ] Simple transpose and "one voice per staff" simplification options
- [ ] Export PDF/SVG of the rendered score

### M4 — Operations
- [ ] Persistent job store (Redis/SQLite) to survive restarts
- [ ] Basic usage metrics and error reporting
- [ ] Optional paid GPU/CPU upgrade or second worker if the queue gets long
- [ ] Optional AI fallback (vision model) for hard scans, user-supplied API key

## Risks
- OMR accuracy on phone photos and dense piano writing is limited; the editor and playback exist so users can fix mistakes.
- Free Spaces sleep when idle and process one score at a time; acceptable for launch.
