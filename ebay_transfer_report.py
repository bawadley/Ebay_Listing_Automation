"""Compare exact eBay Taxonomy fields, generated draft CSV, and manually observed Seller Hub fields.

This report never contacts eBay's seller account and never submits listings.
The API feed's COMPLETED status does not indicate which C: fields imported.
"""
import argparse
import csv
import json
import re
import sys

from listing_automation import ROOT
from ebay_draft_uploader import read_draft_csv


def generate(item_id, imported=None):
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,75}", item_id):
        raise ValueError("Invalid listing ID")
    directory = ROOT / "listing_drafts" / "work" / item_id
    csv_path = directory / "ebay_seller_hub_web_draft.csv"
    aspect_path = directory / "ebay_category_aspects.json"
    if not csv_path.is_file() or not aspect_path.is_file():
        raise ValueError("Generate the CSV with --official-aspects before auditing transfers.")
    rows, _ = read_draft_csv(csv_path)
    if len(rows) != 1:
        raise ValueError("Expected exactly one draft row")
    row = rows[0]
    metadata = json.loads(aspect_path.read_text(encoding="utf-8"))
    if str(metadata.get("listing_id")) != item_id:
        raise ValueError("Aspect report belongs to another listing")
    imported_names = {name.strip().casefold() for name in imported} if imported is not None else None
    details = []
    for aspect in metadata["fields"]:
        name = aspect["name"]
        key = "C:" + name
        value = str(row.get(key) or "").strip()
        if not value:
            label = "NOT_SENT"
            reason = aspect.get("reason") or "No verified value, invalid choice, or exporter omitted this field"
        elif imported_names is None:
            label = "SENT_NOT_VERIFIED"
            reason = "Value exists in CSV; Feed API success does not confirm that Seller Hub imported this field"
        elif name.casefold() in imported_names:
            label = "OBSERVED_IMPORTED"
            reason = "Seller reported this field populated in Seller Hub"
        else:
            label = "NOT_OBSERVED_IMPORTED"
            reason = "Seller did not report this field populated; inspect draft/possible import restrictions"
        details.append({"name": name, "usage": aspect.get("usage"),
                        "required": bool(aspect.get("required")),
                        "taxonomy_mode": aspect.get("mode"),
                        "status": label,
                        "csv_value": value,
                        "reason": reason,
                        "allowed_values": aspect.get("allowed_values", [])})
    sent = [a["name"] for a in details if a["status"] != "NOT_SENT"]
    missing = [a["name"] for a in details if a["status"] == "NOT_SENT"]
    failed = [a["name"] for a in details if a["status"] == "NOT_OBSERVED_IMPORTED"]
    summary = {
        "listing_id": item_id, "category_id": metadata["category_id"],
        "total_official_aspects": len(details),
        "csv_specifics_sent": len(sent),
        "csv_specifics_omitted": len(missing),
        "not_observed_imported": failed,
        "seller_hub_observations_provided": imported_names is not None,
        "disclaimer": "Not sent does not mean unavailable on eBay. "
                      "Not observed imported is a user report, not verified by eBay's API."
    }
    report = {"summary": summary, "details": details,
              "csv_base_fields": {
                  "Title": row.get("Title", ""),
                  "Category ID": row.get("Category ID", ""),
                  "Condition ID": row.get("Condition ID", ""),
                  "Photo URL count": len([u for u in (row.get("Item photo URL") or "").split("|") if u]),
                  "Description present": bool(row.get("Description"))
              }}
    out = directory / "ebay_transfer_report.json"
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print("Official category item specifics:", len(details))
    print("Sent in CSV:", len(sent), ", ".join(sent) if sent else "(none)")
    print("Not sent:", len(missing), ", ".join(missing) if missing else "(none)")
    if imported_names is not None:
        print("Seller Hub fields not observed:", ", ".join(failed) if failed else "(none)")
    print("Report:", out)
    return report


def main():
    parser = argparse.ArgumentParser(description="Check Taxonomy-to-CSV-to-Seller Hub item specifics")
    parser.add_argument("id")
    parser.add_argument("--imported", metavar="FIELDS",
                        help='Comma-separated names you saw populated in Seller Hub, e.g. "Brand,Type,Model"')
    args = parser.parse_args()
    try:
        generate(args.id, None if args.imported is None else args.imported.split(","))
        return 0
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print("ERROR:", exc, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
