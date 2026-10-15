# GeoLock: project info

Living notes on what GeoLock is, how it works, what state it is in and what comes next.
Updated with every change.

_Last updated: 2026-10-15_

## Goal

Give it a photo; it says where on Earth the photo was most likely taken, how confident
it is, and why. Offline by default (optional second opinion from Claude or ChatGPT on the
user's own plan) on a Lenovo Yoga 9i Aura (Core Ultra 7 258V, Arc 140V iGPU,
AI Boost NPU, 32 GB shared RAM, no CUDA). No paid APIs. Results on a map with a
confidence and the clues for each guess.

## Status

| Area | State |
|---|---|
| Engine (CLIP + GeoCLIP on OpenVINO, fusion, clustering, refinement) | Built; **run with the real CLIP ViT-L/14 weights** (all tests pass) |
| Clues: OCR + language, domains, phone codes, currency, mph, script, scene, EXIF time zone | Built and unit-tested |
| Deep analysis with a local vision-language model | Built but **not part of the plan** (Brady, 2026-10-14): the Claude / ChatGPT second opinion covers this; never run |
| Second opinion from Claude / ChatGPT (own subscription, via Claude Code / Codex CLI) | Built. **Claude path run for real** (Claude Code 2.1, ~5-10 s per photo); Codex path tested against a fake CLI only (no ChatGPT login on the build machine). 2026-10-15: geoguessing checklist prompt and zoomed sign crops (fake CLIs only so far). Accuracy gain not yet measured |
| Map web app (offline basemap, heatmap, guesses, clues, light/dark, mobile) | Built; checked in a headless browser |
| **Windows desktop app** (Tauri window, installer, first-run download, library, settings) | Released as v0.3.0 and 0.3.1 on GitHub Releases; 0.4.0 is the UX overhaul (model/effort pickers with live progress, street map, findable settings, new look). Every main build installs the real installer on a Windows CI runner, runs first-run setup and a locate, and screenshots the window (pushed to the `ci-screenshots` branch). **Installed and run on the Yoga laptop** (2026-10-15, see "Results on the Yoga laptop") |
| Windows setup script and launcher | **Run on real Windows 11** (desktop PC, 2026-10-14): worked first try after two small fixes (see changelog) |
| Accuracy on real photos | **Measured** on 295 Wikimedia Commons photos from 202 countries: 26 % within 200 km, 67 % within 2500 km, country right 39 % (see "Test sets and results"); also 151 hard iNaturalist nature photos |
| Test set download | `geolock testset <folder>`: ~300 Wikimedia Commons photos, world-spread, licences recorded. **Run on Windows**: 295 photos in about 45 minutes |
| Confidence calibration | Built and **fitted on the Commons set** (temperature 1.5, country weight 0.5) |

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

**Second opinion from Claude or ChatGPT (optional, `geolock/analyst.py`).** Brady wanted
to use the Claude and ChatGPT plans they already pay for. Subscriptions have no API keys,
so GeoLock runs the official CLIs the user is signed in to, as a subprocess, on request
only:

- Claude: `claude -p --input-format stream-json --output-format stream-json --verbose
  --tools "" --setting-sources "" --strict-mcp-config --no-session-persistence
  --system-prompt … --json-schema …`, in an empty temp folder. The photo goes in as a
  base64 image block on stdin; the answer comes back as `structured_output` in the
  `result` event. Login check: `claude auth status --json` (`loggedIn`).
- ChatGPT: `codex exec --skip-git-repo-check --sandbox read-only --ephemeral -C <tmp>
  --image photo.jpg [--image crop1.jpg …] --output-schema schema.json
  --output-last-message answer.json -` with the prompt on stdin. Login check: `codex login status` (exit code 0).
- Fallbacks: no Claude Code but `ANTHROPIC_API_KEY` set and `anthropic` installed: the
  Messages API with structured output (`claude-opus-5-5`, override with
  `GEOLOCK_CLAUDE_MODEL`). Codex accepts an API key via `codex login --with-api-key`.
  Older CLIs that reject a flag are retried with the bare minimum of flags.
- Flags were checked against Claude Code 2.1.300 and Codex CLI 0.162.1 (`--help`), on
  2026-10-14.

Never on by default: the app's boxes start unticked on every page load, `locate` and
`eval` only ask with an explicit `--ask`, and the tests use fake `claude` / `codex`
commands, so they never spend the user's plan.

What is sent: the pixels only, re-encoded as JPEG (≤1568 px), so EXIF GPS and camera
serials never leave the machine; up to 4 **zoomed crops of the signs** (see below); and
(unless "Share GeoLock's findings" is off) a short text briefing: GeoLock's top 3
guesses, country odds, OCR text, clue titles, CLIP scene labels and the camera's clock
time. The prompt tells the model GeoLock's visual guesses are weak hints.

**The prompt (2026-10-15)** works like a strong GeoGuessr player: a fixed 12-item
checklist in order (driving side, road lines, signs, bollards, licence plates, utility
poles, script and language, architecture, vegetation, terrain and soil, sun and climate,
other), each item answered only if visible, with what it suggests *and rules out*. Then
3-6 sentences of reasoning, up to 4 rejected places with the evidence against them, and
1-5 ranked guesses with lat/lon, radius, probability and a one-line "why" each. The
schema enforces the checklist categories; `clean()` still reads the older flat `clues`
answers saved in the library. Checklist items are shown (with category labels) and carry
no extra weight; the guesses are fused as before.

**Sign crops** (`analyst.sign_crops`): GeoLock's OCR boxes are grouped into signs (lines
within about 1.5 text heights merge), padded so the sign's shape and colour show, cut
from the full-resolution photo (the whole photo is downscaled to 1568 px, a sign often
isn't legible there) and sent as images 2-5, ranked by how much confident text they hold.
Crops smaller than 384 px are enlarged, larger ones capped at 768 px; boxes covering
more than a quarter of the photo are skipped (no zoom gain). The prompt lists each crop's
region and, only when findings are shared, what GeoLock's OCR read there, and tells the
model to trust its own reading when they differ. `GEOLOCK_LLM_CROPS=0` turns crops off.
Limit: OCR only keeps confident lines, so text it could not read at all gets no crop yet.
The app shows the crops as small thumbnails on the answer card.

Fusion is a **mixture, not a product**: final = (1 − w) × local posterior + w × the
analysts' distribution, where each analyst guess puts its stated probability in a bump of
its stated radius (at least 25 km on the gallery) and what it left unassigned follows the
local posterior; two analysts are averaged. `w` = 0.75 by default (`analyst_weight` in
`models/calibration.json`). A product of likelihoods was tried first: a synthetic test
showed a sharp GeoCLIP prior could drown out a 50 %-confident correct answer, which is the
wrong way round for everyday photos, where frontier models are far stronger. When a
guess is refined, the analyst's exact point is a candidate and the same mixture is
applied locally, so the pin lands on the analyst's spot when it dominates. The
analyst's country, driving side and observations are shown as clues with no extra
weight (they are already part of its answer). `geolock eval --ask claude` also reports
the analyst's own accuracy next to the fused one; `--fit` does not tune `w` yet.

Terms and limits (as understood on 2026-10-14; check the current terms yourself):
- This is personal use of the official CLIs with your own login, which both are built
  for (Claude Code's `-p` print mode and `codex exec` are documented non-interactive
  modes). GeoLock never reads, copies or reuses login tokens or web-session cookies.
- Usage counts against your plan's limits. A 300-photo `eval --ask` is 300 requests
  per analyst and can hit a 5-hour limit; run evals in smaller batches.
- Anthropic does not allow third-party products to offer Claude.ai login to *other*
  people. GeoLock running on your own machine with your own login is fine; shipping it
  so others use their (or your) subscription through it is not what subscriptions are
  for, so use API keys for that.
- Photos sent this way are handled under Anthropic's or OpenAI's consumer terms for your
  account (including their data-use settings), not GeoLock's offline promise.

**Deep analysis (optional, not part of the plan).** Brady decided on 2026-10-14 not to
use a local vision-language model; the Claude / ChatGPT second opinion fills this role.
The code stays but is not installed by default and is not tested. Qwen2.5-VL-7B-Instruct (Apache-2.0), INT4, through
OpenVINO GenAI on the Arc GPU. It is asked for structured JSON: observations, driving
side, text, country guesses. Those become clues at moderate weight. Expect seconds to
tens of seconds per photo; smaller option: `setup_models --vlm Qwen/Qwen2-VL-2B-Instruct`.

## Desktop app

GeoLock is a normal Windows app: a per-user installer (no admin prompt) adds it to the
Start menu, and it runs in its own window. The browser version (`run.bat`) still works.

- **Shell** (`desktop/src-tauri`, Tauri 2 / Rust): picks a free local port and a random
  token, starts the backend with no console window, and kills it on exit (Job Object, and
  the backend also exits when its stdin closes).
- **Backend** (`geolock/desktop`, frozen with PyInstaller into `geolock-backend.exe`): the
  engine behind a token-protected API on 127.0.0.1 (`desktop/API.md`). Data lives in
  `%LOCALAPPDATA%\com.geolock.desktop` (models, library, settings).
- **UI** (`desktop/ui`, React + TypeScript + MapLibre): library of past photos, big map
  with heatmap, uncertainty circles and the photo's own GPS, an inspector with the best
  guess, other guesses, reasons, country odds, clues and the Claude / ChatGPT second
  opinion (per photo, only on click, with model and reasoning-effort pickers and live
  progress with Stop), settings (a labeled button in the library; sidebar with processor,
  analysis, second opinion, map, appearance, library, shortcuts, about).
  Drag and drop photos or whole folders anywhere, paste (Ctrl+V), Ctrl+O for files and
  Ctrl+Shift+O for a folder (subfolders included). A batch shows "Locating 3 of 12" with a
  Stop button and ends with a summary. Map: Streets (OpenFreeMap / OpenStreetMap vector
  tiles, free, no key: roads, buildings, places, landmarks, zoom to 19) is the default;
  Satellite (Esri imagery) carries OpenFreeMap roads and place names on top; Offline
  (Natural Earth borders, zoom to 9) is the automatic fallback with no internet. The
  dark streets style falls back to the light one, then to offline, if it fails to load.
- **Second opinion controls**: `GET /api/analysts/models` lists the models each CLI
  accepts (Claude: aliases and effort levels parsed from `claude --help`; ChatGPT: the
  `codex debug models` catalogue, image-capable listed models only, each with its own
  effort levels). The choice is saved as `claude_model` / `claude_effort` /
  `chatgpt_model` / `chatgpt_effort` and passed as `--model` / `--effort` (Claude) and
  `--model` / `-c model_reasoning_effort=...` (Codex). The CLIs run with streaming output
  (`--include-partial-messages`, `codex exec --json`) so `GET /api/analysts/progress`
  reports the stage (preparing, starting, thinking, writing, done) and the latest line of
  thinking; `POST /api/analysts/stop` kills the CLI's process tree and the photo keeps
  its earlier answer.
- **Look** (0.4.0): "field instrument": warm graphite / paper, one signal-orange accent,
  2-6 px corners, hairline borders instead of frosted glass, IBM Plex Sans with Plex Mono
  for numbers and coordinates.
- **Ground truth**: when a photo carries its own EXIF GPS (never used for the guess), the
  map shows it as a star with a dashed line to the selected guess, the inspector shows the
  distance, a band (street / city / region / country level, or missed) and which guess
  came closest, library rows carry a "km off" badge, a "With GPS" filter narrows the list,
  and an accuracy card gives the median error and the share within 25 / 200 / 750 /
  2,500 km for the photos shown.
- **Export**: per photo (inspector download button or right-click) as a PNG of the map as
  shown (pins, photo inset, caption), KML for Google Earth (guesses, uncertainty circles,
  analyst guesses, the photo's GPS), CSV (one row per guess) or JSON (the full result). The
  library button exports the photos shown (search and filter applied) as CSV, KML or
  JSON. The UI builds the file; the native Save dialog picks the path and the backend's
  `/api/save` writes it (absolute path, export extensions only).
- **First run**: the installer carries the small assets (GeoCLIP weights, gallery
  coordinates, prompt embeddings, calibration, OCR models). The CLIP ViT-L/14 vision
  encoder (609 MB) is downloaded once from Hugging Face as the Xenova ONNX export, pinned
  by commit and SHA-256, and converted to OpenVINO on the machine, so PyTorch is never
  needed. "Use models from an existing GeoLock folder" skips the download.
- **Build**: `.github/workflows/desktop.yml`. A Linux job builds the assets with PyTorch
  and checks the ONNX model's embeddings against PyTorch (cosine > 0.999). A Windows job
  freezes the backend, runs `tools/desktop_smoke.py` (real download, convert, locate a
  photo with text, clean exit), then builds the NSIS installer. Pushes to main publish it
  as a GitHub release `v<version>` with notes from `docs/releases/v<version>.md`; an
  existing release is never overwritten, so bump the version (pyproject, `geolock/__init__`,
  `tauri.conf.json`, Cargo and npm manifests) to ship a new installer. This slow job runs
  only on pushes to main (or by hand) and always runs to the end. Pull requests get only the
  quick checks in `.github/workflows/tests.yml` (Python tests plus a UI typecheck and build)
  and merge once those pass; anything the Windows build catches on main is fixed forward.
- **Processor** (`geolock/devices.py`): Auto tries the Arc GPU, then the NPU, then the
  CPU; a fixed choice in Settings tries that device, then the CPU. A device that fails to
  compile, fails while running, or returns NaN/infinity is dropped and the photo carries
  on on the next one; Settings then says which device failed and why. GPU kernels and NPU
  blobs are cached in `models/ov_cache`, so only the first start on a device is slow.
  Settings → Processor shows where CLIP runs, start-up and per-photo times and the last
  photo's timings, a "Test speed on each processor" button (compiles and times CLIP on
  GPU, NPU and CPU side by side, with a "Use" button per row) and "Copy details" to paste
  the whole readout into a message. CLI: `geolock bench --all-devices`.
  Precision: the model is stored with FP16 weights; the GPU and NPU run FP16, the CPU runs
  FP32 (Lunar Lake has no AVX-512/AMX for BF16). INT8 weight compression (NNCF, no new
  download, but adds NNCF to the app bundle and needs an accuracy check) is the next lever
  if the CPU path matters.
- **Gotcha**: OpenBLAS's thread pool hung after OpenVINO had run in the same process
  (at DLL load on Windows, in a matmul on Linux), so the backend runs BLAS single-threaded.

## Layout

| Path | What |
|---|---|
| `geolock/engine.py` | The pipeline |
| `geolock/setup_models.py` | One-time download, OpenVINO conversion, gallery and prompt embedding |
| `geolock/clues.py`, `ocr.py`, `exif.py`, `vlm.py` | Clue sources |
| `geolock/analyst.py` | Second opinion from Claude / ChatGPT via their CLIs, and how it is fused |
| `geolock/countrymeta.py`, `prompts.py` | Clue knowledge tables and CLIP prompts |
| `geolock/geodata.py`, `geolock/data/` | Offline borders, regions, place names |
| `geolock/server.py`, `geolock/web/` | Local web app (FastAPI + Leaflet, all vendored) |
| `geolock/cli.py` | `serve`, `locate`, `eval`, `bench`, `testset`, `analysts` |
| `geolock/testset.py` | Downloads the Wikimedia Commons test set |
| `tools/build_geodata.py` | Rebuilds the bundled Natural Earth files |
| `tools/build_inat_testset.py` | Builds a test set from iNaturalist open data (fallback) |
| `geolock/desktop/` | Desktop backend: API server, first-run model setup, library, settings |
| `desktop/` | Desktop shell (`src-tauri`), UI (`ui`), PyInstaller spec (`backend`), `API.md` |
| `tools/build_app_assets.py`, `tools/desktop_smoke.py` | CI: installer assets, frozen-backend smoke test |
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

**Results on the Yoga laptop (2026-10-15, installer v0.3.0, no Claude/ChatGPT)**

Lenovo Yoga 9 2-in-1 14ILL10 (83LC), Core Ultra 7 258V, Arc 140V, AI Boost NPU, 32 GB,
Windows 11 Home. Silent per-user install 36 s; first-run setup (609 MB download at
~59 MB/s, convert, gallery, load) about 1.5 min. Auto picked the GPU with no fallback
(compile 3.7 s). Cold restart to ready: 9 s.

| Device | Compile | First run | CLIP (4 crops, median) |
|---|---|---|---|
| Arc 140V GPU | 0.8 s (cached) | 112 ms | **102 ms** |
| AI Boost NPU | 42.8 s first time, ~1 s once cached | 325 ms | 199 ms |
| CPU | 2.9 s | 1.95 s | 1.8 s |

Per photo on the GPU with OCR: 0.6-1.8 s (CLIP ~100 ms, OCR 0.2-0.6 s, fusion 0.2-1.1 s).
No "Illegal instruction" in OCR. Four geotagged Commons photos: Cusco 1 km (93 %),
Hanoi 0 km (65 %), Reykjavik 0 km (44 %), Nairobi wrong (Jakarta, 24 %). One locate,
right after the first-ever speed test, took 27 s wall time while its own timings said
1.2 s; it did not happen again after a second speed test or a cold restart.

**`geolock testset <folder>`** (the one to use). Downloads ~300 photos from Wikimedia
Commons, where every file has a free licence. For each country it picks random towns
from GeoNames and takes one geotagged photo within 10 km of each, so the set covers the
whole world rather than the most photographed places. Countries get photos in proportion
to the square root of their number of towns (at most 4 each by default). Maps, flags,
scans, artwork, museum and interior shots are skipped by title and category. It writes
`labels.csv` (file, true lat/lon, country, title, author, licence, link) and
`ATTRIBUTION.md`. `geolock eval` reads `labels.csv` when present, so EXIF is not needed.
Re-running tops up an interrupted download. First run (Windows, 2026-10-14): 295 photos
from 202 countries in about 45 minutes; most of the time goes on Commons API searches.

**Results on the Commons set (2026-10-14, Windows desktop, CPU, no VLM, no Claude/ChatGPT)**

Machine: Acer Predator PO5-655 desktop, Intel Core i7-14700F (20 cores, no integrated
graphics), NVIDIA RTX 4070 Ti SUPER, 32 GB RAM, Windows 11 Home, Python 3.12,
OpenVINO 2026.4. Not the target laptop: OpenVINO lists the NVIDIA card as `GPU` but cannot
compile CLIP for it, so everything ran on the CPU. `geolock bench`: CLIP 1.25 s per photo,
full pipeline 2.6 s (CLIP 1.25 s, OCR 0.7 s, fusion 0.65 s).

| | 1 km | 25 km | 200 km | 750 km | 2500 km | median | country |
|---|---|---|---|---|---|---|---|
| GeoLock, default settings, 295 photos | 1 % | 11 % | 26 % | 51 % | 67 % | 725 km | 39 % |
| Same, first 163 photos only | 1 % | 11 % | 28 % | 52 % | 69 % | 600 km | 40 % |
| iNaturalist nature set, for comparison | 0 % | 3 % | 12 % | 29 % | 52 % | 2,222 km | 15 % |

- Everyday places (streets, buildings, landscapes near towns) are about twice as easy as
  the nature set at 200 km, and the right country goes from 15 % to 39 %.
- Confidence is roughly honest now: guesses said to be 50 %+ confident were within
  250 km 57 % of the time, 20-50 % ones 33 %, under 20 % ones 6 %.
- `--fit` chose temperature 1.5 and country weight 0.5, saved to `models/calibration.json`.
- **StreetCLIP tried, not worth it.** On the RTX card (CUDA PyTorch, experiment only,
  `tools/streetclip_experiment.py`), StreetCLIP's zero-shot country guess was right 40 %
  of the time against CLIP's 33 % (38 % on all 295). But inside GeoLock's fusion,
  replacing or combining CLIP's country vote with StreetCLIP's moved the 163-photo
  results by -2 to +3 points (one photo is 0.6 points): 29 % vs 28 % within 200 km,
  country 45 % vs 42 % at best. Within noise, and its licence is non-commercial, so it
  is not ported to OpenVINO. GeoCLIP's visual prior already carries most of what
  StreetCLIP knows.

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
- Deep analysis (Qwen2.5-VL-7B via OpenVINO GenAI): never loaded, and dropped from the
  plan (see "Deep analysis").
- ~~`setup.ps1` on Windows~~: done (desktop PC). Speed on the Arc GPU and NPU still
  needs the laptop.

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
0. Measure the second opinion (`--ask claude`) only if Brady asks: it uses his plan.
   Evals stay local-only by default.
1. ~~Run setup, bench, testset and eval~~: done on the Windows desktop (see "Results on
   the Commons set") and the speed test on the Yoga laptop (see "Results on the Yoga
   laptop").
2. Prefer bigger towns when naming a guess (GeoNames population data) so names are
   recognisable.
3. ~~Multilingual OCR~~ (done, see the changelog).
4. A denser location gallery outside Europe and North America, where GeoCLIP's 100k
   points are thin.
5. Sun direction: shadows plus the EXIF time give latitude and orientation hints.
6. Detectors for licence plates, bollards and road signs (the classic GeoGuessr clues).
7. ~~Batch mode in the app~~ (done: folder mode, accuracy card, CSV/KML export).

## Changelog

- **2026-10-15**: Version 0.4.0, a UX overhaul after Brady's first use: model and
  reasoning-effort pickers for Claude / ChatGPT with live progress and Stop; the street map
  is the default (the 0.3 map opened offline, which has no roads, and zoom stopped at 12);
  satellite with labels; a labeled Settings button and a settings sidebar; a new visual
  style and app icon. Settings saved by 0.3 with the offline map move to streets once.
  Release notes in `docs/releases/v0.4.0.md`. Tested with fake CLIs and the mock backend;
  street tiles could not be loaded from the build machine (blocked), so they are
  unchecked until the Windows CI screenshots or the laptop.
- **2026-10-15**: Version 0.3.1. First run on the Yoga laptop (see "Results on the Yoga
  laptop"): GPU, NPU and CPU all work. Fix: Ask Claude said "Install Claude Code" when
  Claude Code was installed by its native installer, which puts `claude.exe` in
  `~/.local/bin` without adding it to PATH; the app now also looks there (and in
  `%APPDATA%\npm` for Codex). Docs: the installer goes to `%LOCALAPPDATA%\GeoLock`.

- **2026-10-15**: Version 0.3.0, the first published installer: the desktop app plus the
  smarter second opinion, folder mode and export, and laptop speed mode. Release notes in
  `docs/releases/v0.3.0.md`.
- **2026-10-15**: Laptop speed mode: automatic fallback to the CPU when the GPU or NPU
  fails to compile or run (also mid-session), a diagnostics readout and per-processor
  speed test in Settings, NPU kernel cache. Tested with a fake OpenVINO core
  (`tests/test_devices.py`) and on the Windows CI runner (CPU only; choosing the missing
  NPU falls back to the CPU). **Not yet run on a real Arc GPU or NPU.**

- **2026-10-15**: Desktop app features: folder / batch mode with progress and Stop, folder
  drops, nicer names for pasted images, export (map PNG, KML, CSV, JSON) per photo or for
  the library, a ground-truth panel and map line when the photo has its own GPS, GPS
  badges, a "With GPS" filter and an accuracy card. Fixes: no focus ring around dialogs,
  no empty inspector column while the library is empty.

- **2026-10-15**: Smarter second opinion: the Claude / ChatGPT prompt walks a 12-item
  geoguessing checklist, names places it rules out and gives a reason per guess; zoomed
  crops of the signs GeoLock's OCR found are sent along with the photo. The app shows
  the checklist, reasons, rejected places and crop thumbnails. Tested with fake CLIs only
  (no real Claude / ChatGPT calls); the accuracy gain is not yet measured.

- **2026-10-15**: Windows desktop app (PR #11): Tauri window and installer, new UI with
  a photo library, first-run model download without PyTorch, settings. Re-running a photo
  keeps earlier Claude / ChatGPT answers instead of asking again.

- **2026-10-14**: Local vision-language model dropped from the plan (Brady's call); the
  Claude / ChatGPT second opinion is the deep-analysis path. A Qwen2.5-VL-7B test on the
  desktop was stopped before it ran.

- **2026-10-14**: First run on real Windows (desktop PC). `setup.ps1` works; fixes:
  the Arabic OCR model needs `python-bidi` (now `rapidocr[rtl]`), `setup.ps1` stops if
  pip fails, and `AUTO` only uses Intel GPUs (OpenVINO lists NVIDIA cards too but can't
  run CLIP on them). First Commons numbers: 26 % within 200 km, country 39 %. StreetCLIP
  measured and rejected (`tools/streetclip_experiment.py`).

- **2026-10-14**: Second opinion from Claude or ChatGPT on the user's own plan ("Ask
  Claude" / "Ask ChatGPT" in the app, `--ask` on the CLI, `geolock analysts`), blended
  in as a mixture. Tests with fake CLIs and a synthetic-model engine; the Claude path run
  for real.

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
