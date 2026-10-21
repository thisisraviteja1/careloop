"""Settings loaded from environment variables (and an optional .env file)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def load_dotenv(path: Path | None = None) -> None:
    """Load KEY=VALUE lines from .env into os.environ without overriding existing values."""
    env_path = path or REPO_ROOT / ".env"
    if not env_path.is_file():
        return
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip().strip('"').strip("'")
        if value:  # an empty line in .env must not hide credentials from other sources
            os.environ.setdefault(key.strip(), value)


def _bool(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    ring_access_token: str
    ring_mode: str
    ring_device_id: str
    poll_interval_seconds: int
    aws_region: str
    bedrock_vision_model_id: str
    bedrock_text_model_id: str
    bedrock_guardrail_id: str
    bedrock_guardrail_version: str
    telegram_bot_token: str
    telegram_chat_elder: str
    telegram_chat_caregiver: str
    telegram_chat_neighbor: str
    person_name: str
    caregiver_name: str
    neighbor_name: str
    timezone: str
    margin_minutes: int
    l1_wait_minutes: int
    l2_wait_minutes: int
    ack_secret: str
    public_base_url: str
    database_url: str
    demo_mode: bool
    clock_speed: float
    log_level: str


def get_settings() -> Settings:
    """Read settings from the environment, loading .env first if present."""
    load_dotenv()
    env = os.environ.get
    return Settings(
        ring_access_token=env("RING_ACCESS_TOKEN", ""),
        ring_mode=env("RING_MODE", "fixture"),
        ring_device_id=env("RING_DEVICE_ID", ""),
        poll_interval_seconds=int(env("POLL_INTERVAL_SECONDS", "60")),
        aws_region=env("AWS_REGION", "us-east-1"),
        bedrock_vision_model_id=env("BEDROCK_VISION_MODEL_ID", ""),
        bedrock_text_model_id=env("BEDROCK_TEXT_MODEL_ID", ""),
        bedrock_guardrail_id=env("BEDROCK_GUARDRAIL_ID", ""),
        bedrock_guardrail_version=env("BEDROCK_GUARDRAIL_VERSION", "DRAFT"),
        telegram_bot_token=env("TELEGRAM_BOT_TOKEN", ""),
        telegram_chat_elder=env("TELEGRAM_CHAT_ELDER", ""),
        telegram_chat_caregiver=env("TELEGRAM_CHAT_CAREGIVER", ""),
        telegram_chat_neighbor=env("TELEGRAM_CHAT_NEIGHBOR", ""),
        person_name=env("PERSON_NAME", "Lakshmi"),
        caregiver_name=env("CAREGIVER_NAME", "Suresh"),
        neighbor_name=env("NEIGHBOR_NAME", "Meena"),
        timezone=env("TIMEZONE", "Asia/Kolkata"),
        margin_minutes=int(env("MARGIN_MINUTES", "45")),
        l1_wait_minutes=int(env("L1_WAIT_MINUTES", "30")),
        l2_wait_minutes=int(env("L2_WAIT_MINUTES", "30")),
        ack_secret=env("ACK_SECRET", ""),
        public_base_url=env("PUBLIC_BASE_URL", "http://127.0.0.1:8000"),
        database_url=env("DATABASE_URL", "sqlite:///careloop.db"),
        demo_mode=_bool(env("DEMO_MODE", "true")),
        clock_speed=float(env("CLOCK_SPEED", "60")),
        log_level=env("LOG_LEVEL", "INFO"),
    )
