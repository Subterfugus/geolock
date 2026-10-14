"""Offline geography: country / region lookup and nearest named place."""
import csv
import json
import math
from functools import cached_property
from pathlib import Path

import numpy as np

DATA = Path(__file__).resolve().parent / "data"
EARTH_KM = 6371.0088


def haversine_km(lat1, lon1, lat2, lon2):
    lat1, lon1, lat2, lon2 = map(np.radians, (lat1, lon1, lat2, lon2))
    a = (np.sin((lat2 - lat1) / 2) ** 2
         + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2)
    return 2 * EARTH_KM * np.arcsin(np.sqrt(np.clip(a, 0, 1)))


def to_xyz(lat, lon):
    lat, lon = np.radians(lat), np.radians(lon)
    return np.stack([np.cos(lat) * np.cos(lon), np.cos(lat) * np.sin(lon), np.sin(lat)], -1)


def weighted_center(lat, lon, w):
    """Spherical weighted mean, safe across the antimeridian."""
    v = (to_xyz(lat, lon) * np.asarray(w)[:, None]).sum(0)
    v /= np.linalg.norm(v) + 1e-12
    return math.degrees(math.asin(v[2])), math.degrees(math.atan2(v[1], v[0]))


def _cities_csv():
    import importlib.util
    spec = importlib.util.find_spec("reverse_geocoder")
    if spec is None or not spec.submodule_search_locations:
        return None
    path = Path(list(spec.submodule_search_locations)[0]) / "rg_cities1000.csv"
    return path if path.exists() else None


class _Layer:
    def __init__(self, path):
        from shapely import STRtree
        from shapely.geometry import shape
        fc = json.loads(Path(path).read_text(encoding="utf-8"))
        self.props = [f["properties"] for f in fc["features"]]
        self.geoms = [shape(f["geometry"]) for f in fc["features"]]
        self.tree = STRtree(self.geoms)

    def lookup(self, lat, lon, max_deg=0.5):
        """Index of the polygon containing each point (or nearest within max_deg), -1 if none."""
        import shapely
        lat = np.atleast_1d(np.asarray(lat, dtype=float))
        lon = np.atleast_1d(np.asarray(lon, dtype=float))
        pts = shapely.points(lon, lat)
        out = np.full(len(pts), -1, dtype=np.int32)
        pi, gi = self.tree.query(pts, predicate="intersects")
        out[pi] = gi
        miss = np.where(out < 0)[0]
        if len(miss) and max_deg:
            pi, gi = self.tree.query_nearest(pts[miss], max_distance=max_deg)
            out[miss[pi]] = gi
        return out


class GeoData:
    @cached_property
    def countries(self):
        return _Layer(DATA / "countries.geojson")

    @cached_property
    def admin1(self):
        return _Layer(DATA / "admin1.geojson")

    @cached_property
    def country_codes(self):
        return [p["iso2"] for p in self.countries.props]

    @cached_property
    def country_names(self):
        return [p["name"] for p in self.countries.props]

    @cached_property
    def code_to_index(self):
        return {c: i for i, c in enumerate(self.country_codes)}

    def country_name(self, code):
        i = self.code_to_index.get(code)
        return self.country_names[i] if i is not None else code

    @cached_property
    def _cities(self):
        from scipy.spatial import cKDTree
        path = _cities_csv()
        if path is None:
            return None
        lat, lon, rows = [], [], []
        with open(path, encoding="utf-8") as f:
            for r in csv.DictReader(f):
                lat.append(float(r["lat"]))
                lon.append(float(r["lon"]))
                rows.append((r["name"], r["admin1"], r["cc"]))
        lat, lon = np.array(lat), np.array(lon)
        return cKDTree(to_xyz(lat, lon)), lat, lon, rows

    def nearest_place(self, lat, lon):
        if self._cities is None:
            return None
        tree, clat, clon, rows = self._cities
        _, i = tree.query(to_xyz(np.array(lat), np.array(lon)))
        name, admin1, cc = rows[i]
        return {"name": name, "admin1": admin1, "cc": cc,
                "km": float(haversine_km(lat, lon, clat[i], clon[i]))}

    def places_near(self, lat, lon, radius_km):
        """(lat, lon) arrays of named places within radius_km, for snapping refinement."""
        if self._cities is None:
            return np.zeros(0), np.zeros(0)
        tree, clat, clon, _ = self._cities
        idx = tree.query_ball_point(to_xyz(np.array(lat), np.array(lon)), radius_km / EARTH_KM)
        idx = np.asarray(idx, dtype=int)
        return clat[idx], clon[idx]

    def describe(self, lat, lon):
        ci = int(self.countries.lookup(lat, lon)[0])
        ai = int(self.admin1.lookup(lat, lon, max_deg=0.3)[0])
        country = self.countries.props[ci] if ci >= 0 else None
        region = self.admin1.props[ai]["name"] if ai >= 0 else None
        return {
            "country_code": country["iso2"] if country else None,
            "country": country["name"] if country else "Open water",
            "continent": country["continent"] if country else None,
            "region": region,
            "place": self.nearest_place(lat, lon),
        }
