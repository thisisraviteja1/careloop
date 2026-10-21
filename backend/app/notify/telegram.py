"""Telegram Bot API via httpx: sendMessage with inline buttons, and getUpdates long-polling.

No webhooks and no public URL are needed. Bot tokens are never logged.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

import httpx

from app.notify.base import Recipient, SendResult

logger = logging.getLogger(__name__)

API = "https://api.telegram.org"
TIMEOUT_SECONDS = 10.0
BUTTON_LABEL = {"elder": "I'm OK", "caregiver": "I'm handling it", "neighbor": "I'm handling it"}
CALLBACK_PREFIX = "ack:"


class TelegramError(Exception):
    pass


class TelegramNotifier:
    name = "telegram"

    def __init__(self, bot_token: str, ack_url: Callable[[str], str], *,
                 transport: httpx.BaseTransport | None = None) -> None:
        self._client = httpx.Client(base_url=f"{API}/bot{bot_token}", timeout=TIMEOUT_SECONDS,
                                    transport=transport)
        self._ack_url = ack_url

    def close(self) -> None:
        self._client.close()

    def _call(self, method: str, payload: dict[str, Any], timeout: float | None = None) -> Any:
        try:
            response = self._client.post(f"/{method}", json=payload,
                                         timeout=timeout or TIMEOUT_SECONDS)
        except httpx.HTTPError as exc:
            raise TelegramError(f"{method}: {exc.__class__.__name__}") from exc
        try:
            body = response.json()
        except ValueError as exc:
            raise TelegramError(f"{method}: HTTP {response.status_code}") from exc
        if not body.get("ok"):
            raise TelegramError(f"{method}: {body.get('description', response.status_code)}")
        return body.get("result")

    def send(self, recipient: Recipient, text: str, ack_token: str | None = None) -> SendResult:
        if not recipient.chat_id:
            return SendResult("skipped", f"no Telegram chat for {recipient.role}")
        payload: dict[str, Any] = {"chat_id": recipient.chat_id, "text": text}
        if ack_token:
            label = BUTTON_LABEL.get(recipient.role, "I'm handling it")
            payload["reply_markup"] = {"inline_keyboard": [[
                {"text": label, "callback_data": f"{CALLBACK_PREFIX}{ack_token}"},
            ]]}
            payload["text"] = f"{text}\n\nOr open the big-button page: {self._ack_url(ack_token)}"
        try:
            self._call("sendMessage", payload)
        except TelegramError as exc:
            return SendResult("failed", str(exc))
        return SendResult("sent")

    def get_updates(self, offset: int | None, timeout: int = 20) -> list[dict[str, Any]]:
        payload: dict[str, Any] = {"timeout": timeout, "allowed_updates": ["callback_query"]}
        if offset is not None:
            payload["offset"] = offset
        return self._call("getUpdates", payload, timeout=timeout + TIMEOUT_SECONDS) or []

    def answer_callback(self, callback_id: str, text: str) -> None:
        try:
            self._call("answerCallbackQuery", {"callback_query_id": callback_id, "text": text})
        except TelegramError as exc:
            logger.warning("answerCallbackQuery failed: %s", exc)


def poll_once(bot: TelegramNotifier, offset: int | None,
              handle: Callable[[str, str], str], timeout: int = 20) -> int | None:
    """One getUpdates round. `handle(ack_token, chat_id)` returns the reply text.
    Returns the next offset."""
    for update in bot.get_updates(offset, timeout=timeout):
        offset = int(update["update_id"]) + 1
        query = update.get("callback_query")
        if not query:
            continue
        data = str(query.get("data", ""))
        chat_id = str(((query.get("message") or {}).get("chat") or {}).get("id", ""))
        reply = (handle(data.removeprefix(CALLBACK_PREFIX), chat_id)
                 if data.startswith(CALLBACK_PREFIX) else "Unknown button.")
        bot.answer_callback(str(query.get("id")), reply)
    return offset
