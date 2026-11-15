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
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from pathlib import Path

from ebay_media import cached_image_available
from listing_automation import ROOT
from work_pipeline import package_data
from ebay_category_audit import audit_listing

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
        if not cached_image_available(url):
            return []
        urls.append(url)
    return urls


def photo_url_diagnostics(urls):
    """Check whether an eBay-importer-accessible HTTPS image appears available."""
    for n, url in enumerate(urls, 1):
        try:
            request = Request(url, headers={"User-Agent": "Mozilla/5.0",
                                             "Range": "bytes=0-0"})
            with urlopen(request, timeout=15) as response:
                status = response.status
                mime = response.headers.get("Content-Type", "unknown")
                print("Image", n, "HTTP", status, "content-type:", mime)
                if not mime.lower().startswith("image/"):
                    print("WARNING: image URL did not return an image content type.")
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            print("WARNING: image", n, "URL cannot be fetched:", type(exc).__name__,
                  getattr(exc, "code", ""))
    print("Note: local reachability does not prove that Seller Hub imports the photo.")


def export_one(item_id, check_images=False, include_specifics=True,
               official_aspects=False, upload_images_now=False):
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
    cache_path = output / "ebay_media_cache.json"
    if upload_images_now:
        from ebay_draft_uploader import seller_token
        from ebay_media import upload_images
        print("Uploading/caching", len(photos), "local photos to eBay Media API...")
        urls = upload_images(photos, cache_path, seller_token())
        print("Photos uploaded/cached:", len(urls))
    else:
        urls = cached_photo_urls(photos, cache_path)
    if not urls:
        print("WARNING: no complete matching uploaded photo URL cache. Image column left blank.")
        print("Run this exporter with --upload-images for a NEW listing before API submission.")
    condition = str(facts.get("condition") or "").strip().casefold()
    condition_value = {"used": "USED", "new": "NEW"}.get(condition, "")
    if not condition_value:
        print("WARNING: only NEW/USED supported by official draft template; condition blank.")
    row = {
        ACTION_HEADER: "Draft",
        "Custom label (SKU)": item_id,
        "Category ID": category,
        "Title": title,
        "UPC": "",
        "Price": "",  # Seller fills price when completing the draft.
        "Quantity": str(facts.get("quantity") or "1"),
        "Item photo URL": "|".join(urls),
        "Condition ID": condition_value,  # Official Draft importer accepts NEW / USED.
        "Description": str(listing.get("description") or ""),
        "Format": "FixedPrice",
    }
    validated = None
    if official_aspects:
        validated = audit_listing(item_id)
        print("Live category specifics:", len(validated["fields"]),
              "| missing required:", len(validated["missing_required"]),
              "| invalid:", len(validated["invalid"]))
    fields = list(HEADERS)
    specifics_source = validated["accepted_item_specifics"] if validated else listing.get("item_specifics", {})
    if include_specifics:
        unknown = {"", "n/a", "not specified", "unknown", "not applicable", "none", "null"}
        for name, value in specifics_source.items():
            if not isinstance(name, str) or not name.strip():
                continue
            if not isinstance(value, (str, int, float)):
                continue
            value = str(value).strip()
            if not value or value.casefold() in unknown or "\\n" in name:
                continue
            col = "C:" + name.strip()
            if col not in row:
                row[col] = value
                fields.append(col)
    if include_specifics:
        print("Experimental C: item specifics columns:", len(fields) - len(HEADERS),
              "(eBay does not guarantee extra fields in Create Drafts)")
    if check_images and urls:
        photo_url_diagnostics(urls)
    dest = output / "ebay_seller_hub_web_draft.csv"
    with dest.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream)
        for info in INFO:
            writer.writerow(info + [""] * (len(fields) - len(info)))
        writer.writerow(fields)
        writer.writerow([row.get(key, "") for key in fields])
    print("Seller Hub website draft CSV:", dest)
    print("Photo URLs included:", len(urls))
    print("Condition field:", repr(condition_value),
          "(blank unless seller confirmed NEW or USED)")
    if not condition_value:
        print("ACTION NEEDED: seller must confirm item condition.")
    if include_specifics:
        print("Note: Seller Hub may ignore C: columns despite successful task processing.")
    if official_aspects:
        from ebay_transfer_report import generate
        generate(item_id)
    print("Condition description is not a standard field in the 11-column Drafts template.")
    print("Draft not uploaded; use Seller Hub Reports > Uploads.")
    print("Confirm price, condition, item specifics and photo transfer in Seller Hub.")
    return dest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Export exact official Seller Hub website CSV")
    parser.add_argument("id", help="Researched listing ID, e.g. batch001_1")
    parser.add_argument("--upload-images", action="store_true",
                        help="Upload original folder images to eBay Media API; "
                             "cache URLs and insert them into generated CSV")
    parser.add_argument("--check-images", action="store_true",
                        help="Check if cached image URLs return accessible image data")
    parser.add_argument("--official-aspects", action="store_true",
                        help="Fetch all live eBay Taxonomy specifics, validate values, and save report")
    parser.add_argument("--basic", action="store_true",
                        help="Exact 11-column template, without experimental C: fields")
    args = parser.parse_args()
    try:
        export_one(args.id, check_images=args.check_images,
                   include_specifics=not args.basic,
                   official_aspects=args.official_aspects,
                   upload_images_now=args.upload_images)
    except (OSError, ValueError, RuntimeError, KeyError) as exc:
        print("ERROR:", exc, file=sys.stderr)
        sys.exit(1)
