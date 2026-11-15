"""Upload unpublished Seller Hub drafts through eBay Sell Feed FX_LISTING.

Safety: never posts live listings; refuses all feed Action values except Draft.
A task is checkpointed BEFORE uploading to prevent blind duplicate submissions.
"""
import base64
import csv
import hashlib
import json
import os
import time
import uuid
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode

BASE = "https://api.ebay.com/sell/feed/v1"
AUTH = "https://api.ebay.com/identity/v1/oauth2/token"
TERMINAL = {"COMPLETED", "COMPLETED_WITH_ERROR", "FAILED", "PARTIALLY_PROCESSED"}
OPEN = {"CREATED", "QUEUED", "IN_PROCESS"}


def seller_token():
    """User-authorized OAuth access token, optionally refreshed from long-lived token."""
    refresh = os.environ.get("EBAY_REFRESH_TOKEN", "").strip()
    if not refresh:
        stored = Path(__file__).resolve().parent / ".ebay_oauth.json"
        if stored.is_file():
            try:
                refresh = str(json.loads(stored.read_text(encoding="utf-8")).get("refresh_token") or "")
            except (OSError, ValueError):
                pass
    client = os.environ.get("EBAY_CLIENT_ID", "").strip()
    secret = os.environ.get("EBAY_CLIENT_SECRET", "").strip()
    if refresh and client and secret:
        creds = base64.b64encode((client + ":" + secret).encode()).decode()
        body = urlencode({"grant_type": "refresh_token", "refresh_token": refresh,
                          "scope": "https://api.ebay.com/oauth/api_scope/sell.inventory"}).encode()
        req = Request(AUTH, data=body, method="POST",
                      headers={"Authorization": "Basic " + creds,
                               "Content-Type": "application/x-www-form-urlencoded"})
        try:
            with urlopen(req, timeout=30) as res:
                return json.load(res)["access_token"]
        except HTTPError as exc:
            raise RuntimeError("eBay OAuth refresh failed (HTTP " + str(exc.code) +
                               "); check seller authorization and refresh token.") from exc
    token = os.environ.get("EBAY_USER_ACCESS_TOKEN", "").strip()
    if not token:
        raise RuntimeError(
            "Seller OAuth missing. Set EBAY_USER_ACCESS_TOKEN (user token, not app token) "
            "or EBAY_REFRESH_TOKEN with EBAY_CLIENT_ID and EBAY_CLIENT_SECRET.")
    return token


def call(url, token, method="GET", payload=None, content_type=None, allow_status=False):
    headers = {"Authorization": "Bearer " + token,
               "X-EBAY-C-MARKETPLACE-ID": "EBAY_US"}
    if content_type:
        headers["Content-Type"] = content_type
    req = Request(url, data=payload, headers=headers, method=method)
    try:
        with urlopen(req, timeout=90) as res:
            data = res.read()
            result = json.loads(data) if data else {}
            return result, res.headers.get("Location", ""), res.status
    except HTTPError as exc:
        details = exc.read().decode("utf-8", "replace")[:500]
        raise RuntimeError("eBay Feed API HTTP " + str(exc.code) + ": " + details) from exc


def _save_state(path, state):
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def validate_csv(path):
    if not path.is_file():
        raise FileNotFoundError(str(path))
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        if not reader.fieldnames or "Action" not in reader.fieldnames or "Category ID" not in reader.fieldnames:
            raise ValueError("Expected eBay Seller Hub Create Drafts CSV headers")
        rows = list(reader)
    if not rows:
        raise ValueError("Draft CSV has no eligible listings")
    for row in rows:
        if str(row.get("Action", "")).strip() != "Draft":
            raise ValueError("Refusing to upload: every Action MUST equal Draft")
        if not str(row.get("Category ID", "")).strip().isdigit():
            raise ValueError("Refusing to upload: each row needs a numeric Category ID")
        if not str(row.get("Title", "")).strip() or len(row["Title"]) > 80:
            raise ValueError("Refusing to upload: invalid title in draft CSV")
    return len(rows)


def _multipart(path):
    boundary = "----eBayDraft" + uuid.uuid4().hex
    filename = path.name
    content = path.read_bytes()
    # eBay Feed uploadFile requires multipart/form-data with file, fileName.
    def part(name, data, filename_part=None, contenttype=None):
        header = ('--' + boundary + '\r\nContent-Disposition: form-data; name="' +
                  name + '"')
        if filename_part:
            header += '; filename="' + filename_part + '"'
        header += '\r\n'
        if contenttype:
            header += 'Content-Type: ' + contenttype + '\r\n'
        return (header + '\r\n').encode() + data + b'\r\n'
    body = part("file", content, filename, "text/csv")
    body += part("fileName", filename.encode())
    body += ('--' + boundary + '--\r\n').encode()
    return body, "multipart/form-data; boundary=" + boundary


def status(task_id, token):
    if not task_id or not all(x.isalnum() or x in "-_" for x in task_id):
        raise ValueError("Invalid task ID")
    return call(BASE + "/task/" + task_id, token)[0]


def upload_drafts(csv_path, directory, poll_seconds=90):
    csv_path, directory = Path(csv_path), Path(directory)
    count = validate_csv(csv_path)
    with csv_path.open("r", encoding="utf-8-sig", newline="") as file:
        rows = list(csv.DictReader(file))
    skus = [str(row.get("Custom label (SKU)", "")).strip() for row in rows]
    if any(not sku for sku in skus) or len(skus) != len(set(skus)):
        raise ValueError("Every eBay draft must have a unique non-empty SKU/ID")
    payload = csv_path.read_bytes()
    digest = hashlib.sha256(payload).hexdigest()
    statefile = directory / "ebay_feed_upload_state.json"
    state = json.loads(statefile.read_text(encoding="utf-8")) if statefile.exists() else {}
    submissions = state.get("submissions", {})
    prior = submissions.get(digest)
    if not prior:
        # A modified CSV hashes differently, so protect the listing IDs too.
        # Refuse to re-create drafts if ANY prior batch included the same SKU.
        for past in submissions.values():
            overlap = set(skus) & set(past.get("skus", []))
            if overlap:
                raise RuntimeError(
                    "Duplicate-draft protection: SKU(s) already submitted or attempted: " +
                    ", ".join(sorted(overlap)) +
                    ". Review eBay Seller Hub and local upload state before retrying.")
    token = seller_token()

    if prior and prior.get("task_id"):
        info = status(prior["task_id"], token)
        prior["status"] = info.get("status", "UNKNOWN")
        prior["upload_summary"] = info.get("uploadSummary", {})
        _save_state(statefile, state)
        return {"task_id": prior["task_id"], "status": prior["status"],
                "rows": prior.get("rows", count), "reused": True,
                "upload_summary": prior.get("upload_summary", {})}

    # Never blindly resubmit the same CSV if task creation/upload may have
    # succeeded before a process crash. Human must reconcile this state.
    if prior:
        raise RuntimeError("Prior upload attempt requires manual reconciliation: " + str(statefile))
    state.setdefault("submissions", {})[digest] = {
        "status": "STARTED", "task_id": None, "rows": count, "skus": skus,
        "created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "csv_sha256": digest
    }
    _save_state(statefile, state)
    entry = state["submissions"][digest]
    try:
        task, location, httpstatus = call(
            BASE + "/task", token, method="POST",
            payload=json.dumps({"feedType": "FX_LISTING", "schemaVersion": "1.0",
                                "marketplaceId": "EBAY_US"}).encode("utf-8"),
            content_type="application/json")
        task_id = str(task.get("taskId") or location.rstrip("/").split("/")[-1])
        if not task_id or task_id in ("task", "None"):
            raise RuntimeError("eBay did not return a usable task ID")
        entry["task_id"] = task_id
        entry["status"] = "TASK_CREATED"
        _save_state(statefile, state)
        body, mime = _multipart(csv_path)
        call(BASE + "/task/" + task_id + "/upload_file", token,
             method="POST", payload=body, content_type=mime)
        entry["status"] = "UPLOADED_PROCESSING"
        _save_state(statefile, state)
    except Exception as exc:
        entry["status"] = "UNCERTAIN_CHECK_EBAY_REPORTS"
        entry["last_error"] = str(exc)[:350]
        _save_state(statefile, state)
        raise

    deadline = time.monotonic() + max(0, poll_seconds)
    while True:
        try:
            info = status(task_id, token)
            entry["status"] = str(info.get("status", "UNKNOWN"))
            entry["upload_summary"] = info.get("uploadSummary", {})
            _save_state(statefile, state)
            if entry["status"] in TERMINAL or time.monotonic() >= deadline:
                break
            time.sleep(min(5, max(0, deadline - time.monotonic())))
        except (URLError, TimeoutError, RuntimeError) as exc:
            entry["status"] = "UPLOADED_STATUS_UNKNOWN"
            entry["status_error"] = str(exc)[:250]
            _save_state(statefile, state)
            break
    return {"task_id": task_id, "status": entry["status"], "rows": count,
            "reused": False, "upload_summary": entry.get("upload_summary", {})}
