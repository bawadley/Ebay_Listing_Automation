"""Poll GitHub for ChatGPT-researched listing JSON, preview with local photos.

Default mode is READ-ONLY with respect to eBay. Pass --auto-submit to opt in
to uploading unpublished drafts automatically after a successful preview.
"""
import argparse
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

from listing_automation import ROOT
from work_pipeline import safe_id

INPUT = ROOT / "researched_listings"
STATE = ROOT / "listing_drafts" / "listener_state.json"


def save_state(data):
    STATE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(STATE)


def load_state():
    if not STATE.exists():
        return {}
    value = json.loads(STATE.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("Listener state must be a JSON object")
    return value


def sync_git():
    # Never reset, force-pull, or overwrite local changes. GitHub is the inbox.
    proc = subprocess.run(["git", "pull", "--ff-only", "origin", "main"],
                          cwd=ROOT, capture_output=True, text=True)
    if proc.returncode:
        raise RuntimeError("Git pull failed (no changes processed): " +
                           (proc.stderr or proc.stdout).strip()[-400:])
    message = proc.stdout.strip()
    if message:
        print("GitHub:", message.splitlines()[-1], flush=True)


def run_pipeline(item_id, submit):
    cmd = [sys.executable, str(ROOT / "work_pipeline.py"), item_id]
    if submit:
        cmd.append("--submit")
    proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    if proc.stdout:
        print(proc.stdout.strip(), flush=True)
    if proc.stderr:
        print(proc.stderr.strip(), file=sys.stderr, flush=True)
    return proc.returncode


def process(state, auto_submit):
    if not INPUT.is_dir():
        print("No researched_listings folder yet.", flush=True)
        return
    for path in sorted(INPUT.glob("*.json")):
        if path.stem == "example" or path.stem.endswith("_example"):
            continue
        try:
            item_id = safe_id(path.stem)
        except ValueError:
            print("Skipping invalid listing ID:", path.name, flush=True)
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        prior = state.get(item_id, {})
        if prior.get("status") == "SUBMITTED":
            if prior.get("sha256") != digest:
                print("Already submitted:", item_id,
                      "- updated research must be reviewed in Seller Hub, not resubmitted.",
                      flush=True)
            continue
        desired = "SUBMITTED" if auto_submit else "PREVIEW_READY"
        if prior.get("sha256") == digest and prior.get("status") in (desired, "SUBMITTED"):
            continue
        # Don't repeatedly retry a failed package until the file is corrected.
        if prior.get("sha256") == digest and prior.get("status") == "ERROR":
            continue
        print("Processing", item_id, "-> photo folder from JSON, or listing ID", flush=True)
        code = run_pipeline(item_id, submit=False)
        if code:
            state[item_id] = {"sha256": digest, "status": "ERROR",
                              "reason": "preview failed; correct photo folder or JSON"}
        elif not auto_submit:
            state[item_id] = {"sha256": digest, "status": "PREVIEW_READY",
                              "preview": "listing_drafts/work/" + item_id + "/review.html"}
        else:
            # Explicit opt-in only. Do not submit without a successful preview.
            code = run_pipeline(item_id, submit=True)
            state[item_id] = {"sha256": digest,
                              "status": "SUBMITTED" if code == 0 else "ERROR",
                              "reason": "" if code == 0 else
                                        "upload failed; reconcile task state before retry"}
        save_state(state)
        print(item_id + ":", state[item_id]["status"], flush=True)


def main():
    parser = argparse.ArgumentParser(
        description="Auto-sync researched listings from GitHub and match local product photos")
    parser.add_argument("--interval", type=int, default=60, help="Seconds between checks")
    parser.add_argument("--once", action="store_true", help="Sync and process just once")
    parser.add_argument("--auto-submit", action="store_true",
                        help="OPT-IN: upload images and unpublished drafts to production eBay")
    parser.add_argument("--no-pull", action="store_true", help="Don't run git pull (offline test)")
    args = parser.parse_args()
    if args.interval < 15:
        parser.error("--interval must be at least 15 seconds")
    if args.auto_submit:
        print("AUTO-SUBMIT ENABLED: new drafts will be submitted to production eBay.",
              flush=True)
    else:
        print("Safe mode: preview only. No images or drafts will be sent to eBay.",
              flush=True)
    while True:
        try:
            if not args.no_pull:
                sync_git()
            state = load_state()
            process(state, auto_submit=args.auto_submit)
        except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
            print("Listener error:", exc, file=sys.stderr, flush=True)
        if args.once:
            return 0
        time.sleep(args.interval)


if __name__ == "__main__":
    sys.exit(main())
