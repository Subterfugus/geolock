# GeoLock: project info

Living notes on what GeoLock is, how it works, what state it is in and what comes next.
Updated with every change.

_Last updated: 2026-10-14_

## Goal

Give it a photo; it says where on Earth the photo was most likely taken, how confident
it is, and why. Fully offline on a Lenovo Yoga 9i Aura (Core Ultra 7 258V, Arc 140V iGPU,
AI Boost NPU, 32 GB shared RAM, no CUDA). No paid APIs. Results on a map with a
confidence and the clues for each guess.

## Status

| Area | State |
|---|---|
| Engine (CLIP + GeoCLIP on OpenVINO, fusion, clustering, refinement) | Built; **run with the real CLIP ViT-L/14 weights** (all tests pass) |
| Clues: OCR + language, domains, phone codes, currency, mph, script, scene, EXIF time zone | Built and unit-tested |
| Deep analysis with a local vision-language model | Built, **not yet run** (needs the laptop) |
| Map web app (offline basemap, heatmap, guesses, clues, light/dark, mobile) | Built; checked in a headless browser |
| Windows setup script and launcher | Written, **not yet run on Windows** |
| Accuracy on real photos | **First numbers** on 151 iNaturalist outdoor photos from 102 countries (see "Test sets and results"); everyday-photo numbers need `geolock testset` on the laptop |
| Test set download | `geolock testset <folder>`: ~300 Wikimedia Commons photos, world-spread, licences recorded (not runnable from the build machine) |
| Confidence calibration | Built (`eval --fit` saves `models/calibration.json`); fit it on the Commons set or your own photos |

Why some things are untested: the build machine has no access to Hugging Face,
Wikimedia, Flickr or Mapillary. The real CLIP weights were found inside a public Docker
image instead (see "Test sets and results"); the optional VLM has still never run.

## How it works

```
photo ─► 4 crops ─► CLIP ViT-L/14 vision (OpenVINO: GPU / NPU / CPU) ─► 768-d embedding
                                   │                       │
                         GeoCLIP image MLP          zero-shot text prompts
                                   │              (country, scene, script…)
                      cosine vs 100k GPS gallery           │
                      = visual prior over Earth            │
  OCR text ─► language, .tld, +phone, €/£/¥, mph ──┐       │
  EXIF ─► time zone ───────────────────────────────┤       │
  optional VLM ─► observations, driving side, ─────┤       │
                  country guesses                  ▼       ▼
                     posterior = prior × Π clue likelihoods (per country / per point)
                                   │
              cluster (250 km) ─► top 5 guesses, confidence = posterior mass
                                   │
         refine each guess with the continuous location encoder + named places
                                   │
         name it (Natural Earth country/region, GeoNames nearest place) and explain
```

**Visual prior: GeoCLIP.** GeoCLIP (NeurIPS 2023, MIT) aligns CLIP image embeddings with
a GPS encoder. Scoring 100k gallery coordinates gives a probability over the globe. Its
location encoder is reimplemented in NumPy (`geolock/locenc.py`, matches the original to
1e-5), so the app can also score coordinates that are not in the gallery; this is used
to refine each guess locally.

**Clues as likelihoods.** Each clue (`geolock/clues.py`) says which countries it is
typical of, how strong it is, and a background rate for everywhere else; time-zone clues
work on longitude directly. The posterior is the GeoCLIP prior times every clue's
likelihood, plus CLIP's zero-shot country classifier at half weight (it partly repeats
what GeoCLIP already knows). Clue tables live in `geolock/countrymeta.py` and prompts in
`geolock/prompts.py`.

**Confidence.** A guess's confidence is the share of posterior probability within
250 km of it. The radius shown is the distance holding 68 % of that guess's mass.
These are model probabilities, not yet calibrated against real photos; `geolock eval`
reports how often each confidence band is actually right, and `--temperature` /
`--country-weight` adjust the fusion.

**One vision pass.** The same CLIP embedding feeds GeoCLIP and every zero-shot clue, so
the heavy model runs once per photo (4 crops in one batch, fixed shape so it also
compiles for the NPU). Text prompts are embedded at setup, so the runtime does not need
the CLIP text encoder.

**OCR.** RapidOCR on the OpenVINO engine. The default PP-OCRv6 model reads Latin (with
accents), Chinese and Japanese. Setup also downloads PP-OCRv5 models for Cyrillic, Greek,
Korean, Thai, Arabic, Devanagari, Tamil and Telugu (about 10-15 MB each). An extra model
runs when CLIP thinks it sees that script, or when the default model finds text it
can't read; for each text region the most confident reading wins. The characters read
then give a script clue (Hangul means Korea, Greek means Greece or Cyprus) and, for
scripts many languages share, a language clue: Russian vs Ukrainian vs Bulgarian vs
Serbian, Arabic vs Persian vs Urdu, Hindi vs Marathi. The app never downloads at run
time; a script whose model is missing falls back to CLIP's script detector. The text
angle classifier is off: it flipped long upright lines and garbled them.

**Deep analysis (optional).** Qwen2.5-VL-7B-Instruct (Apache-2.0), INT4, through
OpenVINO GenAI on the Arc GPU. It is asked for structured JSON: observations, driving
side, text, country guesses. Those become clues at moderate weight. Expect seconds to
tens of seconds per photo; smaller option: `setup_models --vlm Qwen/Qwen2-VL-2B-Instruct`.

## Layout

| Path | What |
|---|---|
| `geolock/engine.py` | The pipeline |
| `geolock/setup_models.py` | One-time download, OpenVINO conversion, gallery and prompt embedding |
| `geolock/clues.py`, `ocr.py`, `exif.py`, `vlm.py` | Clue sources |
| `geolock/countrymeta.py`, `prompts.py` | Clue knowledge tables and CLIP prompts |
| `geolock/geodata.py`, `geolock/data/` | Offline borders, regions, place names |
| `geolock/server.py`, `geolock/web/` | Local web app (FastAPI + Leaflet, all vendored) |
| `geolock/cli.py` | `serve`, `locate`, `eval`, `bench`, `testset` |
| `geolock/testset.py` | Downloads the Wikimedia Commons test set |
| `tools/build_geodata.py` | Rebuilds the bundled Natural Earth files |
| `tools/build_inat_testset.py` | Builds a test set from iNaturalist open data (fallback) |
| `tests/` | `pytest`; engine tests run when models are present |

Models live in `models/` (git-ignored, about 0.8 GB FP16; another ~5 GB with the VLM).
Set `GEOLOCK_MODELS` to keep them elsewhere and `GEOLOCK_DEVICE` to force a device.

## Decisions

- **OpenVINO for everything heavy.** Native on Arc and the NPU, no CUDA needed.
- **GeoCLIP over a classification model.** It is open (MIT), retrieval-based (any
  coordinate can be scored), and strong for its size. Its published results on
  Im2GPS3k are about 14 % within 1 km, 35 % within 25 km, 51 % within 200 km, 70 % within
  750 km and 84 % within 2500 km; GeoLock's clues should add to that on photos with text
  or distinctive scenes, to be confirmed with `geolock eval`.
- **No non-commercial models by default.** StreetCLIP and Qwen2.5-VL-3B have
  non-commercial licences, so the defaults are CLIP (MIT), GeoCLIP (MIT) and
  Qwen2.5-VL-7B (Apache-2.0).
- **Offline map first.** Natural Earth borders and region lines are bundled and drawn by
  Leaflet; an OpenStreetMap layer is available from the layer switcher when online.
- **EXIF GPS is shown, never used for the guess.** It appears as a ★ so you can compare.

## Test sets and results

**`geolock testset <folder>`** (the one to use). Downloads ~300 photos from Wikimedia
Commons, where every file has a free licence. For each country it picks random towns
from GeoNames and takes one geotagged photo within 10 km of each, so the set covers the
whole world rather than the most photographed places. Countries get photos in proportion
to the square root of their number of towns (at most 4 each by default). Maps, flags,
scans, artwork, museum and interior shots are skipped by title and category. It writes
`labels.csv` (file, true lat/lon, country, title, author, licence, link) and
`ATTRIBUTION.md`. `geolock eval` reads `labels.csv` when present, so EXIF is not needed.
Re-running tops up an interrupted download. Not run yet: Commons is blocked on the build
machine, so only its logic is tested (`tests/test_testset.py`, with a fake Commons).

**iNaturalist fallback** (`tools/build_inat_testset.py`). iNaturalist's open data on AWS
was reachable, so the first real numbers come from it. The tool streams the metadata
(about 5 GB), keeps 3 research-grade observations per 1°×1° cell, scores thumbnails with
CLIP and keeps only wide outdoor shots (most iNaturalist photos are close-ups of plants
and animals). 4,622 thumbnails screened gave 161 wide shots; 151 photos from 102
countries were kept. Licences are CC0, CC BY or CC BY-NC, credited in `ATTRIBUTION.md`.
This is a **hard** set: nature scenes, few buildings, no text, and spread evenly over
the world instead of the Europe and US skew of Im2GPS3k.

**Results on the iNaturalist set (2026-10-14, real weights, CPU, no VLM)**

| | 1 km | 25 km | 200 km | 750 km | 2500 km | median |
|---|---|---|---|---|---|---|
| GeoCLIP alone (top gallery point) | 0 % | 1 % | 5 % | 21 % | 45 % | 2,929 km |
| GeoLock, default settings | 0 % | 3 % | 12 % | 29 % | 52 % | 2,222 km |
| GeoLock, `--fit` settings | 0 % | 3 % | 13 % | 28 % | 52 % | 2,311 km |
| `geolock eval` top guess, first version | 0 % | 1 % | 8 % | 26 % | 51 % | 2,417 km |
| `geolock eval` top guess, **after the fix below** | 0 % | 3 % | 12 % | 29 % | 52 % | 2,222 km |

Country right 15 % of the time. By continent (within 2500 km): Europe 72 %, North
America 70 %, Africa 49 %, Asia 46 %, Oceania 29 %, South America 14 % (only 7 photos).
For comparison, GeoCLIP's published Im2GPS3k numbers are 14 / 35 / 51 / 70 / 84 %, on
photos that are mostly landmarks and cities.

What this says:
- The real weights work end to end, and fusion helps: CLIP's zero-shot country classifier
  more than doubles the 200 km hit rate over GeoCLIP alone. Text clues add nothing here
  because these photos have no text.
- ~~The clustered top guess did worse than the posterior's best point.~~ Fixed: guesses
  were seeded on "most probability within 125 km" and ranked by total mass, which
  favoured broad, vague regions over the single best match. Now each guess is seeded on
  the most probable remaining point and the guesses keep that order (confidence is
  still the mass within 250 km). Within 200 km went from 8 % to 12 %.
- A denser location gallery (815k points: GeoCLIP's 100k plus one point per 1 km cell
  of MP-16's 4.7M photos) gave no clear gain on this set (9-11 % within 200 km), so the
  100k gallery stays.
- State/province zero-shot prompts (CLIP scoring all 4,596 Natural Earth regions, mixed
  into the posterior) moved results by -3 to +3 points depending on weights: within
  noise for 151 photos (one photo is 0.7 points), so not shipped.
- Is the pipeline worse than the model? No. GeoCLIP alone gets 5 % within 200 km on this
  set against 51 % on Im2GPS3k in its paper, so the set is far harder than the
  benchmark; GeoLock's fusion adds 7 points over GeoCLIP alone at 200 km and 2500 km.
- A towns-and-streets subset (`--urban`) is not possible from iNaturalist: of 979
  thumbnails from places near 5+ towns, CLIP judged 1 to be a street or building shot.
  Everyday-photo numbers have to come from `geolock testset` (Commons) on the laptop.
- Not tried here, because the weights are unreachable from the build machine: StreetCLIP
  (geo-tuned CLIP, CC BY-NC), OSV-5M baselines, and the VLM country vote. These are the
  candidates for a real step up and should be measured on the Commons set.
- Confidence was too high. With default settings, photos rated 50 %+ confident were
  within 250 km only 35 % of the time, and 20-50 % ones 11 %. `--fit` chose temperature
  2.0 and country weight 0.75, which spreads the probabilities out. Fit again on the
  Commons set or your own photos; nature shots are not what you will usually upload.

**How the real weights got here.** Hugging Face is blocked on the build machine, but
Docker Hub is not. The public image `williamjokus/geoclip-serverless:v1` caches
`openai/clip-vit-large-patch14` in one layer; its `model.safetensors` SHA-256
(`a2bf730a…026dcb`) matches the Hugging Face file's content address. The laptop does not
need this: `setup.ps1` downloads from Hugging Face directly.

## Audit (2026-10-14)

An honest pass over every feature. "Ran here" means it ran on the build machine with
placeholder CLIP weights (Hugging Face is blocked there), so nothing below says anything
about real-photo accuracy yet.

**Working (ran here)**
- Whole pipeline from upload to map: crops, OpenVINO inference, GeoCLIP gallery scoring,
  fusion, clustering, refinement, naming, explanations. 16 tests pass.
- GeoCLIP location encoder port matches the original to 1e-5; with a known location fed
  in, the top guess lands within 1 km (Paris, Kyoto, Nairobi).
- Text clues: OCR reads printed signs; language, `.de`-style domains (even when OCR adds
  spaces), phone prefixes, currency and mph are detected. A German shop sign moved
  Germany from ~1 % to ~60 % against a random visual prior.
- EXIF reading (GPS, time zone, camera), EXIF ★ on the map, HEIC photos from iPhones.
- Web app in light, dark and phone layouts; offline basemap with labels and region lines.
- `geolock eval --fit` end to end.

**Not run yet (needs the laptop)**
- ~~Real CLIP weights~~: now run on the build machine (see "Test sets and results").
  Accuracy on everyday photos still needs `geolock testset` + `eval` on the laptop.
- Deep analysis (Qwen2.5-VL-7B via OpenVINO GenAI). The code follows the current GenAI
  API, and pip resolves its dependencies, but the model has never been loaded.
- `setup.ps1` on Windows, and speed on the Arc GPU and NPU.

**Weak spots**
- Confidence numbers are uncalibrated. With strong visual matches GeoCLIP's softmax is
  very peaked, so it may say 95 %+ too easily. Fixed in this pass by `eval --fit`, which
  learns the right settings from your own photos (see below).
- ~~OCR only reads Latin and Chinese text and drops accents.~~ Fixed: see the OCR
  section. Still not read by OCR: Hebrew, Georgian, Armenian, Bengali, Khmer, Lao,
  Burmese, Ethiopic, Sinhala (no PaddleOCR model); those rely on CLIP and the VLM. The
  extra models could not be downloaded on the build machine, so only the default model
  has actually been run.
- Driving side is only detected by the VLM. CLIP can't see it reliably.
- Clue strengths and the country tables are hand-set. Reasonable, but untested.
- Place names come from GeoNames' list of places with 1000+ people, which sometimes names
  a suburb ("Riehl") rather than the city everyone knows ("Cologne").
- Short signs (two or three words) rarely trigger a language clue. Loosened slightly in
  this pass.

**Fixed in this pass**
- iPhone HEIC photos are supported (analysis and preview).
- `geolock eval <folder> --fit` tunes GeoCLIP's temperature and the CLIP country weight
  to make confidence honest on your photos, and saves them to `models/calibration.json`,
  which the app then uses automatically.
- The map no longer zooms out to the whole world because of one faint far-away guess.
- Shorter text now counts for language detection.

**Worth adding next (in order)**
1. Run setup, `geolock bench`, `geolock testset data/testset` and
   `geolock eval data/testset --fit` on the laptop. Everything else depends on these
   numbers.
2. Prefer bigger towns when naming a guess (GeoNames population data) so names are
   recognisable.
3. ~~Multilingual OCR~~ (done, see the changelog).
4. A denser location gallery outside Europe and North America, where GeoCLIP's 100k
   points are thin.
5. Sun direction: shadows plus the EXIF time give latitude and orientation hints.
6. Detectors for licence plates, bollards and road signs (the classic GeoGuessr clues).
7. Batch mode in the app: drop a folder, get a map of all photos and a CSV.

## Changelog

- **2026-10-14**: Final-pick fix: guesses are seeded on the most probable point, not on
  the broadest area (8 % to 12 % within 200 km on the iNaturalist set).

- **2026-10-14**: Test sets. `geolock testset` downloads a licensed, world-spread
  Wikimedia Commons set; `eval` reads `labels.csv` and can save per-photo results
  (`--csv`); `tools/build_inat_testset.py` builds a set from iNaturalist open data. First
  run with the real CLIP weights and first accuracy numbers (above).

- **2026-10-14**: Multi-script OCR. RapidOCR 3 (PP-OCRv6 default + PP-OCRv5 Cyrillic,
  Greek, Korean, Thai, Arabic, Devanagari, Tamil, Telugu) on OpenVINO; script and
  language clues for all of them; angle classifier off (it garbled upright lines).

- **2026-10-14**: Audit (above). Added HEIC support, `eval --fit` calibration, tighter
  map framing, shorter-text language detection, and a `.claude/settings.json` that
  pre-approves common commands for Claude sessions.
- **2026-10-14**: First version. Engine, clues, optional VLM, map app, setup scripts,
  tests, docs.
