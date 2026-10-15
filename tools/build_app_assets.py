"""Build the small model assets the desktop installer carries (run in CI, needs PyTorch).

    pip install torch transformers huggingface_hub onnx openvino && pip install geoclip --no-deps
    python tools/build_app_assets.py [--out geolock/desktop/bundled]

Writes:
  geoclip.npz        GeoCLIP image MLP + location encoder weights (MIT)
  gallery_gps.npy    GeoCLIP's 100k GPS gallery coordinates (embedded on first run)
  prompts.npz        CLIP ViT-L/14 text embeddings of GeoLock's prompts
  calibration.json   fusion settings fitted on the Commons test set (info.md)
  assets.json        the CLIP vision model the app downloads on first run: a pinned
                     Hugging Face URL, size and SHA-256

Before writing assets.json it checks that the ONNX export gives the same image embeddings
as the PyTorch model, after the same conversion the app does (cosine > 0.999), so a broken
or different export can't reach users.
"""
import argparse
import hashlib
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from geolock import prompts  # noqa: E402
from geolock.config import CLIP_ID, CROPS  # noqa: E402
from geolock.geodata import GeoData  # noqa: E402
from geolock.setup_models import geoclip_dir, load_clip, text_embeddings  # noqa: E402

ONNX_REPO = "Xenova/clip-vit-large-patch14"
ONNX_FILES = ["onnx/vision_model_fp16.onnx", "onnx/vision_model.onnx"]  # first one found wins
# Fitted with `geolock eval --fit` on 295 Commons photos (info.md, 2026-10-14).
CALIBRATION = {"temperature": 1.5, "country_weight": 0.5, "analyst_weight": 0.75}


def log(msg):
    print(f"[assets] {msg}", flush=True)


def geoclip_assets(out):
    import torch
    src = geoclip_dir()
    load = lambda p: torch.load(src / p, map_location="cpu", weights_only=True)  # noqa: E731
    mlp = load("weights/image_encoder_mlp_weights.pth")
    loc = load("weights/location_encoder_weights.pth")
    scale = load("weights/logit_scale_weights.pth")
    arrays = {"mlp.w1": mlp["0.weight"].numpy(), "mlp.b1": mlp["0.bias"].numpy(),
              "mlp.w2": mlp["2.weight"].numpy(), "mlp.b2": mlp["2.bias"].numpy(),
              "logit_scale": np.array(float(scale.exp()), dtype=np.float32)}
    arrays.update({f"loc.{k}": v.numpy() for k, v in loc.items()})
    np.savez(out / "geoclip.npz", **arrays)
    gps = np.loadtxt(src / "gps_gallery/coordinates_100K.csv", delimiter=",", skiprows=1,
                     dtype=np.float32)
    np.save(out / "gallery_gps.npy", gps)
    log(f"GeoCLIP weights and {len(gps):,} gallery points written")


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 22), b""):
            h.update(chunk)
    return h.hexdigest()


def vision_check(model, onnx_path, tmp):
    """Same embeddings from the ONNX model (converted like the app does) as from PyTorch?"""
    import openvino as ov
    import torch
    from PIL import Image
    from geolock.desktop.modelsetup import convert_onnx
    from geolock.engine import make_crops
    convert_onnx(onnx_path, tmp)
    compiled = ov.Core().compile_model(tmp / "clip_vision.xml", "CPU")
    rng = np.random.default_rng(0)
    worst = 1.0
    for i in range(3):
        arr = (rng.random((300 + 40 * i, 400, 3)) * 255).astype(np.uint8)
        arr[: 150] = [70 + 50 * i, 130, 200]  # some structure: a "sky"
        x = make_crops(Image.fromarray(arr))
        ov_emb = np.asarray(compiled(x)[0], dtype=np.float32)
        with torch.no_grad():
            pt = model.visual_projection(model.vision_model(pixel_values=torch.from_numpy(x)).pooler_output).numpy()
        cos = (ov_emb * pt).sum(1) / (np.linalg.norm(ov_emb, axis=1) * np.linalg.norm(pt, axis=1))
        worst = min(worst, float(cos.min()))
    log(f"ONNX vs PyTorch image embeddings: worst cosine {worst:.6f}")
    if worst < 0.999:
        sys.exit(f"The ONNX vision model does not match PyTorch (cosine {worst:.5f}).")
    assert compiled.inputs[0].get_partial_shape().to_shape() == [CROPS, 3, 224, 224]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, default=ROOT / "geolock" / "desktop" / "bundled")
    ap.add_argument("--work", type=Path, default=ROOT / "build" / "assets-work")
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    a.work.mkdir(parents=True, exist_ok=True)

    geoclip_assets(a.out)
    model, tok = load_clip()
    geo = GeoData()
    keys, embs, clip_scale = text_embeddings(model, tok, prompts.all_prompt_lists(geo.country_names))
    np.savez(a.out / "prompts.npz", keys=np.array(keys), embs=embs,
             clip_logit_scale=np.float32(clip_scale), country_codes=np.array(geo.country_codes))
    (a.out / "calibration.json").write_text(json.dumps(CALIBRATION, indent=2))
    log(f"{len(keys)} prompt embeddings written")

    from huggingface_hub import HfApi, hf_hub_download
    info = HfApi().model_info(ONNX_REPO, files_metadata=True)
    names = {s.rfilename: s for s in info.siblings}
    fname = next(f for f in ONNX_FILES if f in names)
    path = Path(hf_hub_download(ONNX_REPO, fname, revision=info.sha, cache_dir=a.work / "hf"))
    vision_check(model, path, a.work)
    digest = sha256(path)
    size = path.stat().st_size
    url = f"https://huggingface.co/{ONNX_REPO}/resolve/{info.sha}/{fname}"
    assets = {"clip_vision_onnx": {
        "url": url, "mirrors": [url.replace("https://huggingface.co/", "https://hf-mirror.com/")],
        "size": size, "sha256": digest, "repo": CLIP_ID, "onnx_repo": ONNX_REPO, "file": fname,
        "revision": info.sha, "licence": "MIT",
        "source": f"Hugging Face ({ONNX_REPO}, MIT licence)"}}
    (a.out / "assets.json").write_text(json.dumps(assets, indent=2))
    log(f"assets.json: {fname} @ {info.sha[:10]}, {size / 1e6:.0f} MB, sha256 {digest[:12]}…")


if __name__ == "__main__":
    main()
