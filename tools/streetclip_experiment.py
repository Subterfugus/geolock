"""Experiment: does StreetCLIP's country classifier beat CLIP's inside GeoLock's fusion?

StreetCLIP (geolocal/StreetCLIP, CC BY-NC 4.0) is CLIP ViT-L/14-336 fine-tuned for
geolocation. It is NOT a product dependency (non-commercial licence); this only measures
it on a test set so we know whether it is worth porting to OpenVINO.

Step 1, in a PyTorch venv (CUDA if you have it; no geolock install needed):
    python tools/streetclip_experiment.py embed data/testset models/streetclip_testset.npz \
        --countries models/country_names.json
Step 2, in GeoLock's own venv:
    python tools/streetclip_experiment.py names models/country_names.json   # before step 1
    python tools/streetclip_experiment.py eval data/testset models/streetclip_testset.npz

`eval` runs GeoLock on every photo with CLIP's zero-shot country probabilities replaced
by StreetCLIP's (and with both multiplied), at several country weights, and prints the
same accuracy table as `geolock eval`. The "+ regions" variants also add StreetCLIP's
state/province guess ("A Street View photo in Bavaria, Germany.") as a clue over the
first-level regions (admin1) of the map, which plain CLIP never had.
"""
import argparse
import csv
import json
import sys
from pathlib import Path

import numpy as np

STREETCLIP_ID = "geolocal/StreetCLIP"
THRESHOLDS = [1, 25, 200, 750, 2500]


def read_labels(folder):
    with open(Path(folder) / "labels.csv", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def cmd_names(a):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from geolock.geodata import GeoData
    geo = GeoData()
    names = dict(zip(geo.country_codes, geo.country_names))
    regions = [{"iso2": p.get("iso2"), "name": p.get("name"),
                "country": names.get(p.get("iso2"), "")} for p in geo.admin1.props]
    Path(a.out).write_text(json.dumps({"codes": geo.country_codes, "names": geo.country_names,
                                       "regions": regions}))
    print(f"{len(geo.country_codes)} countries, {len(regions)} regions -> {a.out}")


def _feats(out):
    """get_*_features returns a tensor in transformers 4 and an output object in 5."""
    return out if hasattr(out, "norm") else out.pooler_output


def cmd_embed(a):
    import torch
    from PIL import Image
    from transformers import CLIPModel, CLIPProcessor
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    meta = json.loads(Path(a.countries).read_text())
    model = CLIPModel.from_pretrained(STREETCLIP_ID).to(dev).eval()
    proc = CLIPProcessor.from_pretrained(STREETCLIP_ID)
    # The StreetCLIP paper's prompt.
    texts = [f"A Street View photo in {n}." for n in meta["names"]]
    region_texts = [f"A Street View photo in {r['name']}, {r['country']}." if r["country"]
                    else f"A Street View photo in {r['name']}." for r in meta.get("regions", [])]

    def encode(texts):
        out = []
        for i in range(0, len(texts), 256):
            t = proc(text=texts[i:i + 256], return_tensors="pt", padding=True).to(dev)
            out.append(_feats(model.get_text_features(**t)))
        tf = torch.cat(out)
        return tf / tf.norm(dim=-1, keepdim=True)

    with torch.no_grad():
        tf = encode(texts)
        rf = encode(region_texts) if region_texts else None
        print(f"{len(texts)} country and {len(region_texts)} region prompts encoded", flush=True)
        rows = read_labels(a.folder)
        files, probs, rprobs = [], [], []
        for i, r in enumerate(rows, 1):
            im = Image.open(Path(a.folder) / r["file"]).convert("RGB")
            x = proc(images=im, return_tensors="pt").to(dev)
            f = _feats(model.get_image_features(**x))
            f = f / f.norm(dim=-1, keepdim=True)
            scale = model.logit_scale.exp()
            probs.append((scale * f @ tf.T).softmax(-1)[0].float().cpu().numpy())
            if rf is not None:
                rprobs.append((scale * f @ rf.T).softmax(-1)[0].float().cpu().numpy())
            files.append(r["file"])
            if i % 25 == 0:
                print(f"  {i}/{len(rows)}", flush=True)
    extra = {"region_probs": np.stack(rprobs).astype(np.float16)} if rprobs else {}
    np.savez(a.out, files=np.array(files), probs=np.stack(probs).astype(np.float32),
             codes=np.array(meta["codes"]), **extra)
    top1 = np.mean([meta["codes"][int(p.argmax())] == r["country"] for p, r in zip(probs, rows)])
    print(f"{len(files)} photos on {dev}; StreetCLIP zero-shot country top-1 {top1:.0%} -> {a.out}")


def cmd_eval(a):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from geolock.engine import Geolocator
    from geolock.geodata import haversine_km
    eng = Geolocator()
    sc = np.load(a.npz)
    assert list(sc["codes"]) == list(eng.geo.country_codes), "country lists differ; rerun names+embed"
    sc_probs = dict(zip(sc["files"].tolist(), sc["probs"]))
    rows = [r for r in read_labels(a.folder) if r["file"] in sc_probs]
    from geolock.clues import Clue
    rp = dict(zip(sc["files"].tolist(), sc["region_probs"].astype(np.float32))) if "region_probs" in sc else {}
    n_regions = len(eng.geo.admin1.props)
    if rp:
        assert len(next(iter(rp.values()))) == n_regions, "region lists differ; rerun names+embed"

    def region_clue(p):
        """StreetCLIP's region guess as a clue: each point weighted by its region's
        probability relative to the most likely region."""
        rel = p / p.max()

        def point_fn(lat, lon):
            idx = eng.geo.admin1.lookup(lat, lon, max_deg=0.3)
            out = np.where(idx >= 0, rel[np.maximum(idx, 0)], 0.0)
            return out.reshape(np.shape(lat)) if np.ndim(lat) else float(out[0])
        top = int(p.argmax())
        return Clue(kind="streetclip", title=f"StreetCLIP region: {eng.geo.admin1.props[top].get('name')}",
                    strength=a.region_strength, point_fn=point_fn)

    variants = {"CLIP (current)": [], "StreetCLIP": [], "CLIP x StreetCLIP": []}
    if rp:
        variants.update({"StreetCLIP + regions": [], "CLIP x SC + regions": []})
    errs = {(v, w): [] for v in variants for w in a.weights}
    cc_ok = {k: 0 for k in errs}
    zs_ok = {"CLIP": 0, "StreetCLIP": 0}
    orig = eng.evidence
    for i, r in enumerate(rows, 1):
        truth = (float(r["lat"]), float(r["lon"]))
        im, meta = eng.open_image(Path(a.folder) / r["file"])
        ev = orig(im, meta, use_ocr=not a.no_ocr)
        p_clip, p_sc = ev["p_country_clip"], sc_probs[r["file"]]
        codes = eng.geo.country_codes
        zs_ok["CLIP"] += codes[int(p_clip.argmax())] == r["country"]
        zs_ok["StreetCLIP"] += codes[int(p_sc.argmax())] == r["country"]
        both = (lambda m: m / m.sum())(np.sqrt(p_clip * p_sc))
        mixes = {"CLIP (current)": (p_clip, []), "StreetCLIP": (p_sc, []), "CLIP x StreetCLIP": (both, [])}
        if rp:
            rc = region_clue(rp[r["file"]])
            mixes.update({"StreetCLIP + regions": (p_sc, [rc]), "CLIP x SC + regions": (both, [rc])})
        for v, (p, more) in mixes.items():
            for w in a.weights:
                eng.country_weight = w
                eng.evidence = lambda *_a, _ev=ev, _p=p, _m=more, **_k: dict(
                    _ev, p_country_clip=_p, clues=_ev["clues"] + _m)
                g = eng.locate(im, use_exif_gps=False)["guesses"][0]
                errs[(v, w)].append(float(haversine_km(g["lat"], g["lon"], *truth)))
                cc_ok[(v, w)] += g.get("country_code") == r["country"]
        eng.evidence = orig
        if i % 25 == 0:
            print(f"  {i}/{len(rows)}", flush=True)
    n = len(rows)
    print(f"\n{n} photos. Zero-shot country top-1: CLIP {zs_ok['CLIP'] / n:.0%}, "
          f"StreetCLIP {zs_ok['StreetCLIP'] / n:.0%}")
    print(f"{'variant':20} {'weight':>6} " + " ".join(f"{t:>6}km" for t in THRESHOLDS)
          + "  median  country")
    for (v, w), e in errs.items():
        e = np.array(e)
        print(f"{v:20} {w:>6} " + " ".join(f"{np.mean(e <= t):>7.0%}" for t in THRESHOLDS)
              + f"  {np.median(e):>6.0f}  {cc_ok[(v, w)] / n:>6.0%}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("names")
    s.add_argument("out")
    s = sub.add_parser("embed")
    s.add_argument("folder")
    s.add_argument("out")
    s.add_argument("--countries", required=True)
    s = sub.add_parser("eval")
    s.add_argument("folder")
    s.add_argument("npz")
    s.add_argument("--weights", type=float, nargs="+", default=[0.5, 1.0, 1.5])
    s.add_argument("--no-ocr", action="store_true")
    s.add_argument("--region-strength", type=float, default=0.5)
    a = ap.parse_args()
    {"names": cmd_names, "embed": cmd_embed, "eval": cmd_eval}[a.cmd](a)


if __name__ == "__main__":
    main()
