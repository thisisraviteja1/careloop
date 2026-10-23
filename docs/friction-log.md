# Friction log

Every real tooling problem, written down when it happens. Format: task, steps taken, expected vs. actual, severity, workaround, suggestion.

---

### 1. Ring docs MCP server unreachable from our build environment
- **Task:** confirm Ring API response shapes before writing the probe (Phase 0).
- **Steps:** sent an MCP `initialize` request to `https://knowledge.appstore-mcp.ring.amazon.dev/mcp` from two sandboxed build environments.
- **Expected vs. actual:** expected an MCP handshake; got HTTP 403 from our own network egress proxy (host not on the allowlist). This is a limitation of our environment, not necessarily of the server.
- **Severity:** low
- **Workaround:** read the docs pages directly and the official `AmazonAppDev/ring-api-helloworld` scripts.
- **Suggestion:** publish the same docs as a downloadable bundle (or `llms.txt`) on `developer.amazon.com`, so locked-down CI and agent sandboxes can use them without allowlisting a new host.

### 2. API documentation page is very long, and endpoint examples are hard to find
- **Task:** find the event history response shape and query parameters.
- **Steps:** loaded `developer.amazon.com/docs/ring/api-documentation.html` (about 120,000 characters of text). The endpoint table describes each endpoint in one line; the OAuth sections take most of the page.
- **Expected vs. actual:** expected a per-endpoint reference with an example response, query parameters (time range, pagination) and error codes; found one-line descriptions, with no example JSON for event history, device status, or users/me in the text we could read.
- **Severity:** med
- **Workaround:** wrote a probe that prints and saves real (scrubbed) responses.
- **Suggestion:** split the reference into one page per endpoint with a request example, an example response, query parameters, and pagination rules; or publish an OpenAPI spec.

### 3. Event type names differ between the docs and the official sample
- **Task:** decide which event types count as "activity" (human motion, doorbell press).
- **Steps:** compared the API docs with `scripts/event_history.py` in `ring-api-helloworld`.
- **Expected vs. actual:** expected one naming scheme. The docs describe `motion_detected` (with `attributes.sub_type` such as `human`) and `button_press`; the sample's `--event-types` help text suggests `motion.human,ding`.
- **Severity:** med (a wrong filter silently returns no events, which would look like an inactive person)
- **Workaround:** fetch without a filter and read the real values from the probe output before writing the client.
- **Suggestion:** document the accepted `event_types` filter values next to the `event_type` values that appear in responses, and keep the sample's help text in sync.

### 4. No image snapshot example in the official sample repo
- **Task:** plan the snapshot call (`POST /v1/devices/{id}/media/image/download`).
- **Steps:** searched `ring-api-helloworld/scripts` and its README for "snapshot", "image", "components".
- **Expected vs. actual:** expected a script like the other endpoints have; there is none, and the docs page text we could read does not show the request body.
- **Severity:** low
- **Workaround:** will confirm the body shape with a real token in Phase 1; plan to contribute `scripts/image_snapshot.py` upstream in Phase 8.
- **Suggestion:** add a snapshot example (request body, `components` for multi-camera devices, and the response content type) to the sample repo.

### 5. The official sample says events can't be polled, but the API has an event history endpoint
- **Task:** decide between polling and webhooks for activity (Phase 1).
- **Steps:** read `app/api/ring/events/route.ts` in `ring-api-helloworld`, then the endpoint table in the API docs.
- **Expected vs. actual:** expected the sample and the docs to agree. The sample's comment says "Ring doesn't have a polling API for events - they're delivered via webhooks", while the docs list `GET /v1/history/devices/{device_id}/events`.
- **Severity:** med (a team reading only the sample would think a webhook server with a public URL is required)
- **Workaround:** used the event history endpoint with polling, and kept webhooks out of scope.
- **Suggestion:** update the comment to point to the event history endpoint, and explain when to use history polling versus webhooks.

### 6. No time-range or paging parameters documented for event history
- **Task:** fetch only new events on each poll (Phase 1).
- **Steps:** searched the docs page and the sample for `since`, `until`, `limit`, `cursor` and `page`.
- **Expected vs. actual:** expected a way to ask for events after a timestamp, and a paging rule. Found neither, so every poll may download the whole history.
- **Severity:** med (more data per poll, and a risk of missing events if the history is truncated)
- **Workaround:** the client filters by timestamp after fetching, and follows JSON:API `links.next` for at most 10 pages if present.
- **Suggestion:** document `start`/`end` (or `since`) and paging parameters, the default page size, and the maximum history window.

### 7. SQLModel's newest source rejects naive datetimes
- **Task:** store event timestamps in SQLite (Phase 1).
- **Steps:** ran the poller tests against the latest SQLModel source.
- **Expected vs. actual:** expected naive UTC datetimes to store as before; got `ValueError: Datetime values must have timezone information` from SQLModel's new `UTCDateTime` type.
- **Severity:** low (not a Ring or AWS tool, but it would break a fresh install that picks up the new release)
- **Workaround:** CareLoop declares its own `UTCDateTime` column type, so behaviour is the same on old and new SQLModel releases.
- **Suggestion:** none for the hackathon tools; recorded because it cost time.

### 8. The "simulator" demo requirement doesn't say which simulator to use
- **Task:** plan a demo video that meets the Ring track rule "the demo video must show the project working through a simulator or an actual Ring device".
- **Steps:** read the hackathon Resources page and the Ring docs links on it, looking for a named Ring simulator; then searched the FAQ.
- **Expected vs. actual:** expected the Resources page to name and link the simulator. It names none. Only the FAQ says "a simulator (like the Ring Developer Playground)".
- **Severity:** med (teams without a Ring device can't tell whether their demo will pass the pass/fail review)
- **Workaround:** used the Ring Developer Playground token for live API calls in the demo.
- **Suggestion:** state on the Ring track and Resources pages that the Developer Playground is the simulator, link to it, and say what a Playground token can see (virtual devices, simulated events, snapshots).

### 9. Couldn't get into an AWS account in time to enable Bedrock
- **Task:** sign in to the AWS console to enable Amazon Nova Lite in Bedrock and create an access key (two days before the deadline).
- **Steps:** started AWS account sign-up from India, then tried to sign in to the console over two days.
- **Expected vs. actual:** expected a working account within an hour. Sign-up and then sign-in kept failing, and the hackathon's AWS credit codes had run out on Oct 7, so there was no alternative route.
- **Severity:** high (live Bedrock calls never ran; the demo uses the deterministic fallback)
- **Workaround:** built a deterministic template fallback for every model call, and validated the Bedrock requests with botocore's Stubber.
- **Suggestion:** offer hackathon participants a short-lived sandbox AWS account or Bedrock playground credentials with Nova enabled, so the AWS Builder track doesn't depend on personal card verification.

---

**Still to log by the team (needs real credentials):** the Playground token flow, the first real `make probe` run (device list, event names), Bedrock model access and inference-profile IDs (`scripts/check_bedrock.py`), the snapshot request body, and the Telegram bot setup. Write each one down as it happens, with the exact error text.
