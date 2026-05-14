from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    app_name: str
    host: str
    port: int
    data_dir: Path
    data_url_prefix: str
    cors_origins: tuple[str, ...]
    api_key: str | None = None


def _parse_origins(raw: str | None) -> tuple[str, ...]:
    if not raw:
        return ("*",)
    parts = tuple(p.strip() for p in raw.split(",") if p.strip())
    return parts or ("*",)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    project_root = Path(__file__).resolve().parent.parent
    configured_data_dir = os.getenv("VYBRA_DATA_DIR")
    data_dir = (
        Path(configured_data_dir).expanduser()
        if configured_data_dir
        else project_root / "data"
    )

    api_key = os.getenv("VYBRA_API_KEY") or None

    return Settings(
        app_name="Vybra Beats API",
        host=os.getenv("VYBRA_HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", os.getenv("VYBRA_PORT", "8000"))),
        data_dir=data_dir.resolve(),
        data_url_prefix=os.getenv("VYBRA_DATA_URL_PREFIX", "/data").rstrip("/") or "/data",
        cors_origins=_parse_origins(os.getenv("VYBRA_CORS_ORIGINS")),
        api_key=api_key,
    )
