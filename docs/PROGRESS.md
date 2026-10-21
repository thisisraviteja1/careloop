# Progress

## Phase 0: scaffold and Ring probe

**Done**
- Repo structure, MIT LICENSE, README stub, Makefile (`setup`, `test`, `lint`, `probe`, `run`, `demo` placeholder), `.gitignore`, `.env.example` with every env var.
- `pyproject.toml` with the full fixed stack, ruff config, and pytest config.
- `backend/app/config.py` (settings from env / `.env`, no extra dependency) and a minimal FastAPI app with `/healthz`.
- `backend/app/ring/scrub.py`: removes names, emails, addresses, coordinates, tokens and URL query strings, and replaces IDs with stable pseudonyms (`device-1`, `user-1`). Tested.
- `scripts/ring_probe.py`: calls `/v1/users/me`, `/v1/devices?include=status,capabilities`, then device status and event history for the first device; prints HTTP status and trimmed JSON, summarizes the `event_type` / `sub_type` values actually returned, and saves scrubbed fixtures to `fixtures/ring_*.json`. Stops with a clear message if the device list is empty; clear message on 401.
- Friction log started (4 entries).

**Waiting on a human**
- Run `make probe` with a fresh Playground token and commit the scrubbed `fixtures/ring_*.json`. Phase 1 must not start until the real event shape is known.

**Next**
- Phase 1: clock, database, Ring client (live and fixture modes), poller.

**Open questions**
- Real event type names: docs say `motion_detected` + `sub_type: human` and `button_press`; the hello-world script suggests `motion.human` and `ding`. The probe output settles it.
- Event history pagination and time-range query params are not documented on the page we could read. Check the probe's `links` / `meta` output.
- Snapshot request body (the `components` array) is still unconfirmed.

## Phase 1: clock, database, Ring client, poller

**Done**
- `core/clock.py`: one time source with a speed multiplier, `set_time`, `advance`, and freeze (speed 0).
- `db/`: SQLModel tables `Event`, `Anomaly`, `EscalationStep`, `NotificationLog`, `AuditLog`, `DeviceHealth`. All datetimes use our own `UTCDateTime` column type (aware in, aware UTC out), so behaviour doesn't change between SQLModel releases.
- `ring/client.py`: `live` and `fixture` modes; 10 s timeout, one retry on network or 5xx errors, no retry on 4xx; 401 raises "Ring token expired, regenerate in Playground". Snapshot returns bytes only when the response is an image, otherwise `None`.
- `ring/events.py`: parses event history; activity = human motion or doorbell press, accepting both documented spellings until the real probe confirms one.
- `ring/poller.py`: `sync_once` with a cursor (newest stored event), de-duplication by Ring ID, and device health tracking. `python -m app.ring.poller --once` works in fixture mode.
- `fixtures/sample/`: hand-written synthetic responses (labelled) so fixture mode works before the probe runs.

**Open questions**
- Event history has no documented time filter, so the client filters after fetching and follows `links.next` for up to 10 pages. Revisit once the probe shows real paging.
