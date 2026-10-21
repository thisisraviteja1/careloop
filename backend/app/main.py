"""FastAPI entry point: API, dashboard, ack page, and the single asyncio loop.

Run with:  uvicorn app.main:create_app --factory --app-dir backend
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse

from app.api.ack import router as ack_router
from app.api.routes import ApiError
from app.api.routes import router as api_router
from app.config import REPO_ROOT, Settings, get_settings
from app.core import clock
from app.core.clock import Clock
from app.db.session import init_engine
from app.notify.telegram import TelegramError, poll_once
from app.ring.client import RingAuthError
from app.service import CareLoop

logger = logging.getLogger("careloop")

DASHBOARD = REPO_ROOT / "frontend" / "index.html"


async def tick_loop(svc: CareLoop, interval: float) -> None:
    """Poller → detector → escalation, once per interval (real seconds)."""
    while True:
        try:
            await asyncio.to_thread(svc.tick)
        except RingAuthError as exc:
            logger.error("%s", exc)
        except Exception:  # keep the loop alive; the next tick retries
            logger.exception("tick failed")
        await asyncio.sleep(interval)


async def telegram_loop(svc: CareLoop) -> None:
    """Long-poll getUpdates and turn button taps into acks."""
    offset: int | None = None
    while svc.telegram is not None:
        try:
            offset = await asyncio.to_thread(poll_once, svc.telegram, offset,
                                             svc.handle_telegram_ack, 20)
        except TelegramError as exc:
            logger.warning("Telegram polling: %s", exc)
            await asyncio.sleep(5)


def create_app(settings: Settings | None = None, *, start_loops: bool = True,
               careloop: CareLoop | None = None) -> FastAPI:
    settings = settings or get_settings()
    logging.basicConfig(level=settings.log_level,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        tasks: list[asyncio.Task[None]] = []
        if start_loops:
            interval = 1.0 if settings.demo_mode else float(settings.poll_interval_seconds)
            tasks.append(asyncio.create_task(tick_loop(app.state.careloop, interval)))
            if app.state.careloop.telegram is not None:
                tasks.append(asyncio.create_task(telegram_loop(app.state.careloop)))
        yield
        for task in tasks:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    app = FastAPI(title="CareLoop", version="0.1.0", lifespan=lifespan)
    if careloop is None:
        clock.set_clock(Clock(settings.timezone))
        init_engine(settings.database_url)
        careloop = CareLoop(settings)
    app.state.careloop = careloop
    app.include_router(api_router)
    app.include_router(ack_router)

    @app.exception_handler(ApiError)
    async def api_error(request: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(status_code=exc.status, content={"error": {
            "code": exc.code, "message": exc.message, "details": exc.details}})

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"error": {
            "code": "http_error", "message": str(exc.detail), "details": {}}})

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(status_code=422, content={"error": {
            "code": "invalid_request", "message": "The request is not valid.",
            "details": {"errors": [str(e.get("msg")) for e in exc.errors()]}}})

    @app.exception_handler(ValueError)
    async def value_error(request: Request, exc: ValueError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"error": {
            "code": "bad_request", "message": str(exc), "details": {}}})

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/", include_in_schema=False)
    def dashboard() -> FileResponse:
        return FileResponse(DASHBOARD, media_type="text/html")

    return app

