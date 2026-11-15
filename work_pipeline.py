"""Mac-first ChatGPT Work -> local images -> eBay editable Drafts workflow.

Work creates researched_listings/<id>.json. Run preview first; --submit uploads
pictures to eBay EPS then a Draft-only FX_LISTING feed. Never publishes listings.
No OpenAI API or Ollama call is made by this entry point.
"""
import argparse
import csv
import json
import re
import sys
from pathlib import Path

from listing_automation import ROOT, clean, review_page, export_ebay_seller_hub_drafts
from ebay_aspects import get_category_aspects, complete_aspects

SUPPORTED = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".tif", ".tiff", ".bmp", ".heic", ".avif"}


def safe_id(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,75}", value):
        raise ValueError("Listing ID must use only letters, numbers, underscores or hyphens")
    return value


def package_data(path, photos_root):
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("Research package must be a JSON object")
    item_id = safe_id(raw.get("id"))
    if path.stem != item_id:
        raise ValueError("Research filename must match the listing ID: " + item_id)
    facts = raw.get("seller_details")
    if not isinstance(facts, dict) or not (facts.get("product") or facts.get("product_name")):
        raise ValueError("seller_details.product is required")
    listing = raw.get("listing")
    if not isinstance(listing, dict) or not isinstance(listing.get("item_specifics"), dict):
        raise ValueError("listing.item_specifics must be an object")
    category_id = str(raw.get("ebay_category_id") or facts.get("ebay_category_id") or "")
    if not category_id.isdigit():
        raise ValueError("A numeric ebay_category_id is required for draft submission; "
                         "have Work verify the category and add its ID")
    folder_value = raw.get("photo_folder") or item_id
    if not isinstance(folder_value, str) or Path(folder_value).is_absolute():
        raise ValueError("photo_folder must be a relative directory inside product_photos")
    folder = (photos_root / folder_value).resolve()
    if not folder.is_relative_to(photos_root.resolve()) or not folder.is_dir():
        raise ValueError("Product photo folder missing or outside allowed root: " + str(folder))
    names = raw.get("images")
    if names is None:
        images = sorted(p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in SUPPORTED)
    else:
        if not isinstance(names, list) or not names:
            raise ValueError("images must be a non-empty list when specified")
        images = []
        for name in names:
            if not isinstance(name, str) or Path(name).name != name:
                raise ValueError("Image names must not contain folder paths")
            p = (folder / name).resolve()
            if not p.is_relative_to(folder) or not p.is_file() or p.suffix.lower() not in SUPPORTED:
                raise ValueError("Missing or invalid image: " + str(name))
            images.append(p)
    if not images:
        raise ValueError("No photos found in " + str(folder))
    if len(images) > 12:
        raise ValueError("At most 12 images per listing are supported by this draft feed")
    references = raw.get("research_sources", [])
    if not isinstance(references, list):
        raise ValueError("research_sources must be an array")
    references = [x for x in references if isinstance(x, dict) and
                  str(x.get("url", "")).startswith(("https://", "http://"))]
    return item_id, facts, listing, images, category_id, references, raw


def build_record(pack, fetch_category=False):
    item_id, facts, listing, photos, category_id, refs, package = pack
    record = clean(listing, item_id, photos)
    record["seller_details"] = facts
    record["ebay_category_id"] = category_id
    record["research_sources"] = refs
    record["research_status"] = str(package.get("research_status") or
                                    "Researched in ChatGPT Work; verify sources and fitment")
    record["category_lookup_status"] = "Work selected category; seller review required"
    record["category_selection"] = "WORK_RESEARCHED_REVIEW"
    record["category_aspect_count"] = 0
    # Optional live Taxonomy validation, using existing eBay app token if configured.
    if fetch_category:
        meta = get_category_aspects({**facts, "ebay_category_id": category_id})
        record["category_lookup_status"] = meta["status"]
        if meta.get("aspects"):
            record = complete_aspects(record, facts, meta)
        else:
            record["missing_information"].append(
                "Official category item specifics not retrieved; verify in Seller Hub")
    else:
        record["missing_information"].append(
            "Full eBay category aspect coverage not validated against live Taxonomy")
    return record


def export_one(record, directory, photo_urls=None):
    """Create a Draft-only Seller Hub CSV with supported specifics and EPS URLs."""
    exported = export_ebay_seller_hub_drafts([record], directory)
    if exported["exported"] != 1:
        raise ValueError("No Seller Hub draft row exported: " + str(exported["skipped"]))
    path = directory / "ebay_seller_hub_drafts.csv"
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
        fields = list(rows[0])
    if photo_urls:
        rows[0]["Item photo URL"] = "|".join(photo_urls)
    # Seller Hub category templates use C: prefixes for item specifics.
    # Never submit review placeholders as actual product attributes.
    unknown = {"", "n/a", "not specified", "unknown", "not applicable", "none", "null"}
    for name, value in record.get("item_specifics", {}).items():
        if not isinstance(name, str) or not name.strip():
            continue
        value = str(value).strip()
        if value.casefold() in unknown:
            continue
        status = record.get("item_specifics_status", {}).get(name, {})
        if status.get("status") in ("MISSING", "INVALID_CHOICE"):
            continue
        column = "C:" + name.strip()
        if column in fields:
            continue
        fields.append(column)
        rows[0][column] = value
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    return path

def main():
    parser = argparse.ArgumentParser(description="ChatGPT Work research -> Mac photos -> eBay draft (never publish)")
    parser.add_argument("id", help="Listing ID matching researched_listings/ID.json")
    parser.add_argument("--submit", action="store_true",
                        help="Upload photos and create an UNPUBLISHED draft on your production eBay account")
    parser.add_argument("--research-dir", type=Path, default=ROOT / "researched_listings")
    parser.add_argument("--photos-dir", type=Path, default=ROOT / "product_photos")
    parser.add_argument("--check-category", action="store_true",
                        help="Check exact official category aspects using EBAY_ACCESS_TOKEN")
    args = parser.parse_args()
    item_id = safe_id(args.id)
    try:
        package = package_data((args.research_dir / (item_id + ".json")).resolve(),
                               args.photos_dir.resolve())
        output = ROOT / "listing_drafts" / "work" / item_id
        output.mkdir(parents=True, exist_ok=True)
        record = build_record(package, fetch_category=args.check_category)
        json_path = output / (item_id + ".json")
        json_path.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n",
                             encoding="utf-8")
        review_page([record], output)
        export_one(record, output)
        print("Prepared local preview:", output / "review.html", flush=True)
        print("Photos:", len(package[3]), "| eBay category:", record["ebay_category_id"])
        if not args.submit:
            print("PREVIEW ONLY: no pictures uploaded and no eBay draft created.")
            print("After review, run: python work_pipeline.py " + item_id + " --submit")
            return 0

        # Submission is explicit; seller OAuth is necessary. Never use OpenAI API.
        from ebay_draft_uploader import seller_token, upload_drafts
        from ebay_media import upload_images
        token = seller_token()
        urls = upload_images(package[3], output / "ebay_media_cache.json", token)
        print("eBay EPS photos uploaded:", len(urls), flush=True)
        csv_path = export_one(record, output, urls)
        result = upload_drafts(csv_path, output)
        (output / "ebay_submission_result.json").write_text(
            json.dumps(result, indent=2) + "\n", encoding="utf-8")
        print("Draft-only eBay Feed task:", result["task_id"],
              "status:", result["status"], flush=True)
        summary = result.get("upload_summary") or {}
        failed = int(summary.get("failureCount") or 0)
        succeeded = int(summary.get("successCount") or 0)
        if result["status"] != "COMPLETED" or failed or succeeded < 1:
            print("EBAY DRAFT NOT CONFIRMED: processing status/row counts indicate failure or uncertainty.",
                  file=sys.stderr)
            print("Run: python ebay_feed_report.py " + result["task_id"] +
                  " --id " + item_id, file=sys.stderr)
            print("Do not retry this task blindly or assume a Seller Hub draft exists.",
                  file=sys.stderr)
            print("Fallback: Seller Hub > Reports > Uploads. Use its official Create new drafts template.",
                  file=sys.stderr)
            return 1
        print("eBay reports processing success; verify actual draft in Seller Hub:")
        print("https://www.ebay.com/sh/lst/drafts")
        print("Verify image display and full item specifics before publishing.")
        return 0
    except (OSError, ValueError, RuntimeError, KeyError) as exc:
        print("ERROR:", exc, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
