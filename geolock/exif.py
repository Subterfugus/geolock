"""Read location-relevant EXIF metadata (GPS, time zone, camera)."""
import math
import re

import numpy as np
from PIL import Image

from .clues import Clue


def _ratio(v):
    try:
        return float(v)
    except (TypeError, ValueError, ZeroDivisionError):
        try:
            return v[0] / v[1]
        except Exception:
            return float("nan")


def _dms(vals, ref):
    d, m, s = (_ratio(x) for x in vals)
    deg = d + m / 60 + s / 3600
    return -deg if ref in ("S", "W") else deg


def read_exif(img: Image.Image):
    out = {}
    try:
        ex = img.getexif()
    except Exception:
        return out
    if not ex:
        return out
    make, model = ex.get(0x010F), ex.get(0x0110)
    if make or model:
        out["camera"] = " ".join(str(x).strip("\x00 ") for x in (make, model) if x)
    sub = ex.get_ifd(0x8769) or {}
    when = sub.get(0x9003) or ex.get(0x0132)
    if when:
        out["datetime"] = str(when).strip("\x00 ")
    offset = sub.get(0x9011) or sub.get(0x9010)
    if offset and re.match(r"^[+-]\d{2}:\d{2}$", str(offset).strip()):
        out["utc_offset"] = str(offset).strip()
    gps = ex.get_ifd(0x8825) or {}
    try:
        if 2 in gps and 4 in gps:
            lat = _dms(gps[2], gps.get(1, "N"))
            lon = _dms(gps[4], gps.get(3, "E"))
            if math.isfinite(lat) and math.isfinite(lon) and (lat, lon) != (0.0, 0.0):
                out["gps"] = {"lat": round(lat, 6), "lon": round(lon, 6)}
    except Exception:
        pass
    return out


def exif_clues(meta):
    clues = []
    if "utc_offset" in meta:
        sign = 1 if meta["utc_offset"][0] == "+" else -1
        hh, mm = meta["utc_offset"][1:].split(":")
        hours = sign * (int(hh) + int(mm) / 60)
        # Daylight saving puts clocks an hour ahead of the sun for half the year.
        centre = (hours - 0.5) * 15.0

        def tz_like(lat, lon, centre=centre):
            d = (np.asarray(lon) - centre + 180) % 360 - 180
            return np.exp(-0.5 * (d / 25.0) ** 2)

        side = "E" if centre >= 0 else "W"
        clues.append(Clue(
            kind="timezone", title=f"Camera clock set to UTC{meta['utc_offset']}",
            detail=(f"The photo's EXIF time-zone offset points to longitudes around "
                    f"{abs(centre):.0f}°{side} (time zones are wide and follow politics, "
                    f"so this is soft evidence)."),
            strength=0.6, point_fn=tz_like))
    if "camera" in meta:
        clues.append(Clue(kind="exif", title=f"Camera: {meta['camera']}",
                          detail="Camera model from EXIF (informational)."))
    return clues
