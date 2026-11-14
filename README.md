# eBay Listing Automation — Phase 1: Photo Processor

A local, non-destructive **prototype** for batch editing product photographs. It does not connect to eBay and does not use generative AI.

## Quick start

Requires Python 3.10+.

```bash
git clone https://github.com/bawadley/Ebay_Listing_Automation.git
cd Ebay_Listing_Automation
python -m venv .venv
# Windows PowerShell:
.venv\\Scripts\\Activate.ps1
pip install -r requirements.txt
```

Drop original JPG, PNG, WEBP, or TIFF images in `input/`, then run:

```bash
python photo_processor.py
```

Edited JPG files are written to `output/`, together with a `processing_report.json` containing per-photo status and warnings. **Original files are never modified.** Output filename conflicts are handled with numbered names rather than overwriting previous outputs.

## Configuration

Edit `config.json`:

- `profile`: `conservative`, **`balanced`** (default), or `enhanced`
- `background_mode`: `auto` (default), `whitebox`, or `wood`
- `output_size`: square dimensions in pixels (default `1600`)
- `jpeg_quality`: default `94`
- `subject_fill`: target item coverage when a plausible silhouette is found (default `0.86`)
- `exposure_strength`: whitebox midtone lift from 0 to 1 (default `1.0`)
- `wood_exposure_strength`: separate wood/uncertain midtone lift from 0 to 1 (default `0.15`)
- `background_whitening`: gentle, high-confidence whitebox-only whitening from 0 to 1 (default `0.75`); `0` disables it
- `crop_mode`: `off`, `conservative` (default: local white-margin cropping), or `ai` (vision API object bounding boxes).\n- `crop_margin`: fraction of detected object size reserved as space around items, default `0.07`.\n- `ai_model`: vision-capable OpenAI model, default `gpt-6.1-terra`.
- `fallback_layout`: `original` (default) retains the original rectangle when a crop is unsafe and prevents blurred/solid padding; `square` uses a plain padded canvas if 1:1 is strictly required.
- `smart_crop_enabled`: legacy setting, no longer used by the new safe cropping pipeline.
- `allow_crop_on_wood`: currently intentionally *not implemented*; wood scenes preserve full-frame rather than risking clipping.

## Safety behavior and limitations

- **No AI image generation, background deletion, or object rebuilding.**
- Whitebox photos may use a detected outer silhouette **only to determine crop bounds**. The detected mask is never used to erase pixels, so glare cannot create holes in the product.
- Auto mode detects neutral bright regions across the whole photo, so black lightbox side walls are less likely to cause a false wood classification. The classification is heuristic; verify the reported mode and override it with `background_mode` when necessary.
- Wood/uncertain scenes retain their full original frame and aspect ratio by default, without blur padding. No wood background removal is attempted. Choose `fallback_layout: square` for non-blurred square padding.
- Color correction for whitebox photos is deliberately mild; wood scenes do not use automatic white balance based on the table.
- Wood/uncertain scenes disable automatic global brightness/contrast boosts and use separately adjustable gentler exposure. Whitebox settings remain unchanged.
- The processor does not blur edge extensions anymore. With `fallback_layout: original`, photos can be rectangular; eBay permits this.
- Exposure is adjustable independently from background whitening. Brightness corrections preserve the input file but can still wash out details at high settings.
- Whitening does **not** segment or delete a product: it only brightens smooth, near-neutral, already-light pixels belonging to border-connected regions. It never runs on wood/uncertain backgrounds. This heuristic can still affect white objects that visually merge with the backdrop, so visually review outputs.
- `conservative` statuses mean a safe fallback was used, not necessarily that the image is bad.
- Simple image heuristics **cannot guarantee** perfect item detection, crop safety, or color accuracy. Review photos visually before uploading to eBay. Particularly check glossy metal, transparent parts, cables, off-white objects, and large items near the image edges.

## Next step

Test with real unedited whitebox and wood-table listings. Compare against manually edited reference photos, then add AI-assisted object detection and a before/after review interface **only where testing proves it useful**.

## Safe cropping limitations

Cropping is deliberately conservative. Auto-crop operates only on confident whitebox scenes and requires that every pixel outside the suggested square area look like pale neutral background. It preserves multi-part kits and cables by treating all dark/colorful regions as potentially important. Wood and ambiguous photos keep the original aspect ratio by default, instead of generating distracting blurred bands. This is not a full AI object detector, so zooming aggressively on wood scenes still requires later AI-assisted composition and manual review. Visual inspection is required before publishing.

## AI-assisted cropping (optional)

AI mode uses OpenAI's Responses API with a vision-capable model to return **only rectangular object boxes**. Python combines all detected products and accessories into one 1:1 crop, leaving configurable margins. The AI never edits, erases, or re-generates product pixels. This sends a scaled copy of each photo to the API and can incur API usage costs. ChatGPT subscriptions are separate from API billing.

On macOS Terminal, set an API key for this terminal session:

```bash
export OPENAI_API_KEY="your-key-here"
```

Never commit a key into the repository or config file. Set `"crop_mode": "ai"` in config.json and run `python photo_processor.py`. No key, API error, invalid bounding boxes, uncertain identification, or unsafe geometry means the photo is **not cropped** and the report contains a warning. Some ambiguous group photos might include unrelated tools or miss tiny components; manually inspect every AI crop before publication. Use `"crop_mode": "conservative"` for offline, free processing.

`fallback_layout: "original"` preserves the original image geometry when a crop is unsafe; the result may be rectangular. Crops with enough room become 1:1. The `crop_margin` setting and `subject_fill` control breathing room around the whole group. Automatic subject boxes are not guaranteed pixel-perfect and are **not** a substitute for review.

## Local AI cropping (M2 MacBook Air, 8 GB)

The default crop mode is now `local_ai`, powered by the lightweight **YOLOE-26n prompt-free** open-vocabulary instance segmentation model. It proposes boxes without any OpenAI API token usage. A model download is necessary on first run. This is a specialized local detector, not a language model, and it may miss unusual OEM parts, thin cables, fasteners, transparent bags, or obscure tools. **All local AI results are flagged for manual review.** No model result automatically deletes or regenerates any image pixels.

Use your existing Python 3.13 environment on macOS:

```bash
source .venv/bin/activate
python -m pip install -r requirements-local.txt
python photo_processor.py
open output
```

The system chooses Apple's Metal MPS backend when available, otherwise CPU. To experiment with less memory pressure, lower `local_imgsz` from `640` to `512`. For higher sensitivity, adjust `local_confidence` (default `0.30`), at the cost of more false positives. `local_model` can be `yoloe-26n-seg-pf.pt` or `yoloe-26s-seg-pf.pt`; start with the nano variant on 8GB.

Set `crop_mode` to `off`, `conservative`, `local_ai`, or `ai` (cloud API). Keep `fallback_layout: "original"` to protect full framing. The model's bounding boxes may omit accessories, so inspect every cropped photo and the processing report before publishing. Initial use needs internet to fetch model weights from the Ultralytics model distribution; later inference is local. See https://docs.ultralytics.com/models/yoloe/ for official YOLOE model notes and usage.

## Update: foreground segmentation instead of misleading YOLOE labels

The YOLOE prompt-free test on 13 listing photographs returned many incorrect object names (e.g. insects and food items) and **0 safe crops**. The local default now uses `rembg` with the `isnet-general-use` foreground segmentation model. The model predicts a **mask** instead of guessing part categories. **Only its overall mask bounds are used for cropping**; no background pixels are removed, repainted, or replaced.

Update and install:

```bash
git fetch origin
git reset --hard origin/main
source .venv/bin/activate
python -m pip install -r requirements-local.txt
python photo_processor.py
```

On an M2 with 8 GB RAM, this model runs via ONNX Runtime's CPU backend on reduced-size previews (up to 768 pixels) to limit memory use. The initial model weights are downloaded, then cached locally. Each local photo creates `output/crop_reviews/<source-stem>_mask_preview.jpg`: green overlay = foreground segmentation, orange rectangle = detected union bounds. These previews help you see if the model missed tiny parts or included tabletop clutter. **Review every proposed crop and overlay.** A missed accessory can still cause an unsafe crop, especially with wood backgrounds. Original photos are never changed; output full-frame fallback remains active. Optionally set `local_model: "u2netp"` to use a smaller, less accurate model, and adjust `local_mask_threshold` (1–254, default 105).

Keep `crop_mode: "conservative"` if you want to disable segmentation. No OpenAI API calls are made in `local_ai` mode.

## Python 3.13 / rembg installation repair

Local ISNet/ONNX dependencies need a modern Pillow version. Older photo-processor requirements used `Pillow<12`, which conflicts with current rembg (Pillow >=12.3). Requirements have been updated for Python 3.13 and modern rembg. In the existing virtual environment:

```bash
source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
python -m pip install --upgrade -r requirements-local.txt
python -m pip check
python photo_processor.py
```

If pip still selects an incompatible package, inspect the full resolver error; don't install ancient Pillow releases or remove safety version bounds to force a build. Python 3.13 on Apple Silicon is supported by modern Pillow releases.

## Local mask crop review gate (important)

Testing the mask overlays exposed missed full-sized objects (e.g. rail on IMG_0289 and several tools in IMG_0309 and IMG_0311) and transparent bag edges. A mask-based crop **cannot be assumed complete**. Local AI now emits `output/crop_reviews/<name>_crop_candidate.jpg` whenever a square crop is geometrically possible, but defaults to preserving the full original photo in the listing output. Check the candidate against the mask overlay **and original photo**. Then add the exact original filename to `approved_local_crops` in config.json (e.g. `["IMG_0249.jpeg"]`) and rerun to apply that crop. `allow_local_wood_crop` defaults to `false` until a more reliable tool/parts detector is available. Cropped wood images require both `allow_local_wood_crop: true` and an explicitly approved filename. This gate is deliberate: masks can miss clear packaging, cables and accessories. No API or remote service required.

## Comfortable crop spacing (10% per side)

The default crop now reserves **at least 10% of the detected foreground's larger dimension on each side**, creating a visible gap between items and the crop edge. `crop_margin: 0.10` controls this buffer, and `subject_fill: 0.80` caps the object's intended footprint at ~80% of crop width/height. For slightly tighter framing, set `crop_margin: 0.07` and `subject_fill: 0.86`; the supported margin setting range is 0.05-0.20. This padding is real, **previously photographed background**, not artificial blurred or solid-color borders.

The crop routine checks that all detected bounding boxes have sufficient margin on every side after centering and clamping to photo bounds. If the source doesn't have enough space, it refuses the crop and keeps the original photo. This protects detected items, but segmentation may still miss transparent bags, thin cables and unrelated objects. Local mode continues writing crop candidates for approval, not automatically publishing them.

## Crop review overlay legend (fixed)

`output/crop_reviews/*_mask_preview.jpg` now draws **cyan** for the tight ISNet foreground bounding rectangle, and **orange** for the **actual square crop proposal including `crop_margin` and `subject_fill`**. The orange outline comes from the identical pixel coordinates used to create the crop candidate; changing `crop_margin` visibly moves it when enough background exists. If no safe square fits, the preview says **NO SAFE SQUARE CROP** and draws no misleading orange border. Green is the model mask (not the output cutout). The preview can show a geometric candidate even for wood images withheld from final application; review settings still gate actual cropping.
