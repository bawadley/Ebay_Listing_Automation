"""Official eBay Taxonomy API category-specific item specifics. No eBay publishing."""
import json
import os
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

def _get(path, token, params):
    url = "https://api.ebay.com/commerce/taxonomy/v1/" + path + "?" + urlencode(params)
    req = Request(url, headers={"Authorization": "Bearer " + token,
                               "X-EBAY-C-MARKETPLACE-ID": "EBAY_US"})
    with urlopen(req, timeout=35) as response:
        return json.load(response)

def get_category_aspects(details):
    """Return all actual eBay category aspects, or a clear, non-fatal error."""
    info = {"category_id": str(details.get("ebay_category_id") or "").strip(),
            "category_name": None, "aspects": [], "status": ""}
    token = os.environ.get("EBAY_ACCESS_TOKEN", "").strip()
    if not token:
        info["status"] = "EBAY_ACCESS_TOKEN not set; cannot retrieve official category aspects"
        return info
    try:
        tree_id = str(_get("get_default_category_tree_id", token,
                           {"marketplace_id": "EBAY_US"})["categoryTreeId"])
        if not info["category_id"]:
            query = " ".join(str(details.get(k, "")) for k in ("brand", "product", "model")).strip()
            suggestions = _get("category_tree/" + tree_id + "/get_category_suggestions",
                               token, {"q": query[:100]}).get("categorySuggestions", [])
            if not suggestions:
                info["status"] = "No eBay category suggestions; provide details.ebay_category_id"
                return info
            cat = suggestions[0].get("category", {})
            info["category_id"] = str(cat.get("categoryId") or "")
            info["category_name"] = cat.get("categoryName")
            info["category_selection"] = "AUTO_SUGGESTED_REVIEW"
        else:
            info["category_selection"] = "SELLER_PROVIDED"
        if not info["category_id"].isdigit():
            raise ValueError("Expected numeric eBay leaf category ID")
        response = _get("category_tree/" + tree_id + "/get_item_aspects_for_category",
                        token, {"category_id": info["category_id"]})
        for a in response.get("aspects", []):
            name = str(a.get("localizedAspectName") or "").strip()
            if not name:
                continue
            c = a.get("aspectConstraint") or {}
            info["aspects"].append({
                "name": name,
                "required": bool(c.get("aspectRequired")),
                "usage": "REQUIRED" if c.get("aspectRequired") else c.get("aspectUsage", "OPTIONAL"),
                "mode": c.get("aspectMode", "FREE_TEXT"),
                "cardinality": c.get("itemToAspectCardinality", "SINGLE"),
                "values": [str(v.get("localizedValue")) for v in a.get("aspectValues", [])
                           if v.get("localizedValue")][:100]
            })
        info["status"] = "Loaded " + str(len(info["aspects"])) + " official eBay category fields"
    except (HTTPError, URLError, ValueError, KeyError, TimeoutError) as exc:
        info["status"] = "eBay category lookup failed: " + str(exc)[:250]
    return info

def complete_aspects(record, details, metadata):
    record["ebay_category_id"] = metadata.get("category_id") or None
    record["category_lookup_status"] = metadata.get("status")
    record["category_selection"] = metadata.get("category_selection", "UNKNOWN")
    aspects = metadata.get("aspects", [])
    record["category_aspect_count"] = len(aspects)
    if not aspects:
        record["missing_information"].append(
            "Official eBay category specifics unavailable; cannot guarantee coverage")
        return record
    generated = {k.casefold(): str(v) for k, v in record.get("item_specifics", {}).items()}
    provided = {k.casefold(): str(v) for k, v in details.items()}
    populated, status = {}, {}
    for aspect in aspects:
        name = aspect["name"]
        key = name.casefold()
        value = provided.get(key) or generated.get(key) or ""
        # Fitment is high-risk: similar-looking parts may have different pinouts,
        # firmware, voltage, or connectors. Require seller-confirmed fitment.
        if key in ("compatible model", "compatible brand", "compatible product",
                   "compatible printer", "compatible equipment"):
            verified = (provided.get(key) or
                        provided.get("compatible_models") or
                        provided.get("confirmed_compatibility") or "")
            value = verified
            if not value:
                record["missing_information"].append(
                    "Compatibility not seller-confirmed: verify before listing (" + name + ")")
        value = str(value).strip()
        if not value or value.casefold() in ("n/a", "not applicable", "not specified", "unknown", "none"):
            populated[name] = "Not specified"
            status[name] = {"status": "MISSING", "usage": aspect["usage"]}
            if aspect["required"]:
                record["missing_information"].append("Required eBay aspect needs your input: " + name)
        else:
            populated[name] = value
            choices = aspect.get("values", [])
            bad_choice = aspect.get("mode") == "SELECTION_ONLY" and choices and value.casefold() not in {v.casefold() for v in choices}
            status[name] = {"status": "INVALID_CHOICE" if bad_choice else "VERIFY",
                            "usage": aspect["usage"]}
            if bad_choice:
                record["missing_information"].append("Select a permitted eBay value for " + name)
    record["item_specifics"] = populated
    record["item_specifics_status"] = status
    record["ebay_item_specifics_payload"] = {}
    record["suggested_category"] = metadata.get("category_name") or record["suggested_category"]
    return record
