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

Edited square JPG files are written to `output/`, together with a `processing_report.json` containing per-photo status and warnings. **Original files are never modified.** Output filename conflicts are handled with numbered names rather than overwriting previous outputs.

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
- `smart_crop_enabled`: default `false` to preserve all accessories
- `allow_crop_on_wood`: currently intentionally *not implemented*; wood scenes preserve full-frame rather than risking clipping.

## Safety behavior and limitations

- **No AI image generation, background deletion, or object rebuilding.**
- Whitebox photos may use a detected outer silhouette **only to determine crop bounds**. The detected mask is never used to erase pixels, so glare cannot create holes in the product.
- Auto mode detects neutral bright regions across the whole photo, so black lightbox side walls are less likely to cause a false wood classification. The classification is heuristic; verify the reported mode and override it with `background_mode` when necessary.
- Wooden table and uncertain scenes retain the whole rectangular frame, padded to square with softened reflected edge extensions rather than solid tan bands. This is safer than cropping, although the item may look smaller. No wood background removal is attempted.
- Color correction for whitebox photos is deliberately mild; wood scenes do not use automatic white balance based on the table.
- Wood/uncertain scenes disable automatic global brightness/contrast boosts and use separately adjustable gentler exposure. Whitebox settings remain unchanged.
- Soft padding consists of generated edge extensions outside the photographed area; original pixels are not blurred.
- Exposure is adjustable independently from background whitening. Brightness corrections preserve the input file but can still wash out details at high settings.
- Whitening does **not** segment or delete a product: it only brightens smooth, near-neutral, already-light pixels belonging to border-connected regions. It never runs on wood/uncertain backgrounds. This heuristic can still affect white objects that visually merge with the backdrop, so visually review outputs.
- `conservative` statuses mean a safe fallback was used, not necessarily that the image is bad.
- Simple image heuristics **cannot guarantee** perfect item detection, crop safety, or color accuracy. Review photos visually before uploading to eBay. Particularly check glossy metal, transparent parts, cables, off-white objects, and large items near the image edges.

## Next step

Test with real unedited whitebox and wood-table listings. Compare against manually edited reference photos, then add AI-assisted object detection and a before/after review interface **only where testing proves it useful**.
