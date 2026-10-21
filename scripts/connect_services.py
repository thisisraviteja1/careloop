#!/usr/bin/env python3
"""Check every real service in one go and write a report (no secrets) to connect-report.txt.

Runs, for whatever is configured in .env:
  1. Ring: users/me, devices, status and event history; saves scrubbed fixtures.
  2. Amazon Bedrock: one test call per model, the guardrail if set, then the real
     snapshot description and alert for the fixture image.
  3. Telegram: checks the bot, lists the chats that have messaged it, and sends a test
     message to each configured chat ID.

Usage: .venv/bin/python scripts/connect_services.py
"""

from __future__ import annotations

import contextlib
import io
import sys
import traceback
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import httpx  # noqa: E402

from app.config import get_settings  # noqa: E402

REPORT = REPO_ROOT / "connect-report.txt"


class Tee(io.TextIOBase):
    def __init__(self, *streams: io.TextIOBase) -> None:
        self.streams = streams

    def write(self, text: str) -> int:
        for stream in self.streams:
            stream.write(text)
        return len(text)

    def flush(self) -> None:
        for stream in self.streams:
            if not stream.closed:
                stream.flush()


def section(title: str, run: Callable[[], None]) -> None:
    print(f"\n{'=' * 70}\n{title}\n{'=' * 70}")
    try:
        run()
    except SystemExit:
        pass
    except Exception:  # report everything, keep going
        print("✗ Unexpected error:")
        print(scrub(traceback.format_exc(limit=3)))


def scrub(text: str) -> str:
    """Remove every configured secret from text that goes into the report."""
    settings = get_settings()
    import os

    for secret in (settings.ring_access_token, settings.telegram_bot_token,
                   os.environ.get("AWS_SECRET_ACCESS_KEY", ""), settings.ack_secret):
        if secret and len(secret) > 6:
            text = text.replace(secret, "REDACTED")
    return text


def ring() -> None:
    settings = get_settings()
    if not settings.ring_access_token:
        print("skipped: RING_ACCESS_TOKEN is empty")
        return
    import ring_probe

    try:
        code = ring_probe.run(settings.ring_device_id or None, save_fixtures=True)
    except ring_probe.ProbeError as exc:
        print(f"✗ {exc}")
        return
    print(f"\nprobe exit code: {code} (0 = ok, 1 = error, 3 = no devices)")


def bedrock() -> None:
    settings = get_settings()
    if not (settings.bedrock_vision_model_id or settings.bedrock_text_model_id):
        print("skipped: BEDROCK_VISION_MODEL_ID and BEDROCK_TEXT_MODEL_ID are empty")
        return
    import check_bedrock

    check_bedrock.main()
    print("\n--- real explainer run on the fixture image ---")
    import try_explainer

    try_explainer.main()


def telegram() -> None:
    settings = get_settings()
    token = settings.telegram_bot_token
    if not token:
        print("skipped: TELEGRAM_BOT_TOKEN is empty")
        return
    api = f"https://api.telegram.org/bot{token}"
    with httpx.Client(timeout=15) as client:
        me = client.get(f"{api}/getMe").json()
        if not me.get("ok"):
            print(f"✗ bot token rejected: {me.get('description')}")
            return
        print(f"✓ bot @{me['result'].get('username')} is working")
        updates = client.post(f"{api}/getUpdates", json={
            "allowed_updates": ["message", "callback_query"]}).json().get("result", [])
        chats: dict[str, str] = {}
        for update in updates:
            message = update.get("message") or update.get("edited_message") or {}
            chat = message.get("chat") or {}
            if chat.get("id") is not None:
                label = chat.get("first_name") or chat.get("title") or ""
                if chat.get("username"):
                    label += f" (@{chat['username']})"
                chats[str(chat["id"])] = label.strip()
        print(f"Chats that have messaged the bot: {len(chats)}")
        for chat_id, label in chats.items():
            print(f"  chat id {chat_id}: {label}")
        if not chats:
            print("  → send 'hi' to the bot again. If CareLoop is running (make demo / make run), "
                  "the bot replies with your chat ID instead, because the server reads the "
                  "messages first.")
        roles = {"elder": settings.telegram_chat_elder,
                 "caregiver": settings.telegram_chat_caregiver,
                 "neighbor": settings.telegram_chat_neighbor}
        for role, chat_id in roles.items():
            if not chat_id:
                print(f"  {role}: no chat ID set yet")
                continue
            sent = client.post(f"{api}/sendMessage", json={
                "chat_id": chat_id,
                "text": f"CareLoop test: this chat is set up as the {role}."}).json()
            status = "✓ test message sent" if sent.get("ok") else f"✗ {sent.get('description')}"
            print(f"  {role} ({chat_id}): {status}")


def main() -> int:
    settings = get_settings()
    with REPORT.open("w", encoding="utf-8") as handle:
        tee = Tee(sys.stdout, handle)
        with contextlib.redirect_stdout(tee), contextlib.redirect_stderr(tee):
            now = datetime.now(ZoneInfo(settings.timezone))
            print(f"CareLoop connection report, {now:%Y-%m-%d %H:%M} ({settings.timezone})")
            print(f"Python {sys.version.split()[0]}, AWS region {settings.aws_region}")
            section("1. Ring API", ring)
            section("2. Amazon Bedrock", bedrock)
            section("3. Telegram", telegram)
            print(f"\nReport saved to {REPORT.name} (contains no tokens or keys).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
