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

## Tighter crops (3% default)

`crop_margin` now accepts values from `0.0` to `0.20`; default is `0.03` (3% of the detected group\'s longest dimension, per side). Default `subject_fill` is now `0.90` so that the 3% margin can actually affect framing; with `subject_fill: 0.80`, its 80% target can dominate and make changing `crop_margin` appear ineffective. For tighter crops try `crop_margin: 0.02` and `subject_fill: 0.92`. These margins only protect *detected* items. Local AI candidates still require review/explicit approval; check for missed accessories and transparent bags.

## Wood-background local AI crops (enabled)

Wood/tabletop images now run the same local AI square crop-proposal path as white-background images (`allow_local_wood_crop: true`). The processor draws crop bounds and saves `*_crop_candidate.jpg` when the detected foreground fits with the configured margin. It does **not** automatically apply those crops: inspect each candidate against the original for missing rails, tools and hardware, then add safe files to `approved_local_crops`. Images whose segmentation touches the edge or exceeds the available square keep their original composition. Current preferred settings remain `subject_fill: 0.80` and `crop_margin: 0.05`.

## Phase 2: AI-written eBay listing drafts (photo processor optional)

The new \`listing_automation.py\` creates a **local batch of AI-written, human-reviewable drafts**. **It never connects to eBay, saves Seller Hub drafts, charges listing fees, or publishes listings.** Actual eBay-side draft syncing is a separate future step requiring eBay OAuth, eBay category/aspects, images hosted at HTTPS URLs or uploaded to eBay, selling policies, SKU, price and quantity. The \`drafts.csv\` is a review/export aid, **not** an eBay bulk-upload template.

### Windows PowerShell quick start

With your project folder open and a Python environment already configured:

\`\`\`powershell
git pull origin main
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
$env:OPENAI_API_KEY = "YOUR_OPENAI_API_KEY"
python listing_automation.py --limit 2
start .\listing_drafts\review.html
\`\`\`

The key belongs only in your local PowerShell session or a secure Windows secret store. Never check it into GitHub or put it in \`listing_config.json\`. API calls are billed separately from ChatGPT. Test with \`--limit 1\` or \`--limit 2\` first; after checking, run \`python listing_automation.py\` for the rest.

**Photo grouping:** Photos directly inside \`input/\` become **one listing per image**. If you photograph several angles of one item, put them together in a subfolder such as \`input/printer_board_001/\`; that folder becomes one listing. Alternatively create \`listing_groups.json\` (see \`listing_groups.example.json\`) with \`listings\` entries containing a unique \`id\`, relative \`images\` list and optional seller-verified \`details\` object. The presence of \`listing_groups.json\` uses its grouping instead of auto grouping. If photos from different products get grouped together, the AI may write an inaccurate lot listing.

**Outputs:** \`listing_drafts/review.html\` shows image thumbnails, SEO title, description, possible category, suggestions for condition/item specifics, and warnings. Each product also has editable JSON, plus \`drafts.csv\` and \`listing_report.json\`. Existing drafts are preserved on reruns unless you pass \`--force\` (overwrites prior edits). Photos are only read, not modified, and image processing does not run.

**SEO and accuracy:** eBay recommends an informative title no longer than 80 characters, exact identifiers, suitable categories and required/recommended specifics; the generator prioritizes these and flags missing evidence. Item-specific names/required values depend on eBay's leaf category. The generator only suggests a category name, not a verified category ID, and it does **not** guarantee that all required eBay aspects are supplied. It never assumes electronics work from photos or makes up fitment/MPNs. Always review photos, brand, model, included components, condition, compatibility, price, shipping and returns before transferring a draft to eBay.

Optional \`listing_config.json\` setting \`"web_research": true\` enables a Responses API web-search tool; this may add API cost or require a compatible model/tool combination. Leave it off for a lower-cost first test. Verified product details can instead be supplied in \`listing_groups.json\`.

Official eBay references:
- https://www.ebay.com/sellercenter/listings/create-listings
- https://www.ebay.com/sellercenter/listings/item-specifics
- https://www.ebay.com/help/selling/listings/writing-effective-title?id=4166
- https://developer.ebay.com/api-docs/sell/static/inventory/publishing-offers.html
- https://developer.ebay.com/api-docs/user-guides/static/trading-user-guide/item-specifics-requirements.html


## Local Ollama AI (default)

Install Ollama on Windows: https://ollama.com/download/windows . For Qwen3-VL use Ollama 0.12.7 or newer. In PowerShell:

```powershell
ollama pull qwen3-vl:4b
git pull origin main
.\.venv\Scripts\Activate.ps1
python listing_automation.py --limit 2
start .\listing_drafts\review.html
```

The default `listing_config.json` now selects `provider: "ollama"` and `model: "qwen3-vl:4b"`. The AI photo analysis runs on your own computer through `127.0.0.1:11434`, needs no OpenAI API key or credits, and writes editable local drafts only. If RAM is limited, try `ollama pull qwen3-vl:2b` and set that model in the config. Larger PCs can use `qwen3-vl:8b`. Running the model may be slow without a powerful GPU. It cannot verify live eBay prices or required item specifics without separate online research. Always verify product model, condition and fitment. No listings are published or uploaded to eBay. To use OpenAI again set `provider: "openai"` and `model: "gpt-4.1"` and set OPENAI_API_KEY.


## Seller-first, text-only AI workflow (current default)

**Photos are NOT sent to Ollama or used for product identification.** The seller provides brand, product, exact model/board number, condition, and included parts. Photos named in `listing_groups.json` are simply linked in the local review page. Copy `listing_groups.example.json` to `listing_groups.json`, edit `details` and photo filenames, and group multiple photos of an item under one entry. Each listing MUST include `details.product` or `details.product_name`. The default model is now the quicker text-only `qwen3:4b`: run `ollama pull qwen3:4b` once.

Optional product research: `listing_config.json` sets `web_research: true`, and an `OLLAMA_API_KEY` environment variable enables Ollama's web search API to fetch search snippets about the seller-provided model. Get the key from https://ollama.com/settings/keys . Example in PowerShell: `$env:OLLAMA_API_KEY = "YOUR_OLLAMA_KEY"` (never commit keys). If absent, the generator still runs **offline**, explicitly flags that the details weren't web-verified, and does not fabricate citations. Web results are supporting evidence, not proof of exact hardware compatibility. They are saved as `research_sources` in each local JSON draft. Review against manufacturer specifications. No eBay uploads or publishing. Run `python listing_automation.py --limit 1` then open `listing_drafts/review.html`. Existing drafts are preserved; `--force` regenerates and overwrites them.


## Official eBay category item specifics

The program optionally fetches the exact Required, Recommended, and Optional fields for an eBay category using the eBay Taxonomy API. Supply an eBay production OAuth access token in the PowerShell environment as `EBAY_ACCESS_TOKEN` (not your password or App ID). In `listing_groups.json`, set `details.ebay_category_id` to the correct eBay leaf category ID. If not specified, the program asks eBay for a category suggestion and uses the first match, which you MUST check. No token means the program still produces a listing, but category field completeness cannot be guaranteed. The local AI receives every returned aspect name with supported choices, proposes researched values, and fills unknown draft entries with `Not specified`. Those are REVIEW placeholders only, **not necessarily valid eBay submission values**, especially for required fields. Values are flagged `VERIFY`, `MISSING`, or `INVALID_CHOICE`; the generated `ebay_item_specifics_payload` is deliberately empty until reviewed. All drafts remain local: no eBay uploading or publishing. For API access see https://developer.ebay.com/api-docs/commerce/taxonomy/overview.html and https://developer.ebay.com/api-docs/static/oauth-client-credentials-grant.html .


### Compatibility protection

Generated item specifics no longer accept AI-only guesses for Compatible Model, Compatible Brand, Compatible Product, Compatible Printer, or Compatible Equipment. These fields use seller-verified values from details.compatible_models, details.confirmed_compatibility, or the exact field. Otherwise they become Not specified with a review warning. Existing drafts are not automatically modified; rerun with --force only if overwriting prior draft edits is acceptable.


## ChatGPT-to-GitHub listing workflow (no model API charges)

1. Enter basic product identity and photo paths in `listing_groups.json`. Keep local photos under `input/`; do not commit your photos or personal credentials to GitHub.
2. In ChatGPT, say: \"Research my eBay listing with ID MY_ID: [product name, brand, exact part number, condition, included items]. Find official manufacturer data, the eBay category and all available category specifics; mark unverifiable details Not specified. Save a research package to my GitHub repo in chatgpt_research/MY_ID.json.\" ChatGPT must research and use connected GitHub to commit the resulting JSON. These are **interactive chat turns**, not an autonomous unattended agent.
3. On Windows run `git pull origin main` and `python listing_automation.py --chatgpt --limit 1 --force`, then open `listing_drafts/review.html`. The `--chatgpt` route **never calls Ollama, OpenAI API, or Ollama web search**. It reads only GitHub-synced researched JSON and the locally attached photos. `--force` overwrites prior drafts, so back up changes first.
4. Research package schema example: `chatgpt_research/example.json`. The filename and top-level `id` must match the product `id` in `listing_groups.json`. Required `listing` fields are the same as the existing AI output: `title`, `alternative_titles`, `description`, `category_search`, `item_specifics`, `condition_suggestion`, `condition_notes`, `included_items`, `missing_information`, `evidence_notes`, `search_keywords`, `research_notes`. Sources have `title` and `url`.
5. For **guaranteed completeness of current eBay category fields**, ChatGPT must provide `category_metadata` from the official eBay Taxonomy API response; ChatGPT web research alone may not expose every field. If that metadata is absent, the import deliberately labels category completeness as **unverified**. Your local program already knows how to fetch live aspects using `EBAY_ACCESS_TOKEN` in its regular workflow. No listings are automatically submitted to eBay.


## Default: OpenAI web-researched eBay drafts (2026)

The default provider is now OpenAI `gpt-6.1-terra` with **built-in web search** using the Responses API. Supply your seller-confirmed product identity (product name, brand, exact model/MPN, condition, included parts, color, etc.) in `listing_groups.json`. Photos are associated with the listing only and are not sent for identification. The program looks up exact-model public specifications, uses the official eBay Taxonomy API (if `EBAY_ACCESS_TOKEN` is set) to obtain the category-specific aspects, and generates JSON/CSV/HTML review drafts with clickable research citations. Two OpenAI Responses requests are made per product (web research + JSON listing). Both consume API credits, and web search has a tool fee. Set `OPENAI_API_KEY` in your current PowerShell session (never save credentials in Git), then run `python listing_automation.py --limit 1`. Existing drafts will be preserved until you use `--force` (which overwrites local edits). The existing `--chatgpt` package import and Ollama provider are still available.

**Crucial:** This remains LOCAL DRAFT generation. The eBay Inventory API can create unpublished offer objects, but eBay warns that listings created through that API are *not editable in Seller Hub*. An unpublished offer is not the same as a Seller Hub draft. Therefore this project intentionally does not create an Inventory API offer or publish listings in this phase. Review details on `listing_drafts/review.html` and copy them to your eBay Seller Hub draft manually until a verified Seller-Hub-compatible draft creation workflow is implemented. No eBay account listings are created by this command. Sources: https://developer.ebay.com/api-docs/sell/inventory/overview.html and https://developers.openai.com/api/docs/guides/tools-web-search .


## Import drafts into eBay Seller Hub website (no publishing)

Each run also writes `listing_drafts/ebay_seller_hub_drafts.csv`, formatted with the documented Seller Hub Reports **Create drafts** template headers: `Action=Draft`, `Category ID`, `Title`, `Description`, and optional SKU, etc. Local photographs are NOT URLs; eBay allows you to add them from your computer after importing the draft. Condition ID is left blank because valid IDs vary by category. Prices and business policies remain for your review. This upload will create *unpublished, editable Seller Hub drafts* (not Inventory API offers). **Our script does not upload the CSV; you upload it manually** through eBay > Seller Hub > Reports > Uploads > Upload template, using the "Create drafts" workflow. Download eBay's current Create drafts template there if eBay changes fields. The CSV intentionally contains only officially documented draft fields; generated full category item specifics remain in `review.html` and `drafts.csv` for you to review and fill on the site. Every CSV upload can create new draft records; do not upload the same CSV repeatedly by accident. Drafts with missing numeric eBay category IDs are skipped from the upload CSV and reported in `listing_report.json`.

Official eBay documentation: https://pages.ebay.com/sh/reports/help/create-listings-bulk/ (Creating draft listings) and https://www.ebay.com/help/-/-/seller-hub-reports?id=4096 .

## Direct automatic Seller Hub draft creation (eBay Sell Feed API)

After initial **seller-authorized OAuth** setup, you can run:
```powershell
git pull origin main
python listing_automation.py --limit 1 --upload-drafts
```
This researches products with OpenAI, generates local previews, and uploads the internally generated **Draft-only** CSV through the official eBay Sell Feed API `FX_LISTING` task workflow. **You do not need to open, edit or upload the CSV yourself.** The script creates a Feed task, uploads the file as multipart data, checks task status and saves the eBay task ID in `listing_drafts/ebay_feed_upload_state.json`. The command NEVER uses the API to publish a live listing, and any other Action besides the literal `Draft` is rejected. The result is intended to be a Seller Hub-editable unpublished draft, to be reviewed at https://www.ebay.com/sh/lst/drafts . Local photos are not automatically uploaded; attach them when you open the draft in Seller Hub. Full researched category specifics remain in review.html and may need entering in Seller Hub.

**Once-only account setup:** You need an eBay developer Production app (App ID/Client ID and Cert ID/Client Secret), and an **eBay seller-user OAuth token** granted with scope `https://api.ebay.com/oauth/api_scope/sell.inventory`. The application token `EBAY_ACCESS_TOKEN` used by the Taxonomy API is not sufficient. For first testing, set the seller authorization-code token in PowerShell as `$env:EBAY_USER_ACCESS_TOKEN="YOUR_SELLER_USER_ACCESS_TOKEN"`. For ongoing use, set `EBAY_REFRESH_TOKEN`, `EBAY_CLIENT_ID`, and `EBAY_CLIENT_SECRET`; the script will refresh short-lived access tokens automatically. See eBay OAuth authorization code flow https://developer.ebay.com/api-docs/static/oauth-authorization-code-grant.html . Never commit credentials to GitHub or send them through ChatGPT.

**Safe testing:** Start with a single item and the `--upload-drafts` flag only after the local `review.html` looks correct. The Sell Feed Seller Hub upload has no sandbox support, so it uses your production seller account. A feed may take time to process. `COMPLETED` and a successful uploadSummary is stronger evidence than mere task acceptance; verify in Seller Hub. Check Reports upload results if status is `COMPLETED_WITH_ERROR`. If an attempt is interrupted, the script records its digest and task ID; it will check an existing task rather than resubmit. For unknown states it fails closed to prevent unintended duplicates. The same exact CSV will not be intentionally uploaded twice. **Do not delete the state file to force retries** unless you have confirmed the previous submission did not create drafts.

Implementation intentionally requires an explicit `--upload-drafts` flag rather than automatically creating drafts during local testing. You can eventually make it default after a successful live pilot. To update or change a listing already uploaded, edit its draft in Seller Hub. Since the Feed API creates partial Seller Hub drafts, photo and potentially item-specific metadata completion remains a manual step.

Official sources: https://developer.ebay.com/api-docs/sell/static/feed/fx-feeds-overview.html and https://pages.ebay.com/sh/reports/help/create-listings-bulk/ .


### One-time eBay browser authorization (recommended)

In your Windows PowerShell session, set these **Production** eBay developer values locally (never commit them):

```powershell
$env:EBAY_CLIENT_ID = "YOUR_PRODUCTION_APP_ID"
$env:EBAY_CLIENT_SECRET = "YOUR_PRODUCTION_CERT_ID"
$env:EBAY_RUNAME = "YOUR_PRODUCTION_OAUTH_RUNAME"
python ebay_oauth_setup.py
```

The helper opens the official eBay authorization browser page. Log in to your eBay **seller** account, grant the requested `sell.inventory` scope, then paste the COMPLETE redirected URL into PowerShell. The helper validates the OAuth state and saves your refresh token only to the local, git-ignored `.ebay_oauth.json`. It does not submit any drafts. The uploader will use that saved refresh token and the Client ID/Secret environment variables to refresh access before uploads. The initial seller authorization must be done once manually; eBay requires user consent. Do not upload or disclose the refresh token file. On Windows, protect your local project directory and user account, since chmod cannot guarantee Windows filesystem permissions. The `EBAY_ACCESS_TOKEN` Taxonomy key remains separate from the seller authorization.


## MacBook + ChatGPT Work workflow (recommended; no OpenAI API calls)

1. Copy the project to your Mac via `git clone https://github.com/bawadley/Ebay_Listing_Automation.git`. Install Python 3.11+ and `python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt`.
2. Make folders `researched_listings/` and `product_photos/<id>/`. Put your original photos in `product_photos/<id>/`. Keep photos on the Mac; they're not committed to GitHub.
3. In a ChatGPT Work session with approved local folder access, ask Work to research the exact product, select a verified eBay leaf category ID, enumerate category item-specifics, prepare an accurate title and description, and write `researched_listings/<id>.json` following `researched_listings/example.json`. **If Work cannot write local files, have it provide the JSON for you to save, or commit that file to GitHub for `git pull`.** Work must not invent condition or compatibility. Never give Work your eBay credentials.
4. Preview (offline and safe): `python work_pipeline.py <id>` (add `--check-category` if EBAY_ACCESS_TOKEN is configured). Review `listing_drafts/work/<id>/review.html`. Photos are discovered by filename in the named photo folder. Only JPG/JPEG/PNG/GIF/BMP/TIF/TIFF/WEBP/HEIC/AVIF are supported; max 12. No local photo recognition by the model.
5. Once seller OAuth is set up using `python ebay_oauth_setup.py`, and after reviewing the preview, run `python work_pipeline.py <id> --submit`. It uploads each local photo to eBay Picture Services using the *Media API*, inserts the resulting secure photo URLs in an internally generated `Action=Draft` Seller Hub Feed CSV, and submits it through `FX_LISTING`. You never handle the CSV manually. The result is an **unpublished Seller Hub draft** (subject to feed acceptance). It records the task and a duplicate-protection state under `listing_drafts/work/<id>/`. Check Seller Hub Drafts and Reports for status.
6. **Do not run `--submit` twice for the same item without checking Seller Hub.** The uploader rejects repeat SKU submissions even if content changed. `work_pipeline.py` has no publish/list action.

**Known limitation:** The supported basic Create Drafts feed contains title, description, category, and photo URLs, but not a verified mapping for every dynamic category-specific item-specific column. Therefore the full researched specifics are stored in `review.html` and the JSON file, but they may require further input in Seller Hub. The media integration is coded against eBay's current Media API but has not been live-tested against this seller account; first verify a single test draft. No claim of end-to-end completion until Seller Hub confirms images and attributes. Work's local folder and command execution permissions vary by macOS app/account configuration. If unavailable, execute the command yourself in Mac Terminal.

**Work prompt:** 'Research my product [name/model/condition] for eBay. Find the exact leaf category ID and all published item specifics; verify technical details from manufacturers or reliable sources; use Not specified for unsupported values, and never assume compatibility. Write the complete structured package to researched_listings/<id>.json following the example schema. My photos are in product_photos/<id>/. Then tell me to preview it. Do not publish anything.'

Official docs: https://developer.ebay.com/api-docs/commerce/media/static/overview.html , https://developer.ebay.com/api-docs/sell/static/feed/fx-feeds-overview.html , https://pages.ebay.com/sh/reports/help/create-listings-bulk/ .


### Including item specifics in Seller Hub draft feeds

The Work pipeline now adds supported nonblank item specifics using Seller Hub's dynamic `C:<aspect name>` columns (e.g. `C:Brand`, `C:Type`, `C:Model`), along with photo URLs. Unknown placeholders and values marked `INVALID_CHOICE` are omitted. This follows the Seller Hub category-template column convention, but **each category-specific aspect and permitted value needs verification**; eBay may reject unsupported names or choices in the upload results. Verify actual imported fields in the first live draft rather than assuming all attributes survived. See https://pages.ebay.com/sh/reports/help/create-listings-bulk/ for Seller Hub template guidance.


## Browser ChatGPT -> GitHub -> Mac listener -> eBay Drafts

The Mac can retrieve listing JSON automatically from GitHub without ChatGPT Work or any OpenAI API charges. Each listing has a UNIQUE `id` (e.g. `batch001_1`) and a numeric `photo_folder` field (e.g. `"1"`). This allows you to re-use folders 1, 2, 3, 4 for later batches while keeping eBay listing IDs unique.

Photos stay **only on your computer** in `product_photos/1/`, `product_photos/2/`, etc. ChatGPT creates a researched listing for the exact IDs and commits it to `researched_listings/batch001_1.json`, with `"photo_folder": "1"`. The local listener does a safe `git pull --ff-only` and reads the JSON; it never needs your photos or eBay OAuth tokens in GitHub.

Try this sequence on the Mac:

```bash
git pull origin main
mkdir -p product_photos/1 product_photos/2 product_photos/3 product_photos/4
python3 local_listener.py --once
python3 local_listener.py
```

The listener checks GitHub every 60 seconds and automatically generates local previews in `listing_drafts/work/<id>/review.html`. **Default is preview-only**, so it will NEVER upload to eBay until you explicitly opt in. Once one listing has been reviewed, upload it using `python3 work_pipeline.py batch001_1 --submit` (seller OAuth required). The `--auto-submit` listener option is available only after you've tested a draft and want a fully automatic workflow; it uploads photos and unpublished draft feed records to the production eBay account. There is no publishing operation in this code. The listener stores local status in `listing_drafts/listener_state.json` and won't repeatedly attempt an unchanged errored package; fix its JSON or photo folder, then rerun. eBay's own upload-state protections also apply.

**Example Work/ChatGPT request for four listings:** 'Batch 001: Listing 1 is ..., Listing 2 is ..., Listing 3 is ..., Listing 4 is ... . Research each, find exact eBay leaf category and its item specifics, verify specs, write strong title and description. Save four packages to the GitHub repo in `researched_listings/batch001_1.json` through `batch001_4.json`. Each package's `id` is `batch001_<number>` and `photo_folder` is the matching number `1` through `4`. Copy the exact JSON shape from `researched_listings/example.json` or `researched_listings/numbered_example.json`. Photos are on my computer; don't upload photos to GitHub. Do not publish anything.' 

**Caution:** eBay Feed task acceptance isn't proof the Seller Hub draft was created; check Seller Hub Reports and Drafts. Automatic photo transfer and category aspect mapping must still be verified on one real account. No OpenAI API key is needed for this route. GitHub commit permissions are required for ChatGPT to save the files.
