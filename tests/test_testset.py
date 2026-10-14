"""geolock testset, with a fake Commons client (no network)."""
import csv
import io
import random

from PIL import Image

from geolock import testset
from geolock.geodata import GeoData


def _jpeg():
    buf = io.BytesIO()
    Image.new("RGB", (64, 48), (90, 120, 160)).save(buf, "JPEG")
    return buf.getvalue()


def _ii(title, w=1600, h=1200, mime="image/jpeg", cats="Streets in Paris"):
    return {"mime": mime, "width": w, "height": h, "thumburl": f"https://x/{title}",
            "descriptionurl": f"https://commons/{title}",
            "extmetadata": {"LicenseShortName": {"value": "CC BY-SA 4.0"},
                            "LicenseUrl": {"value": "https://creativecommons.org/licenses/by-sa/4.0"},
                            "Artist": {"value": '<a href="/wiki/User:Ann">Ann</a>'},
                            "Categories": {"value": cats}}}


class FakeCommons:
    """Every search returns one map, one tiny photo and one good photo at the anchor."""

    def __init__(self):
        self.n = 0

    def near(self, lat, lon, radius_m=10000, limit=40):
        self.n += 1
        k = self.n
        return [{"title": f"File:Map of town {k}.jpg", "lat": lat, "lon": lon},
                {"title": f"File:Tiny {k}.jpg", "lat": lat, "lon": lon},
                {"title": f"File:Main street {k}.jpg", "lat": lat, "lon": lon}]

    def info(self, titles, width=1280):
        out = {}
        for t in titles:
            out[t] = _ii(t, w=300, h=200) if "Tiny" in t else _ii(t)
        return out

    def download(self, url):
        return _jpeg()


def test_usable_filters_maps_small_and_non_photos():
    assert testset.usable("File:Main street.jpg", _ii("a"))
    assert testset.usable("File:Maple trees in autumn.jpg", _ii("a"))
    assert testset.usable("File:Plantation road.jpg", _ii("a"))
    assert not testset.usable("File:Map of Lyon.jpg", _ii("a"))
    assert not testset.usable("File:Coat of arms of Bern.jpg", _ii("a"))
    assert not testset.usable("File:Street.jpg", _ii("a", cats="Maps of France"))
    assert not testset.usable("File:Street.jpg", _ii("a", w=500))
    assert not testset.usable("File:Street.png", _ii("a", mime="image/png"))


def test_quotas_spread_and_capped():
    rng = random.Random(0)
    cities = {"US": [(0, 0)] * 10000, "FR": [(0, 0)] * 2500, "LI": [(0, 0)] * 4}
    q = testset.country_quotas(cities, 12, 6, rng)
    assert sum(q.values()) == 12 and max(q.values()) <= 6
    assert q["US"] >= q["FR"] >= q.get("LI", 0)


def test_build_writes_photos_labels_and_credits(tmp_path):
    geo = GeoData()
    rows = testset.build(tmp_path, n=6, per_country=1, seed=1, client=FakeCommons(), geo=geo)
    assert len(rows) == 6
    with open(tmp_path / "labels.csv", encoding="utf-8") as f:
        labels = list(csv.DictReader(f))
    assert [r["file"] for r in labels] == [r["file"] for r in rows]
    for r in labels:
        assert (tmp_path / r["file"]).exists()
        assert r["title"].startswith("File:Main street")
        assert r["author"] == "Ann" and r["license"] == "CC BY-SA 4.0"
        assert geo.describe(float(r["lat"]), float(r["lon"]))["country_code"] == r["country"]
    assert len({r["country"] for r in labels}) == 6
    credits = (tmp_path / "ATTRIBUTION.md").read_text(encoding="utf-8")
    assert "Ann" in credits and "CC BY-SA 4.0" in credits

    # Running again tops up rather than re-downloading.
    more = testset.build(tmp_path, n=6, per_country=1, seed=1, client=FakeCommons(), geo=geo)
    assert len(more) >= 6 and len({r["file"] for r in more}) == len(more)
