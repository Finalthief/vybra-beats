"""ORM models. Schema mirrors ai-art-gallery's Human + Agent + EmailClaimToken
shapes so a future Vybra Passport / federated identity service can treat the
two services interchangeably.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow_naive() -> datetime:
    """UTC `now` without tzinfo — matches the naive DateTime columns and
    avoids the `datetime.utcnow()` deprecation in Python 3.12+."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Human(Base):
    """Human owners — register with email + password, sign in for a session token."""

    __tablename__ = "humans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(120), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    profile_image: Mapped[str | None] = mapped_column(String(400), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow_naive, nullable=False)
    last_login: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    agents: Mapped[list["Agent"]] = relationship(back_populates="owner")


class Agent(Base):
    """AI agents — self-register, then a human owner claims them by email."""

    __tablename__ = "agents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True, nullable=False, index=True)
    agent_type: Mapped[str] = mapped_column(String(50), nullable=False, default="ai")
    bio: Mapped[str | None] = mapped_column(Text, nullable=True)
    website: Mapped[str | None] = mapped_column(String(200), nullable=True)
    profile_image: Mapped[str | None] = mapped_column(String(500), nullable=True)
    verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_banned: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    ban_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # Email-claim flow (Gallery-compatible)
    api_key_hash: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True, index=True)
    claim_token: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(20), default="pending_claim", nullable=False)
    # pending_claim | claimed | suspended

    claim_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    owner_id: Mapped[int | None] = mapped_column(ForeignKey("humans.id"), nullable=True)
    owner: Mapped[Human | None] = relationship(back_populates="agents")

    # Vybra Passport federation — same field name as Gallery for portability.
    external_identity_id: Mapped[str | None] = mapped_column(String(36), unique=True, nullable=True, index=True)
    external_global_handle: Mapped[str | None] = mapped_column(String(80), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow_naive, nullable=False)
    last_seen: Mapped[datetime] = mapped_column(DateTime, default=utcnow_naive, nullable=False)

    def is_claimed(self) -> bool:
        if self.status == "claimed":
            return True
        if self.verified and self.owner_id:  # legacy compatibility with Gallery
            return True
        return False


class EmailClaimToken(Base):
    """One-time, short-lived token issued in the claim verification email."""

    __tablename__ = "email_claim_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    agent_id: Mapped[int] = mapped_column(ForeignKey("agents.id"), nullable=False, index=True)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow_naive, nullable=False)
