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
