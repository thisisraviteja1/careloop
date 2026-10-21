#!/usr/bin/env python3
"""Seed deterministic synthetic history (is_synthetic=true) into the CareLoop database.

Usage: python scripts/seed_history.py --days 28
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.baseline.model import day_key  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.core import clock  # noqa: E402
from app.db.session import init_engine, session_scope  # noqa: E402
from app.demo.seed import DEFAULT_SEED, seed_history  # noqa: E402
from app.detection.detector import WEEKDAYS, hhmm  # noqa: E402
from app.detection.runner import baseline_for  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--days", type=int, default=28)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    args = parser.parse_args()

    settings = get_settings()
    tz = ZoneInfo(settings.timezone)
    init_engine(settings.database_url)
    today = day_key(clock.now().astimezone(tz))
    with session_scope() as session:
        count = seed_history(session, today, args.days, tz, seed=args.seed)
        baseline = baseline_for(session, clock.now().astimezone(tz), tz, settings.margin_minutes)

    print(f"Seeded {count} synthetic events for the {args.days} days before {today}.")
    print(f"Today is a {WEEKDAYS[today.weekday()]}. Baseline state: {baseline.state}, "
          f"{baseline.sample_count} samples ({'pooled' if baseline.pooled else 'same weekday'}).")
    if baseline.threshold is not None:
        print(f"Usual window {hhmm(baseline.window_start)}–{hhmm(baseline.window_end)}, "
              f"alert threshold {hhmm(baseline.threshold)}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
