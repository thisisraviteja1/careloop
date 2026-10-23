"""Remove personal data from Ring API responses before they are saved as fixtures."""

from __future__ import annotations

import re
from typing import Any

REDACTED = "REDACTED"

# Keys whose values are personal or secret. Matched case-insensitively against the key name.
SENSITIVE_KEYS = {
    "name",
    "first_name",
    "last_name",
    "full_name",
    "display_name",
    "email",
    "phone",
    "phone_number",
    "address",
    "address1",
    "address2",
    "street",
    "street1",
    "street2",
    "city",
    "zip",
    "zip_code",
    "postal_code",
    "country",
    "latitude",
    "longitude",
    "lat",
    "lng",
    "lon",
    "description",
    "mac_address",
    "serial_number",
    "ssid",
    "ip_address",
}
SECRET_KEY_PATTERN = re.compile(r"token|secret|password|signature|credential|api_key", re.I)
EMAIL_PATTERN = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
URL_QUERY_PATTERN = re.compile(r"(https?://[^\s\"?]+)\?[^\s\"]*")
# Ring's opaque IDs, e.g. "ava1.ring.device.2EUF4Z44...", also appear inside link URLs.
RING_ID_PATTERN = re.compile(r"ava1\.ring\.([a-z.]+?)\.([A-Z0-9]{16,})")
# Keys holding identifiers we replace with stable pseudonyms so fixtures stay consistent.
ID_KEYS = {"id", "device_id", "account_id", "user_id", "location_id", "event_id"}


class Scrubber:
    """Stateful scrubber: the same real ID always maps to the same pseudonym."""

    def __init__(self) -> None:
        self._ids: dict[str, str] = {}

    def pseudonym(self, value: str, kind: str) -> str:
        if value not in self._ids:
            count = sum(1 for p in self._ids.values() if p.startswith(f"{kind}-")) + 1
            self._ids[value] = f"{kind}-{count}"
        return self._ids[value]

    def scrub(self, data: Any, *, parent_type: str = "item") -> Any:
        """Return a scrubbed deep copy of a JSON-like value."""
        if isinstance(data, dict):
            node_type = str(data.get("type") or parent_type)
            return {k: self._scrub_value(k, v, node_type) for k, v in data.items()}
        if isinstance(data, list):
            return [self.scrub(item, parent_type=parent_type) for item in data]
        if isinstance(data, str):
            return self._scrub_string(data)
        return data

    def _scrub_value(self, key: str, value: Any, node_type: str) -> Any:
        lowered = key.lower()
        if SECRET_KEY_PATTERN.search(lowered) and not isinstance(value, dict | list):
            return REDACTED
        if lowered in SENSITIVE_KEYS and not isinstance(value, dict | list):
            return REDACTED if value not in (None, "") else value
        if lowered in ID_KEYS and isinstance(value, str | int) and value != "":
            kind = lowered.removesuffix("_id") if lowered != "id" else _kind(node_type)
            return self.pseudonym(str(value), kind)
        return self.scrub(value, parent_type=node_type)

    def _scrub_string(self, value: str) -> str:
        value = EMAIL_PATTERN.sub("user@example.com", value)
        value = RING_ID_PATTERN.sub(
            lambda m: self.pseudonym(m.group(0), _kind(m.group(1).split(".")[-1])), value)
        return URL_QUERY_PATTERN.sub(r"\1?REDACTED", value)


def _kind(node_type: str) -> str:
    """Turn a JSON:API type such as 'devices' into a short pseudonym prefix like 'device'."""
    cleaned = re.sub(r"[^a-z0-9]+", "-", node_type.lower()).strip("-") or "item"
    return cleaned.removesuffix("s") if cleaned.endswith("s") and len(cleaned) > 3 else cleaned
