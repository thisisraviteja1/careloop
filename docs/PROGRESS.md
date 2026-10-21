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

## Phase 2: baseline, detector, seed data

**Done**
- `baseline/model.py` (pure): days start at 04:00; first-activity minute per day; per-weekday [p10, p90] window; threshold = p90 + `MARGIN_MINUTES`; pooled fallback under 4 weekday samples; `learning` under 7 days of history. Only days before the judged day are used.
- `detection/detector.py` (pure): `evaluate` returns degraded / normal / learning / waiting / anomaly, with the A1 `facts` JSON.
- `detection/runner.py`: loads activity, applies the device health guard (offline or event errors mean no A1, and the caregiver is told once), and creates at most one A1 per day.
- `scripts/seed_history.py --days 28`: deterministic synthetic history (`is_synthetic=true`), with one 7:40 day, two 6:40 days, later weekends, daytime and vehicle events, and 9:40 PM as the last sighting the evening before.
- Tests cover every case listed in the plan, plus no-peeking and determinism.

## Phase 3: Bedrock vision, explainer, audit

**Done**
- `ai/bedrock.py`: Converse wrapper (text, and image + text), model IDs from env, 10 s timeouts, one retry (botocore `max_attempts=2`). Every call writes an audit row with action, reason and outcome (model ID and token counts, never content).
- `vision/snapshot.py`: `take_snapshot` (audited with the reason "anomaly A1 verification", bytes kept in memory only) and `describe` (the planned prompt, plus a request for a noun phrase so the hedged sentence reads naturally). Validates at most 25 words and the block list; anything else gives "camera image unavailable".
- `ai/safety.py`: forbidden words plus a block list, applied to every model output (Ring Computer Vision Guidelines).
- `ai/explainer.py`: deterministic template in the fixed order, 12-hour times, hedged camera line; optional Bedrock phrasing from the facts JSON and scene only, kept only if it passes the validator (70 words or fewer, no blocked words, key times and name present). Also builds the check-in, neighbor and degraded messages.
- `scripts/check_bedrock.py` (lists models and inference profiles, test call, advice per error code) and `scripts/try_explainer.py`.
- `fixtures/demo_snapshot.jpg`: a **generated illustration** of a doorway with a milk pouch on the mat, no people. Replace it with a real photo (no faces) for the video if you can.
- Tests use botocore's `Stubber`, which also validates every request against the real Converse API schema.

**Waiting on a human**
- Run `python scripts/check_bedrock.py`, then `python scripts/try_explainer.py`, with real AWS credentials. Real Bedrock output has not been seen yet.
