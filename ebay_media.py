"""Upload local product photos to eBay Picture Services using modern Media API.

This replaced the decommissioned Trading UploadSiteHostedPictures method.
Images are uploaded only when a seller explicitly runs --submit.
"""
import hashlib
import json
import mimetypes
import uuid
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

BASE = "https://apim.ebay.com/commerce/media/v1_beta/image"
ALLOWED = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tif", ".tiff",
           ".webp", ".heic", ".avif"}

def _read_json(response):
    blob = response.read()
    return json.loads(blob) if blob else {}


def upload_one(path, token):
    boundary = "----eBayPhoto" + uuid.uuid4().hex
    mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    binary = path.read_bytes()
    prefix = ('--' + boundary + '\r\nContent-Disposition: form-data; '
              'name="image"; filename="' + path.name.replace('"', '') +
              '"\r\nContent-Type: ' + mime + '\r\n\r\n').encode()
    body = prefix + binary + ('\r\n--' + boundary + '--\r\n').encode()
    req = Request(BASE + "/create_image_from_file", data=body, method="POST",
                  headers={"Authorization": "Bearer " + token,
                           "Content-Type": "multipart/form-data; boundary=" + boundary})
    try:
        with urlopen(req, timeout=120) as res:
            created = _read_json(res)
            location = res.headers.get("Location", "")
    except HTTPError as exc:
        raise RuntimeError("eBay photo upload HTTP " + str(exc.code) + ": " +
                           exc.read().decode("utf-8", "replace")[:300]) from exc
    url = created.get("imageUrl")
    if not url and location:
        image_id = location.rstrip("/").split("/")[-1]
        req = Request(BASE + "/" + image_id,
                      headers={"Authorization": "Bearer " + token})
        with urlopen(req, timeout=60) as res:
            url = _read_json(res).get("imageUrl")
    if not isinstance(url, str) or not url.startswith("https://"):
        raise RuntimeError("eBay accepted photo but did not provide an EPS image URL")
    return url


def cached_image_available(url):
    """Reject stale EPS URLs; fail closed on temporary network/auth errors."""
    if not isinstance(url, str) or not url.startswith("https://"):
        return False
    request = Request(url, headers={"Range": "bytes=0-0", "User-Agent": "eBayDraftPhotoCheck/1.0"})
    try:
        with urlopen(request, timeout=20) as response:
            available = response.headers.get("Content-Type", "").lower().startswith("image/")
            response.read(1)
            return available
    except HTTPError as exc:
        if exc.code in (404, 410):
            return False
        raise RuntimeError("Cannot verify cached eBay image (HTTP " + str(exc.code) + "); retry later") from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise RuntimeError("Cannot verify cached eBay image; check connection and retry") from exc


def upload_images(paths, cache_path, token):
    if len(paths) > 12:
        raise ValueError("Only 12 pictures supported for draft feed")
    cache_path = Path(cache_path)
    try:
        cache = json.loads(cache_path.read_text(encoding="utf-8")) if cache_path.exists() else {}
    except ValueError:
        raise RuntimeError("Image upload cache is malformed. Fix before retrying.")
    result = []
    for path in paths:
        path = Path(path)
        if not path.is_file() or path.suffix.lower() not in ALLOWED:
            raise ValueError("Unsupported or missing local photo: " + str(path))
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        entry = cache.get(digest, {})
        url = entry.get("url")
        if not cached_image_available(url):
            url = upload_one(path, token)
            cache[digest] = {"file": path.name, "url": url}
            tmp = cache_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(cache, indent=2) + "\n", encoding="utf-8")
            tmp.replace(cache_path)
        result.append(url)
    return result
