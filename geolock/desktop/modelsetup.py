"""First-run model setup for the desktop app, without PyTorch.

The installer carries everything small (GeoCLIP weights, the GPS gallery coordinates, the
CLIP text-prompt embeddings, the OCR models). What it does not carry is the CLIP ViT-L/14
vision encoder (~600 MB), which is downloaded once from Hugging Face as ONNX and converted
to OpenVINO here. The bundled `assets.json` pins the exact file (commit, size, SHA-256);
CI writes it after checking that the ONNX model gives the same embeddings as the original
PyTorch model (tools/build_app_assets.py).

Steps: download -> convert (ONNX -> OpenVINO IR, fixed batch, FP16) -> gallery (embed the
100k GPS points with the GeoCLIP location encoder, tag countries) -> load (the app's job).
"""
import hashlib
import json
import os
import shutil
import sys
import threading
import time
import urllib.request
from pathlib import Path

import numpy as np

from ..config import CROPS

REQUIRED = ("clip_vision.xml", "clip_vision.bin", "geoclip.npz", "gallery.npz", "prompts.npz")
BUNDLED_FILES = ("geoclip.npz", "prompts.npz", "calibration.json")


def bundled_dir():
    """Where the build put the small assets (geolock/desktop/bundled in a source checkout)."""
    env = os.environ.get("GEOLOCK_BUNDLED")
    if env:
        return Path(env)
    return Path(__file__).resolve().parent / "bundled"


def load_assets():
    p = bundled_dir() / "assets.json"
    return json.loads(p.read_text()) if p.exists() else {}


def models_ready(models_dir):
    md = Path(models_dir)
    if not all((md / f).exists() for f in REQUIRED):
        return False
    try:  # prompts must match the bundled country list, else they're from an older version
        from ..geodata import GeoData
        p = np.load(md / "prompts.npz")
        return p["country_codes"].tolist() == GeoData().country_codes
    except Exception:
        return False


class Cancelled(Exception):
    pass


class ModelSetup:
    """Runs the setup in a background thread and reports progress for the UI."""

    STEPS = [("download", "Download the CLIP vision model"),
             ("convert", "Optimise it for your processor"),
             ("gallery", "Build the map of 100,000 reference places"),
             ("load", "Load the models")]

    def __init__(self, models_dir, on_ready=None):
        self.models_dir = Path(models_dir)
        self.on_ready = on_ready  # called after a successful setup (loads the engine)
        self.assets = load_assets()
        self.lock = threading.Lock()
        self.thread = None
        self.cancel_flag = threading.Event()
        self.error = None
        self.state = {k: "pending" for k, _ in self.STEPS}
        self.progress = None

    # ------------------------------------------------------------------ report
    @property
    def running(self):
        return self.thread is not None and self.thread.is_alive()

    def model_info(self):
        return self.assets.get("clip_vision_onnx") or {}

    def report(self):
        info = self.model_info()
        size_mb = round(info.get("size", 0) / 1e6) if info.get("size") else None
        self.models_dir.mkdir(parents=True, exist_ok=True)
        free = shutil.disk_usage(self.models_dir).free
        ready = models_ready(self.models_dir)
        steps = []
        for k, label in self.STEPS:
            st = "done" if ready else self.state[k]
            steps.append({"id": k, "label": label, "state": st})
        return {
            "ready": ready, "running": self.running,
            "download_mb": size_mb,
            # ONNX file + IR (FP16, same size) + gallery (~100 MB), before the ONNX is deleted
            "disk_needed_mb": round((size_mb or 600) * 2 + 120),
            "free_disk_mb": round(free / 1e6),
            "source": info.get("source", "Hugging Face"),
            "steps": steps, "progress": self.progress, "error": self.error,
            "bundled": bool(self.assets),
        }

    def _set(self, step, state, **progress):
        self.state[step] = state
        if state == "running":
            self.progress = {"step": step, "fraction": None, "done_mb": None, "total_mb": None,
                             "speed_mbps": None, "eta_s": None, "message": "", **progress}
        elif self.progress and self.progress.get("step") == step:
            self.progress = None

    def _prog(self, **kw):
        if self.progress is not None:
            self.progress.update(kw)
        if self.cancel_flag.is_set():
            raise Cancelled()

    # ------------------------------------------------------------------- start
    def start(self):
        with self.lock:
            if self.running:
                return
            if not self.assets:
                self.error = ("This build has no bundled model information. Use models from an "
                              "existing GeoLock folder instead.")
                return
            self.error = None
            self.cancel_flag.clear()
            self.state = {k: "pending" for k, _ in self.STEPS}
            self.thread = threading.Thread(target=self._run, daemon=True, name="model-setup")
            self.thread.start()

    def cancel(self):
        self.cancel_flag.set()

    def _run(self):
        step = "download"
        try:
            md = self.models_dir
            md.mkdir(parents=True, exist_ok=True)
            self._copy_bundled()
            if not (md / "clip_vision.xml").exists():
                step = "download"
                self._set(step, "running", message="Connecting…")
                onnx = self._download()
                self._set(step, "done")
                step = "convert"
                self._set(step, "running", message="Converting to OpenVINO…")
                convert_onnx(onnx, md)
                onnx.unlink(missing_ok=True)
                self._set(step, "done")
            else:
                self._set("download", "done")
                self._set("convert", "done")
            step = "gallery"
            if not (md / "gallery.npz").exists():
                self._set(step, "running", message="Embedding 100,000 places…")
                build_gallery(md, bundled_dir(), progress=lambda f: self._prog(fraction=f))
            self._set(step, "done")
            step = "load"
            self._set(step, "running", message="Loading the models…")
            if self.on_ready:
                self.on_ready()
            self._set(step, "done")
        except Cancelled:
            self.state[step] = "pending"
            self.progress = None
            self.error = None
        except Exception as e:
            self.state[step] = "error"
            self.progress = None
            self.error = _friendly(e)
            print(f"[setup] {step} failed: {type(e).__name__}: {e}", file=sys.stderr, flush=True)

    def _copy_bundled(self):
        src = bundled_dir()
        for f in BUNDLED_FILES:
            if (src / f).exists() and not (self.models_dir / f).exists():
                shutil.copy2(src / f, self.models_dir / f)
        man = self.models_dir / "manifest.json"
        if not man.exists():
            man.write_text(json.dumps({"clip": self.model_info().get("repo", "openai/clip-vit-large-patch14"),
                                       "precision": "fp16", "source": "desktop"}, indent=2))

    def _download(self):
        info = self.model_info()
        tmp = self.models_dir / ".download"
        tmp.mkdir(exist_ok=True)
        dest = tmp / "clip_vision.onnx"
        part = tmp / "clip_vision.onnx.part"
        if dest.exists() and dest.stat().st_size == info["size"]:
            return dest
        total = int(info["size"])
        have = part.stat().st_size if part.exists() else 0
        if have > total:
            part.unlink()
            have = 0
        urls = [info["url"]] + list(info.get("mirrors", []))
        last_err = None
        for url in urls:
            try:
                self._fetch(url, part, have, total)
                break
            except Cancelled:
                raise
            except Exception as e:
                last_err = e
                have = part.stat().st_size if part.exists() else 0
        else:
            raise last_err
        self._prog(message="Checking the download…", fraction=1.0)
        if info.get("sha256") and sha256(part) != info["sha256"]:
            part.unlink()
            raise RuntimeError("The downloaded model is corrupted (checksum mismatch). Try again.")
        part.replace(dest)
        return dest

    def _fetch(self, url, part, have, total):
        req = urllib.request.Request(url, headers={"User-Agent": "GeoLock-desktop"})
        if have:
            req.add_header("Range", f"bytes={have}-")
        t0, done0 = time.time(), have
        with urllib.request.urlopen(req, timeout=60) as r:
            if have and r.status != 206:  # server ignored the range: start over
                have = done0 = 0
            with open(part, "ab" if have else "wb") as f:
                while True:
                    chunk = r.read(1 << 20)
                    if not chunk:
                        break
                    f.write(chunk)
                    have += len(chunk)
                    dt = max(time.time() - t0, 1e-3)
                    speed = (have - done0) / dt
                    self._prog(fraction=have / total, done_mb=round(have / 1e6, 1),
                               total_mb=round(total / 1e6, 1), speed_mbps=round(speed / 1e6, 2),
                               eta_s=round((total - have) / speed) if speed > 0 else None,
                               message=f"Downloading… {have / 1e6:.0f} of {total / 1e6:.0f} MB")
        if have < total:
            raise RuntimeError(f"Download stopped early ({have / 1e6:.0f} of {total / 1e6:.0f} MB).")

    # ------------------------------------------------------------------ import
    def import_folder(self, folder):
        """Copy the models from an existing GeoLock install (its `models` folder)."""
        src = Path(folder)
        if (src / "models" / "clip_vision.xml").exists():
            src = src / "models"
        missing = [f for f in ("clip_vision.xml", "clip_vision.bin", "geoclip.npz") if not (src / f).exists()]
        if missing:
            raise ValueError(f"{src} is not a GeoLock models folder (missing {', '.join(missing)}).")
        if self.running:
            raise ValueError("Setup is already running.")
        md = self.models_dir
        md.mkdir(parents=True, exist_ok=True)
        for f in ("clip_vision.xml", "clip_vision.bin", "geoclip.npz", "gallery.npz",
                  "calibration.json", "manifest.json"):
            if (src / f).exists():
                shutil.copy2(src / f, md / f)
        # Prompt embeddings: the bundled ones match this version's country list.
        bund = bundled_dir() / "prompts.npz"
        if bund.exists():
            shutil.copy2(bund, md / "prompts.npz")
        elif (src / "prompts.npz").exists():
            shutil.copy2(src / "prompts.npz", md / "prompts.npz")
        self.start_finish()

    def start_finish(self):
        """Run the remaining steps (gallery, load) in the background."""
        with self.lock:
            if self.running:
                return
            self.error = None
            self.cancel_flag.clear()
            # clip_vision.xml exists now, so _run skips the download and conversion
            self.thread = threading.Thread(target=self._run, daemon=True, name="model-setup")
            self.thread.start()


def _friendly(e):
    import urllib.error
    if isinstance(e, urllib.error.HTTPError):
        return f"The download server answered {e.code} {e.reason}. Try again later."
    if isinstance(e, (urllib.error.URLError, TimeoutError, ConnectionError)):
        return "Could not reach Hugging Face. Check the internet connection and try again."
    if isinstance(e, OSError) and getattr(e, "errno", None) == 28:
        return "The disk is full. Free some space and try again."
    return f"{type(e).__name__}: {e}"


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 22), b""):
            h.update(chunk)
    return h.hexdigest()


def convert_onnx(onnx_path, out_dir):
    """ONNX CLIP vision model (CLIPVisionModelWithProjection export) -> clip_vision.xml with a
    fixed (CROPS, 3, 224, 224) float32 input `pixel_values` and float32 output `image_embeds`."""
    import openvino as ov
    from openvino.preprocess import PrePostProcessor

    model = ov.convert_model(str(onnx_path))
    out = None
    for o in model.outputs:
        if "image_embeds" in o.get_names():
            out = o
    if out is None:  # single-output export
        out = model.outputs[0]
    model = ov.Model([out], model.get_parameters(), "clip_vision")
    model.reshape({model.inputs[0]: ov.PartialShape([CROPS, 3, 224, 224])})
    ppp = PrePostProcessor(model)
    ppp.input().tensor().set_element_type(ov.Type.f32)
    ppp.output().tensor().set_element_type(ov.Type.f32)
    model = ppp.build()
    model.inputs[0].get_tensor().set_names({"pixel_values"})
    model.outputs[0].get_tensor().set_names({"image_embeds"})
    tmp = Path(out_dir) / "clip_vision.tmp.xml"
    ov.save_model(model, tmp, compress_to_fp16=True)
    # rename only when complete, so a crash never leaves a half-written model behind
    tmp.with_suffix(".bin").replace(Path(out_dir) / "clip_vision.bin")
    xml = tmp.read_text(encoding="utf-8").replace("clip_vision.tmp.bin", "clip_vision.bin")
    (Path(out_dir) / "clip_vision.xml").write_text(xml, encoding="utf-8")
    tmp.unlink()


def build_gallery(models_dir, bundled, progress=None):
    """gallery.npz: the 100k GeoCLIP GPS points, their location embeddings and countries."""
    from ..geodata import GeoData
    from ..locenc import LocationEncoder, normalize
    md = Path(models_dir)
    g = np.load(md / "geoclip.npz")
    enc = LocationEncoder({k[4:]: g[k] for k in g.files if k.startswith("loc.")})
    src = Path(bundled) / "gallery_gps.npy"
    gps = np.load(src).astype(np.float32)
    feats = np.zeros((len(gps), enc(gps[:1]).shape[1]), dtype=np.float16)
    step = 5000
    for i in range(0, len(gps), step):
        feats[i:i + step] = normalize(enc(gps[i:i + step])).astype(np.float16)
        if progress:
            progress(min(1.0, (i + step) / len(gps)) * 0.9)
    country = GeoData().countries.lookup(gps[:, 0], gps[:, 1]).astype(np.int16)
    if progress:
        progress(1.0)
    tmp = md / "gallery.tmp.npz"
    np.savez(tmp, gps=gps, feats=feats, country=country)
    tmp.replace(md / "gallery.npz")
