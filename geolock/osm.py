"""Look up text read in the photo on OpenStreetMap (optional, off by default).

A shop name, street name or company name read off a sign often exists in only a handful
of places. GeoLock asks OpenStreetMap's free place search (Nominatim) where that name
appears, first in the countries GeoLock already favours and then anywhere, and turns a
short list of hits into a clue with a bump around each hit. Names found in many places
("Pharmacy", "Hotel") say nothing and are dropped.

What is sent: the text lines themselves and a list of country codes, nothing else. The
photo never leaves the machine. Nominatim's usage policy asks for at most one request per
second and an identifying User-Agent; GeoLock sends at most MAX_QUERIES (x2) per photo.
"""
import json
import re
import time
import unicodedata
import urllib.parse
import urllib.request

import numpy as np

from .clues import Clue
from .geodata import haversine_km

URL = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "GeoLock/0.4 (offline photo geolocator; desktop app)"
MAX_QUERIES = 3
MAX_HITS = 8      # more distinct places than this: too common a name to mean anything
SIGMA_KM = 20.0   # a hit vouches for its surroundings, not just one building
TIMEOUT_S = 6

# Words on signs everywhere; a line made only of these is not worth a lookup.
GENERIC = set("""
stop exit entrance open closed sale parking park hotel pharmacy apotheke farmacia bank
bar cafe coffee restaurant pizza shop store market supermarket bakery police taxi toilet
toilets wc bus tram metro station centre center city street road avenue only way one no
in out push pull welcome free wifi atm post office school hospital church museum
""".split())

_last_call = [0.0]


def _norm(text):
    s = unicodedata.normalize("NFKC", str(text)).strip()
    return re.sub(r"\s+", " ", s)


def candidates(ocr_lines, max_queries=MAX_QUERIES):
    """The OCR lines worth looking up: confident, with at least four letters, not a bare
    number or a generic sign word. Best (most confident, longest) first, no repeats."""
    seen, out = set(), []
    for l in sorted(ocr_lines or [], key=lambda l: -float(l.get("score", 0)) * len(str(l.get("text", "")))):
        text = _norm(l.get("text", ""))
        letters = sum(ch.isalpha() for ch in text)
        words = [w for w in re.findall(r"\w+", text.casefold()) if not w.isdigit()]
        if (float(l.get("score", 0)) < 0.7 or letters < 4 or len(text) > 60 or not words
                or all(w in GENERIC for w in words)):
            continue
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(text)
        if len(out) >= max_queries:
            break
    return out


def search(text, countries=(), opener=None):
    """Nominatim hits for `text`: [(lat, lon, label)]. Raises on network errors."""
    params = {"q": text, "format": "jsonv2", "limit": str(MAX_HITS + 2)}
    if countries:
        params["countrycodes"] = ",".join(c.lower() for c in countries)
    wait = 1.05 - (time.monotonic() - _last_call[0])  # Nominatim: at most 1 request/s
    if wait > 0:
        time.sleep(wait)
    req = urllib.request.Request(URL + "?" + urllib.parse.urlencode(params),
                                 headers={"User-Agent": USER_AGENT, "Accept-Language": "en"})
    try:
        with (opener or urllib.request.urlopen)(req, timeout=TIMEOUT_S) as r:
            data = json.loads(r.read().decode("utf-8"))
    finally:
        _last_call[0] = time.monotonic()
    hits = []
    for h in data if isinstance(data, list) else []:
        try:
            hits.append((float(h["lat"]), float(h["lon"]), str(h.get("display_name", ""))[:120]))
        except (KeyError, TypeError, ValueError):
            continue
    return hits


def _distinct(hits, km=5.0):
    """Hits merged when closer than `km` (one shop listed as node and building)."""
    out = []
    for h in hits:
        if all(haversine_km(h[0], h[1], o[0], o[1]) > km for o in out):
            out.append(h)
    return out


def osm_clues(ocr_lines, countries=(), opener=None):
    """Clues from looking up the photo's text on OpenStreetMap. countries: iso2 codes to
    search first (GeoLock's top countries); if a name is not found there it is searched
    worldwide. Never raises: a failed lookup becomes an informational clue."""
    texts = candidates(ocr_lines)
    if not texts:
        return []
    clues = []
    for text in texts:
        try:
            hits = search(text, countries, opener) if countries else []
            where = "near GeoLock's guesses"
            if not hits:
                hits, where = search(text, (), opener), "worldwide"
        except Exception as e:
            return clues + [Clue(kind="osm", title="OpenStreetMap lookup failed",
                                 detail=f"{type(e).__name__}: {e}"[:200])]
        spots = _distinct(hits)
        if not spots or len(spots) > MAX_HITS:
            continue
        pts = [(la, lo) for la, lo, _ in spots]

        def point_fn(plat, plon, pts=pts):
            plat, plon = np.asarray(plat, dtype=np.float64), np.asarray(plon, dtype=np.float64)
            best = np.zeros(np.broadcast(plat, plon).shape)
            for la, lo in pts:
                best = np.maximum(best, np.exp(-0.5 * (haversine_km(la, lo, plat, plon) / SIGMA_KM) ** 2))
            return best

        names = "; ".join(label.split(",")[0] + ", " + ", ".join(label.split(",")[-2:]).strip()
                          for _, _, label in spots[:3])
        n = len(spots)
        clues.append(Clue(
            kind="osm", title=f"“{text}” is on OpenStreetMap in {n} place{'s' if n > 1 else ''}",
            detail=f"Found {where}: {names}" + (" …" if n > 3 else "") + ".",
            # one place: strong; a few: each is only one candidate
            strength=0.85 if n == 1 else 0.65 if n <= 3 else 0.45, point_fn=point_fn))
    return clues
