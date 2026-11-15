"""OPTIONAL: Submit official-format Seller Hub 'Create new drafts' CSV through eBay FX_LISTING.

This is a controlled, production eBay test. It NEVER publishes. Do not use if
the same SKU already has a Seller Hub draft. The eBay API may reject Draft
actions (BAF.Error.5); inspect result report.
"""
import argparse
import json
import re
import sys
from pathlib import Path

from ebay_draft_uploader import upload_drafts
from listing_automation import ROOT


def main():
    parser = argparse.ArgumentParser(description="Explicit opt-in to FX_LISTING draft-only API")
    parser.add_argument("id")
    parser.add_argument("--confirm-no-existing-draft", action="store_true",
                        help="Required: confirm SKU has no existing Seller Hub draft")
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,75}", args.id):
        parser.error("Invalid listing ID")
    if not args.confirm_no_existing_draft:
        parser.error("Refusing: review Seller Hub and pass --confirm-no-existing-draft")
    directory = ROOT / "listing_drafts" / "work" / args.id
    path = directory / "ebay_seller_hub_web_draft.csv"
    if not path.exists():
        parser.error("Generate the official CSV using ebay_web_draft.py first")
    try:
        result = upload_drafts(path, directory)
        print("Task ID:", result["task_id"])
        print("Status:", result["status"])
        print("Summary:", json.dumps(result.get("upload_summary", {}), indent=2))
        success = int((result.get("upload_summary") or {}).get("successCount") or 0)
        fail = int((result.get("upload_summary") or {}).get("failureCount") or 0)
        if result["status"] != "COMPLETED" or success < 1 or fail:
            print("NOT CONFIRMED; download report with: python ebay_feed_report.py " +
                  result["task_id"] + " --id " + args.id, file=sys.stderr)
            return 1
        print("Processed successfully; confirm draft and fields in Seller Hub.")
        return 0
    except (OSError, ValueError, RuntimeError, KeyError) as exc:
        print("ERROR:", exc, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
