"""Read-only diagnostics for an EXISTING eBay FX_LISTING feed task.

Downloads eBay's result file without creating, uploading, or publishing anything.
"""
import argparse
import gzip
import io
import json
import re
import sys
import zipfile
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from ebay_draft_uploader import BASE, seller_token, status
from listing_automation import ROOT


def download_result(task_id, token):
    req = Request(BASE + "/task/" + task_id + "/download_result_file",
                  headers={"Authorization": "Bearer " + token,
                           "X-EBAY-C-MARKETPLACE-ID": "EBAY_US",
                           "Accept": "application/octet-stream"})
    try:
        with urlopen(req, timeout=90) as response:
            return response.read()
    except HTTPError as exc:
        message = exc.read().decode("utf-8", errors="replace")[:800]
        raise RuntimeError("eBay result download HTTP " + str(exc.code) + ": " + message) from exc


def decode_report(payload):
    if payload.startswith(b"\x1f\x8b"):
        return gzip.decompress(payload)
    if zipfile.is_zipfile(io.BytesIO(payload)):
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            files = [x for x in archive.infolist() if not x.is_dir()]
            if not files:
                return b"(empty archive)"
            return b"\n\n".join(
                ("--- " + entry.filename + " ---\n").encode("utf-8") + archive.read(entry)
                for entry in files[:10] if entry.file_size <= 5_000_000
            )
    return payload


def main():
    parser = argparse.ArgumentParser(description="Download report for an existing eBay Feed task")
    parser.add_argument("task_id")
    parser.add_argument("--id", default="batch001_1", help="Local listing ID, for report storage")
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", args.task_id):
        parser.error("Invalid task ID")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,75}", args.id):
        parser.error("Invalid listing ID")
    directory = ROOT / "listing_drafts" / "work" / args.id
    directory.mkdir(parents=True, exist_ok=True)
    token = seller_token()
    info = status(args.task_id, token)
    print("eBay task:", args.task_id)
    print("Task status:", info.get("status"))
    print("Upload summary:", json.dumps(info.get("uploadSummary", {}), indent=2))
    (directory / "ebay_feed_task_status.json").write_text(
        json.dumps(info, indent=2) + "\n", encoding="utf-8")
    payload = download_result(args.task_id, token)
    raw = directory / "ebay_feed_result.bin"
    raw.write_bytes(payload)
    decoded = decode_report(payload)
    readable = directory / "ebay_feed_result.txt"
    readable.write_text(decoded.decode("utf-8-sig", errors="replace"), encoding="utf-8")
    print("Downloaded report:", readable)
    print("--- eBay result preview ---")
    print(readable.read_text(encoding="utf-8")[:12000])
    print("--- end report ---")
    print("READ-ONLY: No new draft was submitted.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, RuntimeError, ValueError, zipfile.BadZipFile) as exc:
        print("ERROR:", exc, file=sys.stderr)
        sys.exit(1)
