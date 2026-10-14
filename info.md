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
| Engine (CLIP + GeoCLIP on OpenVINO, fusion, clustering, refinement) | Built; tested end to end with placeholder CLIP weights |
| Clues: OCR + language, domains, phone codes, currency, mph, script, scene, EXIF time zone | Built and unit-tested |
| Deep analysis with a local vision-language model | Built, **not yet run** (needs the laptop) |
| Map web app (offline basemap, heatmap, guesses, clues, light/dark, mobile) | Built; checked in a headless browser |
| Windows setup script and launcher | Written, **not yet run on Windows** |
| Accuracy on real photos | **Not measured yet**: run `geolock eval <folder> --fit` on geotagged photos |
| Confidence calibration | Built (`eval --fit` saves `models/calibration.json`); needs your photos |

Why some things are untested: the build machine had no access to Hugging Face, so the
real CLIP weights (and the optional VLM) could only be downloaded on the laptop. Every
other piece, including the real GeoCLIP location encoder and gallery, ran here.

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

**OCR.** RapidOCR (PP-OCRv3) reads Latin and Chinese text. Umlauts and accents are often
dropped, which the language detector tolerates. Other scripts are covered by CLIP's
script detector and the VLM.

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
| `geolock/cli.py` | `serve`, `locate`, `eval`, `bench` |
| `tools/build_geodata.py` | Rebuilds the bundled Natural Earth files |
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
- Real CLIP weights, so real accuracy, the CLIP country classifier, and the script and
  scene clues are unverified.
- Deep analysis (Qwen2.5-VL-7B via OpenVINO GenAI). The code follows the current GenAI
  API, and pip resolves its dependencies, but the model has never been loaded.
- `setup.ps1` on Windows, and speed on the Arc GPU and NPU.

**Weak spots**
- Confidence numbers are uncalibrated. With strong visual matches GeoCLIP's softmax is
  very peaked, so it may say 95 %+ too easily. Fixed in this pass by `eval --fit`, which
  learns the right settings from your own photos (see below).
- OCR only reads Latin and Chinese text and drops accents. Cyrillic, Arabic, Thai,
  Hangul and others rely on CLIP's rough script detector unless deep analysis is on.
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
1. Run setup, `geolock bench`, and `geolock eval <folder> --fit` on the laptop. Everything
   else depends on these numbers.
2. Prefer bigger towns when naming a guess (GeoNames population data) so names are
   recognisable.
3. Multilingual OCR (PaddleOCR has Cyrillic, Arabic, Korean, Japanese, Devanagari and
   other models), to read signs without the VLM.
4. A denser location gallery outside Europe and North America, where GeoCLIP's 100k
   points are thin.
5. Sun direction: shadows plus the EXIF time give latitude and orientation hints.
6. Detectors for licence plates, bollards and road signs (the classic GeoGuessr clues).
7. Batch mode in the app: drop a folder, get a map of all photos and a CSV.

## Changelog

- **2026-10-14**: Audit (above). Added HEIC support, `eval --fit` calibration, tighter
  map framing, shorter-text language detection, and a `.claude/settings.json` that
  pre-approves common commands for Claude sessions.
- **2026-10-14**: First version. Engine, clues, optional VLM, map app, setup scripts,
  tests, docs.
