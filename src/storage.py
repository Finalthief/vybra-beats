from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .models import BeatResponse, DownloadURLs, dump_model, validate_model


class BeatNotFoundError(FileNotFoundError):
    """Raised when a beat metadata file does not exist."""


class LocalBeatStorage:
    def __init__(self, data_dir: Path, public_prefix: str = "/data") -> None:
        self.data_dir = data_dir
        self.public_prefix = public_prefix.rstrip("/") or "/data"
        self.data_dir.mkdir(parents=True, exist_ok=True)

    def metadata_path(self, beat_id: str) -> Path:
        return self.data_dir / f"{beat_id}.json"

    def asset_path(self, beat_id: str, ext: str) -> Path:
        return self.data_dir / f"{beat_id}.{ext.lstrip('.')}"

    def download_urls(self, beat_id: str) -> DownloadURLs:
        return DownloadURLs(
            mid=f"{self.public_prefix}/{beat_id}.mid",
            wav=f"{self.public_prefix}/{beat_id}.wav",
            mp3=f"{self.public_prefix}/{beat_id}.mp3",
        )

    def build_response(self, render_result: dict[str, Any]) -> BeatResponse:
        beat_id = str(render_result["id"])
        return BeatResponse(
            id=beat_id,
            tempo=int(render_result["tempo"]),
            bars=int(render_result["bars"]),
            duration=float(render_result["duration"]),
            total_notes=int(render_result["total_notes"]),
            instruments=int(render_result["instruments"]),
            download_urls=self.download_urls(beat_id),
        )

    def save_metadata(self, response: BeatResponse) -> None:
        payload = dump_model(response)
        self.metadata_path(response.id).write_text(
            json.dumps(payload, indent=2),
            encoding="utf-8",
        )

    def save_render_result(self, render_result: dict[str, Any]) -> BeatResponse:
        beat_id = str(render_result["id"])
        missing_assets = [
            ext for ext in ("mid", "wav", "mp3") if not self.asset_path(beat_id, ext).exists()
        ]
        if missing_assets:
            missing = ", ".join(missing_assets)
            raise RuntimeError(f"Missing rendered asset(s): {missing}")

        response = self.build_response(render_result)
        self.save_metadata(response)
        return response

    def load_metadata(self, beat_id: str) -> BeatResponse:
        metadata_path = self.metadata_path(beat_id)
        if not metadata_path.exists():
            raise BeatNotFoundError(beat_id)

        payload = json.loads(metadata_path.read_text(encoding="utf-8"))
        payload["download_urls"] = dump_model(self.download_urls(beat_id))
        return validate_model(BeatResponse, payload)
