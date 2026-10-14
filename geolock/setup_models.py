"""One-time model setup: download, convert to OpenVINO, precompute embeddings.

    python -m geolock.setup_models            # CLIP ViT-L/14 + GeoCLIP, FP16
    python -m geolock.setup_models --int8     # smaller / faster weights (tiny accuracy cost)
    python -m geolock.setup_models --vlm      # also export the optional vision-language model
    python -m geolock.setup_models --prompts-only   # after editing geolock/prompts.py

Needs internet once. Afterwards everything runs offline from the models directory.
"""
import argparse
import importlib.util
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

from .config import MODELS_DIR, CLIP_ID, VLM_ID, CROPS
from .geodata import GeoData
from .locenc import LocationEncoder, normalize
from . import prompts


def log(msg):
    print(f"[setup] {msg}", flush=True)


def geoclip_dir():
    spec = importlib.util.find_spec("geoclip")
    if spec is None or not spec.submodule_search_locations:
        sys.exit("The 'geoclip' package is missing. Run: pip install geoclip --no-deps")
    return Path(list(spec.submodule_search_locations)[0]) / "model"


def load_clip(random_init=False):
    import torch
    from transformers import CLIPConfig, CLIPModel, CLIPTokenizer
    if random_init:  # development only: same architecture, random weights
        log("using RANDOM CLIP weights (--random-clip): predictions will be meaningless")
        cfg = CLIPConfig(
            projection_dim=768,
            text_config=dict(hidden_size=768, intermediate_size=3072, num_attention_heads=12,
                             num_hidden_layers=12, projection_dim=768),
            vision_config=dict(hidden_size=1024, intermediate_size=4096, num_hidden_layers=24,
                               num_attention_heads=16, patch_size=14, image_size=224,
                               projection_dim=768))
        torch.manual_seed(0)
        model, tok = CLIPModel(cfg), None
    else:
        log(f"downloading {CLIP_ID} (~1.7 GB, first run only)")
        model = CLIPModel.from_pretrained(CLIP_ID)
        tok = CLIPTokenizer.from_pretrained(CLIP_ID)
    return model.eval(), tok


def export_vision(model, out_dir, int8):
    import torch
    import openvino as ov

    class Vision(torch.nn.Module):
        def __init__(self, clip):
            super().__init__()
            self.vm, self.proj = clip.vision_model, clip.visual_projection

        def forward(self, pixel_values):
            return self.proj(self.vm(pixel_values=pixel_values).pooler_output)

    log("converting CLIP vision encoder to OpenVINO")
    example = torch.zeros(CROPS, 3, 224, 224)
    with torch.no_grad():
        ov_model = ov.convert_model(Vision(model).eval(), example_input=example,
                                    input=[(CROPS, 3, 224, 224)])
    ov_model.inputs[0].get_tensor().set_names({"pixel_values"})
    ov_model.outputs[0].get_tensor().set_names({"image_embeds"})
    if int8:
        import nncf
        log("compressing weights to INT8")
        ov_model = nncf.compress_weights(ov_model)
    ov.save_model(ov_model, out_dir / "clip_vision.xml", compress_to_fp16=not int8)


def text_embeddings(model, tok, groups):
    import torch
    keys, embs = [], []
    log(f"embedding {sum(len(v) for v in groups.values())} text prompts")
    with torch.no_grad():
        for key, texts in groups.items():
            if tok is None:
                ids = torch.randint(1, 1000, (len(texts), 16))
                mask = torch.ones_like(ids)
            else:
                enc = tok(texts, padding=True, return_tensors="pt")
                ids, mask = enc["input_ids"], enc["attention_mask"]
            pooled = model.text_model(input_ids=ids, attention_mask=mask).pooler_output
            e = model.text_projection(pooled).numpy()
            keys.append(key)
            embs.append(normalize(normalize(e).mean(0)))
    return keys, np.stack(embs).astype(np.float32), float(model.logit_scale.detach().exp())


def build_geoclip(out_dir, geo):
    import torch
    src = geoclip_dir()
    log(f"loading GeoCLIP weights from {src}")
    mlp = torch.load(src / "weights/image_encoder_mlp_weights.pth", map_location="cpu",
                     weights_only=True)
    loc = torch.load(src / "weights/location_encoder_weights.pth", map_location="cpu",
                     weights_only=True)
    scale = torch.load(src / "weights/logit_scale_weights.pth", map_location="cpu",
                       weights_only=True)
    arrays = {"mlp.w1": mlp["0.weight"].numpy(), "mlp.b1": mlp["0.bias"].numpy(),
              "mlp.w2": mlp["2.weight"].numpy(), "mlp.b2": mlp["2.bias"].numpy(),
              "logit_scale": np.array(float(scale.exp()), dtype=np.float32)}
    arrays.update({f"loc.{k}": v.numpy() for k, v in loc.items()})
    np.savez(out_dir / "geoclip.npz", **arrays)

    gps = np.loadtxt(src / "gps_gallery/coordinates_100K.csv", delimiter=",", skiprows=1,
                     dtype=np.float32)
    log(f"embedding the {len(gps):,}-point GPS gallery")
    enc = LocationEncoder({k: v.numpy() for k, v in loc.items()})
    t = time.time()
    feats = normalize(enc(gps)).astype(np.float16)
    log(f"  done in {time.time() - t:.1f}s; tagging gallery points with countries")
    country = geo.countries.lookup(gps[:, 0], gps[:, 1]).astype(np.int16)
    np.savez(out_dir / "gallery.npz", gps=gps, feats=feats, country=country)


def export_vlm(out_dir, model_id):
    dest = out_dir / "vlm"
    cli = shutil.which("optimum-cli")
    cmd = ([cli] if cli else [sys.executable, "-m", "optimum.commands.optimum_cli"]) + [
        "export", "openvino", "--model", model_id, "--weight-format", "int4",
        "--trust-remote-code", str(dest)]
    log(f"exporting {model_id} to OpenVINO INT4 (several GB download, takes a while)")
    subprocess.run(cmd, check=True)
    return model_id


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--models-dir", type=Path, default=MODELS_DIR)
    ap.add_argument("--int8", action="store_true", help="INT8 weight compression for CLIP")
    ap.add_argument("--prompts-only", action="store_true", help="only recompute prompt embeddings")
    ap.add_argument("--vlm", nargs="?", const=VLM_ID, default=None, metavar="HF_ID",
                    help=f"also export a vision-language model (default {VLM_ID})")
    ap.add_argument("--vlm-only", action="store_true", help="only export the VLM")
    ap.add_argument("--random-clip", action="store_true", help=argparse.SUPPRESS)
    a = ap.parse_args(argv)

    out = a.models_dir
    out.mkdir(parents=True, exist_ok=True)
    manifest_path = out / "manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    geo = GeoData()

    if not a.vlm_only:
        model, tok = load_clip(a.random_clip)
        if not a.prompts_only:
            export_vision(model, out, a.int8)
            build_geoclip(out, geo)
            manifest.update(clip=CLIP_ID if not a.random_clip else "RANDOM",
                            precision="int8" if a.int8 else "fp16")
        keys, embs, clip_scale = text_embeddings(
            model, tok, prompts.all_prompt_lists(geo.country_names))
        np.savez(out / "prompts.npz", keys=np.array(keys), embs=embs,
                 clip_logit_scale=np.float32(clip_scale),
                 country_codes=np.array(geo.country_codes))
        manifest["prompts_updated"] = time.strftime("%Y-%m-%d %H:%M")
    if a.vlm or a.vlm_only:
        manifest["vlm"] = export_vlm(out, a.vlm or VLM_ID)
    manifest_path.write_text(json.dumps(manifest, indent=2))
    log(f"all set. Models are in {out}")


if __name__ == "__main__":
    main()
