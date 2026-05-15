"""Auth primitives: token hashing, password hashing, HMAC session tokens.

Stdlib-only. The shape mirrors ai-art-gallery's helpers so the same
clients work against both services.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import secrets
import time

# Agent name rule lifted verbatim from ai-art-gallery (NAME_REGEX in backend/app.py).
NAME_REGEX = re.compile(r"^[a-zA-Z0-9_-]{3,32}$")

_PBKDF2_ITERS = 200_000
_PBKDF2_ALGO = "sha256"


# ─── SHA-256 hashing (matches Gallery's hash_token) ──────────────────────
def hash_token(value: str | bytes) -> str:
    """SHA-256 hex digest. Used for api_key_hash + claim email token hash."""
    if isinstance(value, str):
        value = value.encode("utf-8")
    return hashlib.sha256(value).hexdigest()


# ─── Random token generators ─────────────────────────────────────────────
def generate_api_key() -> str:
    """64-char hex string. Shown to the agent once; only the hash is stored."""
    return secrets.token_hex(32)


def generate_claim_token() -> str:
    """URL-safe token embedded in the claim_url given to the human owner."""
    return secrets.token_urlsafe(32)


def generate_one_time_token() -> str:
    """URL-safe token sent in the email confirmation link."""
    return secrets.token_urlsafe(32)


# ─── Password hashing (PBKDF2-SHA256, stdlib) ────────────────────────────
def hash_password(password: str, *, iterations: int = _PBKDF2_ITERS) -> str:
    """Return a self-describing hash: pbkdf2_sha256$iters$b64_salt$b64_hash."""
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(_PBKDF2_ALGO, password.encode("utf-8"), salt, iterations)
    return "pbkdf2_sha256${iters}${salt}${hash}".format(
        iters=iterations,
        salt=base64.b64encode(salt).decode("ascii"),
        hash=base64.b64encode(digest).decode("ascii"),
    )


def verify_password(password: str, stored: str) -> bool:
    """Constant-time verify against the format produced by hash_password."""
    try:
        algo, iter_s, salt_b64, hash_b64 = stored.split("$")
    except ValueError:
        return False
    if algo != "pbkdf2_sha256":
        return False
    try:
        iterations = int(iter_s)
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(hash_b64)
    except Exception:
        return False
    candidate = hashlib.pbkdf2_hmac(_PBKDF2_ALGO, password.encode("utf-8"), salt, iterations)
    return hmac.compare_digest(candidate, expected)


# ─── HMAC-signed session tokens (no DB, no extra deps) ───────────────────
def _b64encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64decode(s: str) -> bytes:
    padding = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + padding)


def make_session_token(human_id: int, secret: str, ttl_seconds: int = 7 * 86_400) -> str:
    """Produce a stateless human-session token signed with `secret`."""
    payload = {"hid": int(human_id), "exp": int(time.time()) + int(ttl_seconds)}
    body = _b64encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    sig = hmac.new(secret.encode("utf-8"), body.encode("utf-8"), hashlib.sha256).digest()
    return f"{body}.{_b64encode(sig)}"


def verify_session_token(token: str, secret: str) -> int | None:
    """Return human_id if the token is valid + unexpired, else None."""
    try:
        body, sig_b64 = token.split(".", 1)
    except ValueError:
        return None
    expected_sig = hmac.new(secret.encode("utf-8"), body.encode("utf-8"), hashlib.sha256).digest()
    given_sig = _b64decode(sig_b64)
    if not hmac.compare_digest(expected_sig, given_sig):
        return None
    try:
        payload = json.loads(_b64decode(body))
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    if int(payload.get("exp", 0)) < int(time.time()):
        return None
    hid = payload.get("hid")
    if not isinstance(hid, int):
        return None
    return hid
