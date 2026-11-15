"""One-time eBay seller OAuth authorization, with local refresh-token storage.

Set EBAY_CLIENT_ID, EBAY_CLIENT_SECRET, EBAY_RUNAME in PowerShell, then run.
Never share or commit the local .ebay_oauth.json.
"""
import base64
import json
import os
import secrets
import webbrowser
from pathlib import Path
from urllib.parse import urlencode, urlparse, parse_qs, unquote
from urllib.request import Request, urlopen
from urllib.error import HTTPError

ROOT = Path(__file__).resolve().parent
SCOPE = "https://api.ebay.com/oauth/api_scope/sell.inventory"

def main():
    client = os.environ.get("EBAY_CLIENT_ID", "").strip()
    secret = os.environ.get("EBAY_CLIENT_SECRET", "").strip()
    runame = os.environ.get("EBAY_RUNAME", "").strip()
    if not (client and secret and runame):
        raise SystemExit("Set EBAY_CLIENT_ID, EBAY_CLIENT_SECRET, and EBAY_RUNAME in PowerShell first.")
    state = secrets.token_urlsafe(20)
    url = "https://auth.ebay.com/oauth2/authorize?" + urlencode({
        "client_id": client, "response_type": "code", "redirect_uri": runame,
        "scope": SCOPE, "state": state
    })
    print("Opening eBay seller authorization. Sign in to your actual seller account.")
    print("If the browser does not open, visit this URL:\n" + url)
    webbrowser.open(url)
    callback = input("\nAfter granting permission, paste the COMPLETE redirected URL here:\n").strip()
    params = parse_qs(urlparse(callback).query)
    if params.get("state", [None])[0] != state:
        raise SystemExit("OAuth state mismatch. Restart authorization; no token saved.")
    if "error" in params:
        raise SystemExit("eBay authorization error: " + str(params["error"][0]))
    code = params.get("code", [None])[0]
    if not code:
        raise SystemExit("No authorization code in redirect URL. No token saved.")
    creds = base64.b64encode((client + ":" + secret).encode()).decode()
    body = urlencode({"grant_type": "authorization_code", "code": code,
                      "redirect_uri": runame}).encode()
    req = Request("https://api.ebay.com/identity/v1/oauth2/token", data=body,
                  method="POST", headers={"Authorization": "Basic " + creds,
                                          "Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urlopen(req, timeout=40) as resp:
            data = json.load(resp)
    except HTTPError as exc:
        raise SystemExit("eBay token exchange failed (HTTP " + str(exc.code) +
                         "). Check Production keys and RuName.") from exc
    refresh = data.get("refresh_token")
    if not refresh:
        raise SystemExit("eBay returned no refresh token. Authorization was not saved.")
    outfile = ROOT / ".ebay_oauth.json"
    if outfile.exists():
        raise SystemExit("Existing local token file: " + str(outfile) +
                         ". Back up/remove it before reauthorizing.")
    outfile.write_text(json.dumps({"refresh_token": refresh}, indent=2) + "\n",
                       encoding="utf-8")
    try:
        os.chmod(outfile, 0o600)
    except OSError:
        pass
    print("Seller connection saved locally. Keep this file private:", outfile)
    print("Future runs will refresh seller access automatically using your environment credentials.")

if __name__ == "__main__":
    main()
