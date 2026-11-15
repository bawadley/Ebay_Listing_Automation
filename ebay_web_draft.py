"""Export an official-format eBay Seller Hub Reports Create Drafts CSV.

Based on the US template eBay-draft-listings-template_US version 0.0.2,
downloaded 2026-11-14. This NEVER submits, creates or publishes anything.
"""
import argparse
import csv
import hashlib
import json
import re
import sys
from pathlib import Path

from listing_automation import ROOT
from work_pipeline import package_data

ACTION_HEADER = "Action(SiteID=US|Country=US|Currency=USD|Version=1193|CC=UTF-8)"
HEADERS = [ACTION_HEADER, "Custom label (SKU)", "Category ID", "Title", "UPC",
           "Price", "Quantity", "Item photo URL", "Condition ID",
           "Description", "Format"]
INFO = [
    ["#INFO", "Version=0.0.2", "Template= eBay-draft-listings-template_US"],
    ["#INFO Action and Category ID are required fields. 1) Set Action to Draft 2) Please find the category ID for your listings here: https://pages.ebay.com/sellerinformation/news/categorychanges.html"],
    ["#INFO After you've successfully uploaded your draft from the Seller Hub Reports tab, complete your drafts to active listings here: https://www.ebay.com/sh/lst/drafts"],
    ["#INFO"],
]


def cached_photo_urls(photos, cache_path):
    if not cache_path.exists():
        return []
    cache = json.loads(cache_path.read_text(encoding="utf-8"))
    urls = []
    for image in photos:
        digest = hashlib.sha256(image.read_bytes()).hexdigest()
        entry = cache.get(digest) or {}
        url = entry.get("url")
        if not isinstance(url, str) or not url.startswith("https://"):
            return []
        urls.append(url)
    return urls


def export_one(item_id):
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,75}", item_id):
        raise ValueError("Invalid listing ID")
    source = ROOT / "researched_listings" / (item_id + ".json")
    pack = package_data(source, ROOT / "product_photos")
    _, facts, listing, photos, category, _, _ = pack
    output = ROOT / "listing_drafts" / "work" / item_id
    output.mkdir(parents=True, exist_ok=True)
    title = str(listing.get("title") or "")
    if not title or len(title) > 80:
        raise ValueError("Listing title missing or over 80 characters")
    urls = cached_photo_urls(photos, output / "ebay_media_cache.json")
    if not urls:
        print("WARNING: no complete matching uploaded photo URL cache. Image column left blank.")
    row = {
        ACTION_HEADER: "Draft",
        "Custom label (SKU)": item_id,
        "Category ID": category,
        "Title": title,
        "UPC": "",
        "Price": "",  # Seller fills price when completing the draft.
        "Quantity": str(facts.get("quantity") or "1"),
        "Item photo URL": "|".join(urls),
        "Condition ID": "",  # Varies by category; complete in Seller Hub.
        "Description": str(listing.get("description") or ""),
        "Format": "FixedPrice",
    }
    dest = output / "ebay_seller_hub_web_draft.csv"
    with dest.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream)
        for info in INFO:
            writer.writerow(info + [""] * (len(HEADERS) - len(info)))
        writer.writerow(HEADERS)
        writer.writerow([row[key] for key in HEADERS])
    print("Seller Hub website draft CSV:", dest)
    print("Photo URLs included:", len(urls))
    print("Draft not uploaded; use Seller Hub Reports > Uploads.")
    print("Confirm price, condition, item specifics and photo transfer in Seller Hub.")
    return dest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Export exact official Seller Hub website CSV")
    parser.add_argument("id", help="Researched listing ID, e.g. batch001_1")
    args = parser.parse_args()
    try:
        export_one(args.id)
    except (OSError, ValueError, RuntimeError, KeyError) as exc:
        print("ERROR:", exc, file=sys.stderr)
        sys.exit(1)
