# Upstream contribution: image snapshot script for `AmazonAppDev/ring-api-helloworld`

**Status: request format verified against the Ring Developer Playground (Oct 23, 2026).** `{"type": "at_timestamp", "timestamp": <epoch ms>}` is accepted with HTTP 303 and a media-host location. The Playground doorbell had no recorded media, so the media host answered 416 MEDIA_NOT_FOUND; the script reports that case clearly. Open the PR saying exactly this.

## Steps
1. Fork `AmazonAppDev/ring-api-helloworld` and copy `scripts/image_snapshot.py` from this folder into the fork's `scripts/`.
2. Test: `python image_snapshot.py --token "$TOKEN"` and check that a real image is saved. If the API needs a different body, fix the script and note it in the PR.
3. Add this row to the scripts table in the fork's README:

   | `image_snapshot.py` | `POST /v1/devices/{id}/media/image/download` | Save the snapshot at a moment (`--timestamp-ms`, default 5 s ago); follows the 303 to the media host |

4. Optionally add option 9 "Image Snapshot" to `explore_apis.py`.
5. Open the PR with the description below and record its URL for Devpost.

## PR description

> **Add an image snapshot script**
>
> The scripts cover every read endpoint except image snapshots, and the request body isn't in the API reference. This adds `scripts/image_snapshot.py` in the same style as the others (argparse, `--token`, device auto-discovery, printed curl). It sends `{"type": "at_timestamp", "timestamp": <epoch ms>}` (the other accepted type is `latest_in_range` with `start_timestamp`/`end_timestamp`), follows the 303 to the media host without forwarding the token, and explains `416 MEDIA_NOT_FOUND`. Verified against the Ring Developer Playground: request accepted (303); the Playground doorbell had no recorded media at the tested times.
