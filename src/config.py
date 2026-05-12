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


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    project_root = Path(__file__).resolve().parent.parent
    configured_data_dir = os.getenv("VYBRA_DATA_DIR")
    data_dir = (
        Path(configured_data_dir).expanduser()
        if configured_data_dir
        else project_root / "data"
    )

    return Settings(
        app_name="Vybra Beats API",
        host=os.getenv("VYBRA_HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", os.getenv("VYBRA_PORT", "8000"))),
        data_dir=data_dir.resolve(),
        data_url_prefix=os.getenv("VYBRA_DATA_URL_PREFIX", "/data").rstrip("/") or "/data",
        cors_origins=("*",),
    )
