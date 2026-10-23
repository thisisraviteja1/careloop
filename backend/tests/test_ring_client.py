from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from app.ring.client import RingAuthError, RingClient, RingError, RingUnavailableError
from app.ring.events import is_activity, parse_events, parse_timestamp

Handler = Callable[[httpx.Request], httpx.Response]


def live(handler: Handler) -> RingClient:
    return RingClient("live", "test-token", transport=httpx.MockTransport(handler))


def test_sends_bearer_token_and_parses_devices() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"data": [{"id": "d1", "type": "devices"}]})

    assert live(handler).first_device_id() == "d1"
    assert seen[0].headers["authorization"] == "Bearer test-token"
    assert seen[0].url.params["include"] == "status,capabilities"


def test_401_raises_token_expired() -> None:
    client = live(lambda r: httpx.Response(401))
    with pytest.raises(RingAuthError, match="regenerate in Playground"):
        client.users_me()


def test_retries_once_on_server_error() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(503)
        return httpx.Response(200, json={"data": {"attributes": {"online": True}}})

    assert live(handler).get_device_status("d1") == "online"
    assert calls["n"] == 2


def test_gives_up_after_one_retry_on_timeouts() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        raise httpx.ReadTimeout("slow", request=request)

    with pytest.raises(RingUnavailableError):
        live(handler).get_device_status("d1")
    assert calls["n"] == 2


def test_client_errors_are_not_retried() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(404)

    with pytest.raises(RingError):
        live(handler).users_me()
    assert calls["n"] == 1


def test_offline_status() -> None:
    client = live(lambda r: httpx.Response(200, json={"data": {"attributes": {"online": False}}}))
    assert client.get_device_status("d1") == "offline"


def test_events_follow_next_link_and_filter_since() -> None:
    page1 = {"data": [{"id": "e1", "attributes": {"event_type": "motion_detected",
                                                  "sub_type": "human",
                                                  "start": "2026-10-21T01:00:00Z"}}],
             "links": {"next": "https://api.amazonvision.com/v1/history/devices/d1/events?p=2"}}
    page2 = {"data": [{"id": "e2", "attributes": {"event_type": "button_press",
                                                  "start": "2026-10-21T02:00:00Z"}}]}

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=page2 if request.url.params.get("p") == "2" else page1)

    events = live(handler).get_events("d1", since=datetime(2026, 10, 21, 1, 30, tzinfo=UTC))
    assert [e.ring_event_id for e in events] == ["e2"]
    assert events[0].is_activity


def test_snapshot_returns_image_bytes_only() -> None:
    def image(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"\xff\xd8jpeg", headers={"content-type": "image/jpeg"})

    def not_image(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"errors": []})

    assert live(image).get_snapshot("d1") == b"\xff\xd8jpeg"
    assert live(not_image).get_snapshot("d1") is None
    assert live(lambda r: httpx.Response(403)).get_snapshot("d1") is None


def test_fixture_mode_reads_sample_files(tmp_path: Path) -> None:
    client = RingClient("fixture")
    assert client.first_device_id() == "device-1"
    events = client.get_events("device-1")
    assert len(events) == 4
    assert [e.is_activity for e in events] == [True, True, False, True]


def test_live_mode_without_token_is_an_auth_error() -> None:
    with pytest.raises(RingAuthError):
        RingClient("live", "")


@pytest.mark.parametrize(
    ("event_type", "sub_type", "expected"),
    [("motion_detected", "human", True), ("motion_detected", "vehicle", False),
     ("motion_detected", None, False), ("button_press", None, True), ("ding", None, True),
     ("motion.human", None, True), ("live_view", None, False)],
)
def test_activity_classification(event_type: str, sub_type: str | None, expected: bool) -> None:
    assert is_activity(event_type, sub_type) is expected


def test_timestamp_formats() -> None:
    expected = datetime(2026, 10, 21, 1, 0, tzinfo=UTC)
    assert parse_timestamp("2026-10-21T01:00:00Z") == expected
    assert parse_timestamp(int(expected.timestamp())) == expected
    assert parse_timestamp(int(expected.timestamp() * 1000)) == expected
    assert parse_timestamp("not a date") is None


def test_unreadable_items_are_skipped() -> None:
    body = {"data": [{"id": "x", "attributes": {}}, {"attributes": {"start": "2026-10-21"}}]}
    assert parse_events(body, "d1") == []


def test_snapshot_follows_redirect_without_leaking_the_token() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.host == "api.amazonvision.com":
            return httpx.Response(303, headers={"location": "https://download.example.dev/m/1"})
        return httpx.Response(200, content=b"\xff\xd8\xffimg",
                              headers={"content-type": "image/jpeg"})

    at = datetime(2026, 10, 23, 7, 38, 20, tzinfo=UTC)
    assert live(handler).get_snapshot("d1", at=at) == b"\xff\xd8\xffimg"
    import json as _json
    assert _json.loads(seen[0].content) == {"type": "at_timestamp",
                                            "timestamp": int(at.timestamp() * 1000)}
    assert "authorization" not in seen[1].headers


def test_snapshot_media_not_found_is_none() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "api.amazonvision.com":
            return httpx.Response(303, headers={"location": "https://download.example.dev/m/1"})
        return httpx.Response(416, json={"errors": [{"code": "MEDIA_NOT_FOUND"}]})

    assert live(handler).get_snapshot("d1") is None
