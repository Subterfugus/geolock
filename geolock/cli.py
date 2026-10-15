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
        r = eng.locate(path, use_ocr=not a.no_ocr, use_vlm=a.vlm, ask=a.ask or (),
                       share_local=not a.no_share_local, osm=a.osm)
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
        for an in r.get("analysts", []):
            if not an["ok"]:
                print(f"  {an['name']}: failed: {an['error']}")
                continue
            print(f"  {an['name']} ({an['via']}, {an['ms'] / 1000:.0f} s): {an['reasoning']}")
            if an.get("crops"):
                print(f"    (also sent {len(an['crops'])} zoomed crop(s) of signs)")
            for c in an.get("checklist", []):
                print(f"    - {c['label']}: {c['seen']}" + (f" -> {c['suggests']}" if c["suggests"] else ""))
            for g in an["guesses"]:
                print(f"    {g['confidence']:6.1%}  {g['lat']:.4f}, {g['lon']:.4f}  ±{g['radius_km']:.0f} km  "
                      f"{', '.join(x for x in (g['place'], g['country']) if x)}"
                      + (f"  ({g['why']})" if g.get("why") else ""))
            for x in an.get("ruled_out", []):
                print(f"    not {x['place']}: {x['why']}")
        for c in r["clues"]:
            if c["strength"] > 0:
                print(f"  clue: {c['title']} — {c['detail']}")


def _truth_labels(folder):
    """labels.csv in the folder (from `geolock testset`), if any: {relative path: (lat, lon)}."""
    from .testset import read_labels
    return {r["file"]: (float(r["lat"]), float(r["lon"])) for r in read_labels(folder)}


def cmd_eval(a):
    """Accuracy on geotagged photos: a labels.csv in the folder (as written by
    `geolock testset`) gives the true locations, otherwise the photos' EXIF GPS does.

    With --fit, also searches the fusion settings (GeoCLIP temperature and the weight of
    CLIP's country classifier) that make the confidence numbers most honest on these
    photos, and saves them to models/calibration.json for the app to use.
    """
    import numpy as np
    from .geodata import haversine_km
    eng = _engine(a)
    files = sorted(p for p in Path(a.folder).rglob("*") if p.suffix.lower() in IMAGE_EXT)
    labels = _truth_labels(a.folder)
    thresholds = [1, 25, 200, 750, 2500]
    errs, conf, country_ok, cases, rows = [], [], 0, [], []
    llm_errs = {}  # analyst name -> error of its own top guess, to compare with the fused one
    for p in files:
        try:
            im, meta = eng.open_image(p)
        except Exception as e:
            print(f"   skip  {p.name}: {e}")
            continue
        rel = p.relative_to(a.folder).as_posix()
        truth = ({"lat": labels[rel][0], "lon": labels[rel][1]} if rel in labels
                 else meta.get("gps"))
        if not truth:
            continue
        r = eng.locate(im, use_ocr=not a.no_ocr, use_vlm=a.vlm, use_exif_gps=False, keep_evidence=a.fit,
                       ask=a.ask or (), share_local=not a.no_share_local, osm=a.osm)
        g = r["guesses"][0]
        e = float(haversine_km(g["lat"], g["lon"], truth["lat"], truth["lon"]))
        for an in r.get("analysts", []):
            ag = an["guesses"][0] if an["ok"] else None
            llm_errs.setdefault(an["name"], []).append(
                float(haversine_km(ag["lat"], ag["lon"], truth["lat"], truth["lon"])) if ag else np.inf)
        tc = eng.geo.describe(truth["lat"], truth["lon"])["country_code"]
        country_ok += int(tc == g.get("country_code"))
        rows.append({"file": rel, "true_lat": truth["lat"], "true_lon": truth["lon"],
                     "true_country": tc, "guess_lat": round(g["lat"], 5),
                     "guess_lon": round(g["lon"], 5), "guess_country": g.get("country_code"),
                     "error_km": round(e, 1), "confidence": round(g["confidence"], 4)})
        errs.append(e)
        conf.append(g["confidence"])
        if a.fit:
            ev = r["_evidence"]
            near = haversine_km(truth["lat"], truth["lon"], eng.gps[:, 0], eng.gps[:, 1]) <= a.cluster_km
            cases.append((ev, near, truth))
        print(f"{e:8.1f} km  conf {g['confidence']:.0%}  {p.name}")
    n = len(errs)
    if not n:
        sys.exit("No photos with a known location (labels.csv or EXIF GPS) found.")
    errs = np.array(errs)
    print(f"\n{n} photos.  Median error {np.median(errs):.0f} km.  Country accuracy {country_ok / n:.0%}")
    for t in thresholds:
        print(f"  within {t:>5} km: {np.mean(errs <= t):.0%}")
    for name, le in llm_errs.items():
        le = np.array(le)
        print(f"  {name} alone (its top guess; failures count as misses): "
              + ", ".join(f"{t} km {np.mean(le <= t):.0%}" for t in thresholds)
              + f", median {np.median(le):.0f} km")
    conf = np.array(conf)
    print(f"  (settings: temperature {eng.temperature}, country weight {eng.country_weight})")
    for lo, hi in ((0, .2), (.2, .5), (.5, 1.01)):
        m = (conf >= lo) & (conf < hi)
        if m.any():
            print(f"  said {lo:.0%}-{min(hi, 1):.0%} confident: {m.sum()} photos, actually within "
                  f"{a.cluster_km:.0f} km {np.mean(errs[m] <= a.cluster_km):.0%} of the time")
    if a.csv:
        import csv
        with open(a.csv, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
        print(f"  per-photo results saved to {a.csv}")
    if a.fit:
        _fit(eng, cases, a)


def _fit(eng, cases, a):
    """Pick the settings that maximise the probability given to the true area."""
    import json
    import time as _t
    import numpy as np
    if len(cases) < 20:
        print(f"\nOnly {len(cases)} photos; --fit needs at least 20 to be meaningful. Not saving.")
        return
    best = None
    print("\nFitting fusion settings (mean log-probability of the true area; higher is better):")
    for t in (0.5, 0.75, 1.0, 1.5, 2.0, 3.0, 4.0):
        for w in (0.0, 0.25, 0.5, 0.75, 1.0):
            score = 0.0
            for ev, near, _ in cases:
                lp, _, _ = eng.posterior(ev["q"], ev["p_country_clip"], ev["clues"], t, w)
                score += np.log(np.exp(lp[near]).sum() + 1e-6)
            score /= len(cases)
            if best is None or score > best[0]:
                best = (score, t, w)
    score, t, w = best
    cal = {"temperature": t, "country_weight": w, "score": round(float(score), 4),
           "photos": len(cases), "fitted": _t.strftime("%Y-%m-%d %H:%M")}
    (eng.models_dir / "calibration.json").write_text(json.dumps(cal, indent=2))
    print(f"  best: temperature {t}, country weight {w} (score {score:.3f}). "
          f"Saved to {eng.models_dir / 'calibration.json'}; the app uses it from now on.")


def cmd_bench(a):
    import numpy as np
    from PIL import Image
    eng = _engine(a)
    if eng.runner.fallback:
        print(eng.runner.fallback)
    if a.all_devices:
        for r in eng.benchmark(a.n):
            res = f"{r['ms']} ms per photo (compile {r['compile_ms']} ms)" if r["ok"] else r["error"]
            print(f"{r['device']:4} {res}  {r['name'] or ''}")
        return
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


def cmd_analysts(a):
    from .analyst import detect
    for key, st in detect(refresh=True).items():
        mark = "ready" if st["available"] else "not available"
        print(f"{key:8} {mark:14} {st['detail']}")


def _ask_args(s):
    s.add_argument("--ask", action="append", choices=["claude", "chatgpt"],
                   help="also ask Claude or ChatGPT with your own login (repeatable; "
                        "sends the photo without its metadata)")
    s.add_argument("--no-share-local", action="store_true",
                   help="don't tell the analyst what GeoLock found (blind second opinion)")
    s.add_argument("--osm", action="store_true",
                   help="look up text read in the photo on OpenStreetMap (sends the text only)")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="geolock", description="Offline photo geolocation")
    ap.add_argument("--models-dir", type=Path, default=MODELS_DIR)
    ap.add_argument("--device", default=DEVICE, help="AUTO (default), GPU, NPU or CPU")
    ap.add_argument("--country-weight", type=float, default=None,
                    help="weight of CLIP's zero-shot country classifier in the fusion")
    ap.add_argument("--temperature", type=float, default=None,
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
    _ask_args(s)
    s = sub.add_parser("eval", help="measure accuracy on a folder of geotagged photos")
    s.add_argument("folder")
    s.add_argument("--no-ocr", action="store_true")
    s.add_argument("--vlm", action="store_true")
    _ask_args(s)
    s.add_argument("--cluster-km", type=float, default=250.0)
    s.add_argument("--fit", action="store_true",
                   help="tune the fusion settings on these photos and save them")
    s.add_argument("--csv", metavar="PATH", help="save per-photo results to a CSV file")
    s = sub.add_parser("testset", help="download an openly licensed geotagged test set")
    s.add_argument("folder")
    s.add_argument("-n", type=int, default=300, help="number of photos (default 300)")
    s.add_argument("--per-country", type=int, default=4, help="at most this many per country")
    s.add_argument("--radius-km", type=float, default=10.0,
                   help="search radius around each random town")
    s.add_argument("--seed", type=int, default=0)
    sub.add_parser("analysts", help="check whether Claude / ChatGPT can be asked from here")
    s = sub.add_parser("bench", help="time the models on this machine")
    s.add_argument("-n", type=int, default=10)
    s.add_argument("--all-devices", action="store_true", help="time CLIP on the GPU, NPU and CPU side by side")
    a = ap.parse_args(argv)
    if a.cmd in (None, "serve"):
        if a.cmd is None:
            a.host, a.port, a.no_browser = "127.0.0.1", 7860, False
        cmd_serve(a)
    elif a.cmd == "testset":
        from .testset import main as testset_main
        testset_main(a)
    else:
        {"locate": cmd_locate, "eval": cmd_eval, "bench": cmd_bench, "analysts": cmd_analysts}[a.cmd](a)


if __name__ == "__main__":
    main()
