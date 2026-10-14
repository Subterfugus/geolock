"""Fast tests that need no downloaded models."""
import numpy as np
import pytest
from PIL import Image

from geolock.clues import Clue
from geolock.engine import make_crops
from geolock.exif import exif_clues
from geolock.geodata import GeoData, haversine_km, weighted_center
from geolock.locenc import equal_earth
from geolock.ocr import TextReader
from geolock.vlm import parse, vlm_clues


@pytest.fixture(scope="module")
def geo():
    return GeoData()


def test_country_lookup(geo):
    idx = geo.countries.lookup([48.8566, 35.68, -33.87, 0.0], [2.3522, 139.69, 151.21, -30.0])
    codes = [geo.country_codes[i] if i >= 0 else None for i in idx]
    assert codes == ["FR", "JP", "AU", None]


def test_describe_names_region_and_place(geo):
    d = geo.describe(52.52, 13.405)
    assert d["country_code"] == "DE" and d["region"] == "Berlin"
    assert d["place"]["km"] < 10


def test_distance_and_center():
    assert abs(haversine_km(51.5074, -0.1278, 48.8566, 2.3522) - 344) < 3
    lat, lon = weighted_center(np.array([0.0, 0.0]), np.array([179.0, -179.0]), np.array([1, 1]))
    assert abs(lat) < 1e-6 and abs(abs(lon) - 180) < 1e-6


def test_equal_earth_origin():
    assert np.allclose(equal_earth(np.array([[0.0, 0.0]])), 0)


def test_crops_shape_any_aspect():
    for size in [(1200, 800), (600, 1400), (224, 224)]:
        x = make_crops(Image.new("RGB", size, (10, 200, 30)))
        assert x.shape == (4, 3, 224, 224) and x.dtype == np.float32


def test_clue_likelihood_prefers_listed_countries():
    c = Clue(kind="x", title="t", strength=0.8, countries={"DE": 1, "AT": 0.5}, background=0.1)
    ll = c.country_loglik(["DE", "AT", "FR"])
    assert ll[0] == pytest.approx(0) and ll[0] > ll[1] > ll[2]
    assert Clue(kind="x", title="t").country_loglik(["DE"]) is None


def test_text_patterns():
    r = TextReader()
    kinds = {c.kind: c for c in r._patterns("Visit www.example. co.uk or call +49 30 123, 5 € only, 30 mph")}
    assert set(kinds) >= {"domain", "phone", "currency", "units"}
    assert "GB" in kinds["domain"].countries and "DE" in kinds["phone"].countries


def test_language_clue():
    r = TextReader()
    clues = r.clues([{"text": "Öffnungszeiten täglich von sieben bis achtzehn Uhr geöffnet", "score": 0.9, "box": []}])
    lang = [c for c in clues if c.kind == "language"]
    assert lang and lang[0].countries.get("DE") == 1


def test_timezone_clue_peaks_near_offset():
    (c,) = exif_clues({"utc_offset": "+09:00"})
    assert c.point_fn(35.0, 135.0) > 0.9 and c.point_fn(40.0, -74.0) < 0.01


def test_vlm_json_parsing():
    raw = 'Sure! {"clues":[{"clue":"Cyrillic signs","suggests":"Russia"}],"driving_side":"right",' \
          '"countries":[{"country":"Russia","iso2":"RU","probability":0.6},],"region_guess":"Siberia"}'
    data = parse(raw)
    assert data["countries"][0]["iso2"] == "RU"
    clues = vlm_clues(data, raw, lambda n: None, ["RU", "GB", "JP"])
    side = [c for c in clues if c.kind == "driving"][0]
    assert set(side.countries) == {"RU"}
    guess = [c for c in clues if c.kind == "vlm_guess"][0]
    assert guess.countries == {"RU": 1.0}


def test_heic_photos_open(tmp_path):
    pytest.importorskip("pillow_heif")
    import geolock.engine  # registers the HEIF opener
    p = tmp_path / "x.heic"
    Image.new("RGB", (64, 48), (200, 10, 10)).save(p)
    assert Image.open(p).size == (64, 48)
