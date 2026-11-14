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
- `auto_crop_enabled`: default `true`; crops only when every excluded margin pixel appears neutral white. No segmentation or generative edits.
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
