"""FastAPI entry point. The scheduler loop and API routes arrive in Phase 5."""

from fastapi import FastAPI

app = FastAPI(title="CareLoop", version="0.0.1")


@app.get("/healthz")
def healthz() -> dict[str, str]:
    """Liveness check."""
    return {"status": "ok"}
