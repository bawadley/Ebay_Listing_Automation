# eBay Listing Automation

Prepare product photos and human-reviewed eBay drafts from seller facts and ChatGPT research packages. No entry point publishes live listings. Draft submission and image uploads contact production eBay only when explicitly requested.

## Setup

Use Python 3.11 or newer and a virtual environment (the current NumPy dependency requires 3.11+):

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
# Optional local foreground detection:
python -m pip install -r requirements-local.txt
```

On Windows, activate with `.venv\Scripts\Activate.ps1`.

## Main workflow

Create `researched_listings/<ID>.json` using `researched_listings/example.json` as the schema. Put original product photos in `product_photos/<ID>/`, or set `photo_folder` in the package to another relative folder. IDs allow letters, numbers, underscores and hyphens. Each listing supports up to 12 photos.

```bash
python work_pipeline.py <ID>
```

Open `listing_drafts/work/<ID>/review.html`. Correct the source research package before the first preview, or edit the generated `<ID>.json` afterward. Saved preview JSON corrections are preserved on subsequent runs and submission. The CSV and HTML are regenerated from that JSON; edit the JSON, rather than the generated CSV, for persistent changes.

After changing the source research package or photo selection, explicitly rebuild and review:

```bash
python work_pipeline.py <ID> --refresh-preview
```

This replaces local preview corrections. To validate category specifics while building a new preview, add `--check-category`. Compatibility brands and models must have separate seller-confirmed values; general compatibility notes only supply Compatible Model.

After review, choose one submission route for a new SKU:

- `python work_pipeline.py <ID> --submit` uploads photos and a draft-only FX_LISTING feed using the saved preview. This feed may be rejected by eBay; inspect its report.
- `python ebay_web_draft.py <ID> --official-aspects --upload-images --check-images` builds the website template directly from the **source research package**, independently of saved preview corrections. Upload its CSV through Seller Hub Reports > Uploads.

Seller OAuth requires `EBAY_USER_ACCESS_TOKEN`, or `EBAY_CLIENT_ID` and `EBAY_CLIENT_SECRET` with a refresh token from `ebay_oauth_setup.py`. Taxonomy lookup uses `EBAY_ACCESS_TOKEN` or the client credentials. Keep credentials out of Git.

A successful feed task does not guarantee every photo or C: item-specific column transferred. Verify the actual draft, condition, price, photos and specifics in Seller Hub before publishing. Do not submit an existing SKU through a second route. Duplicate protection is local to the upload state directory and cannot detect manual website imports or attempts on another computer.

## Listener and recovery

```bash
python local_listener.py --once
python local_listener.py
```

The listener pulls `main` and prepares previews; it preserves existing preview corrections. `--auto-submit` explicitly enables production draft uploads. After fixing a missing folder, network issue or credentials, retry failed packages once with:

```bash
python local_listener.py --once --retry-errors
```

Retry does not erase upload checkpoints or create another task for an already-attempted SKU. An uncertain or rejected feed may need manual reconciliation. Retrieve its report using `python ebay_feed_report.py <TASK_ID> --id <ID>`. Never delete upload state to bypass duplicate protection. Run only one listener/uploader for a given output directory at a time.

Photo URLs are checked before cache reuse. Unavailable images are reuploaded during explicit upload operations; temporary network failures stop the operation so they do not cause unnecessary uploads. The website exporter leaves photos blank when its cache is missing or stale unless `--upload-images` is supplied.

## Photo processing and other tools

`python photo_processor.py` reads `input/` and writes edited copies and a report to `output/`, using `config.json`. Originals are preserved. Local AI crop candidates require filename approval in `approved_local_crops`; inspect overlays for missed accessories. Review image edits before use.

`listing_automation.py` is the older model/API generation workflow. `ebay_category_audit.py`, `ebay_transfer_report.py` and `ebay_feed_report.py` provide diagnostics. `ebay_api_draft.py` is an explicit production experiment; its FX_DRAFT option remains undocumented and is never selected automatically.

## Verification

```bash
python -m unittest discover -s tests -v
```

Tests use temporary files and mocked network calls; they do not contact eBay. Earlier experiments and detailed photo configuration notes are preserved in [the development history](docs/workflow-history.md); commands there may be superseded.
