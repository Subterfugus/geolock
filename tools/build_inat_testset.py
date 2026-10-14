"""Build a geotagged test set from iNaturalist's open data on AWS (no API, no account).

    python tools/build_inat_testset.py data/inat-testset            # ~300 photos
    python tools/build_inat_testset.py data/inat-testset --metadata inat.tar.gz

`geolock testset` (Wikimedia Commons) is the better test for everyday photos; use this
when Commons is unreachable. iNaturalist observations are wildlife records, so most photos
are close-ups of plants and animals. This tool keeps only the wide outdoor shots
(landscapes, habitats, roads, towns), judged by CLIP, so the set tests the same kind of
"where is this?" scene that GeoLock is for, with a bias towards nature.

Steps: stream the metadata tarball once (about 5 GB) keeping a few research-grade
observations per 1°x1° cell; score small thumbnails of their photos with CLIP; download
the best wide shots, at most --per-country per country; write labels.csv and
ATTRIBUTION.md like `geolock testset`. Needs the `setup` extras (torch, transformers).
Licences are CC0, CC BY or CC BY-NC (iNaturalist's open-data subset). Coordinates of
sensitive species are blurred by iNaturalist by up to ~20 km; with research-grade
records and the per-cell sampling these are rare.
"""
import argparse
import csv
import io
import json
import random
import sys
import tarfile
import urllib.request
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from geolock.geodata import GeoData  # noqa: E402
from geolock.testset import write_labels, read_labels  # noqa: E402

BUCKET = "https://inaturalist-open-data.s3.amazonaws.com"
METADATA = BUCKET + "/metadata/inaturalist-open-data-20210407.tar.gz"
LICENSES = {
    "CC0": "https://creativecommons.org/publicdomain/zero/1.0/",
    "CC-BY": "https://creativecommons.org/licenses/by/4.0/",
    "CC-BY-NC": "https://creativecommons.org/licenses/by-nc/4.0/",
    "CC-BY-SA": "https://creativecommons.org/licenses/by-sa/4.0/",
    "CC-BY-NC-SA": "https://creativecommons.org/licenses/by-nc-sa/4.0/",
    "CC-BY-ND": "https://creativecommons.org/licenses/by-nd/4.0/",
    "CC-BY-NC-ND": "https://creativecommons.org/licenses/by-nc-nd/4.0/",
}
WIDE = ["a landscape photo", "a photo of a street in a town", "a photo of buildings",
        "a photo of a road", "a photo of a beach and the sea", "a photo of a forest",
        "a photo of mountains", "a photo of a river or lake", "a photo of a desert",
        "a photo of fields and farmland", "a photo of a park", "a photo of a coastline"]
# --urban: only towns and cities (streets, buildings), closer to everyday photos.
URBAN = ["a photo of a street in a town", "a photo of buildings", "a photo of a city",
         "a photo of houses", "a photo of a road with cars", "a photo of a market",
         "a photo of a village", "a photo of a church or temple", "a photo of a harbour with boats"]
CLOSE = ["a close-up photo of a plant", "a close-up photo of a flower",
         "a close-up photo of an insect", "a photo of a bird", "a photo of an animal",
         "a photo of a mushroom", "a close-up photo of leaves", "a photo of a reptile",
         "a photo of a fish", "a photo of a spider", "a macro photo", "a photo of a tree trunk",
         "a photo of a hand holding something", "a photo of a dead animal", "a photo of moss"]


def log(msg):
    print(f"[inat] {msg}", flush=True)


def stream_candidates(src, per_cell=3, seed=0):
    """One pass over the metadata tarball: a few research-grade observations per 1° cell,
    with their photos and observer logins."""
    rnd = random.Random(seed)
    raw = open(src, "rb") if Path(src).exists() else urllib.request.urlopen(src, timeout=120)
    cells, seen, picked, photos, logins = {}, Counter(), {}, defaultdict(list), {}
    with tarfile.open(fileobj=raw, mode="r|gz") as t:
        for m in t:
            f = t.extractfile(m)
            if f is None:
                continue
            rows = (line.decode("utf-8", "replace").rstrip("\r\n").split("\t") for line in f)
            head = next(rows)
            ix = {k: i for i, k in enumerate(head)}
            log(f"reading {m.name.rsplit('/', 1)[-1]}")
            if m.name.endswith("observations.csv"):
                for row in rows:
                    try:
                        if row[ix["quality_grade"]] != "research":
                            continue
                        acc = row[ix["positional_accuracy"]]
                        if acc and float(acc) > 2000:
                            continue
                        lat, lon = float(row[ix["latitude"]]), float(row[ix["longitude"]])
                    except (ValueError, IndexError):
                        continue
                    c = (int(lat // 1), int(lon // 1))
                    seen[c] += 1
                    rec = (row[ix["observation_uuid"]], lat, lon, row[ix["observer_id"]])
                    lst = cells.setdefault(c, [])
                    if len(lst) < per_cell:
                        lst.append(rec)
                    elif (j := rnd.randrange(seen[c])) < per_cell:
                        lst[j] = rec
                picked = {r[0]: r for lst in cells.values() for r in lst}
                log(f"  {len(picked):,} observations kept from {len(cells):,} cells")
            elif m.name.endswith("photos.csv"):
                for row in rows:
                    try:
                        if row[ix["observation_uuid"]] in picked:
                            photos[row[ix["observation_uuid"]]].append(
                                (row[ix["photo_id"]], row[ix["extension"]], row[ix["license"]]))
                    except IndexError:
                        continue
            elif m.name.endswith("observers.csv"):
                need = {r[3] for r in picked.values()}
                for row in rows:
                    try:
                        if row[ix["observer_id"]] in need:
                            logins[row[ix["observer_id"]]] = row[ix["login"]]
                    except IndexError:
                        continue
    out = []
    for uuid, (_, lat, lon, obs) in picked.items():
        for pid, ext, lic in photos.get(uuid, []):
            out.append({"obs": uuid, "photo_id": pid, "ext": ext, "license": lic,
                        "lat": lat, "lon": lon, "observer": logins.get(obs, obs)})
    return out


def fetch(url):
    try:
        with urllib.request.urlopen(url, timeout=60) as r:
            return r.read()
    except Exception:
        return None


def photo_url(c, size):
    return f"{BUCKET}/photos/{c['photo_id']}/{size}.{c['ext']}"


class WideShotScorer:
    """P(wide outdoor shot) from CLIP ViT-L/14, the same model GeoLock uses."""

    def __init__(self, keep=WIDE):
        import torch
        from transformers import CLIPModel, CLIPProcessor
        self.torch = torch
        self.model = CLIPModel.from_pretrained("openai/clip-vit-large-patch14").eval()
        self.proc = CLIPProcessor.from_pretrained("openai/clip-vit-large-patch14")
        with torch.no_grad():
            others = CLOSE + ([] if keep is WIDE else [p for p in WIDE if p not in keep])
            t = self.proc(text=keep + others, return_tensors="pt", padding=True)
            e = self.model.text_projection(self.model.text_model(**t).pooler_output)
        self.text = (e / e.norm(dim=-1, keepdim=True)).numpy()
        self.n_keep = len(keep)

    def __call__(self, images):
        with self.torch.no_grad():
            x = self.proc(images=images, return_tensors="pt")
            pooled = self.model.vision_model(pixel_values=x["pixel_values"]).pooler_output
            e = self.model.visual_projection(pooled).numpy()
        e /= np.linalg.norm(e, axis=1, keepdims=True)
        logits = 100 * e @ self.text.T
        p = np.exp(logits - logits.max(1, keepdims=True))
        p /= p.sum(1, keepdims=True)
        return p[:, :self.n_keep].sum(1)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("folder", type=Path)
    ap.add_argument("--metadata", default=METADATA, help="tarball path or URL")
    ap.add_argument("-n", type=int, default=300)
    ap.add_argument("--per-country", type=int, default=4)
    ap.add_argument("--screen", type=int, default=6000, help="thumbnails to score with CLIP")
    ap.add_argument("--min-wide", type=float, default=0.7, help="CLIP wide-shot probability")
    ap.add_argument("--urban", action="store_true",
                    help="only photos taken in towns, of streets and buildings")
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()
    a.folder.mkdir(parents=True, exist_ok=True)
    rng = random.Random(a.seed)
    geo = GeoData()

    cache = a.folder / ".candidates.jsonl"
    if cache.exists():
        cands = [json.loads(x) for x in cache.read_text().splitlines()]
    else:
        cands = stream_candidates(a.metadata, seed=a.seed)
        cache.write_text("\n".join(json.dumps(c) for c in cands))
    cands = [c for c in cands if c["license"] in LICENSES]
    if a.urban:  # at least 5 GeoNames places (1000+ people) within 10 km
        def town_count(c):
            return len(geo.places_near(c["lat"], c["lon"], 10)[0])
        cands = [c for c in cands if town_count(c) >= 5]
    ccodes = geo.countries.lookup(np.array([c["lat"] for c in cands]),
                                  np.array([c["lon"] for c in cands]))
    by_cc = defaultdict(list)
    for c, i in zip(cands, ccodes):
        if i >= 0:
            c["country"] = geo.country_codes[i]
            by_cc[c["country"]].append(c)
    log(f"{len(cands):,} candidate photos in {len(by_cc)} countries")

    # Screen an equal number of thumbnails per country (more where photos are plentiful).
    per = max(4, a.screen // max(1, len(by_cc)))
    screen = []
    for cc, lst in by_cc.items():
        rng.shuffle(lst)
        screen += lst[:per]
    log(f"scoring {len(screen):,} thumbnails with CLIP")
    with ThreadPoolExecutor(16) as ex:
        thumbs = list(ex.map(lambda c: fetch(photo_url(c, "small")), screen))
    scorer = WideShotScorer(URBAN if a.urban else WIDE)
    ok = [(c, t) for c, t in zip(screen, thumbs) if t]
    scores = []
    for i in range(0, len(ok), 32):
        ims = []
        for _, t in ok[i:i + 32]:
            try:
                ims.append(Image.open(io.BytesIO(t)).convert("RGB"))
            except Exception:
                ims.append(Image.new("RGB", (32, 32)))
        scores.extend(scorer(ims).tolist())
    wide = defaultdict(list)
    for (c, _), s in zip(ok, scores):
        if s >= a.min_wide:
            c["wide"] = round(s, 3)
            wide[c["country"]].append(c)
    log(f"{sum(map(len, wide.values()))} wide shots in {len(wide)} countries")

    # Take the widest shots, one observation each, round-robin over countries.
    rows = read_labels(a.folder)
    have = Counter(r["country"] for r in rows)
    used = {r["title"] for r in rows}
    queues = {cc: sorted(v, key=lambda c: -c["wide"]) for cc, v in wide.items()}
    obs_used = set()
    while len(rows) < a.n and any(queues.values()):
        for cc in sorted(queues, key=lambda k: (have[k], rng.random())):
            if len(rows) >= a.n:
                break
            q = queues[cc]
            while q and (q[0]["obs"] in obs_used or f"iNaturalist photo {q[0]['photo_id']}" in used):
                q.pop(0)
            if not q or have[cc] >= a.per_country:
                queues[cc] = []
                continue
            c = q.pop(0)
            data = fetch(photo_url(c, "large"))
            if not data:
                continue
            name = f"{cc}_{have[cc] + 1:02d}.{c['ext']}"
            (a.folder / name).write_bytes(data)
            have[cc] += 1
            obs_used.add(c["obs"])
            rows.append({"file": name, "lat": f"{c['lat']:.6f}", "lon": f"{c['lon']:.6f}",
                         "country": cc, "source": "inaturalist",
                         "title": f"iNaturalist photo {c['photo_id']}",
                         "author": c["observer"], "license": c["license"],
                         "license_url": LICENSES[c["license"]],
                         "page_url": f"https://www.inaturalist.org/photos/{c['photo_id']}"})
        write_labels(a.folder, rows)
    write_labels(a.folder, rows)
    log(f"done: {len(rows)} photos from {len(have)} countries in {a.folder}")


if __name__ == "__main__":
    main()
