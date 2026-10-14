"""Evidence objects: one visible clue and what it implies about the location."""
from dataclasses import dataclass, field

import numpy as np


@dataclass
class Clue:
    kind: str                 # exif | ocr | language | script | scene | vlm | timezone ...
    title: str                # short headline, e.g. "Text in German"
    detail: str = ""          # one-line explanation of what was seen
    strength: float = 0.0     # 0..1, how much to trust it (0 = shown only, no effect)
    countries: dict = field(default_factory=dict)  # iso2 -> 0..1 typicality
    background: float = 0.15  # likelihood (relative) for countries not listed
    point_fn: object = None   # optional f(lat, lon) -> likelihood multiplier per point
    # Outside analysts (Claude, ChatGPT) are blended in as a mixture instead of multiplied:
    # spots = [(lat, lon, radius_km, prob)], mix > 0 marks the clue (see Geolocator.mix_analysts).
    mix: float = 0.0
    spots: list = field(default_factory=list)

    def country_loglik(self, codes):
        """Per-country log-likelihood vector for the list of iso2 codes."""
        if self.strength <= 0 or not self.countries:
            return None
        w = np.array([self.countries.get(c, 0.0) for c in codes], dtype=np.float64)
        bg = self.background
        return np.log((1 - self.strength) + self.strength * (bg + (1 - bg) * w))

    def to_json(self, name_fn=None):
        top = sorted(self.countries.items(), key=lambda kv: -kv[1])
        return {
            "kind": self.kind, "title": self.title, "detail": self.detail,
            "strength": round(float(max(self.strength, self.mix)), 3),
            "countries": [{"code": c, "name": name_fn(c) if name_fn else c, "weight": w}
                          for c, w in top[:12]],
            "n_countries": len(self.countries),
        }

    def effect_on(self, code):
        """+1 supports, -1 argues against, 0 neutral for a given country."""
        if self.strength <= 0:
            return 0
        if self.countries:
            return 1 if self.countries.get(code, 0) >= 0.5 else -1
        return 0
