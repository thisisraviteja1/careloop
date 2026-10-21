#!/usr/bin/env python3
"""Run one demo scenario in the terminal, with the real Bedrock and Telegram paths when
configured (otherwise the deterministic fallbacks).

Usage: python scripts/demo_scenario.py --scenario missed-morning [--speed 60]
"""

from __future__ import annotations

import argparse
import logging
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.config import get_settings  # noqa: E402
from app.core import clock  # noqa: E402
from app.core.clock import Clock  # noqa: E402
from app.db.session import init_engine  # noqa: E402
from app.demo.scenarios import SCENARIOS  # noqa: E402
from app.notify.telegram import TelegramError, poll_once  # noqa: E402
from app.service import CareLoop  # noqa: E402

TIMEOUT_REAL_SECONDS = 300


def telegram_thread(svc: CareLoop, stop: threading.Event) -> None:
    offset = None
    while not stop.is_set() and svc.telegram is not None:
        try:
            offset = poll_once(svc.telegram, offset, svc.handle_telegram_ack, timeout=2)
        except TelegramError as exc:
            logging.warning("Telegram: %s", exc)
            time.sleep(2)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--scenario", choices=sorted(SCENARIOS), default="missed-morning")
    parser.add_argument("--speed", type=float, default=None)
    args = parser.parse_args()

    settings = get_settings()
    if not settings.demo_mode:
        print("Set DEMO_MODE=true to run scenarios.")
        return 2
    logging.basicConfig(level=logging.WARNING)
    clock.set_clock(Clock(settings.timezone))
    init_engine(settings.database_url)
    svc = CareLoop(settings)
    svc.demo_seed(28)
    state = svc.demo_run(args.scenario, args.speed)
    print(f"Scenario: {args.scenario}: {SCENARIOS[args.scenario]}")
    print(f"Speed ×{clock.get_clock().speed:g}. Synthetic history, fixture image.\n")

    stop = threading.Event()
    threading.Thread(target=telegram_thread, args=(svc, stop), daemon=True).start()
    printed = 0
    started = time.monotonic()
    try:
        while not state.finished and time.monotonic() - started < TIMEOUT_REAL_SECONDS:
            svc.tick()
            for line in state.log[printed:]:
                print(f"  {line['time']:>8}  {line['text']}")
            printed = len(state.log)
            time.sleep(1)
    finally:
        stop.set()
    for line in state.log[printed:]:
        print(f"  {line['time']:>8}  {line['text']}")
    print(f"\nFinished in {time.monotonic() - started:.0f} real seconds.")
    return 0 if state.finished else 1


if __name__ == "__main__":
    sys.exit(main())
