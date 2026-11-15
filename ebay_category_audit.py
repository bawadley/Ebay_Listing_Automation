"""Fetch all official eBay category item specifics and validate listing data.

Read-only: authenticates to Taxonomy API, never creates an eBay listing.
"""
import argparse
import json
import re
import sys

from ebay_aspects import get_category_aspects
from listing_automation import ROOT
from work_pipeline import package_data

UNKNOWN = {"", "n/a", "not specified", "unknown", "not applicable", "none", "null"}
COMPATIBILITY = {"compatible model", "compatible brand", "compatible printer",
                 "compatible product", "compatible equipment"}


def audit_listing(item_id, write=True):
    package = package_data(ROOT / "researched_listings" / (item_id + ".json"),
                           ROOT / "product_photos")
    _, facts, listing, _, category, _, _ = package
    meta = get_category_aspects({**facts, "ebay_category_id": category})
    if not meta.get("aspects"):
        raise RuntimeError(meta.get("status") or "No eBay category metadata returned")
    known = {k.casefold(): (k, v) for k, v in listing["item_specifics"].items()}
    # Match only seller-confirmed facts, not guessed cross-model compatibility.
    confirmed = {k.casefold(): v for k, v in facts.items() if isinstance(k, str)}
    rows = []
    accepted = {}
    for aspect in meta["aspects"]:
        name = aspect["name"]
        key = name.casefold()
        raw = known.get(key, ("", ""))[1]
        if key in COMPATIBILITY:
            raw = confirmed.get(key) or confirmed.get("confirmed_compatibility") or ""
        value = str(raw).strip()
        if value.casefold() in UNKNOWN:
            value = ""
        choices = aspect.get("values", [])
        mode = str(aspect.get("mode") or "")
        valid = True
        reason = ""
        if value and mode == "SELECTION_ONLY" and choices:
            match = next((choice for choice in choices if choice.casefold() == value.casefold()), None)
            if match:
                value = match
            else:
                valid = False
                reason = "value not one of eBay's selection-only choices"
        max_len = aspect.get("max_length")
        if value and max_len and len(value) > int(max_len):
            valid = False
            reason = "value exceeds eBay's maximum length"
        if value and valid:
            accepted[name] = value
        rows.append({"name": name, "usage": aspect.get("usage"),
                     "required": aspect.get("required"), "mode": mode,
                     "cardinality": aspect.get("cardinality"),
                     "max_length": max_len,
                     "allowed_values": choices,
                     "value": value if valid else "",
                     "suggested_value": value if not valid else "",
                     "status": "VALID" if value and valid else "INVALID" if value else "MISSING",
                     "reason": reason})
    report = {"listing_id": item_id, "category_id": category,
              "metadata_status": meta["status"], "fields": rows,
              "accepted_item_specifics": accepted,
              "missing_required": [r["name"] for r in rows if r["required"] and r["status"] != "VALID"],
              "missing_recommended": [r["name"] for r in rows if r["usage"] == "RECOMMENDED" and r["status"] == "MISSING"],
              "invalid": [r["name"] for r in rows if r["status"] == "INVALID"],
              "unmatched_research_fields": [name for name in listing["item_specifics"]
                  if name.casefold() not in {r["name"].casefold() for r in rows}]}
    if write:
        folder = ROOT / "listing_drafts" / "work" / item_id
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "ebay_category_aspects.json").write_text(
            json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser(description="Read-only live eBay category specifics audit")
    parser.add_argument("id")
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,75}", args.id):
        parser.error("Invalid listing ID")
    try:
        report = audit_listing(args.id)
        print(report["metadata_status"])
        print("Valid populated:", len(report["accepted_item_specifics"]))
        print("Missing required:", ", ".join(report["missing_required"]) or "none")
        print("Missing recommended:", ", ".join(report["missing_recommended"]) or "none")
        print("Invalid choices:", ", ".join(report["invalid"]) or "none")
        print("All exact fields and eBay dropdown options saved in:")
        print(ROOT / "listing_drafts" / "work" / args.id / "ebay_category_aspects.json")
        return 0
    except (OSError, ValueError, KeyError, RuntimeError) as exc:
        print("ERROR:", exc, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
