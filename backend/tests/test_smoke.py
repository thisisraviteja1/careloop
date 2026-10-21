from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import create_app


def test_healthz_and_dashboard(monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "sqlite://")
    monkeypatch.setenv("DEMO_MODE", "true")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "")
    client = TestClient(create_app(get_settings(), start_loops=False))
    assert client.get("/healthz").json() == {"status": "ok"}
    page = client.get("/")
    assert page.status_code == 200 and "CareLoop" in page.text
