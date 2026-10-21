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
