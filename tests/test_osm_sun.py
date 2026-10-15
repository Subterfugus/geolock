"""OpenStreetMap lookup of sign text (fake Nominatim) and the daylight clue."""
import io
import json
from datetime import datetime, timezone

import numpy as np
import pytest
from PIL import Image

from geolock import osm
from geolock.sun import daylight_clue, light_level, parse_utc, sun_elevation


class FakeNominatim:
    """Answers like Nominatim from a {query: [(lat, lon, name)]} table; records requests."""

    def __init__(self, table, fail=False):
        self.table, self.fail, self.requests = table, fail, []

    def __call__(self, req, timeout=None):
        from urllib.parse import parse_qs, urlparse
        if self.fail:
            raise OSError("no network")
        q = parse_qs(urlparse(req.full_url).query)
        self.requests.append({"q": q["q"][0], "countries": q.get("countrycodes", [""])[0],
                              "ua": req.get_header("User-agent")})
        key = (q["q"][0], q.get("countrycodes", [""])[0])
        hits = self.table.get(key, self.table.get(q["q"][0], []))
        body = json.dumps([{"lat": str(a), "lon": str(b), "display_name": n} for a, b, n in hits])
        return io.BytesIO(body.encode())


@pytest.fixture(autouse=True)
def no_wait(monkeypatch):
    monkeypatch.setattr(osm.time, "sleep", lambda s: None)


def line(text, score=0.95):
    return {"text": text, "score": score, "box": [[0, 0], [10, 0], [10, 5], [0, 5]]}


def test_only_specific_confident_text_is_looked_up():
    lines = [line("PHARMACY"), line("Bäckerei Schmitz"), line("12345"), line("Hotel Bar"),
             line("Kaufhof Galeria", 0.5), line("bäckerei schmitz"), line("ab")]
    assert osm.candidates(lines) == ["Bäckerei Schmitz"]


def test_a_rare_name_becomes_a_strong_point_clue():
    fake = FakeNominatim({("Bäckerei Schmitz", "de,at"): [
        (50.93, 6.95, "Bäckerei Schmitz, Hohe Straße, Köln, Nordrhein-Westfalen, Deutschland")]})
    (c,) = osm.osm_clues([line("Bäckerei Schmitz")], ["DE", "AT"], opener=fake)
    assert c.kind == "osm" and c.strength == 0.85 and "1 place" in c.title
    near, far = c.point_fn(np.array([50.95, 48.2]), np.array([6.96, 16.4]))
    assert near > 0.9 and far < 1e-6
    assert fake.requests[0]["ua"].startswith("GeoLock")


def test_searches_worldwide_when_not_found_nearby_and_drops_common_names():
    common = [(i, i, f"Spar {i}") for i in range(10)]
    fake = FakeNominatim({("Rossmann Drogerie", ""): [(52.5, 13.4, "Rossmann, Berlin, Deutschland")],
                          "Spar Express": common})
    clues = osm.osm_clues([line("Rossmann Drogerie"), line("Spar Express")], ["PL"], opener=fake)
    assert [c.title.split("”")[0] for c in clues] == ["“Rossmann Drogerie"]
    assert "worldwide" in clues[0].detail
    assert [r["countries"] for r in fake.requests[:2]] == ["pl", ""]


def test_lookup_failure_is_shown_not_raised():
    (c,) = osm.osm_clues([line("Bäckerei Schmitz")], ["DE"], opener=FakeNominatim({}, fail=True))
    assert c.title == "OpenStreetMap lookup failed" and c.strength == 0
    assert osm.osm_clues([], ["DE"]) == []


def test_sun_elevation_matches_known_cases():
    noon = datetime(2026, 6, 21, 12, 0, tzinfo=timezone.utc)
    assert sun_elevation(noon, 23.44, 0.0) == pytest.approx(90, abs=1)   # overhead at the tropic
    assert sun_elevation(noon, 0.0, 180.0) < -60                          # midnight opposite
    late = datetime(2026, 6, 21, 19, 45, tzinfo=timezone.utc)            # 21:45 in Berlin
    oslo, rome = sun_elevation(late, [59.9, 41.9], [10.75, 12.5])
    assert oslo > 0 > rome


def _photo(brightness):
    return Image.new("RGB", (400, 300), (brightness,) * 3)


def test_daylight_late_on_a_june_evening_points_north():
    meta = {"datetime": "2026:06:21 21:45:00", "utc_offset": "+02:00"}
    assert parse_utc(meta) == datetime(2026, 6, 21, 19, 45, tzinfo=timezone.utc)
    assert light_level(_photo(200)) == "day" and light_level(_photo(10)) == "night"
    assert light_level(_photo(80)) is None
    c = daylight_clue(_photo(200), meta)
    assert c and c.kind == "sun" and "21:45" in c.title
    oslo, rome = c.point_fn(np.array([59.9, 41.9]), np.array([10.75, 12.5]))
    assert oslo > 0.9 and rome < 0.1
    # no offset, indoors, twilight, or a broken clock: no clue
    assert daylight_clue(_photo(200), {"datetime": meta["datetime"]}) is None
    assert daylight_clue(_photo(200), meta, indoors=True) is None
    assert daylight_clue(_photo(80), meta) is None
    assert daylight_clue(_photo(200), dict(meta, datetime="1980:01:01 00:00:00")) is None


def test_daylight_at_noon_says_nothing():
    meta = {"datetime": "2026:06:21 12:00:00", "utc_offset": "+02:00"}
    assert daylight_clue(_photo(200), meta) is None
