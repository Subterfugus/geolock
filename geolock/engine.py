"""The geolocation engine: image in, ranked map guesses with confidence and clues out.

Pipeline
1. CLIP ViT-L/14 vision encoder (OpenVINO, on the Arc GPU / NPU / CPU) embeds 4 crops.
2. GeoCLIP maps that embedding into a GPS embedding space and scores 100k gallery
   locations around the world  -> a visual prior over the globe.
3. Clues re-weight that prior: CLIP zero-shot country + scene attributes, OCR'd text
   (language, domains, phone codes, currency), EXIF time zone, and optionally a local
   vision-language model. Each clue is a likelihood over countries or coordinates.
4. The posterior is clustered into distinct guesses; each guess is refined with the
   continuous location encoder, named with offline geodata and explained.
"""
import io
import json
import time
from functools import cached_property
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps

try:  # iPhone photos (HEIC/HEIF)
    from pillow_heif import register_heif_opener
    register_heif_opener()
except ImportError:
    pass

from . import prompts
from .clues import Clue
from .config import CROPS, DEVICE, MODELS_DIR
from .countrymeta import SCRIPT_COUNTRIES
from .exif import exif_clues, read_exif
from .geodata import GeoData, haversine_km, weighted_center
from .locenc import LocationEncoder, normalize
from .ocr import TextReader

MEAN = np.array([0.48145466, 0.4578275, 0.40821073], dtype=np.float32)
STD = np.array([0.26862954, 0.26130258, 0.27577711], dtype=np.float32)


def _resize_short(im, size=224):
    w, h = im.size
    s = size / min(w, h)
    return im.resize((max(size, round(w * s)), max(size, round(h * s))), Image.BICUBIC)


def make_crops(im, size=224):
    """Centre, both ends along the long side, and the whole frame letterboxed."""
    r = _resize_short(im, size)
    w, h = r.size
    if w >= h:
        boxes = [((w - size) // 2, 0), (0, 0), (w - size, 0)]
    else:
        boxes = [(0, (h - size) // 2), (0, 0), (0, h - size)]
    crops = [r.crop((x, y, x + size, y + size)) for x, y in boxes]
    lb = im.copy()
    lb.thumbnail((size, size), Image.BICUBIC)
    canvas = Image.new("RGB", (size, size), tuple(int(c * 255) for c in MEAN))
    canvas.paste(lb, ((size - lb.width) // 2, (size - lb.height) // 2))
    crops.append(canvas)
    arr = np.stack([np.asarray(c, dtype=np.float32) / 255.0 for c in crops[:CROPS]])
    return ((arr - MEAN) / STD).transpose(0, 3, 1, 2).copy()


def _softmax(x):
    x = x - x.max()
    e = np.exp(x)
    return e / e.sum()


def _log_softmax(x):
    x = x - x.max()
    return x - np.log(np.exp(x).sum())


class Geolocator:
    def __init__(self, models_dir=MODELS_DIR, device=DEVICE, country_weight=None,
                 temperature=None, cluster_km=250.0):
        self.models_dir = Path(models_dir)
        self.requested_device = device
        # Fusion settings: explicit arguments win, then `geolock eval --fit` results, then defaults.
        cal_path = self.models_dir / "calibration.json"
        self.calibration = json.loads(cal_path.read_text()) if cal_path.exists() else {}
        self.country_weight = (country_weight if country_weight is not None
                               else self.calibration.get("country_weight", 0.5))
        self.temperature = (temperature if temperature is not None
                            else self.calibration.get("temperature", 1.0))
        self.cluster_km = cluster_km
        self.geo = GeoData()
        self.reader = TextReader()
        self._load()

    # ---------------------------------------------------------------- loading
    def _load(self):
        import openvino as ov
        md = self.models_dir
        if not (md / "clip_vision.xml").exists():
            raise FileNotFoundError(
                f"No models in {md}. Run the setup first: python -m geolock.setup_models")
        self.core = ov.Core()
        self.manifest = json.loads((md / "manifest.json").read_text()) if (md / "manifest.json").exists() else {}
        model = self.core.read_model(md / "clip_vision.xml")
        self.device, self.vision = self._compile(model)

        g = np.load(md / "geoclip.npz")
        self.mlp = [g["mlp.w1"].T, g["mlp.b1"], g["mlp.w2"].T, g["mlp.b2"]]
        self.geo_scale = float(g["logit_scale"])
        self.loc_encoder = LocationEncoder({k[4:]: g[k] for k in g.files if k.startswith("loc.")})

        gal = np.load(md / "gallery.npz")
        self.gps = gal["gps"].astype(np.float64)
        self.gal_feats = gal["feats"].astype(np.float32)
        self.gal_country = gal["country"].astype(np.int64)

        p = np.load(md / "prompts.npz")
        emb = dict(zip(p["keys"].tolist(), p["embs"]))
        self.clip_scale = float(p["clip_logit_scale"])
        codes = self.geo.country_codes
        if p["country_codes"].tolist() != codes:
            raise RuntimeError("prompts.npz is stale; run: python -m geolock.setup_models --prompts-only")
        self.country_text = np.stack([emb[f"country/{i}"] for i in range(len(codes))])
        self.attr_text = {k: np.stack([emb[f"attr/{k}/{j}"] for j in range(len(a["options"]))])
                          for k, a in prompts.ATTRIBUTES.items()}

    def _compile(self, model):
        avail = self.core.available_devices
        order = {"AUTO": ["GPU", "NPU", "CPU"]}.get(self.requested_device.upper(),
                                                   [self.requested_device.upper(), "CPU"])
        errors = []
        for dev in order:
            if not any(a.startswith(dev) for a in avail):
                continue
            try:
                cfg = {"PERFORMANCE_HINT": "LATENCY"}
                if dev == "GPU":
                    cfg["CACHE_DIR"] = str(self.models_dir / "ov_cache")
                return dev, self.core.compile_model(model, dev, cfg)
            except Exception as e:  # e.g. NPU driver missing -> fall through
                errors.append(f"{dev}: {e}")
        raise RuntimeError("Could not compile CLIP on any device:\n" + "\n".join(errors))

    def warmup(self):
        """Load lazy geodata and run the models once so the first real photo is fast."""
        self.geo.admin1, self.geo.nearest_place(0.0, 0.0)
        self.reader.ocr, self.reader.lang_detector
        self.locate(Image.new("RGB", (320, 240), (128, 128, 128)), use_ocr=True)

    @cached_property
    def vlm(self):
        from .vlm import VisionLanguageModel
        dev = "GPU" if any(d.startswith("GPU") for d in self.core.available_devices) else "CPU"
        return VisionLanguageModel(self.models_dir / "vlm", dev)

    @property
    def has_vlm(self):
        return self.vlm.available

    # --------------------------------------------------------------- helpers
    def embed(self, im):
        out = self.vision(make_crops(im))[0]
        return np.asarray(out, dtype=np.float32)  # (CROPS, 768)

    def geoclip_query(self, img_emb):
        w1, b1, w2, b2 = self.mlp
        h = np.maximum(img_emb @ w1 + b1, 0) @ w2 + b2
        return normalize(h)

    def geo_logits(self, q, feats):
        return self.geo_scale * (feats @ q) / self.temperature

    def attribute_probs(self, img_n):
        res = {}
        for key, text in self.attr_text.items():
            res[key] = _softmax(self.clip_scale * text @ img_n)
        return res

    def code_from_name(self, name):
        name = (name or "").strip().lower()
        for code, n in zip(self.geo.country_codes, self.geo.country_names):
            if n.lower() == name:
                return code
        return None

    # ------------------------------------------------------------ main entry
    def open_image(self, image):
        if isinstance(image, (bytes, bytearray)):
            im = Image.open(io.BytesIO(image))
        elif isinstance(image, Image.Image):
            im = image
        else:
            im = Image.open(image)
        meta = read_exif(im)
        return ImageOps.exif_transpose(im).convert("RGB"), meta

    def evidence(self, im, meta, use_ocr=True, use_vlm=False, timings=None):
        """Everything the photo tells us, before fusion: GeoCLIP query, CLIP country
        probabilities, clues, scene labels, OCR lines and raw VLM output."""
        timings = {} if timings is None else timings
        t0 = time.perf_counter()
        codes = self.geo.country_codes
        emb_mean = self.embed(im).mean(0)
        timings["clip_ms"] = round((time.perf_counter() - t0) * 1000)
        q = self.geoclip_query(emb_mean)

        # CLIP zero-shot country and scene attributes
        img_n = normalize(emb_mean)
        p_country_clip = _softmax(self.clip_scale * self.country_text @ img_n)
        attrs = self.attribute_probs(img_n)
        clues = []
        scene = []
        for key, probs in attrs.items():
            spec = prompts.ATTRIBUTES[key]
            j = int(probs.argmax())
            opt = spec["options"][j]
            p = float(probs[j])
            chance = 1.0 / len(probs)
            scene.append({"attribute": spec["title"], "value": opt["label"], "prob": round(p, 3)})
            if key == "script":
                countries = SCRIPT_COUNTRIES.get(opt["label"])
                if countries and p > 0.3:
                    clues.append(Clue(kind="script", title=f"Signs appear to use {opt['label']} script",
                                      detail=f"CLIP script detector: {p:.0%}.",
                                      strength=min(0.75, (p - chance) * 0.9), countries=countries,
                                      background=0.08))
            elif opt.get("countries") and p > 2.5 * chance and p > 0.25:
                clues.append(Clue(kind="scene", title=f"{spec['title']}: {opt['label']}",
                                  detail=f"CLIP scene classifier: {p:.0%} (vs {chance:.0%} by chance).",
                                  strength=min(0.5, (p - chance)), countries=opt["countries"],
                                  background=0.35))

        # text in the image
        ocr_lines = []
        if use_ocr:
            t = time.perf_counter()
            try:
                ocr_lines = self.reader.read(im)
                clues += self.reader.clues(ocr_lines)
            except Exception as e:
                clues.append(Clue(kind="ocr", title="Text reading failed", detail=str(e)[:200]))
            timings["ocr_ms"] = round((time.perf_counter() - t) * 1000)

        clues += exif_clues(meta)

        # optional vision-language model
        vlm_raw = None
        if use_vlm and self.has_vlm:
            from .vlm import vlm_clues
            t = time.perf_counter()
            try:
                vlm_raw, data = self.vlm.analyse(im)
                clues += vlm_clues(data, vlm_raw, self.code_from_name, codes)
            except Exception as e:
                clues.append(Clue(kind="vlm", title="Vision-language model failed", detail=str(e)[:200]))
            timings["vlm_ms"] = round((time.perf_counter() - t) * 1000)
        return {"q": q, "p_country_clip": p_country_clip, "clues": clues, "scene": scene,
                "ocr": ocr_lines, "vlm_raw": vlm_raw}

    def posterior(self, q, p_country_clip, clues, temperature=None, country_weight=None):
        """Fuse GeoCLIP's visual prior with every clue. Returns (log_post, log_geo, country_ll)."""
        temperature = self.temperature if temperature is None else temperature
        country_weight = self.country_weight if country_weight is None else country_weight
        log_geo = _log_softmax(self.geo_scale * (self.gal_feats @ q) / temperature)
        country_ll = country_weight * np.log(p_country_clip + 1e-9)
        for c in clues:
            ll = c.country_loglik(self.geo.country_codes)
            if ll is not None:
                country_ll = country_ll + ll
        ll_pad = np.append(country_ll, np.median(country_ll))  # index -1 = open water
        log_post = log_geo + ll_pad[self.gal_country]
        for c in clues:
            if c.point_fn is not None and c.strength > 0:
                log_post = log_post + np.log((1 - c.strength) + c.strength * c.point_fn(self.gps[:, 0], self.gps[:, 1]))
        return log_post - np.log(np.exp(log_post - log_post.max()).sum()) - log_post.max(), log_geo, country_ll

    def locate(self, image, use_ocr=True, use_vlm=False, use_exif_gps=True, top_k=5,
               keep_evidence=False):
        t0 = time.perf_counter()
        timings = {}
        im, meta = self.open_image(image)
        codes = self.geo.country_codes
        n_c = len(codes)
        ev = self.evidence(im, meta, use_ocr, use_vlm, timings)
        q, p_country_clip, clues = ev["q"], ev["p_country_clip"], ev["clues"]
        scene, ocr_lines, vlm_raw = ev["scene"], ev["ocr"], ev["vlm_raw"]
        log_post, log_geo, country_ll = self.posterior(q, p_country_clip, clues)
        post = np.exp(log_post)
        p_geo = np.exp(log_geo)

        # country distribution
        country_mass = np.bincount(np.where(self.gal_country >= 0, self.gal_country, n_c),
                                   weights=post, minlength=n_c + 1)[:n_c]
        top_c = np.argsort(-country_mass)[:8]
        countries = [{"code": codes[i], "name": self.geo.country_names[i],
                      "prob": round(float(country_mass[i]), 4),
                      "clip_prob": round(float(p_country_clip[i]), 4)}
                     for i in top_c if country_mass[i] > 0.005]

        # 4. cluster into guesses, refine, describe
        t = time.perf_counter()
        guesses = self._guesses(post, p_geo, q, country_ll, clues, top_k)
        for g in guesses:
            g.update(self.geo.describe(g["lat"], g["lon"]))
            g["why"] = self._explain(g, clues, p_country_clip)
        timings["fusion_ms"] = round((time.perf_counter() - t) * 1000)

        heat_idx = np.argsort(-post)[:1500]
        hmax = float(post[heat_idx[0]])
        heat = [[round(float(self.gps[i, 0]), 3), round(float(self.gps[i, 1]), 3),
                 round(float(post[i] / hmax), 4)] for i in heat_idx if post[i] / hmax > 0.01]

        exif_gps = meta.get("gps")
        result = {
            "image": {"width": im.width, "height": im.height},
            "exif": meta,
            "exif_gps": exif_gps if use_exif_gps else None,
            "guesses": guesses,
            "countries": countries,
            "clues": [c.to_json(self.geo.country_name) for c in clues],
            "scene": scene,
            "ocr": ocr_lines[:40],
            "vlm_raw": vlm_raw,
            "heat": heat,
            "device": self.device,
            "timings": timings,
        }
        if exif_gps and use_exif_gps:
            for g in guesses:
                g["km_from_exif"] = round(float(haversine_km(g["lat"], g["lon"], exif_gps["lat"], exif_gps["lon"])), 1)
            result["exif_place"] = self.geo.describe(exif_gps["lat"], exif_gps["lon"])
        timings["total_ms"] = round((time.perf_counter() - t0) * 1000)
        if keep_evidence:
            result["_evidence"] = ev
        return result

    # ------------------------------------------------------------- internals
    def _guesses(self, post, p_geo, q, country_ll, clues, top_k):
        # Work on the points that carry nearly all the mass; the rest cannot matter.
        order = np.argsort(-post)
        keep = order[:max(2000, int(np.searchsorted(np.cumsum(post[order]), 0.995)) + 1)][:20000]
        lat, lon, w_all, g_all = self.gps[keep, 0], self.gps[keep, 1], post[keep], p_geo[keep]
        remaining = np.ones(len(keep), dtype=bool)
        cand = np.arange(min(300, len(keep)))  # seeds come from the strongest points
        out = []
        for _ in range(top_k):
            live = cand[remaining[cand]]
            if not len(live):
                break
            # seed = candidate with the most posterior mass around it (not just the peak)
            dens = [w_all[remaining & (haversine_km(lat[i], lon[i], lat, lon) <= self.cluster_km / 2)].sum()
                    for i in live[:60]]
            seed = int(live[int(np.argmax(dens))])
            d = haversine_km(lat[seed], lon[seed], lat, lon)
            members = remaining & (d <= self.cluster_km)
            mass = float(w_all[members].sum())
            if out and mass < 0.01:
                break
            core = members & (d <= self.cluster_km / 2)
            clat, clon = weighted_center(lat[core], lon[core], w_all[core])
            rlat, rlon = self._refine(clat, clon, q, country_ll, clues, lat[core], lon[core], w_all[core])
            dm = haversine_km(rlat, rlon, lat[members], lon[members])
            w = w_all[members] / w_all[members].sum()
            o = np.argsort(dm)
            k = min(int(np.searchsorted(np.cumsum(w[o]), 0.68)), len(o) - 1)
            out.append({
                "lat": round(rlat, 5), "lon": round(rlon, 5),
                "confidence": round(mass, 4),
                "label": "high" if mass >= 0.5 else "medium" if mass >= 0.2 else "low",
                "radius_km": round(max(float(dm[o][k]), 5.0), 1),
                "visual_mass": round(float(g_all[members].sum()), 4),
            })
            remaining &= ~members
        out.sort(key=lambda g: -g["confidence"])
        return out

    def _refine(self, clat, clon, q, country_ll, clues, mlat, mlon, mpost):
        """Score a local cloud of candidate coordinates with the continuous encoder."""
        rng = np.random.default_rng(0)
        spread = max(15.0, float(np.average(haversine_km(clat, clon, mlat, mlon), weights=mpost)))
        n = 384
        r_km = np.abs(rng.normal(0, spread, n))
        bearing = rng.uniform(0, 2 * np.pi, n)
        dlat = (r_km / 111.2) * np.cos(bearing)
        dlon = (r_km / (111.2 * max(np.cos(np.radians(clat)), 0.05))) * np.sin(bearing)
        plat, plon = self.geo.places_near(clat, clon, min(self.cluster_km / 2, 2 * spread))
        if len(plat) > 600:
            keep = rng.choice(len(plat), 600, replace=False)
            plat, plon = plat[keep], plon[keep]
        cand_lat = np.concatenate([[clat], clat + dlat, plat, mlat])
        cand_lon = np.concatenate([[clon], (clon + dlon + 180) % 360 - 180, plon, mlon])
        cand_lat = np.clip(cand_lat, -89.9, 89.9)
        feats = normalize(self.loc_encoder(np.stack([cand_lat, cand_lon], 1)))
        score = self.geo_logits(q, feats)
        ci = self.geo.countries.lookup(cand_lat, cand_lon, max_deg=0.2)
        ll_pad = np.append(country_ll, country_ll.min())
        score = score + ll_pad[ci]
        for c in clues:
            if c.point_fn is not None and c.strength > 0:
                score += np.log((1 - c.strength) + c.strength * c.point_fn(cand_lat, cand_lon))
        w = _softmax(score)
        top = np.argsort(-w)[:8]
        rlat, rlon = weighted_center(cand_lat[top], cand_lon[top], w[top])
        if haversine_km(rlat, rlon, clat, clon) > self.cluster_km / 2:
            return clat, clon
        return float(rlat), float(rlon)

    def _explain(self, g, clues, p_clip):
        code = g.get("country_code")
        why = [{"effect": 1 if g["visual_mass"] >= 0.05 else 0,
                "text": f"Visual similarity (GeoCLIP) puts {g['visual_mass']:.0%} of its weight in this area."}]
        idx = self.geo.code_to_index.get(code)
        if idx is not None:
            rank = int((p_clip > p_clip[idx]).sum()) + 1
            why.append({"effect": 1 if rank <= 3 else (0 if rank <= 10 else -1),
                        "text": f"CLIP's country classifier ranks {g['country']} #{rank} ({p_clip[idx]:.0%})."})
        for c in clues:
            if c.point_fn is not None and c.strength > 0:
                like = float(c.point_fn(g["lat"], g["lon"]))
                why.append({"effect": 1 if like > 0.6 else -1 if like < 0.3 else 0, "text": c.title})
                continue
            e = c.effect_on(code) if code else 0
            if e:
                why.append({"effect": e, "text": c.title})
        return why
