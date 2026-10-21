import httpx
import pytest

from scripts.ring_probe import ProbeError, call


def _client(status: int, body: object) -> httpx.Client:
    transport = httpx.MockTransport(lambda request: httpx.Response(status, json=body))
    return httpx.Client(base_url="https://api.amazonvision.com", transport=transport)


def test_call_returns_json() -> None:
    with _client(200, {"data": []}) as client:
        assert call(client, "GET", "/v1/devices") == {"data": []}


def test_401_gives_clear_token_message() -> None:
    with _client(401, {"errors": []}) as client, pytest.raises(ProbeError, match="Playground"):
        call(client, "GET", "/v1/users/me")


def test_other_errors_raise() -> None:
    with _client(500, {"errors": []}) as client, pytest.raises(ProbeError, match="HTTP 500"):
        call(client, "GET", "/v1/devices")
