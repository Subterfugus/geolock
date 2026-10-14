# GeoLock

Drop in a photo; GeoLock tells you where on Earth it was most likely taken, how sure it
is, and why. It runs entirely on your laptop with OpenVINO (Intel Arc GPU, NPU or CPU).
No cloud, no API keys, no subscriptions.

![Ranked guesses on a map, a confidence for each, and the clues behind them](docs/screenshot.png)

<sub>UI preview from a test sign, rendered with placeholder model weights, so the visual-similarity numbers in it are meaningless; the text clues are real.</sub>

## Quick start (Windows)

1. Install [Python 3.12](https://www.python.org/downloads/) (tick "Add python.exe to PATH").
2. Open PowerShell in this folder and run:

   ```powershell
   Set-ExecutionPolicy -Scope Process Bypass
   .\setup.ps1          # one time: ~2.5 GB download, 5-10 minutes
   ```

   Options: `-Int8` for smaller, faster CLIP weights; `-Vlm` to also install the
   optional deep-analysis model (another ~6 GB, see below).
3. Double-click `run.bat` (or `.venv\Scripts\python -m geolock`). The app opens at
   <http://127.0.0.1:7860>. Drag a photo onto it, or paste one with Ctrl+V.

After setup, nothing needs the internet. The "OpenStreetMap" map layer (top right of
the map) is the only optional online feature; the default offline map is built in.

Linux/macOS: `./setup.sh` then `.venv/bin/python -m geolock`.

## What it shows

- **Up to five guesses** on the map, numbered and coloured by confidence, each with a
  circle for its likely radius and the nearest named place.
- **Confidence** for each guess: the share of the model's probability that falls within
  ~250 km of it. High ≥ 50 %, medium ≥ 20 %, low below that.
- **Country odds**, with CLIP's opinion alone on hover.
- **Clues**: text read in the photo (Latin, Cyrillic, Greek, Chinese, Japanese, Korean,
  Thai, Arabic, Devanagari, Tamil, Telugu) and its language, web domains, phone prefixes,
  currency signs, mph signs, writing system, architecture and road-marking hints, EXIF
  time zone, and with deep analysis the model's own observations (driving side, plates,
  bollards, vegetation and so on). Each guess lists which clues back it (✓) or argue
  against it (✗).
- A **heatmap** of everywhere the model considered, and the photo's own **EXIF GPS**
  (★) when present so you can check the answer.

## Command line

```bash
geolock locate photo.jpg [--json] [--vlm]   # print guesses
geolock eval ~/Pictures/trips --fit         # accuracy on your own geotagged photos,
                                            # and tune confidence to match them
geolock bench                               # model speed on this machine
geolock --device NPU serve                  # pick a device (AUTO, GPU, NPU, CPU)
```

`geolock eval` hides each photo's EXIF GPS from the model, predicts, and reports how
often it lands within 1 / 25 / 200 / 750 / 2500 km and whether the confidence levels are
honest. It is the best way to see how well GeoLock does on the kind of photos you take.
With `--fit` (20+ photos) it also tunes the fusion so the confidence numbers match how
often it is actually right, and the app uses those settings from then on.

HEIC photos from iPhones work too.

## How it works

See [info.md](info.md) for the full design, model choices and status.

## Licences

GeoLock's code is MIT. Models and data have their own (all free and open); see
[THIRD_PARTY.md](THIRD_PARTY.md).
