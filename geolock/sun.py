"""Daylight as a latitude clue: was the sun up where the photo could have been taken?

The camera's EXIF clock and time-zone offset give the exact moment (UTC) the photo was
taken. At that moment the sun is up over one half of the Earth and down over the other,
and the edge between them runs at an angle that depends on the date: on a June evening
the sun is still up in Oslo long after it has set in Rome. So a daylight photo at 21:45
local time in June can only have been taken far north; a night photo at 18:00 in
December rules out the far south. The time-zone clue already narrows the longitude; this
one narrows the latitude.

Shadows would say more (their direction gives the sun's bearing) but need to know which
way the camera faced, which photos without GPS almost never record, so they are not used.

Day or night is read from the pixels of the top of the photo (the sky, usually); indoor
photos and twilight are skipped because their brightness says nothing about the sun.
"""
import math
import re
from datetime import datetime, timedelta, timezone

import numpy as np

from .clues import Clue

DAY_LUMA = 115    # mean brightness (0-255) of the top of the photo for "daylight"
NIGHT_LUMA = 35   # and for "night"


def parse_utc(meta):
    """The photo's moment in UTC from EXIF DateTimeOriginal + OffsetTimeOriginal, or None."""
    when, off = meta.get("datetime"), meta.get("utc_offset")
    if not when or not off:
        return None
    try:
        local = datetime.strptime(str(when)[:19], "%Y:%m:%d %H:%M:%S")
        m = re.match(r"^([+-])(\d{2}):(\d{2})$", off)
        sign = 1 if m.group(1) == "+" else -1
        delta = timedelta(hours=int(m.group(2)), minutes=int(m.group(3)))
    except (ValueError, AttributeError):
        return None
    if local.year < 1990:  # an unset camera clock
        return None
    return (local - sign * delta).replace(tzinfo=timezone.utc)


def sun_elevation(utc, lat, lon):
    """Solar elevation in degrees at `utc` (aware datetime) for arrays of lat/lon.
    NOAA's low-precision formulas: within about 0.5 degrees, plenty for day vs night."""
    lat = np.radians(np.asarray(lat, dtype=np.float64))
    lon = np.asarray(lon, dtype=np.float64)
    day = utc.timetuple().tm_yday
    hours = utc.hour + utc.minute / 60 + utc.second / 3600
    g = 2 * math.pi / 365 * (day - 1 + (hours - 12) / 24)
    eqtime = 229.18 * (0.000075 + 0.001868 * math.cos(g) - 0.032077 * math.sin(g)
                       - 0.014615 * math.cos(2 * g) - 0.040849 * math.sin(2 * g))
    decl = (0.006918 - 0.399912 * math.cos(g) + 0.070257 * math.sin(g)
            - 0.006758 * math.cos(2 * g) + 0.000907 * math.sin(2 * g)
            - 0.002697 * math.cos(3 * g) + 0.00148 * math.sin(3 * g))
    solar_min = hours * 60 + eqtime + 4 * lon  # true solar time, minutes
    ha = np.radians(solar_min / 4 - 180)
    cos_zen = np.sin(lat) * math.sin(decl) + np.cos(lat) * math.cos(decl) * np.cos(ha)
    return 90 - np.degrees(np.arccos(np.clip(cos_zen, -1, 1)))


def light_level(img):
    """'day', 'night' or None (in between) from the top 40% of the photo."""
    im = img.convert("L")
    w, h = im.size
    top = np.asarray(im.crop((0, 0, w, max(1, int(0.4 * h)))).resize((64, 26)), dtype=np.float64)
    mean = top.mean()
    if mean >= DAY_LUMA:
        return "day"
    if mean <= NIGHT_LUMA and np.percentile(top, 90) < 90:  # dark sky, not a dark wall
        return "night"
    return None


def daylight_clue(img, meta, indoors=False):
    """A point clue on where the sun was up (or down) when the photo was taken, or None
    when there is no exact time, the photo is indoors or at twilight, or the answer is
    the same almost everywhere (nothing learned)."""
    utc = parse_utc(meta)
    if utc is None or indoors:
        return None
    level = light_level(img)
    if level is None:
        return None
    if level == "day":  # sun up, allowing a little for bright twilight
        def like(lat, lon, utc=utc):
            return 1 / (1 + np.exp(-(sun_elevation(utc, lat, lon) + 3) / 1.5))
    else:  # properly dark: the sun well below the horizon
        def like(lat, lon, utc=utc):
            return 1 / (1 + np.exp((sun_elevation(utc, lat, lon) + 8) / 2))
    # Is it informative? Check over all land-ish latitudes near the time-zone longitude.
    sign = 1 if meta["utc_offset"][0] == "+" else -1
    hh, mm = meta["utc_offset"][1:].split(":")
    centre = sign * (int(hh) + int(mm) / 60) * 15
    lat, lon = np.meshgrid(np.arange(-55, 71, 1.0), centre + np.arange(-20, 21, 2.0))
    ok = like(lat.ravel(), lon.ravel()) > 0.5
    if ok.mean() > 0.95 or ok.mean() < 0.02:
        return None  # the same everywhere in that time zone, or no place fits (bad clock)
    lats = lat.ravel()[ok]
    when = utc + timedelta(hours=sign * int(hh), minutes=sign * int(mm))
    span = f"{_deg(lats.min())} to {_deg(lats.max())}"
    word = "Daylight" if level == "day" else "Dark sky"
    return Clue(
        kind="sun", title=f"{word} at {when:%H:%M} on {when:%d %b} (UTC{meta['utc_offset']})",
        detail=(f"At that moment the sun was {'up' if level == 'day' else 'down'} in this time "
                f"zone only between about {span}. Assumes the camera clock was right."),
        strength=0.6, point_fn=like)


def _deg(x):
    return f"{abs(x):.0f}°{'N' if x >= 0 else 'S'}"
