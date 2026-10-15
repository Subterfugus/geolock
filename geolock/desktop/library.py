"""The desktop app's photo library and settings, stored under the data folder.

history/<id>/result.json   the full result (as returned to the UI)
history/<id>/summary.json  what the library list needs
history/<id>/photo.jpg     a 2048 px copy with the EXIF kept, for re-runs and display
history/<id>/thumb.jpg     320 px thumbnail
settings.json
"""
import io
import json
import re
import secrets
import shutil
import threading
import time
from pathlib import Path

from PIL import Image, ImageOps

try:
    from pillow_heif import register_heif_opener
    register_heif_opener()
except ImportError:
    pass

DEFAULT_SETTINGS = {
    "device": "AUTO",
    "read_text": True,
    "show_exif_gps": True,
    "share_findings": True,
    "keep_history": True,
    "theme": "system",
    "map_style": "streets",
    "claude_model": "",       # "" = the CLI's own default; else an alias or model name
    "claude_effort": "",      # "" = default; else low | medium | high | xhigh | max
    "chatgpt_model": "",
    "chatgpt_effort": "",
    "settings_rev": 2,
}
_CHOICES = {"device": ("AUTO", "GPU", "NPU", "CPU"), "theme": ("system", "light", "dark"),
            "map_style": ("offline", "streets", "satellite"),
            "claude_effort": ("", "minimal", "low", "medium", "high", "xhigh", "max"),
            "chatgpt_effort": ("", "minimal", "low", "medium", "high", "xhigh", "max")}
# Model names go on a command line: letters, digits and . _ - : [ ] only, never a leading "-".
_MODEL = re.compile(r"^(|[A-Za-z0-9][A-Za-z0-9._:\[\]-]{0,79})$")


class Settings:
    def __init__(self, path):
        self.path = Path(path)
        self.lock = threading.Lock()
        try:
            stored = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            stored = {}
        self.values = {**DEFAULT_SETTINGS, **{k: v for k, v in stored.items() if k in DEFAULT_SETTINGS}}
        if stored and stored.get("settings_rev", 1) < 2:
            # 0.3 saved the offline map as everyone's default; streets (with offline as the
            # automatic fallback) is the default now.
            if self.values["map_style"] == "offline":
                self.values["map_style"] = "streets"
            self.values["settings_rev"] = 2

    def update(self, changes):
        with self.lock:
            for k, v in (changes or {}).items():
                if k not in DEFAULT_SETTINGS or k == "settings_rev":
                    continue
                if k.endswith("_model"):
                    v = str(v or "").strip()
                    if not _MODEL.match(v):
                        raise ValueError(f"{k}: not a model name")
                elif isinstance(DEFAULT_SETTINGS[k], bool):
                    v = bool(v)
                elif k in _CHOICES:
                    v = str(v)
                    v = v.upper() if k == "device" else v.lower()
                    v = "" if v == "default" else v
                    if v not in _CHOICES[k]:
                        raise ValueError(f"{k} must be one of {', '.join(_CHOICES[k])}")
                self.values[k] = v
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self.values, indent=2), encoding="utf-8")
            return dict(self.values)

    def __getitem__(self, k):
        return self.values[k]


def _photo_copy(data, max_side=2048):
    """(jpeg bytes, thumb bytes) from the uploaded file, keeping EXIF in the copy."""
    im = Image.open(io.BytesIO(data))
    exif = im.getexif()
    for ifd in (0x8769, 0x8825):  # load the Exif and GPS sub-IFDs so they're written back
        try:
            exif.get_ifd(ifd)
        except Exception:
            pass
    im = ImageOps.exif_transpose(im).convert("RGB")
    exif[0x0112] = 1  # pixels are upright now
    big = im.copy()
    big.thumbnail((max_side, max_side), Image.LANCZOS)
    buf = io.BytesIO()
    try:
        big.save(buf, "JPEG", quality=90, exif=exif.tobytes())
    except Exception:
        buf = io.BytesIO()
        big.save(buf, "JPEG", quality=90)
    th = im.copy()
    th.thumbnail((320, 320), Image.LANCZOS)
    tbuf = io.BytesIO()
    th.save(tbuf, "JPEG", quality=82)
    return buf.getvalue(), tbuf.getvalue()


def summary_of(result):
    g = (result.get("guesses") or [{}])[0]
    place = g.get("place") or {}
    return {
        "id": result["id"], "name": result.get("name"), "created": result.get("created"),
        "thumb_url": result.get("thumb_url"),
        "top": {"lat": g.get("lat"), "lon": g.get("lon"), "confidence": g.get("confidence"),
                "label": g.get("label"), "country": g.get("country"),
                "country_code": g.get("country_code"), "place": place.get("name"),
                "region": g.get("region")} if g else None,
        "analysts": [a["provider"] for a in result.get("analysts", []) if a.get("ok")],
        "has_exif_gps": bool((result.get("exif") or {}).get("gps")),
        "km_from_exif": g.get("km_from_exif"),
    }


EXPORT_SUFFIXES = (".json", ".csv", ".kml", ".png")
MAX_EXPORT_BYTES = 200 * 1024 * 1024


def write_export(path, data):
    """Writes an export the UI built to the path the user picked in the Save dialog.

    Only absolute paths with an export extension, into a folder that exists, are allowed:
    the token keeps other programs out, and this keeps a bug in the UI from writing anywhere
    else. Returns the resolved path.
    """
    p = Path(str(path or "").strip().strip('"'))
    if not p.is_absolute():
        raise ValueError("Choose where to save the file.")
    if p.suffix.lower() not in EXPORT_SUFFIXES:
        raise ValueError(f"Exports are saved as {', '.join(EXPORT_SUFFIXES)} files.")
    if not p.parent.is_dir():
        raise ValueError(f"The folder {p.parent} does not exist.")
    if len(data) > MAX_EXPORT_BYTES:
        raise ValueError("That export is too large.")
    tmp = p.with_name(p.name + ".part")
    tmp.write_bytes(data)
    tmp.replace(p)
    return p


class Library:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()
        self.memory = {}  # results not written to disk (keep_history off), this session only

    @staticmethod
    def new_id():
        return time.strftime("%Y%m%d-%H%M%S", time.gmtime()) + "-" + secrets.token_hex(3)

    def _dir(self, rid):
        if not rid or any(c not in "0123456789abcdef-" for c in rid):
            raise KeyError(rid)
        return self.root / rid

    def add_photo(self, rid, data, keep=True):
        photo, thumb = _photo_copy(data)
        if keep:
            d = self._dir(rid)
            d.mkdir(parents=True, exist_ok=True)
            (d / "photo.jpg").write_bytes(photo)
            (d / "thumb.jpg").write_bytes(thumb)
        else:
            self.memory[rid] = {"photo": photo, "thumb": thumb}
        return photo

    def save(self, result, keep=True):
        rid = result["id"]
        if not keep:
            self.memory.setdefault(rid, {})["result"] = result
            return
        d = self._dir(rid)
        with self.lock:
            d.mkdir(parents=True, exist_ok=True)
            (d / "result.json").write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
            (d / "summary.json").write_text(json.dumps(summary_of(result), ensure_ascii=False),
                                            encoding="utf-8")

    def get(self, rid):
        if rid in self.memory and "result" in self.memory[rid]:
            return self.memory[rid]["result"]
        p = self._dir(rid) / "result.json"
        if not p.exists():
            raise KeyError(rid)
        return json.loads(p.read_text(encoding="utf-8"))

    def file(self, rid, kind):
        """Bytes of photo.jpg or thumb.jpg."""
        if rid in self.memory and kind in self.memory[rid]:
            return self.memory[rid][kind]
        p = self._dir(rid) / f"{kind}.jpg"
        if not p.exists():
            raise KeyError(rid)
        return p.read_bytes()

    def list(self):
        out = [summary_of(m["result"]) for m in self.memory.values() if "result" in m]
        for d in self.root.iterdir():
            s = d / "summary.json"
            if s.exists():
                try:
                    out.append(json.loads(s.read_text(encoding="utf-8")))
                except Exception:
                    pass
        return sorted(out, key=lambda s: s.get("created") or "", reverse=True)

    def delete(self, rid):
        self.memory.pop(rid, None)
        d = self._dir(rid)
        if d.exists():
            shutil.rmtree(d, ignore_errors=True)

    def clear(self):
        n = len(self.memory)
        self.memory.clear()
        for d in list(self.root.iterdir()):
            if d.is_dir():
                shutil.rmtree(d, ignore_errors=True)
                n += 1
        return n
