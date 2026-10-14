"""End-to-end test; runs only when models have been set up."""
import numpy as np
import pytest
from PIL import Image

from geolock.config import MODELS_DIR

pytestmark = pytest.mark.skipif(not (MODELS_DIR / "gallery.npz").exists(),
                                reason="models not set up (python -m geolock.setup_models)")


@pytest.fixture(scope="module")
def engine():
    from geolock.engine import Geolocator
    return Geolocator(device="CPU")


def test_locate_returns_ranked_guesses(engine):
    r = engine.locate(Image.new("RGB", (800, 600), (90, 130, 170)), use_ocr=False)
    conf = [g["confidence"] for g in r["guesses"]]
    assert conf == sorted(conf, reverse=True) and 0 < sum(conf) <= 1.0001
    assert all("why" in g and "country" in g for g in r["guesses"])


@pytest.mark.parametrize("lat,lon,code", [(48.8566, 2.3522, "FR"), (35.0116, 135.7681, "JP"),
                                          (-1.2864, 36.8172, "KE")])
def test_fusion_recovers_a_known_location(engine, lat, lon, code, monkeypatch):
    """Feed the GeoCLIP query for a known place; the top guess must land there."""
    from geolock.geodata import haversine_km
    from geolock.locenc import normalize
    q = normalize(engine.loc_encoder(np.array([[lat, lon]]))[0])
    monkeypatch.setattr(engine, "geoclip_query", lambda e: q)
    g = engine.locate(Image.new("RGB", (640, 480)), use_ocr=False)["guesses"][0]
    assert g["country_code"] == code and haversine_km(g["lat"], g["lon"], lat, lon) < 25


def test_posterior_is_normalised_and_temperature_spreads_it(engine):
    from geolock.locenc import normalize
    q = normalize(engine.loc_encoder(np.array([[48.85, 2.35]]))[0])
    p_clip = np.full(len(engine.geo.country_codes), 1 / len(engine.geo.country_codes))
    sharp, _, _ = engine.posterior(q, p_clip, [], temperature=1.0)
    soft, _, _ = engine.posterior(q, p_clip, [], temperature=4.0)
    assert np.exp(sharp).sum() == pytest.approx(1, abs=1e-6)
    assert np.exp(soft).max() < np.exp(sharp).max()
