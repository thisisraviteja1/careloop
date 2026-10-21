#!/usr/bin/env python3
"""Run the fixture image and sample facts through the real Bedrock path and print the result."""

from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.ai.bedrock import Bedrock  # noqa: E402
from app.ai.explainer import alert_parts, checkin_message, explain, validate_alert  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.vision.snapshot import describe  # noqa: E402


def main() -> int:
    settings = get_settings()
    tz = ZoneInfo(settings.timezone)
    now = datetime.now(tz).replace(hour=9, minute=15, second=0, microsecond=0)
    facts = {
        "kind": "A1", "day": now.date().isoformat(), "person_name": settings.person_name,
        "last_seen_ts": (now - timedelta(days=1)).replace(hour=21, minute=40).isoformat(),
        "usual_window_start": "06:45", "usual_window_end": "07:20", "threshold": "08:05",
        "weekday": now.strftime("%A"), "sample_count": 4, "pooled": False,
        "margin_minutes": 45,
    }
    audit_rows: list[tuple[str, str, str]] = []
    bedrock = Bedrock(settings.aws_region, audit=lambda *row: audit_rows.append(row))
    image = (REPO_ROOT / "fixtures" / "demo_snapshot.jpg").read_bytes()

    scene = describe(image, bedrock, settings.bedrock_vision_model_id)
    print(f"Scene: {scene}\n")
    result = explain(facts, scene, now, now, bedrock, settings.bedrock_text_model_id)
    parts = alert_parts(facts, scene, now, now)
    print(f"Alert ({result.source}, {len(result.text.split())} words):\n{result.text}\n")
    if result.problems:
        print(f"Model output rejected because: {'; '.join(result.problems)}")
    print(f"Validator on the final text: {validate_alert(result.text, parts) or 'OK'}")
    print(f"Check-in: {checkin_message(settings.person_name, now)}\n")
    print("Audit rows:")
    for row in audit_rows:
        print(f"  {row}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
