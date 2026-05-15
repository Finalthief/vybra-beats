from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.api import create_app
from src.config import Settings
from src.storage import LocalBeatStorage


def _make_settings(tmp_path: Path, *, api_key: str | None = None) -> Settings:
    data_dir = tmp_path / "data"
    return Settings(
        app_name="Vybra Beats Test",
        host="127.0.0.1",
        port=0,
        data_dir=data_dir,
        data_url_prefix="/data",
        cors_origins=("*",),
        api_key=api_key,
        database_url=f"sqlite:///{tmp_path / 'test.db'}",
        auth_secret="test-secret-do-not-use-in-prod",
        app_url="http://testserver",
    )


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return _make_settings(tmp_path)


@pytest.fixture
def storage(settings: Settings) -> LocalBeatStorage:
    return LocalBeatStorage(settings.data_dir, settings.data_url_prefix)


@pytest.fixture
def client(settings: Settings) -> TestClient:
    app = create_app(settings)
    return TestClient(app)


@pytest.fixture
def authed_settings(tmp_path: Path) -> Settings:
    return _make_settings(tmp_path, api_key="test-secret")


@pytest.fixture
def authed_client(authed_settings: Settings) -> TestClient:
    app = create_app(authed_settings)
    return TestClient(app)
