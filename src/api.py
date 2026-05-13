from __future__ import annotations

import importlib
import importlib.util
import logging
from functools import lru_cache
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .config import Settings, get_settings
from .models import BeatRequest, BeatResponse, HealthResponse, InstrumentsResponse, dump_model
from .storage import BeatNotFoundError, LocalBeatStorage


logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def load_make_beat_module():
    try:
        return importlib.import_module("scripts.make_beat")
    except ModuleNotFoundError as exc:
        if exc.name not in {"scripts", "scripts.make_beat"}:
            raise

    module_path = Path(__file__).resolve().parent.parent / "scripts" / "make_beat.py"
    spec = importlib.util.spec_from_file_location("scripts.make_beat", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load beat engine at {module_path}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def render_beat(spec: dict[str, Any], storage: LocalBeatStorage) -> BeatResponse:
    make_beat = load_make_beat_module()
    midi, metadata = make_beat.build_beat(spec)
    render_result = make_beat.save_beat(midi, metadata, str(storage.data_dir))
    
    # Check if chiptune rendering is requested
    is_chiptune = spec.get("chiptune", False) or any(
        i.get("kit") == "chiptune" for i in spec.get("instruments", [])
    )
    
    if is_chiptune and any(
        i.get("type") == "drum" for i in spec.get("instruments", [])
    ):
        try:
            from . import chiptune as ct
            import random
            
            # Extract drum pattern for chiptune noise channel
            drum_track = []
            for inst in spec.get("instruments", []):
                if inst.get("type") == "drum":
                    pattern = inst.get("pattern", {})
                    for drum_name, hits in pattern.items():
                        if drum_name in ("snare", "clap", "hihat_o"):
                            step_duration = 60.0 / spec.get("tempo", 120) / 4
                            for step_idx, val in enumerate(hits):
                                if val:
                                    t = step_idx * step_duration
                                    vel = inst.get("velocity", 100)
                                    drum_track.append((0, t, 0.1, vel // 2))
            
            # Extract melodic notes for square/triangle channels
            mel_notes = []
            for inst in spec.get("instruments", []):
                if inst.get("type") == "melodic":
                    for note in inst.get("notes", []):
                        pitch = note.get("pitch", 36)
                        start = note.get("start", 0) * 60.0 / spec.get("tempo", 120)
                        dur = note.get("duration", 0.5)
                        vel = note.get("velocity", 80)
                        mel_notes.append((pitch, start, dur, vel))
            
            # Render chiptune audio
            if mel_notes:
                square_samples = ct.render_from_midi_notes(
                    mel_notes, wave_type="square", duty_cycle=0.5
                )
            else:
                square_samples = []
            
            if drum_track:
                noise_samples = ct.render_from_midi_notes(
                    drum_track, wave_type="noise"
                )
            else:
                noise_samples = []
            
            all_tracks = [t for t in [square_samples, noise_samples] if t]
            
            if all_tracks:
                mixed = ct.mix_tracks(all_tracks)
                chiptune_path = storage.asset_path(render_result["id"], "chiptune.wav")
                ct.save_wav(mixed, str(chiptune_path))
                
                # Also convert to mp3
                import os as _os
                mp3_path = storage.asset_path(render_result["id"], "chiptune.mp3")
                _os.system(f'ffmpeg -y -i "{chiptune_path}" -codec:a libmp3lame -b:a 320k "{mp3_path}" 2>nul')
        
        except Exception:
            logger.warning("Chiptune rendering failed, falling back to MIDI render", exc_info=True)
    
    return storage.save_render_result(render_result, is_chiptune)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    storage = LocalBeatStorage(settings.data_dir, settings.data_url_prefix)

    app = FastAPI(title=settings.app_name)
    app.state.settings = settings
    app.state.storage = storage

    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.mount(
        settings.data_url_prefix,
        StaticFiles(directory=storage.data_dir),
        name="data",
    )

    @app.get("/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        return HealthResponse(status="ok")

    @app.post("/api/beats", response_model=BeatResponse, status_code=201)
    async def create_beat(spec: BeatRequest) -> BeatResponse:
        try:
            return await run_in_threadpool(render_beat, dump_model(spec), storage)
        except Exception as exc:  # pragma: no cover - exercised through API
            logger.exception("Beat render failed")
            raise HTTPException(status_code=500, detail=str(exc) or "Beat render failed") from exc

    @app.get("/api/beats/{beat_id}", response_model=BeatResponse)
    def get_beat(beat_id: str) -> BeatResponse:
        try:
            return storage.load_metadata(beat_id)
        except BeatNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Beat not found") from exc

    @app.get("/api/instruments", response_model=InstrumentsResponse)
    def get_instruments() -> InstrumentsResponse:
        try:
            make_beat = load_make_beat_module()
        except Exception as exc:  # pragma: no cover - depends on local runtime deps
            logger.exception("Instrument catalog load failed")
            raise HTTPException(status_code=500, detail=str(exc) or "Unable to load instruments") from exc

        return InstrumentsResponse(
            drum_kits=["trap", "live", "electronic", "chiptune", "lo-fi"],
            gm_drum_map=make_beat.GM_DRUMS,
            melodic_instruments=sorted(make_beat.GM_INSTRUMENTS.keys()),
            gm_melodic_map=make_beat.GM_INSTRUMENTS,
            chiptune_kits=["chiptune-nes", "chiptune-gameboy", "chiptune-arcade"],
        )

    return app


app = create_app()


def main() -> None:
    settings = get_settings()
    uvicorn.run("src.api:app", host=settings.host, port=settings.port, reload=False)


if __name__ == "__main__":
    main()
