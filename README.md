# Vybra Beats

DAW-as-an-API: Agents submit musical patterns as JSON, get back finished audio.

## Quick Start

```
pip install -r requirements.txt
python -m src.api
```

POST to `http://localhost:8000/api/beats` with your pattern JSON.

## Test

```
uv run python scripts/make_beat.py < scripts/test_beat.json
```

## API

`POST /api/beats` — Create a beat from patterns
`GET /api/beats/:id` — Get beat metadata
`GET /api/instruments` — List available instruments

## Architecture

```
[Agent] → POST JSON patterns → [FastAPI] → [Beat Engine] → MIDI → WAV → MP3 → R2
```

The beat engine generates MIDI using `pretty_midi`, renders via FluidSynth/ffmpeg, and returns audio URLs.
