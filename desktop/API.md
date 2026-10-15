# GeoLock desktop: backend API

The desktop app is three parts:

| Part | Where | What |
|---|---|---|
| Shell | `desktop/src-tauri/` | Tauri 2 (Rust). Opens the window, starts the backend, stops it on exit. |
| UI | `desktop/ui/` | React + TypeScript + Vite + MapLibre GL. Talks to the backend over HTTP. |
| Backend | `geolock/desktop/` | The existing Python engine behind FastAPI, frozen with PyInstaller into `geolock-backend.exe`. |

## How the shell starts the backend

1. The shell picks a free port on 127.0.0.1 and a random 32-character token.
2. It runs `geolock-backend.exe --port <port> --token <token> --data-dir <dir>` with no console
   window (`CREATE_NO_WINDOW`). `<dir>` is Tauri's app local data dir
   (`%LOCALAPPDATA%\com.geolock.desktop`). The backend's stdin is a pipe; the backend exits
   when it reads EOF, so it dies with the shell even after a crash.
3. The UI calls the Tauri command `backend_info` → `{ "url": "http://127.0.0.1:<port>",
   "token": "<token>", "dataDir": "<dir>", "logFile": "<path>" }` and polls `GET /api/status`
   until it answers.
4. On exit the shell kills the backend process.

Dev without Tauri: `python -m geolock.desktop --port 7861 --no-token` (real engine) or
`node desktop/ui/mock/server.mjs` (fake data, also on port 7861). The UI uses
`VITE_BACKEND_URL` (default `http://127.0.0.1:7861`) and no token when `window.__TAURI__`
is absent.

## Conventions

- Every `/api/*` request carries the header `X-GeoLock-Token: <token>`. URLs used in
  `<img src>` carry it as `?t=<token>` instead. `/data/*` needs no token.
- CORS allows `http://tauri.localhost`, `tauri://localhost`, `http://localhost:1420`
  and `http://127.0.0.1:1420`.
- Errors: HTTP 4xx/5xx with `{"detail": "human readable message"}`.
- Times are ISO 8601 UTC strings. Probabilities are 0..1. Distances are km.

## Status and first-run setup

### `GET /api/status`
```json
{
  "state": "needs_setup",          // needs_setup | setting_up | loading | ready | error
  "error": null,                   // message when state == "error"
  "version": "0.4.4",
  "device": "GPU",                 // where CLIP runs once loaded: GPU | NPU | CPU | null
  "device_name": "Intel(R) Arc(TM) 140V GPU (16GB)",
  "available_devices": ["CPU", "GPU", "NPU"],
  "diagnostics": {                 // null until the models are loaded
    "requested": "AUTO",           // the device setting
    "device": "GPU", "device_name": "Intel(R) Arc(TM) 140V GPU (16GB)",
    "compile_ms": 4200,            // preparing CLIP for the device
    "first_run_ms": 1900,          // first photo (one-off kernel set-up)
    "last_run_ms": 190,            // CLIP on the latest photo
    "runs": 3, "warmup_ms": 3100,
    "load_ms": 7400,               // compile + warm-up, until ready
    "last_locate": {"device": "GPU", "timings": {"clip_ms": 190, "total_ms": 1100}, "at": 1760000000.0},
    "fallback": null,              // one sentence when a device failed and GeoLock fell back
    "attempts": [{"device": "GPU", "step": "compile", "ok": true, "ms": 4200, "error": null}]
  },
  "analysts": {
    "claude":  {"available": true,  "via": "claude-code", "detail": "Claude Code, your Claude login"},
    "chatgpt": {"available": false, "via": null, "detail": "Install the Codex CLI and sign in (codex login) to use your ChatGPT plan."}
  },
  "data_dir": "C:\\Users\\Brady\\AppData\\Local\\com.geolock.desktop",
  "models_dir": "C:\\Users\\Brady\\AppData\\Local\\com.geolock.desktop\\models"
}
```
`loading` = models are on disk and being compiled for the device (10-60 s on first start,
a few seconds after that thanks to the OpenVINO cache).

If the chosen device fails to compile, fails while running, or returns NaN/infinity, CLIP
moves to the next device (Auto: GPU → NPU → CPU; a fixed choice: that device → CPU) and
the photo carries on; `diagnostics.fallback` says what happened.

### `POST /api/diagnostics/benchmark` → speed test, `GET` → the last one (`rows: []` if none)
Compiles CLIP on every device and times it (median of 3 runs). Waits for any running
analysis. Can take up to a minute the first time (NPU compilation).
```json
{"at": 1760000000.0, "rows": [
  {"device": "GPU", "name": "Intel(R) Arc(TM) 140V GPU (16GB)", "ok": true,
   "compile_ms": 3900, "first_run_ms": 1700, "ms": 185, "error": null},
  {"device": "NPU", "name": "Intel(R) AI Boost", "ok": false, "compile_ms": null,
   "first_run_ms": null, "ms": null, "error": "RuntimeError: [NPU] driver not found"}]}
```

### `GET /api/setup`
```json
{
  "ready": false,
  "running": false,
  "download_mb": 608,              // what "Download" will fetch
  "disk_needed_mb": 1400,          // peak disk use during setup
  "free_disk_mb": 412000,
  "source": "Hugging Face (Xenova/clip-vit-large-patch14, MIT licence)",
  "steps": [
    {"id": "download", "label": "Download the CLIP vision model", "state": "pending"},   // pending | running | done | error
    {"id": "convert",  "label": "Optimise it for your processor",  "state": "pending"},
    {"id": "gallery",  "label": "Build the map of 100,000 reference places", "state": "pending"},
    {"id": "load",     "label": "Load the models", "state": "pending"}
  ],
  "progress": {                    // null when not running
    "step": "download",
    "fraction": 0.42,              // 0..1 within this step, null if unknown
    "done_mb": 255.3, "total_mb": 608.0,
    "speed_mbps": 11.2,            // megabytes per second, download step only
    "eta_s": 31,
    "message": "Downloading… 255 of 608 MB"
  },
  "error": null
}
```

### `POST /api/setup/start`
Starts (or resumes) the download and setup in the background. Returns `GET /api/setup`.
A partial download resumes where it stopped.

### `POST /api/setup/cancel`
Stops a running setup; the partial download is kept for resuming.

### `POST /api/setup/import`  body `{"folder": "C:\\path\\to\\geolock\\models"}`
Uses models from an existing GeoLock install (the folder with `clip_vision.xml`). Copies
what is needed. 400 with a readable message if the folder is not a GeoLock models folder.

## Second opinion: models, progress, stop

### `GET /api/analysts/models` (`?refresh=true` to ask the CLIs again; cached 10 min)
```json
{"claude":  {"installed": true, "efforts": ["low", "medium", "high", "xhigh", "max"],
             "models": [{"id": "", "name": "Default", "description": "What Claude Code uses for your plan"},
                        {"id": "opus", "name": "Opus", "description": "The latest Opus model"}]},
 "chatgpt": {"installed": true, "efforts": ["low", "medium", "high", "xhigh", "max"],
             "models": [{"id": "", "name": "Default", "description": "What your Codex settings pick"},
                        {"id": "gpt-6.1-sol", "name": "GPT-6.1-Sol", "description": "…",
                         "efforts": ["low", "medium", "high", "xhigh", "max"], "default_effort": "low"}]}}
```
`id: ""` means the CLI's own default. The chosen model and effort are settings
(`claude_model`, `claude_effort`, `chatgpt_model`, `chatgpt_effort`; effort is `""` or
one of minimal, low, medium, high, xhigh, max) and apply to every ask.

### `GET /api/analysts/progress`
What the analysts of the current (or last) ask are doing. Polled by the UI while it waits.
```json
{"running": true, "now": 1760000012.3,
 "providers": {"claude": {"stage": "thinking", "started": 1760000003.1, "updated": 1760000012.1,
                          "model": "claude-opus-5-5", "effort": "high",
                          "note": "Reading the shop sign in the second crop", "chars": 2600, "error": null}}}
```
`stage`: preparing → starting → thinking → writing → done | error | stopped. `note` is the
latest line of the model's thinking when the CLI shares it (may be empty).

### `POST /api/analysts/stop` → `{"stopped": 1}`
Ends the running analysts (the CLI and its child processes). The ask then returns with that
analyst's earlier answer if the photo had one, else an answer with `ok: false, stopped: true`.

## Locating photos

### `POST /api/locate`  (multipart form)
| field | type | default | |
|---|---|---|---|
| `file` | file | required | JPEG, PNG, WebP, HEIC, TIFF, BMP |
| `name` | string | file name | shown in the library |
| `ocr` | bool | true | read text in the photo |
| `exif_gps` | bool | true | show the photo's own GPS (never used for the guess) |
| `ask` | string | "" | comma list of `claude`, `chatgpt`. **The UI never sends this unless the user clicked a second-opinion button for this photo.** |
| `share_local` | bool | true | send GeoLock's findings to the analyst along with the photo |

Returns a **Result** (below) and stores it in the library. Takes 1-5 s locally, plus
5-60 s per analyst. Requests are processed one at a time.

### Result
```json
{
  "id": "20261014-235501-a1b2c3",
  "name": "IMG_2041.jpg",
  "created": "2026-10-14T23:55:01Z",
  "image_url": "/api/history/20261014-235501-a1b2c3/image",   // add ?t=<token>
  "thumb_url": "/api/history/20261014-235501-a1b2c3/thumb",
  "image": {"width": 4032, "height": 3024},
  "options": {"ocr": true, "exif_gps": true, "ask": [], "share_local": true},
  "guesses": [
    {
      "lat": 48.85341, "lon": 2.3488,
      "confidence": 0.46,                    // share of probability within 250 km
      "label": "medium",                     // high (>=0.5) | medium (>=0.2) | low
      "radius_km": 38.5,                     // 68 % of this guess's probability is within it
      "visual_mass": 0.31,
      "country_code": "FR", "country": "France", "continent": "Europe",
      "region": "Île-de-France",
      "place": {"name": "Paris", "admin1": "Île-de-France", "cc": "FR", "km": 1.2},  // may be null
      "km_from_exif": 3.4,                   // only when the photo has GPS
      "why": [
        {"effect": 1,  "text": "Visual similarity (GeoCLIP) puts 31% of its weight in this area."},
        {"effect": 1,  "text": "CLIP's country classifier ranks France #1 (22%)."},
        {"effect": 1,  "text": "Text in French"},
        {"effect": -1, "text": "Traffic drives on the left"}
      ]                                      // effect: 1 supports, 0 neutral, -1 argues against
    }
  ],
  "countries": [{"code": "FR", "name": "France", "prob": 0.58, "clip_prob": 0.22}],
  "clues": [
    {"kind": "language", "title": "Text in French", "detail": "Language detector: 92% (\"boulangerie, rue…\").",
     "strength": 0.7, "countries": [{"code": "FR", "name": "France", "weight": 1.0}], "n_countries": 12}
  ],
  // kind: ocr | language | script | domain | phone | currency | units | scene | timezone | exif
  //       | claude | chatgpt | vlm ; strength 0 = shown only, no effect on the guess
  "scene": [{"attribute": "Setting", "value": "city street", "prob": 0.61}],
  "ocr": [{"text": "BOULANGERIE", "score": 0.97, "box": [[x,y],[x,y],[x,y],[x,y]], "model": "default"}],
  //   box is in original-image pixel coordinates (4 corners)
  "analysts": [
    {"provider": "claude", "name": "Claude", "via": "Claude Code, your Claude login", "ok": true,
     "error": null, "model": "claude-opus-5-5", "effort": "high", "ms": 8400,
     "reasoning": "Haussmann façades, Paris street signs…",
     "checklist": [{"category": "signs", "label": "Signs",
                    "seen": "Blue enamel street plate", "suggests": "Paris"}],
     //   category: driving_side | road_markings | signs | bollards | plates | poles
     //             | script_language | architecture | vegetation | terrain_soil | sun_climate | other
     //   absent on answers saved before 2026-10-15 (they only have "clues")
     "ruled_out": [{"place": "Brussels", "why": "Signs would be bilingual"}],
     "crops": [{"box": [330, 700, 1880, 950], "text": "BOULANGERIE"}],
     //   zoomed crops sent with the photo: [x0, y0, x1, y1] in result-image pixels, OCR text
     "clues": [{"clue": "Signs: Blue enamel street plate", "suggests": "Paris"}],  // flat list
     "driving_side": "right", "text_seen": "Rue de Rivoli",
     "guesses": [{"place": "Rue de Rivoli, Paris", "country": "France", "iso2": "FR",
                  "lat": 48.8606, "lon": 2.3376, "radius_km": 2, "confidence": 0.7,
                  "why": "The street sign names Rue de Rivoli", "km_from_exif": 1.1}]}
  ],
  "heat": [[48.85, 2.35, 1.0], [45.76, 4.83, 0.31]],   // [lat, lon, weight 0..1], up to 1500 points
  "exif": {"camera": "Apple iPhone 15", "datetime": "2026:07:03 14:22:10", "utc_offset": "+02:00",
           "gps": {"lat": 48.8530, "lon": 2.3499}},
  "exif_gps": {"lat": 48.8530, "lon": 2.3499},          // null unless shown
  "exif_place": {"country": "France", "region": "Île-de-France", "place": {"name": "Paris"}},
  "device": "GPU",
  "timings": {"clip_ms": 210, "ocr_ms": 640, "fusion_ms": 380, "llm_ms": 8400, "total_ms": 9700}
}
```

## Library (history)

Results are kept in `<data-dir>/history/` with a 2048 px copy of the photo (EXIF kept so a
re-run still sees the camera clock and GPS) and a 320 px thumbnail.

### `GET /api/history` → newest first
```json
[{"id": "…", "name": "IMG_2041.jpg", "created": "…", "thumb_url": "/api/history/…/thumb",
  "top": {"lat": 48.85, "lon": 2.35, "confidence": 0.46, "label": "medium",
          "country": "France", "country_code": "FR", "place": "Paris", "region": "Île-de-France"},
  "analysts": ["claude"], "has_exif_gps": true, "km_from_exif": 3.4}]
```

### `GET /api/history/{id}` → Result
### `DELETE /api/history/{id}` → `{"ok": true}`
### `DELETE /api/history` → clears everything, `{"ok": true, "deleted": 12}`
### `POST /api/history/{id}/rerun`  (form: `ocr`, `exif_gps`, `ask`, `share_local`) → Result
Re-analyses the stored photo (same id). This is how "Ask Claude" / "Ask ChatGPT" on an
existing photo works. Earlier analyst answers are kept unless that analyst is asked again.
### `GET /api/history/{id}/image` and `/thumb` → JPEG

## Export

### `POST /api/save`  (multipart: `path`, `file`) → `{"path": "C:\\…\\paris-geolock.kml", "bytes": 5321}`
Writes an export the UI built (JSON, CSV, KML or a PNG of the map) to the path the user
picked in the native Save dialog. `path` must be absolute, end in `.json`, `.csv`, `.kml`
or `.png`, and be in a folder that exists; otherwise 400 with a readable message. In the
browser dev mode the UI downloads the file instead and never calls this.

## Settings

### `GET /api/settings`, `PUT /api/settings` (JSON body with any subset) → full settings
```json
{
  "device": "AUTO",            // AUTO | GPU | NPU | CPU; change reloads the models (state -> loading)
  "read_text": true,           // default for the ocr option
  "show_exif_gps": true,
  "share_findings": true,      // default for share_local when asking an analyst
  "analyst_web_search": true,  // Claude/ChatGPT may search the web to check what they read
  "osm_lookup": false,         // look up text read in the photo on OpenStreetMap (text only)
  "keep_history": true,        // false: results are not stored (the current session still shows them)
  "theme": "system",           // system | light | dark (the UI applies it)
  "map_style": "streets",      // streets | satellite | offline (the map shown; offline is the automatic fallback)
  "claude_model": "",          // "" = the CLI's default, else an id from /api/analysts/models
  "claude_effort": "",         // "" | minimal | low | medium | high | xhigh | max
  "chatgpt_model": "",
  "chatgpt_effort": "",
  "check_updates": true,       // the UI calls POST /api/update/check once at startup
  "settings_rev": 2            // read-only; 0.3 settings with map_style "offline" are moved to "streets" once
}
```
There is deliberately **no** setting that asks Claude or ChatGPT automatically.

### `POST /api/analysts/refresh` → `{"claude": {...}, "chatgpt": {...}}` (re-checks logins)

## Updates

Each release carries `latest.json` next to the installer (written by CI with
`tools/update_manifest.py`): version, notes (markdown), and the installer's name, GitHub
URL, size and SHA-256. The backend reads it from the newest release
(`https://github.com/Subterfugus/geolock/releases/latest/download/latest.json`).

### `GET /api/update` → the current state; `POST /api/update/check` → checks, then the state
```json
{
  "state": "available",        // idle | checking | up_to_date | available | downloading | ready | error
  "current": "0.4.4", "latest": "0.5.0", "notes": "markdown", "published_at": "2026-10-20T12:00:00Z",
  "size_mb": 398, "free_disk_mb": 212000,
  "progress": null,            // while downloading: {fraction, done_mb, total_mb, speed_mbps, eta_s}
  "installer_path": null,      // when ready: <data dir>\updates\GeoLock_0.5.0_x64-setup.exe
  "error": null, "checked_at": 1760529600, "releases_url": "https://github.com/Subterfugus/geolock/releases"
}
```
The check downloads only the manifest. A finished, checksum-verified download from an
earlier run is found again (`ready`). Installers for this version or older are deleted at
startup.

### `POST /api/update/download` → starts (or resumes) the download; poll `GET /api/update`
### `POST /api/update/cancel` → stops it; the partial file is kept for a resume

Installing is the shell's job: the UI invokes `install_update {path}`. The shell accepts
only a `*-setup.exe` directly in `<data dir>\updates`, stops the backend, runs the
installer with `/P /UPDATE /R` (progress window, no questions, keeps shortcuts, starts
GeoLock again) and exits.

## Static data
`GET /data/countries.geojson` (242 countries; properties `iso2, name, continent, subregion,
lx, ly, minlabel` where `lx/ly` is the label point and `minlabel` the zoom to show it at) and
`GET /data/admin1.geojson` (4,596 states/provinces, 3.6 MB; properties include `name`).
