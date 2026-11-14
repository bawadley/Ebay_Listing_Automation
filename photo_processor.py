"""Non-destructive, conservative batch editor for eBay product photographs.

Run: python photo_processor.py
Only reads from input/, writes to output/, and never replaces source files.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

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
    c = corners(rgb)
    median = np.median(c, axis=0)
    near_gray = float(np.max(median) - np.min(median)) < 24
    bright = float(np.min(median)) > 175
    spread = float(np.mean(np.std(c, axis=0)))
    if near_gray and bright and spread < 37:
        return "whitebox", min(1.0, max(0.0, (float(np.min(median)) - 155) / 55))
    return "wood", 0.0  # Treat all uncertain scenes as preserve-background.


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
                          fill: float) -> tuple[Image.Image, bool]:
    """Square composition, never crop pixels from the bounding rectangle."""
    w, h = image.size
    if bounds is None:
        # Safe fallback: extend the frame instead of cutting off unknown product regions.
        side = max(w, h)
        canvas = Image.new("RGB", (side, side), tuple(map(int, np.median(
            corners(np.asarray(image)), axis=0))))
        canvas.paste(image, ((side - w) // 2, (side - h) // 2))
        return canvas, False

    left, top, right, bottom = bounds
    bw, bh = right - left, bottom - top
    side = max(bw, bh) / max(.5, min(fill, .93))
    side = int(np.ceil(side))
    cx, cy = (left + right) / 2, (top + bottom) / 2
    # Only crop when square region fits *inside* existing photograph.
    if side > min(w, h):
        return crop_with_safe_margin(image, None, fill)
    x0 = int(np.clip(round(cx - side / 2), 0, w - side))
    y0 = int(np.clip(round(cy - side / 2), 0, h - side))
    if not (x0 <= left and y0 <= top and x0 + side >= right and y0 + side >= bottom):
        return crop_with_safe_margin(image, None, fill)
    return image.crop((x0, y0, x0 + side, y0 + side)), True


def lift_midtones(image: Image.Image, amount: float) -> Image.Image:
    """Lift midtones with a gentle curve; protect pure black and white endpoints.

    This cannot recover details that were clipped in the original photograph.
    """
    if amount <= 0:
        return image
    rgb = np.asarray(image, dtype=np.float32) / 255.0
    # Raises shadows/midtones while tapering toward zero change at highlights.
    lifted = rgb + amount * rgb * (1.0 - rgb)
    return Image.fromarray(np.uint8(np.round(np.clip(lifted, 0, 1) * 255)), "RGB")


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
    result = Image.fromarray(np.uint8(np.round(rgb)), "RGB")
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

        bounds = None
        if mode == "whitebox":
            bounds, reason = subject_bounds(original, profile["border_threshold"])
            if reason:
                record["notes"].append(reason)
        elif settings.get("allow_crop_on_wood", False):
            record["notes"].append("Wood crop requested but disabled until subject detection is validated")
        else:
            record["notes"].append("Wood/uncertain scene: preserved full frame")

        image, cropped = crop_with_safe_margin(image, bounds, settings["subject_fill"])
        image = correct_colors(image, mode, profile)
        image = lift_midtones(image, float(settings.get("exposure_strength", 0.35)))
        size = int(settings["output_size"])
        image = image.resize((size, size), Image.Resampling.LANCZOS)
        target = output / f"{path.stem}_edited.jpg"
        if target.exists():
            n = 2
            while (output / f"{path.stem}_edited_{n}.jpg").exists():
                n += 1
            target = output / f"{path.stem}_edited_{n}.jpg"
        image.save(target, "JPEG", quality=settings["jpeg_quality"], subsampling=0)
        record["output"] = target.name
        record["crop"] = "subject-aware" if cropped else "full-frame square padding"
        record["status"] = "optimized" if cropped and not record["notes"] else "conservative"
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
    if not (0 <= float(settings.get("exposure_strength", 0.35)) <= 1):
        parser.error("exposure_strength must be between 0 and 1")
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
