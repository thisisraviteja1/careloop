#!/usr/bin/env python3
"""Download an image snapshot (JPEG or PNG) from a Ring camera."""

import argparse
import json

import requests

API_BASE = "https://api.amazonvision.com"


def get_image_snapshot(token, device_id, output, components=None):
    """Request a snapshot and save it to `output`."""
    url = f"{API_BASE}/v1/devices/{device_id}/media/image/download"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    body = {"components": components} if components else {}

    print(f"\n→ POST {url}")
    print(f'  curl -X POST "{url}" \\')
    print(f'    -H "Authorization: Bearer $TOKEN" \\')
    print(f'    -H "Content-Type: application/json" \\')
    print(f"    -d '{json.dumps(body)}' --output {output}\n")

    response = requests.post(url, headers=headers, json=body)
    response.raise_for_status()

    content_type = response.headers.get("Content-Type", "")
    if not content_type.startswith("image/"):
        print(f"Expected an image but got {content_type or 'no content type'}:")
        print(response.text[:500])
        return None

    with open(output, "wb") as handle:
        handle.write(response.content)
    print(f"Saved {len(response.content)} bytes ({content_type}) to {output}")
    return output


def _resolve_device_id(token, device_id):
    if device_id:
        return device_id
    from list_devices import list_devices
    devices = list_devices(token)
    if not devices:
        raise SystemExit("No devices found. Cannot auto-discover device ID.")
    return devices[0]["id"]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Download a Ring camera image snapshot")
    parser.add_argument("--token", required=True, help="Ring API access token")
    parser.add_argument("--device-id", help="Device ID (auto-discovered if not provided)")
    parser.add_argument("--components", help="Camera modules on multi-camera devices "
                                             "(comma-separated)")
    parser.add_argument("--output", default="snapshot.jpg", help="Where to save the image")
    args = parser.parse_args()
    resolved_id = _resolve_device_id(args.token, args.device_id)
    components = args.components.split(",") if args.components else None
    get_image_snapshot(args.token, resolved_id, args.output, components)
