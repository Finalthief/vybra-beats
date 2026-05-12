# Vybra Beats — Build Spec for Codex

## What to Build
A FastAPI web application + background rendering engine at `src/`.

The core beat engine already exists at `scripts/make_beat.py` — import and reuse it.

## Project Structure to Create

```
src/
├── __init__.py
├── api.py              # FastAPI app with routes
├── models.py           # Pydantic models for request/response
├── config.py           # Settings
└── storage.py          # Local file storage (R2 later)
```

## API Endpoints

### POST /api/beats
- Accept the beat spec JSON (see scripts/test_beat.json for format)
- Call make_beat.build_beat() to generate MIDI
- Call make_beat.save_beat() to render audio
- Return { id, tempo, bars, duration, total_notes, instruments, download_urls }
- Store results in data/ directory

### GET /api/beats/{id}
- Return metadata for a previously created beat

### GET /api/instruments
- Return available drum kits and melodic instruments
- Include GM drum map and melodic instrument list from make_beat.py

### GET /health
- Return {"status": "ok"} for health checks

## Rendering
- Use ffmpeg (assumed on PATH) for MIDI→WAV→MP3 conversion (already works in make_beat.py)
- Output goes to data/ directory (gitignored)

## CORS
- Allow all origins for development

## Running
- `python -m src.api` starts uvicorn on port 8000
- Requirements in requirements.txt (already created)
