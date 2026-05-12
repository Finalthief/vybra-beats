from __future__ import annotations

from typing import Any, TypeVar

try:
    from pydantic import BaseModel, ConfigDict, Field
except ImportError:  # pragma: no cover - Pydantic v1 fallback
    from pydantic import BaseModel, Field  # type: ignore

    ConfigDict = None


T = TypeVar("T", bound=BaseModel)


class RequestModel(BaseModel):
    if ConfigDict is not None:
        model_config = ConfigDict(extra="allow")
    else:  # pragma: no cover - Pydantic v1 fallback
        class Config:
            extra = "allow"


class ResponseModel(BaseModel):
    if ConfigDict is not None:
        model_config = ConfigDict(extra="ignore")
    else:  # pragma: no cover - Pydantic v1 fallback
        class Config:
            extra = "ignore"


class BeatRequest(RequestModel):
    tempo: int = 120
    bars: int = 4
    timeSignature: list[int] = Field(default_factory=lambda: [4, 4])
    swing: float = 0.0
    instruments: list[dict[str, Any]] = Field(default_factory=list)

    # Metadata
    title: str = "Untitled Beat"
    agent_name: str = "Anonymous"
    genre: str = "electronic"
    key_signature: str = ""
    description: str = ""
    tags: list[str] = Field(default_factory=list)
    builds_on: list[str] = Field(default_factory=list)
    license: str = "vybra-standard"


class DownloadURLs(ResponseModel):
    mid: str
    wav: str
    mp3: str


class BeatResponse(ResponseModel):
    id: str
    tempo: int
    bars: int
    duration: float
    total_notes: int
    instruments: int
    download_urls: DownloadURLs

    # Metadata
    title: str = "Untitled Beat"
    agent_name: str = "Anonymous"
    agent_id: str = ""
    genre: str = "electronic"
    key_signature: str = ""
    description: str = ""
    tags: list[str] = Field(default_factory=list)
    builds_on: list[str] = Field(default_factory=list)
    license: str = "vybra-standard"
    created_at: str = ""
    kit: str = "trap"
    chiptune: bool = False


class InstrumentsResponse(ResponseModel):
    drum_kits: list[str]
    gm_drum_map: dict[str, int]
    melodic_instruments: list[str]
    gm_melodic_map: dict[str, int]
    chiptune_kits: list[str] = Field(default_factory=list)


class HealthResponse(ResponseModel):
    status: str


def dump_model(model: BaseModel) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump(mode="json")
    return model.dict()


def validate_model(model_cls: type[T], payload: dict[str, Any]) -> T:
    if hasattr(model_cls, "model_validate"):
        return model_cls.model_validate(payload)  # type: ignore[attr-defined]
    return model_cls.parse_obj(payload)
