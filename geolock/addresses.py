"""Licence plates and postcodes read in the photo.

OCR already reads plate and address text; this module says what it means.

Plates: a line that is exactly a plate in a known national format (`AB-123-CD` is France,
`AB12 CDE` is Britain, `12가 3456` is Korea) is a country clue. Cars cross borders and many
formats are shared, so a plate is a moderate clue, weaker when the format fits several
countries. Only formats distinctive enough not to match ordinary words or numbers are used.

Postcodes: a postcode in a distinctive national format (`SW1A 1AA`, `1012 AB`, `00-950`,
`〒100-0001`) is a country clue, and if it is in GeoNames' free postcode list it becomes a
point near that postcode. A plain 4 or 5 digit number is a postcode in dozens of countries,
so it counts only when the text next to it names the town that postcode belongs to
(`75008 Paris`, `10115 Berlin`); then it pins the photo to that town.

The postcode list (postcodes.npz, about 1.5 million postcodes) is built from GeoNames'
allCountries.zip by tools/build_postcodes.py. Without it, plates and postcode formats still
work; only the lookups are skipped.
"""
import re
import unicodedata
from bisect import bisect_left
from functools import lru_cache
from pathlib import Path

import numpy as np

from .clues import Clue
from .geodata import haversine_km, norm_name

SIGMA_KM = 8.0         # a postcode covers a town or a district, not a street
PLATE_STRENGTH = 0.55  # one plate, one country; lower when the format is shared
MIN_SCORE = 0.6        # OCR confidence below this is too unreliable for exact formats

# Romanian county codes, Swiss cantons, Indian states and Irish counties keep those formats
# from matching random letter-number strings.
_RO = "AB|AR|AG|BC|BH|BN|BT|BV|BR|BZ|CS|CL|CJ|CT|CV|DB|DJ|GL|GR|GJ|HR|HD|IL|IS|IF|MM|MH|MS|NT|OT|PH|SM|SJ|SB|SV|TR|TM|TL|VS|VL|VN|B"
_CH = "AG|AI|AR|BE|BL|BS|FR|GE|GL|GR|JU|LU|NE|NW|OW|SG|SH|SO|SZ|TG|TI|UR|VD|VS|ZG|ZH"
_IN = "AN|AP|AR|AS|BR|CG|CH|DD|DL|DN|GA|GJ|HP|HR|JH|JK|KA|KL|LA|LD|MH|ML|MN|MP|MZ|NL|OD|OR|PB|PY|RJ|SK|TN|TR|TS|UK|UP|WB"
_IE = "C|CE|CN|CW|D|DL|G|KE|KK|KY|L|LD|LH|LK|LM|LS|MH|MN|MO|OY|RN|SO|T|W|WH|WX|WW"
_CYR = "ABEKMHOPCTYX"  # Cyrillic plate letters, as OCR usually reads them (Latin look-alikes)

# (pattern on the whole normalised line, {country: weight}). Lines are upper-cased, with
# dashes unified and runs of spaces collapsed.
PLATES = [
    (r"[A-Z]{2}-\d{3}-[A-Z]{2}", {"FR": 1, "IT": 0.3, "SK": 0.3}),
    (r"[A-Z]{2} ?\d{3} ?[A-Z]{2}", {"IT": 1, "AR": 0.8, "FR": 0.5, "SK": 0.4}),
    (r"[A-Z]{2}\d{2} ?[A-Z]{3}", {"GB": 1}),
    (r"\d{4} ?[BCDFGHJKLMNPRSTVWXYZ]{3}", {"ES": 1}),
    (r"[A-ZÄÖÜ]{1,3}[ -][A-Z]{1,2} ?\d{1,4}[EH]?", {"DE": 1, "AT": 0.2}),
    (r"\d{2}-[A-Z]{2}-\d{2}|[A-Z]{2}-\d{2}-[A-Z]{2}|\d{2}-\d{2}-[A-Z]{2}|[A-Z]{2}-\d{2}-\d{2}", {"PT": 1, "NL": 0.5}),
    (r"\d{2}-[A-Z]{3}-\d|\d-[A-Z]{3}-\d{2}|[A-Z]-\d{3}-[A-Z]{2}|[A-Z]{2}-\d{3}-[A-Z]|[A-Z]{3}-\d{2}-[A-Z]|[A-Z]-\d{2}-[A-Z]{3}", {"NL": 1}),
    (r"[A-Z]{3}\d[A-Z]\d{2}", {"BR": 1}),
    (rf"[{_CYR}]\d{{3}}[{_CYR}]{{2}} ?\d{{2,3}}", {"RU": 1}),
    (rf"[{_CYR}I]{{2}} ?\d{{4}} ?[{_CYR}I]{{2}}", {"UA": 1, "BG": 0.6}),
    (rf"(?:{_RO}) \d{{2,3}} [A-Z]{{3}}", {"RO": 1}),
    (rf"(?:{_CH}) ?\d{{3,6}}", {"CH": 1}),
    (r"[A-Z]{3} ?\d{2}[A-Z0-9]", {"SE": 1, "LT": 0.4}),
    (r"[A-Z]{3}-\d{3}", {"FI": 1, "HU": 1}),
    (r"[A-Z]{2} [A-Z]{2}-\d{3}", {"HU": 1}),
    (r"[A-Z]{2} ?\d{5}", {"NO": 1, "DK": 1}),
    (rf"(?:{_IN}) ?\d{{1,2}} ?[A-Z]{{1,3}} ?\d{{4}}", {"IN": 1}),
    (r"(?:0[1-9]|[1-7]\d|8[01]) ?[A-Z]{1,3} ?\d{2,5}", {"TR": 1}),
    (r"[ABEZHIKMNOPTXY]{3}-\d{4}", {"GR": 1}),
    (r"\d[A-Z][0-9A-Z] ?\d{4}", {"CZ": 1}),
    (r"\d-[A-Z]{3}-\d{3}", {"BE": 1}),
    (rf"\d{{2,3}}-(?:{_IE})-\d{{1,6}}", {"IE": 1}),
    (r"\d{3} ?[A-Z]{3}", {"EE": 1}),
    (r"[A-Z]{2}-\d{4}", {"LV": 1}),
    (r"[A-Z]{3}-\d{2,3}-[A-Z0-9]", {"MX": 1}),
    (r"\d{2}[A-Z]\d?-\d{3}\.?\d{2}", {"VN": 1}),
    (r"[京津沪渝冀豫云辽黑湘皖鲁新苏浙赣鄂桂甘晋蒙陕吉闽贵粤青藏川宁琼][A-Z]·?[A-Z0-9]{5,6}", {"CN": 1}),
    (r"\d{2,3}[가-힣] ?\d{4}", {"KR": 1}),
    (r"\d{2,3} ?[ぁ-ん] ?\d{1,2}-\d{2}", {"JP": 1}),
]
_PLATES = [(re.compile(p), c) for p, c in PLATES]

# Distinctive postcode formats, searched anywhere in a line: (pattern, country, lookup key
# for the GeoNames list, which keeps only the outward part for GB and CA).
POSTCODES = [
    (r"\b([A-Z]{1,2}\d[A-Z\d]?) ?\d[A-Z]{2}\b", "GB", lambda m: m.group(1)),
    (r"\b([ABCEGHJ-NPRSTVXY]\d[A-Z]) ?\d[A-Z]\d\b", "CA", lambda m: m.group(1)),
    (r"\b([1-9]\d{3}) ?(?!SA|SD|SS|AM|PM|KM|CM|MM|KG|HP|KW|AD|BC)[A-Z]{2}\b", "NL", lambda m: m.group(1)),
    (r"\b(\d{2}-\d{3})\b", "PL", lambda m: m.group(1)),
    (r"\b(\d{4}-\d{3})\b", "PT", lambda m: m.group(1)),
    (r"\b(\d{5}-\d{3})\b", "BR", lambda m: m.group(1)),
    (r"〒 ?(\d{3}-\d{4})", "JP", lambda m: m.group(1)),
    (r"\b([AC-FHKNPRTV-Y]\d{2}|D6W) ?[0-9AC-FHKNPRTV-Y]{4}\b", "IE", lambda m: m.group(1)),
    (r"\b([A-Z]\d{4}[A-Z]{3})\b", "AR", lambda m: m.group(1)),
]
_POSTCODES = [(re.compile(p), cc, key) for p, cc, key in POSTCODES]
_NUMBER = re.compile(r"(?<![\d.,:/-])(\d{4,5})(?![\d.,:/-])")


def _line(text, upper=True):
    s = unicodedata.normalize("NFKC", str(text)).strip()
    s = s.upper() if upper else s
    s = re.sub(r"[‐-―−]", "-", s)
    s = re.sub(r"\s*-\s*", "-", s)
    return re.sub(r"\s+", " ", s)


def plate_country(text):
    """{country: weight} if `text` is exactly a plate in a known format, else None."""
    s = _line(text)
    if not (4 <= len(s) <= 13) or not re.search(r"\d", s) or not re.search(r"[^\d\s.-]", s):
        return None
    hit = {}
    for pat, countries in _PLATES:
        if pat.fullmatch(s):
            for c, w in countries.items():
                hit[c] = max(hit.get(c, 0), w)
    return hit or None


def plate_clues(lines):
    clues = []
    seen = set()
    for l in lines or []:
        if float(l.get("score", 1)) < MIN_SCORE:
            continue
        countries = plate_country(l.get("text", ""))
        key = _line(l.get("text", ""))
        if not countries or key in seen:
            continue
        seen.add(key)
        full = [c for c, w in countries.items() if w >= 1]
        names = ", ".join(sorted(countries, key=lambda c: -countries[c]))
        clues.append(Clue(
            kind="plate", title=f"Licence plate “{key}”",
            detail=f"The plate format fits {names}. Cars do cross borders.",
            strength=PLATE_STRENGTH if len(full) == 1 else PLATE_STRENGTH * 0.75,
            countries=countries, background=0.1))
    return clues


# ------------------------------------------------------------------ postcode list
class Postcodes:
    """GeoNames postcodes: sorted keys "CC code" with one point (the mean of the places
    using it) and the normalised names of those places and their regions."""

    def __init__(self, path):
        z = np.load(path)
        self.keys = bytes(z["keys"]).decode("utf-8").split("\n")
        self.names = bytes(z["names"]).decode("utf-8").split("\n")
        self.lat = z["lat"].astype(np.float64)
        self.lon = z["lon"].astype(np.float64)
        self._by_code = None

    def get(self, cc, code):
        """Row of postcode `code` in country `cc`, or None."""
        key = f"{cc} {code}"
        i = bisect_left(self.keys, key)
        return i if i < len(self.keys) and self.keys[i] == key else None

    def with_code(self, code):
        """Rows of every country that uses `code`."""
        if self._by_code is None:
            idx = {}
            for i, k in enumerate(self.keys):
                idx.setdefault(k[3:], []).append(i)
            self._by_code = idx
        return self._by_code.get(code, [])

    def place_names(self, row):
        return [n for n in self.names[row].split("|") if n]


def find_postcodes(models_dir=None):
    """The postcode list from the models folder or the app's bundled files, or None."""
    paths = []
    if models_dir:
        paths.append(Path(models_dir) / "postcodes.npz")
    try:
        from .desktop.modelsetup import bundled_dir
        paths.append(bundled_dir() / "postcodes.npz")
    except Exception:
        pass
    for p in paths:
        if p.exists():
            return _load(str(p))
    return None


@lru_cache(maxsize=2)
def _load(path):
    return Postcodes(path)


def _point_fn(pts):
    def point_fn(plat, plon, pts=pts):
        plat, plon = np.asarray(plat, dtype=np.float64), np.asarray(plon, dtype=np.float64)
        best = np.zeros(np.broadcast(plat, plon).shape)
        for la, lo in pts:
            best = np.maximum(best, np.exp(-0.5 * (haversine_km(la, lo, plat, plon) / SIGMA_KM) ** 2))
        return best
    return point_fn


def _named(names, words):
    """The first place name (all its words) found in the normalised word list."""
    joined = " " + " ".join(words) + " "
    for n in names:
        if len(n) >= 3 and f" {n} " in joined:
            return n
    return None


def postcode_clues(lines, table=None):
    """Clues from postcodes in the OCR lines. `table` is a Postcodes list or None."""
    good = [l for l in lines or [] if float(l.get("score", 1)) >= MIN_SCORE]
    clues, seen = [], set()
    for i, l in enumerate(good):
        s = _line(l.get("text", ""))
        if plate_country(s):
            continue  # a plate, not an address
        # 1. distinctive formats (letters in postcodes are capitals: "1012 AB", not "1000 to")
        for pat, cc, key in _POSTCODES:
            for m in pat.finditer(_line(l.get("text", ""), upper=False)):
                code = key(m)
                if (cc, code) in seen:
                    continue
                seen.add((cc, code))
                row = table.get(cc, code) if table else None
                if row is not None:
                    names = table.place_names(row)
                    clues.append(Clue(
                        kind="postcode", title=f"Postcode {m.group(0)} ({cc})",
                        detail=f"GeoNames places it at {names[0].title() if names else 'a known spot'}.",
                        strength=0.8, countries={cc: 1}, background=0.1,
                        point_fn=_point_fn([(table.lat[row], table.lon[row])])))
                else:
                    clues.append(Clue(
                        kind="postcode", title=f"Postcode format {m.group(0)} ({cc})",
                        detail=f"Looks like a {cc} postcode; not in the postcode list.",
                        strength=0.45, countries={cc: 1}, background=0.2))
        # 2. a plain 4-5 digit number with the town's name next to it
        if table is None:
            continue
        near = " ".join(_line(x.get("text", "")) for x in good[max(0, i - 1):i + 2])
        words = norm_name(near).split()
        for m in _NUMBER.finditer(s):
            code = m.group(1)
            pts, where = [], []
            for row in table.with_code(code):
                hit = _named(table.place_names(row), words)
                if hit:
                    pts.append((table.lat[row], table.lon[row]))
                    where.append((table.keys[row][:2], hit))
            if not pts or len(pts) > 4 or ("num", code) in seen or any(code == k for _, k in seen):
                continue
            seen.add(("num", code))
            ccs = sorted({c for c, _ in where})
            label = "; ".join(f"{n.title()} ({c})" for c, n in where[:3])
            clues.append(Clue(
                kind="postcode", title=f"Postcode {code} with the town's name",
                detail=f"{code} next to the name of the town it belongs to: {label}.",
                strength=0.85 if len(ccs) == 1 else 0.7, countries={c: 1 for c in ccs},
                background=0.05, point_fn=_point_fn(pts)))
    return clues


def address_clues(lines, models_dir=None):
    """Plate and postcode clues for the OCR lines. Never raises."""
    try:
        out = plate_clues(lines)
    except Exception:
        out = []
    try:
        table = find_postcodes(models_dir) if lines else None
        out += postcode_clues(lines, table)
    except Exception:
        pass
    return out
