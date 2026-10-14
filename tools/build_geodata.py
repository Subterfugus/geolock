"""Build the compact, bundled geodata files from Natural Earth (public domain).

Run once by the maintainer; the outputs are committed under geolock/data/.

    python tools/build_geodata.py <dir with ne_50m_admin_0_countries.geojson and ne_10m_admin_1_states_provinces.geojson>
"""
import json
import sys
from pathlib import Path

from shapely.geometry import mapping, shape

OUT = Path(__file__).resolve().parent.parent / "geolock" / "data"


def _round(obj, nd):
    if isinstance(obj, float):
        return round(obj, nd)
    if isinstance(obj, (list, tuple)):
        return [_round(o, nd) for o in obj]
    if isinstance(obj, dict):
        return {k: _round(v, nd) for k, v in obj.items()}
    return obj


def simplify(features, tol, nd, props_fn):
    out = []
    for f in features:
        geom = shape(f["geometry"]).simplify(tol, preserve_topology=True)
        if geom.is_empty:
            continue
        out.append({"type": "Feature", "properties": props_fn(f["properties"]),
                    "geometry": _round(mapping(geom), nd)})
    return {"type": "FeatureCollection", "features": out}


def country_code(p):
    code = p["ISO_A2_EH"]
    if code in ("-99", None, ""):
        code = p["ADM0_A3"]  # Somaliland, N. Cyprus, Siachen: keep a unique code
    return code


def main(src):
    src = Path(src)
    countries = json.loads((src / "ne_50m_admin_0_countries.geojson").read_text())
    fc = simplify(countries["features"], 0.02, 3, lambda p: {
        "iso2": country_code(p), "name": p["NAME"], "continent": p["CONTINENT"],
        "subregion": p["SUBREGION"], "lx": round(p["LABEL_X"], 2), "ly": round(p["LABEL_Y"], 2),
        "minlabel": p["MIN_LABEL"]})
    (OUT / "countries.geojson").write_text(json.dumps(fc, separators=(",", ":")))

    admin1 = json.loads((src / "ne_10m_admin_1_states_provinces.geojson").read_text())
    fa = simplify(admin1["features"], 0.03, 3, lambda p: {
        "name": p["name"], "iso2": p["iso_a2"], "type": p["type_en"]})
    (OUT / "admin1.geojson").write_text(json.dumps(fa, separators=(",", ":")))
    for name in ("countries.geojson", "admin1.geojson"):
        print(name, (OUT / name).stat().st_size // 1024, "KB")


if __name__ == "__main__":
    main(sys.argv[1])
