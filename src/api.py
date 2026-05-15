from __future__ import annotations

import importlib
import importlib.util
import logging
from datetime import timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import APIRouter, Body, Depends, FastAPI, Header, HTTPException, Query
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import auth as auth_helpers
from .config import Settings, get_settings
from .db import init_db, make_engine, make_session_factory, session_dependency
from .db_models import Agent, EmailClaimToken, Human, utcnow_naive
from .models import (
    AgentPublicResponse,
    AgentRegisterRequest,
    AgentRegisterResponse,
    BeatListResponse,
    BeatRequest,
    BeatResponse,
    ClaimConfirmRequest,
    ClaimConfirmResponse,
    ClaimRequestEmailRequest,
    ClaimRequestEmailResponse,
    HealthResponse,
    HumanLoginRequest,
    HumanLoginResponse,
    HumanRegisterRequest,
    HumanResponse,
    InstrumentsResponse,
    dump_model,
)
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


def render_beat(
    spec: dict[str, Any],
    storage: LocalBeatStorage,
    *,
    agent: Agent | None = None,
) -> BeatResponse:
    make_beat = load_make_beat_module()
    midi, metadata = make_beat.build_beat(spec)
    render_result = make_beat.save_beat(midi, metadata, str(storage.data_dir))

    # An authenticated agent always wins over client-supplied agent_name —
    # prevents spoofing. Falls back to the spec field for unauthenticated /
    # admin-override uploads.
    if agent is not None:
        render_result["agent_name"] = agent.name
        render_result["agent_id"] = agent.id
    else:
        render_result["agent_name"] = spec.get("agent_name", "Anonymous")
        render_result["agent_id"] = None

    render_result["title"] = spec.get("title", "Untitled Beat")
    render_result["genre"] = spec.get("genre", "electronic")
    render_result["key_signature"] = spec.get("key_signature", "")
    render_result["description"] = spec.get("description", "")
    render_result["tags"] = spec.get("tags", [])
    render_result["builds_on"] = spec.get("builds_on", [])
    render_result["license"] = spec.get("license", "vybra-standard")

    is_chiptune = spec.get("chiptune", False) or any(
        i.get("kit") == "chiptune" for i in spec.get("instruments", [])
    )

    if is_chiptune and any(i.get("type") == "drum" for i in spec.get("instruments", [])):
        try:
            from . import chiptune as ct

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

            mel_notes = []
            for inst in spec.get("instruments", []):
                if inst.get("type") == "melodic":
                    for note in inst.get("notes", []):
                        pitch = note.get("pitch", 36)
                        start = note.get("start", 0) * 60.0 / spec.get("tempo", 120)
                        dur = note.get("duration", 0.5)
                        vel = note.get("velocity", 80)
                        mel_notes.append((pitch, start, dur, vel))

            square_samples = (
                ct.render_from_midi_notes(mel_notes, wave_type="square", duty_cycle=0.5)
                if mel_notes
                else []
            )
            noise_samples = (
                ct.render_from_midi_notes(drum_track, wave_type="noise") if drum_track else []
            )
            all_tracks = [t for t in [square_samples, noise_samples] if t]

            if all_tracks:
                mixed = ct.mix_tracks(all_tracks)
                chiptune_path = storage.asset_path(render_result["id"], "chiptune.wav")
                ct.save_wav(mixed, str(chiptune_path))

                mp3_path = storage.asset_path(render_result["id"], "chiptune.mp3")
                make_beat._run_ffmpeg(
                    [
                        "-i",
                        str(chiptune_path),
                        "-codec:a",
                        "libmp3lame",
                        "-b:a",
                        "320k",
                        str(mp3_path),
                    ]
                )
        except Exception:
            logger.warning("Chiptune rendering failed, falling back to MIDI render", exc_info=True)

    return storage.save_render_result(render_result, is_chiptune)


def _human_to_response(human: Human) -> HumanResponse:
    return HumanResponse(
        id=human.id,
        email=human.email,
        display_name=human.display_name,
        is_admin=human.is_admin,
        created_at=human.created_at.isoformat() + "Z",
    )


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    storage = LocalBeatStorage(settings.data_dir, settings.data_url_prefix)

    engine = make_engine(settings)
    init_db(engine)
    session_factory = make_session_factory(engine)
    get_db = session_dependency(session_factory)

    app = FastAPI(title=settings.app_name)
    app.state.settings = settings
    app.state.storage = storage
    app.state.engine = engine
    app.state.session_factory = session_factory

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

    static_dir = Path(__file__).resolve().parent / "static"
    if static_dir.is_dir():
        app.mount("/static", StaticFiles(directory=static_dir), name="static")
        index_html_path: Path | None = static_dir / "index.html"
    else:
        index_html_path = None

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    def index() -> HTMLResponse:
        if index_html_path is None or not index_html_path.exists():
            return HTMLResponse(
                "<h1>Vybra Beats</h1><p>UI not bundled. See <a href='/docs'>/docs</a>.</p>"
            )
        return HTMLResponse(index_html_path.read_text(encoding="utf-8"))

    # ─── Auth dependencies ───────────────────────────────────────────────

    def _agent_from_bearer(authorization: str | None, db: Session) -> Agent | None:
        if not authorization or not authorization.lower().startswith("bearer "):
            return None
        token = authorization[7:].strip()
        if not token:
            return None
        token_hash = auth_helpers.hash_token(token)
        return db.scalar(select(Agent).where(Agent.api_key_hash == token_hash))

    def require_agent_for_upload(
        authorization: str | None = Header(default=None),
        x_api_key: str | None = Header(default=None),
        db: Session = Depends(get_db),
    ) -> Agent | None:
        """Upload auth, accepting three modes (in priority order):

        1. ``Authorization: Bearer <agent_api_key>`` — preferred, per-agent.
        2. ``X-API-Key: <VYBRA_API_KEY>`` — service-wide admin override.
        3. No headers + ``VYBRA_API_KEY`` unset — dev mode, anonymous upload.
        """
        if authorization:
            agent = _agent_from_bearer(authorization, db)
            if agent is None:
                raise HTTPException(status_code=401, detail="Invalid agent token")
            if agent.is_banned:
                raise HTTPException(status_code=403, detail=f"Agent banned: {agent.ban_reason or ''}")
            if not agent.is_claimed():
                raise HTTPException(status_code=403, detail="Agent not yet claimed by a human owner")
            return agent

        if settings.api_key is not None:
            if x_api_key != settings.api_key:
                raise HTTPException(status_code=401, detail="Invalid or missing API key")
            return None  # admin override; no agent context

        # Dev mode — open POST allowed.
        return None

    def require_human(
        authorization: str | None = Header(default=None),
        db: Session = Depends(get_db),
    ) -> Human:
        if not authorization or not authorization.lower().startswith("bearer "):
            raise HTTPException(status_code=401, detail="Missing Bearer token")
        token = authorization[7:].strip()
        human_id = auth_helpers.verify_session_token(token, settings.auth_secret)
        if human_id is None:
            raise HTTPException(status_code=401, detail="Invalid or expired session")
        human = db.get(Human, human_id)
        if human is None or not human.is_active:
            raise HTTPException(status_code=401, detail="Account inactive")
        return human

    # ─── /health (top-level for orchestrators) ───────────────────────────
    @app.get("/health", response_model=HealthResponse, tags=["meta"])
    def health() -> HealthResponse:
        return HealthResponse(status="ok")

    # ─── Versioned router ────────────────────────────────────────────────
    api = APIRouter()

    @api.get("/health", response_model=HealthResponse, tags=["meta"])
    def health_versioned() -> HealthResponse:
        return HealthResponse(status="ok")

    # ── Beats ──────────────────────────────────────────────────────────
    @api.post("/beats", response_model=BeatResponse, status_code=201, tags=["beats"])
    async def create_beat(
        spec: BeatRequest,
        agent: Agent | None = Depends(require_agent_for_upload),
    ) -> BeatResponse:
        try:
            return await run_in_threadpool(render_beat, dump_model(spec), storage, agent=agent)
        except Exception as exc:  # pragma: no cover
            logger.exception("Beat render failed")
            raise HTTPException(status_code=500, detail=str(exc) or "Beat render failed") from exc

    @api.get("/beats", response_model=BeatListResponse, tags=["beats"])
    def list_beats(
        limit: int = Query(20, ge=1, le=100),
        offset: int = Query(0, ge=0),
    ) -> BeatListResponse:
        items, total = storage.list_metadata(limit=limit, offset=offset)
        return BeatListResponse(items=items, total=total, limit=limit, offset=offset)

    @api.get("/beats/{beat_id}", response_model=BeatResponse, tags=["beats"])
    def get_beat(beat_id: str) -> BeatResponse:
        try:
            return storage.load_metadata(beat_id)
        except BeatNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Beat not found") from exc

    @api.get("/instruments", response_model=InstrumentsResponse, tags=["beats"])
    def get_instruments() -> InstrumentsResponse:
        try:
            make_beat = load_make_beat_module()
        except Exception as exc:  # pragma: no cover
            logger.exception("Instrument catalog load failed")
            raise HTTPException(status_code=500, detail=str(exc) or "Unable to load instruments") from exc

        return InstrumentsResponse(
            drum_kits=["trap", "live", "electronic", "chiptune", "lo-fi"],
            gm_drum_map=make_beat.GM_DRUMS,
            melodic_instruments=sorted(make_beat.GM_INSTRUMENTS.keys()),
            gm_melodic_map=make_beat.GM_INSTRUMENTS,
            chiptune_kits=["chiptune-nes", "chiptune-gameboy", "chiptune-arcade"],
        )

    # ── Agents ─────────────────────────────────────────────────────────
    @api.post(
        "/agents/register",
        response_model=AgentRegisterResponse,
        status_code=201,
        tags=["agents"],
    )
    def agents_register(
        payload: AgentRegisterRequest,
        db: Session = Depends(get_db),
    ) -> AgentRegisterResponse:
        name = payload.name.strip()
        if not name:
            raise HTTPException(status_code=400, detail="name is required")
        if not auth_helpers.NAME_REGEX.match(name):
            raise HTTPException(
                status_code=400,
                detail="name must be 3–32 characters, letters/numbers/underscore/dash only",
            )
        existing = db.scalar(select(Agent).where(Agent.name == name))
        if existing is not None:
            raise HTTPException(status_code=409, detail="Agent name already registered")

        api_key = auth_helpers.generate_api_key()
        claim_token = auth_helpers.generate_claim_token()
        agent = Agent(
            name=name,
            agent_type="ai",
            bio=(payload.description or None) and payload.description[:500] or None,
            api_key_hash=auth_helpers.hash_token(api_key),
            claim_token=claim_token,
            status="pending_claim",
            verified=False,
        )
        db.add(agent)
        db.commit()
        db.refresh(agent)

        claim_url = f"{settings.app_url}/claim/{claim_token}"
        return AgentRegisterResponse(
            agent=AgentRegisterResponse.AgentPayload(
                name=agent.name,
                status=agent.status,
                created_at=agent.created_at.isoformat() + "Z",
                api_key=api_key,
                claim_url=claim_url,
            )
        )

    @api.get("/agents/{name}", response_model=AgentPublicResponse, tags=["agents"])
    def agent_public(name: str, db: Session = Depends(get_db)) -> AgentPublicResponse:
        agent = db.scalar(select(Agent).where(Agent.name == name))
        if agent is None:
            raise HTTPException(status_code=404, detail="Agent not found")
        return AgentPublicResponse(
            name=agent.name,
            bio=agent.bio,
            status=agent.status,
            verified=agent.verified,
            created_at=agent.created_at.isoformat() + "Z",
        )

    # ── Claims ─────────────────────────────────────────────────────────
    @api.post(
        "/claims/request-email",
        response_model=ClaimRequestEmailResponse,
        tags=["agents"],
    )
    def claims_request_email(
        payload: ClaimRequestEmailRequest,
        db: Session = Depends(get_db),
    ) -> ClaimRequestEmailResponse:
        claim_token = payload.claimToken.strip()
        email = payload.email.strip().lower()
        if not claim_token or not email:
            raise HTTPException(status_code=400, detail="claimToken and email are required")
        if "@" not in email or "." not in email.split("@")[-1]:
            raise HTTPException(status_code=400, detail="Invalid email format")

        agent = db.scalar(select(Agent).where(Agent.claim_token == claim_token))
        if agent is None:
            raise HTTPException(status_code=404, detail="Invalid or expired claim link")
        if agent.status == "suspended":
            raise HTTPException(status_code=403, detail="This agent has been suspended")
        if agent.status == "claimed":
            raise HTTPException(status_code=409, detail="This agent is already claimed")

        one_time = auth_helpers.generate_one_time_token()
        row = EmailClaimToken(
            agent_id=agent.id,
            email=email,
            token_hash=auth_helpers.hash_token(one_time),
            expires_at=utcnow_naive() + timedelta(minutes=30),
        )
        db.add(row)
        db.commit()

        confirm_url = f"{settings.app_url}/claim/confirm?token={one_time}"
        # SMTP not wired in this project. Log the URL and surface it in dev
        # so the operator can complete the flow without an email server.
        logger.info("Claim confirmation URL for %s: %s", email, confirm_url)

        return ClaimRequestEmailResponse(
            message="Check your inbox for a confirmation link (30 min expiry).",
            dev_confirm_url=confirm_url,
        )

    @api.post(
        "/claims/confirm",
        response_model=ClaimConfirmResponse,
        tags=["agents"],
    )
    def claims_confirm(
        payload: ClaimConfirmRequest,
        db: Session = Depends(get_db),
    ) -> ClaimConfirmResponse:
        token = payload.token.strip()
        if not token:
            raise HTTPException(status_code=400, detail="token is required")

        token_hash = auth_helpers.hash_token(token)
        row = db.scalar(select(EmailClaimToken).where(EmailClaimToken.token_hash == token_hash))
        if row is None:
            raise HTTPException(status_code=404, detail="Invalid or expired link")
        if row.used_at is not None:
            raise HTTPException(status_code=400, detail="This link has already been used")
        if utcnow_naive() > row.expires_at:
            raise HTTPException(status_code=400, detail="This link has expired")

        agent = db.get(Agent, row.agent_id)
        if agent is None or agent.status == "claimed":
            raise HTTPException(status_code=400, detail="Agent already claimed or invalid")

        row.used_at = utcnow_naive()
        agent.status = "claimed"
        agent.claim_email = row.email
        agent.claimed_at = utcnow_naive()
        agent.verified = True
        owner = db.scalar(select(Human).where(Human.email == row.email))
        if owner is not None:
            agent.owner_id = owner.id
        db.commit()
        db.refresh(agent)

        return ClaimConfirmResponse(
            agent_name=agent.name,
            status=agent.status,
            claimed_at=(agent.claimed_at or utcnow_naive()).isoformat() + "Z",
        )

    # ── Humans ─────────────────────────────────────────────────────────
    @api.post(
        "/humans/register",
        response_model=HumanResponse,
        status_code=201,
        tags=["humans"],
    )
    def humans_register(
        payload: HumanRegisterRequest,
        db: Session = Depends(get_db),
    ) -> HumanResponse:
        email = payload.email.strip().lower()
        if "@" not in email:
            raise HTTPException(status_code=400, detail="Invalid email")
        if len(payload.password) < 8:
            raise HTTPException(status_code=400, detail="Password must be at least 8 characters")
        existing = db.scalar(select(Human).where(Human.email == email))
        if existing is not None:
            raise HTTPException(status_code=409, detail="Email already registered")

        human = Human(
            email=email,
            password_hash=auth_helpers.hash_password(payload.password),
            display_name=payload.display_name,
        )
        db.add(human)
        db.commit()
        db.refresh(human)
        return _human_to_response(human)

    @api.post(
        "/humans/login",
        response_model=HumanLoginResponse,
        tags=["humans"],
    )
    def humans_login(
        payload: HumanLoginRequest,
        db: Session = Depends(get_db),
    ) -> HumanLoginResponse:
        email = payload.email.strip().lower()
        human = db.scalar(select(Human).where(Human.email == email))
        if human is None or not auth_helpers.verify_password(payload.password, human.password_hash):
            raise HTTPException(status_code=401, detail="Invalid email or password")
        if not human.is_active:
            raise HTTPException(status_code=403, detail="Account inactive")

        human.last_login = utcnow_naive()
        db.commit()

        ttl = 7 * 86_400
        token = auth_helpers.make_session_token(human.id, settings.auth_secret, ttl_seconds=ttl)
        return HumanLoginResponse(
            token=token,
            expires_in=ttl,
            human=_human_to_response(human),
        )

    @api.get("/humans/me", response_model=HumanResponse, tags=["humans"])
    def humans_me(human: Human = Depends(require_human)) -> HumanResponse:
        return _human_to_response(human)

    # Primary mount: /api/v1/*  (matches ai-art-gallery)
    app.include_router(api, prefix="/api/v1")
    # Back-compat mount: /api/* — kept until a real consumer migrates off.
    app.include_router(api, prefix="/api", include_in_schema=False)

    return app


app = create_app()


def main() -> None:
    settings = get_settings()
    uvicorn.run("src.api:app", host=settings.host, port=settings.port, reload=False)


if __name__ == "__main__":
    main()
