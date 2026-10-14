"""GeoCLIP's location encoder re-implemented in NumPy.

GeoCLIP (Vivanco et al., NeurIPS 2023, MIT licence) embeds GPS coordinates with an
Equal Earth projection, random Fourier features at three scales and small MLPs.
Running it in NumPy lets the app score *any* coordinate at inference time, which is
how predictions are refined beyond the fixed 100k-point gallery.
"""
import numpy as np

A1, A2, A3, A4 = 1.340264, -0.081106, 0.000893, 0.003796
SF = 66.50336


def equal_earth(latlon):
    lat = np.radians(latlon[:, 0])
    lon = np.radians(latlon[:, 1])
    theta = np.arcsin(np.sqrt(3.0) / 2 * np.sin(lat))
    den = 3 * (9 * A4 * theta**8 + 7 * A3 * theta**6 + 3 * A2 * theta**2 + A1)
    x = 2 * np.sqrt(3.0) * lon * np.cos(theta) / den
    y = A4 * theta**9 + A3 * theta**7 + A2 * theta**3 + A1 * theta
    return np.stack([x, y], 1) * SF / 180


class LocationEncoder:
    def __init__(self, weights):
        """weights: dict of arrays named like the original state dict (LocEnc{i}.…)."""
        self.caps = []
        i = 0
        while f"LocEnc{i}.capsule.0.b" in weights:
            p = f"LocEnc{i}."
            self.caps.append({
                "b": weights[p + "capsule.0.b"].astype(np.float32),
                "layers": [(weights[p + f"capsule.{k}.weight"].astype(np.float32).T,
                            weights[p + f"capsule.{k}.bias"].astype(np.float32))
                           for k in (1, 3, 5)],
                "head": (weights[p + "head.0.weight"].astype(np.float32).T,
                         weights[p + "head.0.bias"].astype(np.float32)),
            })
            i += 1
        if not self.caps:
            raise ValueError("no location encoder weights found")

    def __call__(self, latlon, batch=8192):
        latlon = np.asarray(latlon, dtype=np.float64).reshape(-1, 2)
        out = np.empty((len(latlon), 512), dtype=np.float32)
        for s in range(0, len(latlon), batch):
            xy = equal_earth(latlon[s:s + batch]).astype(np.float32)
            acc = 0
            for c in self.caps:
                vp = 2 * np.pi * xy @ c["b"].T
                h = np.concatenate([np.cos(vp), np.sin(vp)], 1)
                for w, b in c["layers"]:
                    h = np.maximum(h @ w + b, 0)
                acc = acc + h @ c["head"][0] + c["head"][1]
            out[s:s + batch] = acc
        return out


def normalize(x, axis=-1):
    return x / (np.linalg.norm(x, axis=axis, keepdims=True) + 1e-12)
