"""Command line: serve the app, locate photos, evaluate, benchmark."""
import argparse
import json
import sys
import time
import webbrowser
from pathlib import Path

from .config import DEVICE, MODELS_DIR

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".bmp", ".tif", ".tiff"}


def _engine(a):
    from .engine import Geolocator
    return Geolocator(a.models_dir, device=a.device, country_weight=a.country_weight,
                      temperature=a.temperature)


def cmd_serve(a):
    import uvicorn
    from .server import create_app
    eng = _engine(a)
    print("Warming up models…")
    eng.warmup()
    url = f"http://{a.host}:{a.port}"
    print(f"GeoLock running on {eng.device} at {url}  (Ctrl+C to stop)")
    if not a.no_browser:
        webbrowser.open(url)
    uvicorn.run(create_app(eng), host=a.host, port=a.port, log_level="warning")


def cmd_locate(a):
    eng = _engine(a)
    for path in a.images:
        r = eng.locate(path, use_ocr=not a.no_ocr, use_vlm=a.vlm)
        if a.json:
            r.pop("heat", None)
            print(json.dumps(r, indent=2, ensure_ascii=False))
            continue
        print(f"\n{path}  ({r['device']}, {r['timings']['total_ms']} ms)")
        if r.get("exif_gps"):
            g = r["exif_gps"]
            print(f"  EXIF GPS: {g['lat']:.4f}, {g['lon']:.4f}")
        for i, g in enumerate(r["guesses"], 1):
            place = g.get("place") or {}
            where = ", ".join(x for x in (place.get("name"), g.get("region"), g["country"]) if x)
            print(f"  {i}. {g['confidence']:6.1%} {g['label']:6}  {g['lat']:.4f}, {g['lon']:.4f}  "
                  f"±{g['radius_km']:.0f} km  near {where}")
        print("  Countries: " + ", ".join(f"{c['name']} {c['prob']:.0%}" for c in r["countries"][:5]))
        for c in r["clues"]:
            if c["strength"] > 0:
                print(f"  clue: {c['title']} — {c['detail']}")


def cmd_eval(a):
    """Accuracy on your own geotagged photos (their EXIF GPS is the ground truth)."""
    import numpy as np
    from PIL import Image
    from .exif import read_exif
    from .geodata import haversine_km
    eng = _engine(a)
    files = [p for p in Path(a.folder).rglob("*") if p.suffix.lower() in IMAGE_EXT]
    thresholds = [1, 25, 200, 750, 2500]
    errs, conf, country_ok, n = [], [], 0, 0
    for p in files:
        try:
            truth = read_exif(Image.open(p)).get("gps")
        except Exception:
            continue
        if not truth:
            continue
        r = eng.locate(p, use_ocr=not a.no_ocr, use_vlm=a.vlm, use_exif_gps=False)
        g = r["guesses"][0]
        e = float(haversine_km(g["lat"], g["lon"], truth["lat"], truth["lon"]))
        tc = eng.geo.describe(truth["lat"], truth["lon"])["country_code"]
        country_ok += int(tc == g.get("country_code"))
        errs.append(e)
        conf.append(g["confidence"])
        n += 1
        print(f"{e:8.1f} km  conf {g['confidence']:.0%}  {p.name}")
    if not n:
        sys.exit("No photos with EXIF GPS found.")
    errs = np.array(errs)
    print(f"\n{n} photos.  Median error {np.median(errs):.0f} km.  Country accuracy {country_ok / n:.0%}")
    for t in thresholds:
        print(f"  within {t:>5} km: {np.mean(errs <= t):.0%}")
    conf = np.array(conf)
    for lo, hi in ((0, .2), (.2, .5), (.5, 1.01)):
        m = (conf >= lo) & (conf < hi)
        if m.any():
            print(f"  confidence {lo:.0%}-{min(hi, 1):.0%}: {m.sum()} photos, "
                  f"{np.mean(errs[m] <= a.cluster_km):.0%} within {a.cluster_km:.0f} km")


def cmd_bench(a):
    import numpy as np
    from PIL import Image
    eng = _engine(a)
    img = Image.fromarray((np.random.default_rng(0).random((768, 1024, 3)) * 255).astype("uint8"))
    eng.locate(img, use_ocr=False)
    t = time.perf_counter()
    for _ in range(a.n):
        eng.embed(img)
    print(f"CLIP on {eng.device}: {(time.perf_counter() - t) / a.n * 1000:.0f} ms per photo "
          f"({eng.core.available_devices} available)")
    t = time.perf_counter()
    r = eng.locate(img, use_ocr=True)
    print(f"Full pipeline: {(time.perf_counter() - t) * 1000:.0f} ms  {r['timings']}")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="geolock", description="Offline photo geolocation")
    ap.add_argument("--models-dir", type=Path, default=MODELS_DIR)
    ap.add_argument("--device", default=DEVICE, help="AUTO (default), GPU, NPU or CPU")
    ap.add_argument("--country-weight", type=float, default=0.5,
                    help="weight of CLIP's zero-shot country classifier in the fusion")
    ap.add_argument("--temperature", type=float, default=1.0,
                    help=">1 spreads GeoCLIP's probabilities (less confident)")
    sub = ap.add_subparsers(dest="cmd")
    s = sub.add_parser("serve", help="start the map app (default)")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=7860)
    s.add_argument("--no-browser", action="store_true")
    s = sub.add_parser("locate", help="locate photos from the command line")
    s.add_argument("images", nargs="+")
    s.add_argument("--json", action="store_true")
    s.add_argument("--no-ocr", action="store_true")
    s.add_argument("--vlm", action="store_true", help="use the vision-language model")
    s = sub.add_parser("eval", help="measure accuracy on a folder of geotagged photos")
    s.add_argument("folder")
    s.add_argument("--no-ocr", action="store_true")
    s.add_argument("--vlm", action="store_true")
    s.add_argument("--cluster-km", type=float, default=250.0)
    s = sub.add_parser("bench", help="time the models on this machine")
    s.add_argument("-n", type=int, default=10)
    a = ap.parse_args(argv)
    if a.cmd in (None, "serve"):
        if a.cmd is None:
            a.host, a.port, a.no_browser = "127.0.0.1", 7860, False
        cmd_serve(a)
    else:
        {"locate": cmd_locate, "eval": cmd_eval, "bench": cmd_bench}[a.cmd](a)


if __name__ == "__main__":
    main()
