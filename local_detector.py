"""Local object proposals using YOLOE prompt-free segmentation.

First use downloads pretrained model weights. Inference runs locally thereafter.
Detection is NOT proof that every eBay accessory was identified.
"""
from __future__ import annotations

import numpy as np
from PIL import Image

_model_cache = {}


def detect_items(image: Image.Image, settings: dict) -> tuple[list[dict], bool, str]:
    try:
        import torch
        from ultralytics import YOLOE
    except ImportError:
        return [], True, "Install local dependencies: pip install -r requirements-local.txt"

    model_name = str(settings.get("local_model", "yoloe-26n-seg-pf.pt"))
    if model_name not in {"yoloe-26n-seg-pf.pt", "yoloe-26s-seg-pf.pt"}:
        return [], True, "Unsupported local model. Use a supported prompt-free YOLOE checkpoint."
    try:
        if model_name not in _model_cache:
            _model_cache[model_name] = YOLOE(model_name)
        model = _model_cache[model_name]
        device = "mps" if torch.backends.mps.is_available() else "cpu"
        preview = image.copy()
        preview.thumbnail((1280, 1280), Image.Resampling.LANCZOS)
        outputs = model.predict(
            source=preview, device=device,
            imgsz=int(settings.get("local_imgsz", 640)),
            conf=float(settings.get("local_confidence", 0.30)),
            max_det=50, verbose=False)
        detected = outputs[0].boxes
        if detected is None or len(detected) == 0:
            return [], True, "Local model detected no objects: original frame preserved"

        boxes = []
        pw, ph = preview.size
        for coords, conf, cls in zip(
            detected.xyxy.cpu().numpy(),
            detected.conf.cpu().numpy(),
            detected.cls.cpu().numpy()
        ):
            left, top, right, bottom = map(float, coords)
            if right <= left or bottom <= top:
                continue
            label = str(outputs[0].names.get(int(cls), "object"))
            boxes.append({
                "label": label,
                "box": [
                    max(0, min(1000, int(round(left * 1000 / pw)))),
                    max(0, min(1000, int(round(top * 1000 / ph)))),
                    max(0, min(1000, int(round(right * 1000 / pw)))),
                    max(0, min(1000, int(round(bottom * 1000 / ph))))
                ],
                "confidence": round(float(conf), 3)
            })
        boxes = [b for b in boxes if b["box"][0] < b["box"][2] and b["box"][1] < b["box"][3]]
        if not boxes:
            return [], True, "Local bounding boxes invalid"
        # Model may not recognize specialized replacement parts or tiny accessories.
        # Flag every local result for human review until validated on real listings.
        return boxes, True, "Local YOLOE proposal only: verify all parts and accessories before listing"
    except Exception as exc:
        return [], True, f"Local detection error ({type(exc).__name__}): {str(exc)[:200]}"
