# Vybra Beats

DAW-as-an-API: Agents submit musical patterns as JSON, get back finished audio.

## System requirements

- Python 3.10+
- `ffmpeg` on `PATH` — used for WAV→MP3 transcoding and (currently) MIDI→WAV.
- **Soundfont caveat:** `ffmpeg` alone cannot synthesize MIDI to audio. To
  render non-chiptune beats to real audio you need FluidSynth plus a `.sf2`
  soundfont, then route MIDI→WAV through it. The current pipeline calls ffmpeg
  directly on `.mid` files, which will fail silently without a synth backend.
  The chiptune path (`chiptune: true`) renders its own WAV in pure Python and
  does not depend on a soundfont.

## Quick start

```
pip install -r requirements.txt
python -m src.api
```

POST to `http://localhost:8000/api/beats` with your pattern JSON.

## Test

```
pip install -r requirements-dev.txt
pytest
```

You can also run the beat engine standalone:

```
python scripts/make_beat.py < scripts/test_beat.json
```

## Docker

```
docker build -t vybra-beats .
docker run -p 8000:8000 vybra-beats
```

The image installs `ffmpeg`.

## Configuration

Copy `.env.example` and set whichever variables you need. Notable ones:

- `VYBRA_API_KEY` — if set, `POST /api/beats` requires `X-API-Key: <value>`.
- `VYBRA_CORS_ORIGINS` — comma-separated allowed origins (default `*`).
- `VYBRA_DATA_DIR` — where rendered files are stored (default `./data`).

## API

All routes are mounted under `/api/v1/*` (primary) and `/api/*` (back-compat
alias, kept until the `/api/*` path has no real consumers).

- `POST /api/v1/beats` — create a beat from patterns. Returns 201 with download URLs.
- `GET  /api/v1/beats` — list beats, newest first. Query: `limit` (1-100, default 20), `offset` (default 0).
- `GET  /api/v1/beats/{id}` — get beat metadata.
- `GET  /api/v1/instruments` — list available drum kits, melodic instruments, and GM maps.
- `GET  /api/v1/health` — liveness check. `GET /health` is also exposed for orchestrators.

## Architecture

```
[Agent] → POST JSON patterns → [FastAPI] → [Beat Engine] → MIDI → WAV → MP3
                                                                       ↓
                                                                  local data/
```

The beat engine generates MIDI using `pretty_midi`. Audio rendering goes
through `ffmpeg` (with the caveat noted above). The chiptune path bypasses
ffmpeg for synthesis and produces WAV directly in Python.
