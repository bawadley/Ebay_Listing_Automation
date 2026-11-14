"""Non-destructive, conservative batch editor for eBay product photographs.

Run: python photo_processor.py
Only reads from input/, writes to output/, and never replaces source files.
"""
from __future__ import annotations

import argparse
import base64
import io
import json
import math
import os
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import cv2
import numpy as np
from PIL import Image, ImageEnhance, ImageOps

ROOT = Path(__file__).resolve().parent
EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff"}
PROFILES = {
    "conservative": {"max_gain": 1.05, "color_gain": 0.025, "contrast": 1.00, "border_threshold": 33},
    "balanced": {"max_gain": 1.13, "color_gain": 0.055, "contrast": 1.025, "border_threshold": 27},
    "enhanced": {"max_gain": 1.22, "color_gain": 0.085, "contrast": 1.055, "border_threshold": 23},
}


def corners(rgb: np.ndarray) -> np.ndarray:
    """Collect small border-corner patches; avoid using product center."""
    h, w = rgb.shape[:2]
    sy, sx = max(2, h // 12), max(2, w // 12)
    return np.concatenate([
        rgb[:sy, :sx].reshape(-1, 3),
        rgb[:sy, -sx:].reshape(-1, 3),
        rgb[-sy:, :sx].reshape(-1, 3),
        rgb[-sy:, -sx:].reshape(-1, 3),
    ], axis=0).astype(np.float32)


def detect_background(rgb: np.ndarray) -> tuple[str, float]:
    """Detect a white photo-box scene even when dark fabric occupies corners.

    Use the whole image, not corner color alone. Warm wooden tabletops contain
    substantial orange/brown pixels, unlike a neutral lightbox background.
    Uncertain images still follow the preserve-background path.
    """
    preview = cv2.resize(rgb, (256, 256), interpolation=cv2.INTER_AREA).astype(np.float32)
    darkest = np.min(preview, axis=2)
    chroma = np.max(preview, axis=2) - darkest
    neutral_light = (darkest > 170) & (chroma < 23)
    warm_wood = ((preview[:, :, 0] - preview[:, :, 2] > 25)
                 & (preview[:, :, 1] - preview[:, :, 2] > 7)
                 & (preview[:, :, 0] > preview[:, :, 1]))
    light_fraction = float(np.mean(neutral_light))
    wood_fraction = float(np.mean(warm_wood))
    if light_fraction >= 0.20 and wood_fraction < 0.13:
        return "whitebox", round(min(1.0, light_fraction / 0.65), 2)
    return "wood", 0.0  # Means wood OR uncertain: never apply whitening.


def subject_bounds(rgb: np.ndarray, threshold: float) -> tuple[tuple[int, int, int, int] | None, str]:
    """Find a plausible *outer* silhouette; never use this mask to erase pixels."""
    h, w = rgb.shape[:2]
    c = corners(rgb)
    bg = np.median(c, axis=0)
    # Border variation check: textured backgrounds are unsafe for segmentation.
    if float(np.mean(np.std(c, axis=0))) > 38:
        return None, "Background too varied for safe subject detection"
    lab = cv2.cvtColor(rgb, cv2.COLOR_RGB2LAB).astype(np.float32)
    bg_lab = cv2.cvtColor(np.uint8([[bg]]), cv2.COLOR_RGB2LAB).astype(np.float32)[0, 0]
    distance = np.sqrt(np.sum((lab - bg_lab) ** 2, axis=2))
    mask = np.uint8(distance > threshold) * 255
    scale = max(3, int(min(h, w) * .012))
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (scale | 1, scale | 1))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    if count <= 1:
        return None, "No confident product silhouette"
    idx = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    x, y, bw, bh, area = map(int, stats[idx])
    if area < h * w * .025:
        return None, "Detected shape is too small"
    if x < w * .012 or y < h * .012 or x + bw > w * .988 or y + bh > h * .988:
        return None, "Product may touch image edge"
    return (x, y, x + bw, y + bh), ""


def crop_with_safe_margin(image: Image.Image, bounds: tuple[int, int, int, int] | None,
                          fill: float, padding_mode: str = "solid") -> tuple[Image.Image, bool]:
    """Square composition, never crop pixels from the bounding rectangle."""
    w, h = image.size
    if bounds is None:
        # Safe fallback: extend the frame instead of cutting off unknown product regions.
        side = max(w, h)
        left_pad, top_pad = (side - w) // 2, (side - h) // 2
        right_pad, bottom_pad = side - w - left_pad, side - h - top_pad
        if padding_mode == "soft":
            # Reflect and blur outside the photo only; never blur photographed pixels.
            source = np.asarray(image)
            extended = cv2.copyMakeBorder(source, top_pad, bottom_pad,
                                          left_pad, right_pad, cv2.BORDER_REFLECT_101)
            blurred = cv2.GaussianBlur(extended, (0, 0), sigmaX=max(12, side / 65))
            blurred[top_pad:top_pad + h, left_pad:left_pad + w] = source
            return Image.fromarray(blurred), False
        canvas = Image.new("RGB", (side, side), tuple(map(int, np.median(
            corners(np.asarray(image)), axis=0))))
        canvas.paste(image, (left_pad, top_pad))
        return canvas, False

    left, top, right, bottom = bounds
    bw, bh = right - left, bottom - top
    side = max(bw, bh) / max(.5, min(fill, .93))
    side = int(np.ceil(side))
    cx, cy = (left + right) / 2, (top + bottom) / 2
    # Only crop when square region fits *inside* existing photograph.
    if side > min(w, h):
        return crop_with_safe_margin(image, None, fill, padding_mode)
    x0 = int(np.clip(round(cx - side / 2), 0, w - side))
    y0 = int(np.clip(round(cy - side / 2), 0, h - side))
    if not (x0 <= left and y0 <= top and x0 + side >= right and y0 + side >= bottom):
        return crop_with_safe_margin(image, None, fill, padding_mode)
    return image.crop((x0, y0, x0 + side, y0 + side)), True


def safe_auto_square_crop(image: Image.Image, mode: str, fill: float) -> tuple[Image.Image, bool, str]:
    """Crop only clearly empty neutral margins around *all* non-background pixels.

    This isn't segmentation: each excluded pixel must look like a white
    background. Metallic glare and transparent parts make detection uncertain,
    so the conservative fallback is to keep the complete photograph.
    Wood/uncertain scenes are never automatically cropped.
    """
    w, h = image.size
    if mode != "whitebox":
        return image, False, "Wood/uncertain: cannot safely distinguish objects from table"
    rgb = np.asarray(image, dtype=np.uint8)
    short = min(w, h)
    # Preserve dark labels, accessories, shadows and photobox walls.
    low = rgb.min(axis=2).astype(np.int16)
    high = rgb.max(axis=2).astype(np.int16)
    object_pixel = (low < 205) | ((high - low) > 24)
    ys, xs = np.nonzero(object_pixel)
    if len(xs) == 0:
        return image, False, "No reliably visible item"
    left, top, right, bottom = int(xs.min()), int(ys.min()), int(xs.max() + 1), int(ys.max() + 1)
    margin = max(12, int(short * (1.0 / fill - 1.0) * .35))
    side = max(right - left + 2 * margin, bottom - top + 2 * margin)
    side = min(side, short)
    if side >= short * .97:
        return image, False, "Item/accessories or studio walls reach frame edges"
    center_x, center_y = (left + right) // 2, (top + bottom) // 2
    x0 = max(0, min(w - side, center_x - side // 2))
    y0 = max(0, min(h - side, center_y - side // 2))
    x1, y1 = x0 + side, y0 + side
    if left < x0 or right > x1 or top < y0 or bottom > y1:
        return image, False, "Crop would cut off detected content"
    # Every discarded border pixel must be confidently pale neutral.
    # Reject when even a small amount of product/label/detail is excluded.
    discarded = np.ones((h, w), dtype=bool)
    discarded[y0:y1, x0:x1] = False
    if np.any(object_pixel & discarded):
        return image, False, "Discarded margin contains product-like pixels"
    return image.crop((x0, y0, x1, y1)), True, "Clear white margins removed"


def ai_detect_items(image: Image.Image, settings: dict) -> tuple[list[dict], bool, str]:
    """Ask a vision model for boxes (not modified image pixels).

    Boxes use normalized 0..1000 x/y coordinates. A failed call never crops.
    Requires OPENAI_API_KEY; API usage can incur charges and sends photos online.
    """
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        return [], True, "OPENAI_API_KEY missing; AI cropping skipped"
    thumb = image.copy()
    thumb.thumbnail((1024, 1024), Image.Resampling.LANCZOS)
    buffer = io.BytesIO()
    thumb.save(buffer, "JPEG", quality=86)
    image_url = "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")
    instructions = (
        "You analyze REAL eBay listing photos to propose framing, not edit images. "
        "Find ALL items that may be included in the listing: main object, loose "
        "parts, fasteners, plugs, wires, bags, packaging, and accessories. "
        "Exclude the table, studio walls and incidental room clutter. "
        "When you cannot tell which objects are for sale, set review_required true. "
        "Do not omit uncertain small accessories; include their boxes instead. "
        "Return ONLY compact JSON with keys boxes, review_required, reason. "
        "boxes is an array of {label, box:[left,top,right,bottom]}, normalized "
        "integers 0..1000. No markdown. If items touch photo edges, boxes must "
        "reach 0 or 1000 accordingly. Be conservative about cutoffs."
    )
    data = {
        "model": settings.get("ai_model", "gpt-6.1-terra"),
        "input": [{
            "role": "user",
            "content": [
                {"type": "input_text", "text": instructions},
                {"type": "input_image", "image_url": image_url, "detail": "high"}
            ]
        }],
        "max_output_tokens": 900
    }
    request = Request("https://api.openai.com/v1/responses",
        data=json.dumps(data).encode("utf-8"),
        headers={"Authorization": "Bearer " + key,
                 "Content-Type": "application/json"},
        method="POST")
    try:
        with urlopen(request, timeout=75) as response:
            payload = json.load(response)
        segments = [part.get("text", "") for item in payload.get("output", [])
                    for part in item.get("content", []) if part.get("type") == "output_text"]
        answer = json.loads("".join(segments))
        boxes = answer.get("boxes", [])
        if not isinstance(boxes, list) or not boxes or len(boxes) > 50:
            return [], True, "No usable item bounding boxes returned"
        for item in boxes:
            values = item.get("box") if isinstance(item, dict) else None
            if (not isinstance(values, list) or len(values) != 4
                or not all(isinstance(v, (int, float)) and math.isfinite(v) for v in values)
                or not (0 <= values[0] < values[2] <= 1000
                        and 0 <= values[1] < values[3] <= 1000)):
                return [], True, "AI returned invalid box coordinates"
        return boxes, bool(answer.get("review_required", True)), str(answer.get("reason", ""))[:240]
    except (HTTPError, URLError, TimeoutError, ValueError, KeyError) as exc:
        return [], True, "AI detection failed: " + str(exc)[:180]


def crop_from_ai_boxes(image: Image.Image, boxes: list[dict],
                       fill: float, margin_fraction: float) -> tuple[Image.Image, bool, str]:
    """Create square crop containing *all* returned boxes plus breathing room.

    If any bounding box falls beyond the feasible square, keep source intact.
    """
    w, h = image.size
    if not boxes:
        return image, False, "No AI boxes"
    x0 = min(b["box"][0] for b in boxes) * w / 1000
    y0 = min(b["box"][1] for b in boxes) * h / 1000
    x1 = max(b["box"][2] for b in boxes) * w / 1000
    y1 = max(b["box"][3] for b in boxes) * h / 1000
    bw, bh = x1-x0, y1-y0
    if min(bw, bh) <= 0:
        return image, False, "Invalid union bounding box"
    margin = max(10, round(max(bw, bh) * margin_fraction))
    side = math.ceil(max(bw+2*margin, bh+2*margin, max(bw, bh)/fill))
    if side > min(w, h):
        return image, False, "All items cannot fit safely inside a square crop"
    cx, cy = (x0+x1)/2, (y0+y1)/2
    left = int(max(0, min(w-side, round(cx-side/2))))
    top = int(max(0, min(h-side, round(cy-side/2))))
    if left > x0-margin or top > y0-margin or left+side < x1+margin or top+side < y1+margin:
        return image, False, "Insufficient room for safe crop margins"
    # Converting model coordinates to real pixels cannot guarantee it saw every part.
    return image.crop((left, top, left+side, top+side)), True, "AI box-based square crop"


def lift_midtones(image: Image.Image, amount: float) -> Image.Image:
    """Lift midtones with a gentle curve; protect pure black and white endpoints.

    This cannot recover details that were clipped in the original photograph.
    """
    if amount <= 0:
        return image
    rgb = np.asarray(image, dtype=np.float32) / 255.0
    # Raises shadows/midtones while tapering toward zero change at highlights.
    lifted = rgb + amount * rgb * (1.0 - rgb)
    return Image.fromarray(np.uint8(np.round(np.clip(lifted, 0, 1) * 255)))


def correct_colors(image: Image.Image, mode: str, profile: dict) -> Image.Image:
    rgb = np.asarray(image).astype(np.float32)
    if mode == "whitebox":
        c = corners(np.uint8(rgb))
        ref = np.median(c, axis=0)
        target = float(np.mean(ref))
        raw = target / np.maximum(ref, 1)
        amount = profile["color_gain"] / .055
        gains = 1 + (raw - 1) * amount
        gains = np.clip(gains, 1 - profile["color_gain"], 1 + profile["color_gain"])
        rgb = np.clip(rgb * gains.reshape(1, 1, 3), 0, 255)
    result = Image.fromarray(np.uint8(np.round(rgb)))
    gray = np.asarray(result.convert("L"))
    median = float(np.median(gray))
    # Gentle brightening only for genuinely dark photos; no blanket whitening.
    if median < 125:
        requested = 125 / max(median, 1)
        gain = min(profile["max_gain"], requested)
        result = ImageEnhance.Brightness(result).enhance(gain)
    if profile["contrast"] != 1:
        result = ImageEnhance.Contrast(result).enhance(profile["contrast"])
    return result


def whiten_background(image: Image.Image, strength: float) -> tuple[Image.Image, float]:
    """Gently lift only high-confidence connected neutral white background.

    Never cuts out or replaces pixels. Deliberately leaves ambiguous areas alone.
    Returns edited image and fraction of pixels affected.
    """
    if strength <= 0:
        return image, 0.0
    rgb = np.asarray(image, dtype=np.uint8)
    h, w = rgb.shape[:2]
    low = np.min(rgb, axis=2)
    high = np.max(rgb, axis=2)
    # White-ish, nearly neutral, locally smooth regions only.
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    fgray = gray.astype(np.float32)
    mean = cv2.GaussianBlur(fgray, (0, 0), 3)
    variance = cv2.GaussianBlur(fgray * fgray, (0, 0), 3) - mean * mean
    smooth = variance < 45
    candidate = (low >= 224) & ((high.astype(np.int16) - low.astype(np.int16)) <= 18) & smooth
    # Only components connected to the outer image border can be background.
    labels_n, labels = cv2.connectedComponents(candidate.astype(np.uint8), 8)
    edge = np.concatenate((labels[0, :], labels[-1, :], labels[:, 0], labels[:, -1]))
    approved_ids = np.unique(edge[edge != 0])
    if len(approved_ids) == 0:
        return image, 0.0
    approved = np.isin(labels, approved_ids) & candidate
    # Protect the edge around darker objects from halos and accidental spill.
    kernel = np.ones((5, 5), dtype=np.uint8)
    safe = cv2.erode(approved.astype(np.uint8), kernel, iterations=1).astype(bool)
    if not np.any(safe):
        return image, 0.0
    pixels = rgb.astype(np.float32)
    # Nonlinear highlight-only correction: preserve shadows and midtones.
    eligibility = np.clip((low.astype(np.float32) - 224) / 24, 0, 1)
    alpha = (safe.astype(np.float32) * eligibility * strength)[..., None]
    whitened = pixels + (255.0 - pixels) * alpha
    out = Image.fromarray(np.uint8(np.round(np.clip(whitened, 0, 255))))
    return out, float(np.mean(alpha[..., 0] > 0))


def process(path: Path, output: Path, settings: dict) -> dict:
    record = {"file": path.name, "status": "conservative", "notes": []}
    try:
        with Image.open(path) as source:
            image = ImageOps.exif_transpose(source).convert("RGB")
        if min(image.size) < 500:
            record["notes"].append("Low source resolution; output will be upscaled")
        original = np.asarray(image)
        detected, confidence = detect_background(original)
        requested_mode = settings["background_mode"]
        mode = detected if requested_mode == "auto" else requested_mode
        record["background"] = mode
        record["background_confidence"] = round(confidence, 2)
        profile = PROFILES[settings["profile"]]

        original_size = image.size
        cropped = False
        crop_mode = settings.get("crop_mode", "conservative")
        review_required = False
        if crop_mode == "off":
            reason = "Cropping disabled"
        elif crop_mode == "conservative":
            image, cropped, reason = safe_auto_square_crop(image, mode, settings["subject_fill"])
        else:
            boxes, review_required, note = ai_detect_items(image, settings)
            record["ai_detected_items"] = [str(x.get("label", "item"))[:80] for x in boxes]
            if not boxes:
                reason = note
            else:
                image, cropped, reason = crop_from_ai_boxes(
                    image, boxes, settings["subject_fill"],
                    float(settings.get("crop_margin", 0.07)))
                if note:
                    record["notes"].append(note)
        record["notes"].append(reason)
        if crop_mode == "ai" and (review_required or not cropped):
            record["notes"].append("AI result requires visual review")
        # Preserve every photographed pixel when the crop is uncertain.
        # The output may be rectangular; eBay accepts rectangular product photos.
        padding_mode = "none"
        if not cropped and settings.get("fallback_layout", "original") == "square":
            image, _ = crop_with_safe_margin(image, None, settings["subject_fill"], "solid")
            padding_mode = "solid"
            record["notes"].append("Square padding used: source kept intact")
        record["original_dimensions"] = list(original_size)
        record["crop"] = "safe-square" if cropped else ("square padding" if padding_mode == "solid" else "original aspect ratio")
        correction_profile = {**profile, "max_gain": 1.0, "contrast": 1.0} if mode == "wood" else profile
        image = correct_colors(image, mode, correction_profile)
        exposure = (float(settings.get("wood_exposure_strength", 0.15)) if mode == "wood"
                    else float(settings.get("exposure_strength", 1.0)))
        record["exposure_applied"] = exposure
        image = lift_midtones(image, exposure)
        whitening_strength = float(settings.get("background_whitening", 0.0))
        if mode == "whitebox" and whitening_strength > 0:
            image, affected_fraction = whiten_background(image, whitening_strength)
            record["background_whitening_coverage"] = round(affected_fraction, 4)
            if affected_fraction < 0.02:
                record["notes"].append("Whitening skipped most of photo: background was uncertain")
        elif whitening_strength > 0:
            record["notes"].append("Background whitening skipped for wood/uncertain scene")
        size = int(settings["output_size"])
        w, h = image.size
        factor = size / max(w, h)
        image = image.resize((max(1, round(w * factor)), max(1, round(h * factor))),
                             Image.Resampling.LANCZOS)
        target = output / f"{path.stem}_edited.jpg"
        if target.exists():
            n = 2
            while (output / f"{path.stem}_edited_{n}.jpg").exists():
                n += 1
            target = output / f"{path.stem}_edited_{n}.jpg"
        image.save(target, "JPEG", quality=settings["jpeg_quality"], subsampling=0)
        record["output"] = target.name
        record["padding_mode"] = padding_mode
        record["output_dimensions"] = list(image.size)
        record["status"] = ("needs_review" if crop_mode == "ai" and review_required
                            else "optimized" if cropped else "conservative")
        if not cropped:
            record["notes"].append("Check composition: auto crop was not safe")
    except Exception as exc:
        record["status"] = "needs_review"
        record["notes"].append(f"Processing error: {exc}")
    return record


def main() -> None:
    parser = argparse.ArgumentParser(description="Safe batch eBay photo processor")
    parser.add_argument("--config", type=Path, default=ROOT / "config.json")
    args = parser.parse_args()
    settings = json.loads(args.config.read_text(encoding="utf-8"))
    if settings.get("profile") not in PROFILES:
        parser.error("profile must be conservative, balanced or enhanced")
    if settings.get("background_mode") not in {"auto", "whitebox", "wood"}:
        parser.error("background_mode must be auto, whitebox or wood")
    if not (512 <= int(settings["output_size"]) <= 4096):
        parser.error("output_size must be between 512 and 4096")
    if not (.5 <= float(settings["subject_fill"]) <= .93):
        parser.error("subject_fill must be between 0.5 and 0.93")
    if not (0 <= float(settings.get("wood_exposure_strength", 0.15)) <= 1):
        parser.error("wood_exposure_strength must be between 0 and 1")
    if not (0 <= float(settings.get("exposure_strength", 0.35)) <= 1):
        parser.error("exposure_strength must be between 0 and 1")
    if not (0 <= float(settings.get("background_whitening", 0.0)) <= 1):
        parser.error("background_whitening must be between 0 and 1")
    if settings.get("crop_mode", "conservative") not in {"off", "conservative", "ai"}:
        parser.error("crop_mode must be off, conservative or ai")
    if not (0.02 <= float(settings.get("crop_margin", 0.07)) <= 0.20):
        parser.error("crop_margin must be between 0.02 and 0.20")
    if settings.get("fallback_layout", "original") not in {"original", "square"}:
        parser.error("fallback_layout must be original or square")
    if not (75 <= int(settings["jpeg_quality"]) <= 100):
        parser.error("jpeg_quality must be between 75 and 100")

    input_dir, output_dir = ROOT / "input", ROOT / "output"
    input_dir.mkdir(exist_ok=True)
    output_dir.mkdir(exist_ok=True)
    photos = sorted(p for p in input_dir.iterdir()
                    if p.is_file() and p.suffix.lower() in EXTENSIONS)
    if not photos:
        print("No photos found. Put JPG/PNG/WEBP/TIFF files into input/ and run again.")
        return
    records = [process(path, output_dir, settings) for path in photos]
    summary = {
        "profile": settings["profile"],
        "total": len(records),
        "optimized": sum(x["status"] == "optimized" for x in records),
        "conservative": sum(x["status"] == "conservative" for x in records),
        "needs_review": sum(x["status"] == "needs_review" for x in records),
        "photos": records
    }
    (output_dir / "processing_report.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in summary.items() if k != "photos"}, indent=2))
    print(f"See {output_dir / 'processing_report.json'} for per-photo notes.")


if __name__ == "__main__":
    main()
