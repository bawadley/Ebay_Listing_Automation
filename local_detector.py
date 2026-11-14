"""Local foreground-mask crop proposals; pixels are NEVER removed from sale photos.

Runs rembg/ISNet on a reduced preview via ONNX CPU on Apple Silicon.
A review visualization is saved separately. No crop unless mask is plausible.
"""
from __future__ import annotations

import numpy as np
from PIL import Image

_session = None


def detect_items(image: Image.Image, settings: dict, review_path=None):
    global _session
    try:
        from rembg import new_session, remove
    except ImportError:
        return [], True, "Install rembg: pip install -r requirements-local.txt"
    model = settings.get("local_model", "isnet-general-use")
    if model not in ("isnet-general-use", "u2netp"):
        return [], True, "Unsupported segmentation model"
    try:
        if _session is None or _session[0] != model:
            _session = (model, new_session(model))
        preview = image.copy()
        preview.thumbnail((768, 768), Image.Resampling.LANCZOS)
        mask_image = remove(preview, session=_session[1], only_mask=True)
        values = np.asarray(mask_image.convert("L"), dtype=np.uint8)
        threshold = int(settings.get("local_mask_threshold", 105))
        foreground = values >= threshold
        h, w = foreground.shape
        # Reject empty, near-full, or scattered masks.
        coverage = float(foreground.mean())
        # A hole-free bounding rectangle must account for all detected foreground,
        # including separate hardware and cables, rather than only the largest blob.
        ys, xs = np.nonzero(foreground)
        if len(xs) == 0:
            return [], True, "No foreground detected"
        left, top, right, bottom = int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1
        if review_path is not None:
            overlay = preview.convert("RGBA")
            tint = Image.new("RGBA", overlay.size, (0, 0, 0, 0))
            tint_pixels = np.zeros((h, w, 4), dtype=np.uint8)
            tint_pixels[..., 0] = 0
            tint_pixels[..., 1] = 210
            tint_pixels[..., 2] = 90
            tint_pixels[..., 3] = foreground.astype(np.uint8) * 105
            tint = Image.fromarray(tint_pixels, "RGBA")
            overlay = Image.alpha_composite(overlay, tint)
            # Crop rectangle is drawn later by the main processor, using the
            # exact same pixel geometry as the candidate crop.
            overlay.convert("RGB").save(review_path, "JPEG", quality=90)
        if not (0.006 <= coverage <= 0.88):
            return [], True, f"Foreground mask untrustworthy (coverage {coverage:.1%})"
        # Reject speckles near photo boundaries before they make crop unsafe.
        pad = max(2, round(min(w,h) * .005))
        if foreground[:pad].mean() > .10 or foreground[-pad:].mean() > .10:
            return [], True, "Foreground touches top/bottom edge; review required"
        if foreground[:, :pad].mean() > .10 or foreground[:, -pad:].mean() > .10:
            return [], True, "Foreground touches left/right edge; review required"
        box = [round(left * 1000 / w), round(top * 1000 / h),
               round(right * 1000 / w), round(bottom * 1000 / h)]
        if box[0] >= box[2] or box[1] >= box[3]:
            return [], True, "Invalid mask bounds"
        return [{"label": "segmented foreground", "box": box}], True, (
            f"Local segmentation mask covers {coverage:.1%}; inspect review overlay for missed accessories")
    except Exception as exc:
        return [], True, f"Local segmentation error ({type(exc).__name__}): {str(exc)[:180]}"
