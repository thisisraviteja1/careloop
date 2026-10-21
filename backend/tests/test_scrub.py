import json

from app.ring.scrub import REDACTED, Scrubber

USERS_ME = {
    "data": {
        "id": "acct-998877",
        "type": "users",
        "attributes": {
            "first_name": "Real",
            "last_name": "Person",
            "email": "real.person@example.org",
        },
    }
}

DEVICES = {
    "data": [
        {
            "id": "dev-abc123",
            "type": "devices",
            "attributes": {
                "name": "Real Person's Front Door",
                "location": {"address": "12 Real Street", "latitude": 17.4, "longitude": 78.5},
                "online": True,
            },
        }
    ],
    "links": {"next": "https://api.amazonvision.com/v1/devices?page_token=secret123"},
}


def test_personal_fields_are_redacted() -> None:
    out = Scrubber().scrub(USERS_ME)
    attrs = out["data"]["attributes"]
    assert attrs == {"first_name": REDACTED, "last_name": REDACTED, "email": REDACTED}
    assert "acct-998877" not in json.dumps(out)


def test_nested_location_and_urls_are_scrubbed() -> None:
    text = json.dumps(Scrubber().scrub(DEVICES))
    for secret in ("Real Person", "12 Real Street", "17.4", "secret123", "dev-abc123"):
        assert secret not in text
    assert '"online": true' in text


def test_ids_map_to_stable_pseudonyms() -> None:
    scrubber = Scrubber()
    first = scrubber.scrub(DEVICES)["data"][0]["id"]
    again = scrubber.scrub({"data": {"id": "dev-abc123", "type": "devices"}})["data"]["id"]
    assert first == again == "device-1"


def test_token_like_keys_and_inline_emails() -> None:
    out = Scrubber().scrub({"access_token": "eyJabc", "note": "contact a.b@example.org"})
    assert out == {"access_token": REDACTED, "note": "contact user@example.com"}


def test_event_attributes_are_kept() -> None:
    event = {"id": "ev-1", "type": "events", "attributes": {"event_type": "motion_detected",
                                                             "sub_type": "human",
                                                             "start": "2026-10-21T07:02:00Z"}}
    attrs = Scrubber().scrub({"data": [event]})["data"][0]["attributes"]
    assert attrs == event["attributes"]
