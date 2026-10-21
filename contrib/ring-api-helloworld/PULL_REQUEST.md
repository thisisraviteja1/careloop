# Upstream contribution: image snapshot script for `AmazonAppDev/ring-api-helloworld`

**Status: prepared, not opened.** The request body for the snapshot endpoint is not shown in the docs we could read, so this must be tested with a real Playground token and a real camera before the PR is opened. If no device is available, don't open it.

## Steps
1. Fork `AmazonAppDev/ring-api-helloworld` and copy `scripts/image_snapshot.py` from this folder into the fork's `scripts/`.
2. Test: `python image_snapshot.py --token "$TOKEN"` and check that a real image is saved. If the API needs a different body, fix the script and note it in the PR.
3. Add this row to the scripts table in the fork's README:

   | `image_snapshot.py` | `POST /v1/devices/{id}/media/image/download` | Save a JPEG/PNG snapshot (optional `--components` for multi-camera devices) |

4. Optionally add option 9 "Image Snapshot" to `explore_apis.py`.
5. Open the PR with the description below and record its URL for Devpost.

## PR description

> **Add an image snapshot script**
>
> The scripts cover every read endpoint except image snapshots. This adds `scripts/image_snapshot.py` in the same style as the others (argparse, `--token`, device auto-discovery, a printed curl equivalent). It calls `POST /v1/devices/{id}/media/image/download`, supports `--components` for multi-camera devices, checks the response is an image before saving, and prints the body otherwise. Tested against a real device with a Playground token.
