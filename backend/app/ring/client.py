"""Ring API client. The only place in CareLoop that talks HTTP to Ring.

Modes:
- `live`: calls https://api.amazonvision.com with a Playground access token.
- `fixture`: reads `fixtures/ring_*.json` saved by `scripts/ring_probe.py`, falling back to
  the synthetic samples in `fixtures/sample/` (labelled as synthetic).
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import httpx

from app.config import REPO_ROOT
from app.core import clock
from app.ring.events import RingEvent, parse_events

logger = logging.getLogger(__name__)

API_BASE = "https://api.amazonvision.com"
TIMEOUT_SECONDS = 10.0
MAX_EVENT_PAGES = 10
FIXTURES_DIR = REPO_ROOT / "fixtures"


class RingError(Exception):
    """A Ring API call failed."""


class RingAuthError(RingError):
    """The access token was rejected."""

    def __init__(self) -> None:
        super().__init__("Ring token expired, regenerate in Playground")


class RingUnavailableError(RingError):
    """Ring could not be reached, or answered with a server error, after one retry."""


class RingClient:
    """Small typed wrapper over the Ring endpoints CareLoop uses."""

    def __init__(self, mode: str = "fixture", token: str = "", *,
                 base_url: str = API_BASE, fixtures_dir: Path = FIXTURES_DIR,
                 transport: httpx.BaseTransport | None = None) -> None:
        if mode not in {"live", "fixture"}:
            raise ValueError("RING_MODE must be 'live' or 'fixture'")
        if mode == "live" and not token:
            raise RingAuthError()
        self.mode = mode
        self.fixtures_dir = fixtures_dir
        self._transport = transport
        self._http: httpx.Client | None = None
        if mode == "live":
            self._http = httpx.Client(
                base_url=base_url,
                headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
                timeout=TIMEOUT_SECONDS,
                transport=transport,
            )

    def close(self) -> None:
        if self._http is not None:
            self._http.close()

    # ---- endpoints -------------------------------------------------------------------

    def users_me(self) -> dict[str, Any]:
        return self._get_json("/v1/users/me", fixture="users_me")

    def list_devices(self) -> list[dict[str, Any]]:
        body = self._get_json("/v1/devices", fixture="devices",
                              params={"include": "status,capabilities"})
        data = body.get("data", [])
        return data if isinstance(data, list) else []

    def first_device_id(self) -> str | None:
        devices = self.list_devices()
        return str(devices[0]["id"]) if devices else None

    def get_device_status(self, device_id: str) -> str:
        """Return 'online' or 'offline'."""
        body = self._get_json(f"/v1/devices/{device_id}/status", fixture="device_status")
        attrs = (body.get("data") or {}).get("attributes") or {}
        online = attrs.get("online")
        if online is None and isinstance(attrs.get("status"), str):
            online = attrs["status"].lower() == "online"
        return "online" if online else "offline"

    def get_events(self, device_id: str, since: datetime | None = None) -> list[RingEvent]:
        """Event history after `since`, oldest first.

        The docs we could read show no time-range parameters, so we fetch the history and
        filter here, following JSON:API `links.next` for at most MAX_EVENT_PAGES pages.
        """
        path: str | None = f"/v1/history/devices/{device_id}/events"
        events: list[RingEvent] = []
        for _ in range(MAX_EVENT_PAGES):
            if path is None:
                break
            body = self._get_json(path, fixture="events")
            events.extend(parse_events(body, device_id))
            path = _next_link(body) if self.mode == "live" else None
        if since is not None:
            events = [e for e in events if e.ts > since]
        return sorted(events, key=lambda e: e.ts)

    def get_snapshot(self, device_id: str, at: datetime | None = None) -> bytes | None:
        """A still image from the camera at `at` (default: 5 s ago), or None if unavailable.

        Verified against the Ring Developer Playground: the body is
        {"type": "at_timestamp", "timestamp": <epoch ms>} (the other type is
        "latest_in_range" with start_timestamp/end_timestamp), the API answers 303 with the
        image location, and the media host answers 416 MEDIA_NOT_FOUND when the camera
        recorded nothing at that moment. Bytes are kept in memory only.
        """
        if self.mode == "fixture":
            path = self.fixtures_dir / "demo_snapshot.jpg"
            return path.read_bytes() if path.is_file() else None
        moment = at or clock.now() - timedelta(seconds=5)
        payload = {"type": "at_timestamp", "timestamp": int(moment.timestamp() * 1000)}
        try:
            response = self._request("POST", f"/v1/devices/{device_id}/media/image/download",
                                     json=payload)
        except RingAuthError:
            raise
        except RingError as exc:
            logger.warning("snapshot unavailable: %s", exc)
            return None
        if response.status_code in (301, 302, 303, 307, 308):
            location = response.headers.get("location", "")
            if not location:
                return None
            # The media host is a different origin: never forward the Ring token to it.
            try:
                with httpx.Client(timeout=TIMEOUT_SECONDS, transport=self._transport) as plain:
                    response = plain.get(location)
            except httpx.HTTPError as exc:
                logger.warning("snapshot download failed: %s", exc.__class__.__name__)
                return None
            if response.status_code >= 400:
                logger.info("no snapshot at that moment (HTTP %s)", response.status_code)
                return None
        content_type = response.headers.get("content-type", "")
        if not (content_type.startswith("image/") or response.content[:3] == b"\xff\xd8\xff"):
            logger.warning("snapshot response was %s, not an image", content_type)
            return None
        return response.content

    # ---- plumbing --------------------------------------------------------------------

    def _get_json(self, path: str, *, fixture: str,
                  params: dict[str, str] | None = None) -> dict[str, Any]:
        if self.mode == "fixture":
            return self._fixture(fixture)
        response = self._request("GET", path, params=params)
        try:
            body = response.json()
        except ValueError as exc:
            raise RingError(f"{path} returned non-JSON content") from exc
        return body if isinstance(body, dict) else {"data": body}

    def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        """One request with a 10 s timeout and one retry on network or server errors."""
        assert self._http is not None
        last_error = "unknown error"
        for attempt in (1, 2):
            try:
                response = self._http.request(method, path, **kwargs)
            except httpx.HTTPError as exc:
                last_error = exc.__class__.__name__
                logger.warning("Ring %s %s failed (attempt %d): %s", method, path, attempt,
                               last_error)
                continue
            if response.status_code == 401:
                raise RingAuthError()
            if response.status_code >= 500:
                last_error = f"HTTP {response.status_code}"
                logger.warning("Ring %s %s returned %s (attempt %d)", method, path,
                               response.status_code, attempt)
                continue
            if response.status_code >= 400:
                raise RingError(f"{method} {path} returned HTTP {response.status_code}")
            return response
        raise RingUnavailableError(f"{method} {path} failed after retry: {last_error}")

    def _fixture(self, name: str) -> dict[str, Any]:
        for folder in (self.fixtures_dir, self.fixtures_dir / "sample"):
            path = folder / f"ring_{name}.json"
            if path.is_file():
                return json.loads(path.read_text(encoding="utf-8"))
        raise RingError(f"No fixture ring_{name}.json in {self.fixtures_dir}")


def _next_link(body: dict[str, Any]) -> str | None:
    links = body.get("links") or {}
    nxt = links.get("next") if isinstance(links, dict) else None
    if isinstance(nxt, dict):
        nxt = nxt.get("href")
    if not nxt or not isinstance(nxt, str):
        return None
    return nxt.removeprefix(API_BASE)
