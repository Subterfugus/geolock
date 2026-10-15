"""Licence plates and postcodes read by OCR (geolock/addresses.py)."""
import sys
import zipfile
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from geolock.addresses import Postcodes, address_clues, plate_country, plate_clues, postcode_clues  # noqa: E402
from geolock.clues import Clue  # noqa: E402


def lines(*texts, score=0.95):
    return [{"text": t, "score": score} for t in texts]


@pytest.mark.parametrize("text,country", [
    ("AB-123-CD", "FR"), ("AB 123 CD", "IT"), ("AB12 CDE", "GB"), ("1234 BCD", "ES"),
    ("B MW 1234", "DE"), ("12-AB-34", "PT"), ("ABC1D23", "BR"), ("A123BC 77", "RU"),
    ("AA 1234 BB", "UA"), ("CJ 12 ABC", "RO"), ("ZH 123456", "CH"), ("34 ABC 123", "TR"),
    ("1-ABC-123", "BE"), ("191-D-12345", "IE"), ("12가 3456", "KR"), ("京A·12345", "CN"),
    ("MH 12 AB 1234", "IN"), ("ΙΚΑ-1234".replace("Ι", "I").replace("Κ", "K").replace("Α", "A"), "GR"),
])
def test_plate_formats(text, country):
    hit = plate_country(text)
    assert hit and hit[country] == 1, (text, hit)


@pytest.mark.parametrize("text", ["HOTEL", "1234", "OPEN 24 HOURS", "WWW.EXAMPLE.COM",
                                  "75008 PARIS", "Tel 0123 456 789", "2019"])
def test_ordinary_text_is_not_a_plate(text):
    assert plate_country(text) is None


def test_plate_clue_strength_and_duplicates():
    cl = plate_clues(lines("AB12 CDE", "ab12 cde", "AB-123-CD") + lines("XY99 ZZZ", score=0.3))
    assert [c.kind for c in cl] == ["plate", "plate"]  # duplicate and unsure reading dropped
    gb, fr = cl
    assert gb.countries == {"GB": 1} and 0 < gb.strength <= 0.6
    assert fr.countries["FR"] == 1 and fr.strength <= gb.strength
    ll = gb.country_loglik(["GB", "DE"])
    assert ll[0] > ll[1]


def _postcode_zip(tmp_path):
    rows = [  # country, code, place, admin1 name, admin1 code, admin2 name, ..., lat, lon
        ("FR", "75008", "Paris 08", "Île-de-France", "11", "Paris", "75", "", "", "48.8763", "2.3183"),
        ("DE", "75008", "Musterdorf", "Bayern", "BY", "", "", "", "", "48.0", "11.0"),
        ("DE", "10115", "Berlin", "Berlin", "BE", "", "", "", "", "52.5323", "13.3846"),
        ("NL", "1012", "Amsterdam", "Noord-Holland", "07", "", "", "", "", "52.3731", "4.8922"),
        ("PL", "00-950", "Warszawa", "Mazowieckie", "78", "", "", "", "", "52.2297", "21.0122"),
        ("GB", "SW1A", "London", "England", "ENG", "", "", "", "", "51.501", "-0.141"),
    ]
    z = tmp_path / "allCountries.zip"
    with zipfile.ZipFile(z, "w") as f:
        f.writestr("allCountries.txt", "".join("\t".join(r) + "\t4\n" for r in rows))
    return z


@pytest.fixture
def table(tmp_path):
    import build_postcodes
    keys, lat, lon, names = build_postcodes.build(_postcode_zip(tmp_path))
    out = tmp_path / "postcodes.npz"
    np.savez_compressed(out, keys=np.frombuffer("\n".join(keys).encode(), dtype=np.uint8),
                        names=np.frombuffer("\n".join(names).encode(), dtype=np.uint8), lat=lat, lon=lon)
    return Postcodes(out)


def test_postcode_table(table):
    assert table.get("DE", "10115") is not None and table.get("DE", "99999") is None
    assert sorted(table.keys[i][:2] for i in table.with_code("75008")) == ["DE", "FR"]
    assert "paris" in table.place_names(table.get("FR", "75008"))


def test_number_with_town_name_pins_the_town(table):
    cl = postcode_clues(lines("Rue du Faubourg", "75008 Paris"), table)
    assert len(cl) == 1 and cl[0].countries == {"FR": 1}
    pf = cl[0].point_fn(np.array([48.88, 52.5]), np.array([2.32, 13.4]))
    assert pf[0] > 0.9 and pf[1] < 1e-6


def test_town_name_on_the_next_line_counts(table):
    cl = postcode_clues(lines("10115", "Berlin Mitte"), table)
    assert cl and cl[0].countries == {"DE": 1}


def test_bare_number_says_nothing(table):
    assert postcode_clues(lines("75008"), table) == []
    assert postcode_clues(lines("Open 1000 to 1800"), table) == []


def test_distinctive_formats(table):
    cl = postcode_clues(lines("1012 AB Amsterdam", "00-950 Warszawa", "London SW1A 1AA"), table)
    by = {next(iter(c.countries)): c for c in cl}
    assert set(by) == {"NL", "PL", "GB"}
    assert all(c.point_fn is not None and c.strength == 0.8 for c in by.values())
    # a format that is not in the list is still a (weaker) country clue
    cl = postcode_clues(lines("M5V 3L9"), table)
    assert cl[0].countries == {"CA": 1} and cl[0].point_fn is None and cl[0].strength < 0.8


def test_without_the_list_formats_still_count():
    cl = postcode_clues(lines("1012 AB Amsterdam", "75008 Paris"), None)
    assert [next(iter(c.countries)) for c in cl] == ["NL"]


def test_address_clues_never_raises(monkeypatch):
    import geolock.addresses as ad
    monkeypatch.setattr(ad, "find_postcodes", lambda md=None: (_ for _ in ()).throw(OSError("x")))
    out = address_clues(lines("AB12 CDE"))
    assert [c.kind for c in out] == ["plate"]


def test_clue_scales():
    c = Clue(kind="plate", title="t", strength=0.5, countries={"GB": 1})
    assert c.fit_group == "text"
    assert c.scaled({"text": 1.5}) == 0.75 and c.scaled({"text": 4}) == 0.97
    assert c.scaled({"scene": 0}) == 0.5 and c.scaled(None) == 0.5
    assert Clue(kind="script", title="s", group="scene").fit_group == "scene"
    assert c.country_loglik(["GB"], 0) is None
