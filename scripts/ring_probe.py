#!/usr/bin/env python3
"""Phase 0 Ring probe: call the real Ring API and save scrubbed responses as fixtures.

Usage:
    RING_ACCESS_TOKEN=... python scripts/ring_probe.py
    python scripts/ring_probe.py --device-id <id> --no-save

The token comes from the Ring Developer Playground ("Generate Token") and lives about
30 minutes. It is read from the environment or .env and is never printed or saved.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import httpx

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.config import load_dotenv  # noqa: E402
from app.ring.scrub import Scrubber  # noqa: E402

API_BASE = "https://api.amazonvision.com"
FIXTURES = REPO_ROOT / "fixtures"
TIMEOUT_SECONDS = 10.0
TRIM_CHARS = 2500


class ProbeError(Exception):
    """A probe step failed in a way the human needs to act on."""


def call(client: httpx.Client, method: str, path: str, **kwargs: Any) -> Any:
    """Make one request, print status and trimmed JSON, and return the parsed body."""
    print(f"\n→ {method} {path}")
    try:
        response = client.request(method, path, **kwargs)
    except httpx.HTTPError as exc:
        raise ProbeError(f"Network error calling {path}: {exc.__class__.__name__}") from exc
    print(f"  HTTP {response.status_code}  ({response.elapsed.total_seconds() * 1000:.0f} ms)")
    if response.status_code == 401:
        raise ProbeError("Ring token expired or invalid, regenerate it in the Playground.")
    if response.status_code >= 400:
        raise ProbeError(f"{path} returned HTTP {response.status_code}: {response.text[:500]}")
    try:
        body = response.json()
    except ValueError:
        print(f"  (non-JSON body, {len(response.content)} bytes)")
        return None
    text = json.dumps(body, indent=2)
    print(text if len(text) <= TRIM_CHARS else text[:TRIM_CHARS] + "\n  … (trimmed)")
    return body


def summarize_events(body: Any) -> None:
    """Print the event type values and attribute keys actually returned."""
    items = body.get("data", []) if isinstance(body, dict) else []
    types = Counter(str(item.get("attributes", {}).get("event_type")) for item in items)
    sub_types = Counter(str(item.get("attributes", {}).get("sub_type")) for item in items)
    keys = sorted({k for item in items for k in item.get("attributes", {})})
    print(f"\n  Events returned: {len(items)}")
    print(f"  event_type values: {dict(types)}")
    print(f"  sub_type values:   {dict(sub_types)}")
    print(f"  attribute keys:    {keys}")
    print(f"  top-level keys:    {sorted(body) if isinstance(body, dict) else type(body)}")


def save(name: str, body: Any, scrubber: Scrubber) -> None:
    path = FIXTURES / f"ring_{name}.json"
    path.write_text(json.dumps(scrubber.scrub(body), indent=2) + "\n", encoding="utf-8")
    print(f"  saved scrubbed → {path.relative_to(REPO_ROOT)}")


def run(device_id: str | None, save_fixtures: bool) -> int:
    load_dotenv()
    token = os.environ.get("RING_ACCESS_TOKEN", "").strip()
    if not token:
        print("RING_ACCESS_TOKEN is not set. Generate one in the Ring Developer Playground.")
        return 2

    scrubber = Scrubber()
    responses: dict[str, Any] = {}
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    with httpx.Client(base_url=API_BASE, headers=headers, timeout=TIMEOUT_SECONDS) as client:
        responses["users_me"] = call(client, "GET", "/v1/users/me")
        devices = call(client, "GET", "/v1/devices", params={"include": "status,capabilities"})
        responses["devices"] = devices

        device_list = devices.get("data", []) if isinstance(devices, dict) else []
        if not device_list and not device_id:
            print(
                "\n⚠ The device list is empty: this token does not expose any Ring device.\n"
                "  Stop here. Log it in docs/friction-log.md and ask the team how to proceed\n"
                "  (fixture mode still works for development)."
            )
            if save_fixtures:
                for name, body in responses.items():
                    save(name, body, scrubber)
            return 3

        device_id = device_id or str(device_list[0]["id"])
        print(f"\nUsing device {scrubber.pseudonym(device_id, 'device')} (real ID not shown)")
        responses["device_status"] = call(client, "GET", f"/v1/devices/{device_id}/status")
        responses["events"] = call(client, "GET", f"/v1/history/devices/{device_id}/events")
        summarize_events(responses["events"])

    if save_fixtures:
        FIXTURES.mkdir(exist_ok=True)
        for name, body in responses.items():
            if body is not None:
                save(name, body, scrubber)
        print("\nReview the saved files before committing: names, emails and IDs are replaced.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--device-id", help="Probe this device instead of the first one listed")
    parser.add_argument("--no-save", action="store_true", help="Print only, don't write fixtures")
    args = parser.parse_args()
    try:
        return run(args.device_id, save_fixtures=not args.no_save)
    except ProbeError as exc:
        print(f"\n✗ {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
