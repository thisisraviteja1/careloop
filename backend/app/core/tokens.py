"""Signed, expiring ack tokens. Short enough for Telegram callback data (64 bytes)."""

from __future__ import annotations

import base64
import hashlib
import hmac
from dataclasses import dataclass
from datetime import UTC, datetime

ROLE_CODES = {"elder": "e", "caregiver": "c", "neighbor": "n", "dashboard": "d"}
CODE_ROLES = {v: k for k, v in ROLE_CODES.items()}
SIG_CHARS = 22  # 16 bytes of HMAC-SHA256, base64url


class TokenError(Exception):
    """The token is malformed, tampered with, or expired."""


@dataclass(frozen=True)
class AckClaim:
    anomaly_id: int
    role: str
    expires_at: datetime


def _sig(secret: str, payload: str) -> str:
    digest = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).decode().rstrip("=")[:SIG_CHARS]


def sign_ack(secret: str, anomaly_id: int, role: str, expires_at: datetime) -> str:
    if not secret:
        raise ValueError("ACK_SECRET is empty")
    payload = f"{anomaly_id}.{ROLE_CODES[role]}.{int(expires_at.timestamp()):x}"
    return f"{payload}.{_sig(secret, payload)}"


def verify_ack(secret: str, token: str, now: datetime) -> AckClaim:
    """Return the claim, or raise TokenError."""
    parts = token.split(".")
    if len(parts) != 4 or not secret:
        raise TokenError("malformed")
    payload, sig = ".".join(parts[:3]), parts[3]
    if not hmac.compare_digest(sig, _sig(secret, payload)):
        raise TokenError("bad signature")
    try:
        anomaly_id, role = int(parts[0]), CODE_ROLES[parts[1]]
        expires_at = datetime.fromtimestamp(int(parts[2], 16), tz=UTC)
    except (ValueError, KeyError) as exc:
        raise TokenError("malformed") from exc
    if now >= expires_at:
        raise TokenError("expired")
    return AckClaim(anomaly_id, role, expires_at)
