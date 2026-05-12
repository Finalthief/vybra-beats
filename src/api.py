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
    return storage.save_render_result(render_result)


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
            drum_kits=["trap"],
            gm_drum_map=make_beat.GM_DRUMS,
            melodic_instruments=sorted(make_beat.GM_INSTRUMENTS.keys()),
            gm_melodic_map=make_beat.GM_INSTRUMENTS,
        )

    return app


app = create_app()


def main() -> None:
    settings = get_settings()
    uvicorn.run("src.api:app", host=settings.host, port=settings.port, reload=False)


if __name__ == "__main__":
    main()
