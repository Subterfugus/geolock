"""Download an openly licensed, world-spread test set of geotagged photos.

    geolock testset data/testset              # ~300 photos from Wikimedia Commons
    geolock testset data/testset -n 600 --per-country 6
    geolock eval data/testset --fit

Photos come from Wikimedia Commons (every file there is under a free licence). For each
country, random towns from GeoNames are used as anchors and Commons is searched for a
geotagged photo near each one, so the set covers the whole world rather than the places
people photograph most. Maps, flags, logos, scans, paintings and similar are skipped.

The folder gets the photos plus:
  labels.csv       file, true lat/lon, country, and the licence and author of each photo
  ATTRIBUTION.md   the credits the licences ask for

`geolock eval` reads labels.csv, so the photos' own EXIF is never needed. Re-running the
command tops the folder up instead of starting again.
"""
import csv
import html
import json
import math
import random
import re
import time
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path

API = "https://commons.wikimedia.org/w/api.php"
USER_AGENT = "GeoLock-testset/0.1 (https://github.com/Subterfugus/geolock; offline geolocation research)"
LABEL_FIELDS = ["file", "lat", "lon", "country", "source", "title", "author", "license",
                "license_url", "page_url"]

# Files that are not photos of a place, or that show the place in a way GeoLock is not
# meant for (maps, documents, artwork, objects on a plain background).
_SKIP = re.compile(
    r"\b(map|karte|carte|mapa|mappa|plan|diagram|chart|graph|logo|flag|coat[ _]of[ _]arms|"
    r"wappen|blason|emblem|seal|stamp|banknote|coin|scan|scanned|document|letter|newspaper|"
    r"book|page|painting|drawing|engraving|lithograph|illustration|poster|screenshot|svg|"
    r"icon|signature|specimen|herbarium|museum|interior|x-ray|microscope|microscopy)s?\b",
    re.I)
MIN_SIDE = 600


def log(msg):
    print(f"[testset] {msg}", flush=True)


class Commons:
    """Minimal, polite client for the Commons API (no third-party HTTP library)."""

    def __init__(self, pause=0.2, opener=None):
        self.pause = pause
        self.open = opener or urllib.request.urlopen
        self._last = 0.0

    def _get(self, url, binary=False, tries=5):
        for attempt in range(tries):
            wait = self.pause - (time.time() - self._last)
            if wait > 0:
                time.sleep(wait)
            self._last = time.time()
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            try:
                with self.open(req, timeout=60) as r:
                    data = r.read()
                return data if binary else json.loads(data)
            except urllib.error.HTTPError as e:
                if e.code not in (429, 500, 502, 503, 504) or attempt == tries - 1:
                    raise
            except (urllib.error.URLError, TimeoutError):
                if attempt == tries - 1:
                    raise
            time.sleep(2 ** attempt)

    def api(self, **params):
        params.update(format="json", formatversion="2", maxlag="5")
        return self._get(API + "?" + urllib.parse.urlencode(params))

    def near(self, lat, lon, radius_m=10000, limit=40):
        """Geotagged files within radius_m of a point: [{title, lat, lon}]."""
        d = self.api(action="query", list="geosearch", gscoord=f"{lat}|{lon}",
                     gsradius=int(radius_m), gslimit=limit, gsnamespace=6)
        return d.get("query", {}).get("geosearch", [])

    def info(self, titles, width=1280):
        """Image info (thumbnail URL, size, mime, licence, author) for up to 50 titles."""
        d = self.api(action="query", titles="|".join(titles), prop="imageinfo",
                     iiprop="url|size|mime|extmetadata", iiurlwidth=width,
                     iiextmetadatafilter="LicenseShortName|LicenseUrl|Artist|Categories|"
                                         "UsageTerms|AttributionRequired")
        out = {}
        for p in d.get("query", {}).get("pages", []):
            ii = (p.get("imageinfo") or [None])[0]
            if ii:
                out[p["title"]] = ii
        return out

    def download(self, url):
        return self._get(url, binary=True)


def _meta(ii, key):
    v = (ii.get("extmetadata") or {}).get(key, {}).get("value", "")
    return html.unescape(re.sub(r"<[^>]+>", "", str(v))).strip()


def usable(title, ii):
    """Is this Commons file a real photo we can use?"""
    if ii.get("mime") != "image/jpeg":
        return False
    if min(ii.get("width", 0), ii.get("height", 0)) < MIN_SIDE:
        return False
    if _SKIP.search(title.replace("_", " ")) or _SKIP.search(_meta(ii, "Categories")):
        return False
    return bool(_meta(ii, "LicenseShortName")) and bool(ii.get("thumburl"))


def country_quotas(cities_by_cc, n, per_country, rng):
    """Spread n photos over countries: grows with the square root of how many towns a
    country has (so big countries get more, but small ones are not ignored)."""
    w = {cc: math.sqrt(len(v)) for cc, v in cities_by_cc.items() if v}
    total = sum(w.values())
    quota = {cc: min(per_country, max(1, round(n * x / total))) for cc, x in w.items()}
    # Trim or top up to hit n, at random, respecting the per-country cap.
    ccs = list(quota)
    while sum(quota.values()) > n:
        cc = rng.choice([c for c in ccs if quota[c] > 0])
        quota[cc] -= 1
    while sum(quota.values()) < n and any(quota[c] < per_country for c in ccs):
        cc = rng.choice([c for c in ccs if quota[c] < per_country])
        quota[cc] += 1
    return {cc: q for cc, q in quota.items() if q > 0}


def load_cities(geo):
    from .geodata import _cities_csv
    path = _cities_csv()
    if path is None:
        raise SystemExit("The reverse_geocoder package (GeoNames towns) is missing.")
    by_cc = defaultdict(list)
    with open(path, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            by_cc[r["cc"]].append((float(r["lat"]), float(r["lon"])))
    known = set(geo.country_codes)
    return {cc: v for cc, v in by_cc.items() if cc in known}


def read_labels(folder):
    path = Path(folder) / "labels.csv"
    if not path.exists():
        return []
    with open(path, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def write_labels(folder, rows):
    folder = Path(folder)
    with open(folder / "labels.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=LABEL_FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    lines = ["# Photo credits", "",
             "Each photo keeps its original licence; follow it if you share the photos.", "",
             "| File | Title | Author | Licence |", "|---|---|---|---|"]
    for r in rows:
        lic = f"[{r['license']}]({r['license_url']})" if r.get("license_url") else r["license"]
        title = f"[{r['title']}]({r['page_url']})" if r.get("page_url") else r["title"]
        author = (r.get("author") or "unknown").replace("|", "/")
        lines.append(f"| {r['file']} | {title.replace('|', '/')} | {author} | {lic} |")
    (folder / "ATTRIBUTION.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def build(folder, n=300, per_country=4, radius_km=10, seed=0, client=None, geo=None):
    from .geodata import GeoData
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    geo = geo or GeoData()
    rng = random.Random(seed)
    client = client or Commons()
    rows = read_labels(folder)
    have = Counter(r["country"] for r in rows)
    used = {r["title"] for r in rows}
    cities = load_cities(geo)
    quotas = country_quotas(cities, n, per_country, rng)
    log(f"{len(rows)} photos already in {folder}; aiming for {sum(quotas.values())} "
        f"across {len(quotas)} countries")
    order = list(quotas)
    rng.shuffle(order)
    for cc in order:
        need = quotas[cc] - have[cc]
        anchors = rng.sample(cities[cc], min(len(cities[cc]), need * 4 + 4))
        for lat, lon in anchors:
            if need <= 0:
                break
            try:
                hits = [h for h in client.near(lat, lon, radius_km * 1000)
                        if h["title"] not in used]
                if not hits:
                    continue
                rng.shuffle(hits)
                infos = client.info([h["title"] for h in hits[:20]])
            except Exception as e:  # network trouble on one anchor is not fatal
                log(f"  {cc}: skipped an anchor ({e})")
                continue
            for h in hits[:20]:
                ii = infos.get(h["title"])
                if not ii or not usable(h["title"], ii):
                    continue
                # The file's own coordinate must be in the country we are filling.
                if geo.describe(h["lat"], h["lon"])["country_code"] != cc:
                    continue
                name = f"{cc}_{have[cc] + 1:02d}.jpg"
                try:
                    (folder / name).write_bytes(client.download(ii["thumburl"]))
                except Exception as e:
                    log(f"  {cc}: download failed ({e})")
                    continue
                rows.append({
                    "file": name, "lat": f"{h['lat']:.6f}", "lon": f"{h['lon']:.6f}",
                    "country": cc, "source": "wikimedia-commons", "title": h["title"],
                    "author": _meta(ii, "Artist"), "license": _meta(ii, "LicenseShortName"),
                    "license_url": _meta(ii, "LicenseUrl"),
                    "page_url": ii.get("descriptionurl", "")})
                used.add(h["title"])
                have[cc] += 1
                need -= 1
                break
        write_labels(folder, rows)  # after every country, so an interrupted run keeps its work
        log(f"  {cc}: {have[cc]}/{quotas[cc]}   total {len(rows)}")
    write_labels(folder, rows)
    log(f"done: {len(rows)} photos from {len(have)} countries in {folder}")
    return rows


def main(a):
    build(a.folder, n=a.n, per_country=a.per_country, radius_km=a.radius_km, seed=a.seed)
