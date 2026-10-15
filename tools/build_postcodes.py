"""Build postcodes.npz (the postcode list GeoLock's address reader looks codes up in)
from GeoNames' free allCountries.zip (about 16 MB, CC BY 4.0):

    https://download.geonames.org/export/zip/allCountries.zip

Usage: python tools/build_postcodes.py path/to/allCountries.zip [out.npz ...]
Writes to geolock/desktop/bundled/postcodes.npz and models/postcodes.npz by default.

One row per (country, postcode): the mean position of the places using it, and the
normalised names of those places and their first two admin levels (for "75008 Paris").
"""
import io
import sys
import zipfile
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from geolock.geodata import norm_name  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = [ROOT / "geolock" / "desktop" / "bundled" / "postcodes.npz", ROOT / "models" / "postcodes.npz"]


def build(zip_path):
    rows = {}
    with zipfile.ZipFile(zip_path) as z:
        with z.open("allCountries.txt") as f:
            for line in io.TextIOWrapper(f, encoding="utf-8"):
                p = line.rstrip("\n").split("\t")
                if len(p) < 11 or not p[9] or not p[10]:
                    continue
                cc, code = p[0].upper(), p[1].strip().upper()
                if not code or " " in code and cc not in ("GB", "CA", "NL", "SE", "CZ", "SK", "GR"):
                    continue
                try:
                    lat, lon = float(p[9]), float(p[10])
                except ValueError:
                    continue
                r = rows.setdefault(f"{cc} {code}", [0.0, 0.0, 0, set()])
                r[0] += lat
                r[1] += lon
                r[2] += 1
                for n in (p[2], p[3], p[5]):  # place, admin1, admin2
                    n = norm_name(n)
                    if n:
                        r[3].add(n)
    keys = sorted(rows)
    lat = np.array([rows[k][0] / rows[k][2] for k in keys], dtype=np.float32)
    lon = np.array([rows[k][1] / rows[k][2] for k in keys], dtype=np.float32)
    # place names first (most specific), longest first so "saint denis" beats "denis"
    names = ["|".join(sorted(rows[k][3], key=lambda n: -len(n))[:12]) for k in keys]
    return keys, lat, lon, names


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    keys, lat, lon, names = build(sys.argv[1])
    outs = [Path(p) for p in sys.argv[2:]] or DEFAULT_OUT
    for out in outs:
        out.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(out, keys=np.frombuffer("\n".join(keys).encode("utf-8"), dtype=np.uint8),
                            names=np.frombuffer("\n".join(names).encode("utf-8"), dtype=np.uint8),
                            lat=lat, lon=lon)
        print(f"{out}: {len(keys)} postcodes, {out.stat().st_size / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
