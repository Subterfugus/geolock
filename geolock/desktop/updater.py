"""Update check and download for the desktop app.

Each release carries a small `latest.json` next to the installer (written by CI with
tools/update_manifest.py):

    {"version": "0.5.0", "published_at": "...", "notes": "markdown",
     "installer": {"name": "GeoLock_0.5.0_x64-setup.exe", "url": "https://...",
                   "size": 398458880, "sha256": "..."}}

The app reads it from the newest GitHub release, says what is new and how big the
download is, and downloads only when the user asks. The installer is checked against the
size and SHA-256 in the manifest before the shell is allowed to run it (the shell's
`install_update` command runs it with /P /UPDATE /R and closes the app).
"""
import hashlib
import json
import re
import shutil
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

from .. import __version__

# Where releases are published. The feed is that repo's newest release's latest.json.
UPDATE_REPO = "Subterfugus/geolock"
FEED_URL = f"https://github.com/{UPDATE_REPO}/releases/latest/download/latest.json"
RELEASES_URL = f"https://github.com/{UPDATE_REPO}/releases"
# The installer must come from GitHub; the manifest cannot point the app anywhere else.
_ALLOWED_URL = re.compile(r"^https://github\.com/[\w.-]+/[\w.-]+/releases/download/")
_NAME = re.compile(r"^[\w.() -]{1,120}-setup\.exe$")
_UA = {"User-Agent": f"GeoLock-desktop/{__version__}"}


class Cancelled(Exception):
    pass


def parse_version(v):
    """'0.10.2' -> (0, 10, 2). Anything after the numbers (like '-beta') is ignored."""
    m = re.match(r"^\s*v?(\d+(?:\.\d+)*)", str(v or ""))
    if not m:
        raise ValueError(f"not a version: {v!r}")
    return tuple(int(x) for x in m.group(1).split("."))


def newer(a, b):
    """True if version a is newer than version b."""
    pa, pb = parse_version(a), parse_version(b)
    n = max(len(pa), len(pb))
    return pa + (0,) * (n - len(pa)) > pb + (0,) * (n - len(pb))


def validate_manifest(m):
    """Returns a clean manifest, or raises ValueError if anything is missing or odd."""
    if not isinstance(m, dict):
        raise ValueError("the update information is not an object")
    version = str(m.get("version", ""))
    parse_version(version)
    inst = m.get("installer") or {}
    name, url = str(inst.get("name", "")), str(inst.get("url", ""))
    size, digest = inst.get("size"), str(inst.get("sha256", "")).lower()
    if not _NAME.match(name):
        raise ValueError("the installer name is not a GeoLock setup file")
    if not _ALLOWED_URL.match(url):
        raise ValueError("the installer is not on GitHub")
    if not isinstance(size, int) or size <= 0:
        raise ValueError("the installer size is missing")
    if not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise ValueError("the installer checksum is missing")
    return {"version": version, "published_at": m.get("published_at"),
            "notes": str(m.get("notes") or "")[:20000],
            "installer": {"name": name, "url": url, "size": size, "sha256": digest}}


class Updater:
    """Checks for a newer release and downloads its installer in the background.

    States: idle, checking, up_to_date, available, downloading, ready, error.
    """

    def __init__(self, data_dir, feed_url=None, current=__version__):
        self.dir = Path(data_dir) / "updates"
        self.feed_url = feed_url or FEED_URL
        self.current = current
        self.lock = threading.Lock()
        self.state = "idle"
        self.error = None
        self.manifest = None
        self.checked_at = None
        self.progress = None
        self.path = None
        self.thread = None
        self.cancel_flag = threading.Event()
        self._clean_old()

    # ------------------------------------------------------------------ report
    def report(self):
        m = self.manifest
        free = None
        try:
            self.dir.mkdir(parents=True, exist_ok=True)
            free = round(shutil.disk_usage(self.dir).free / 1e6)
        except OSError:
            pass
        return {
            "state": self.state, "current": self.current, "error": self.error,
            "checked_at": self.checked_at,
            "latest": m["version"] if m else None,
            "notes": m["notes"] if m else None,
            "published_at": m["published_at"] if m else None,
            "size_mb": round(m["installer"]["size"] / 1e6) if m else None,
            "free_disk_mb": free,
            "progress": self.progress,
            "installer_path": str(self.path) if self.state == "ready" and self.path else None,
            "releases_url": RELEASES_URL,
        }

    # ------------------------------------------------------------------- check
    def check(self):
        """Fetch the manifest (a few KB). Returns the report; never raises."""
        with self.lock:
            if self.state in ("checking", "downloading"):
                return self.report()
            self.state, self.error = "checking", None
        try:
            req = urllib.request.Request(self.feed_url, headers=_UA)
            with urllib.request.urlopen(req, timeout=20) as r:
                raw = r.read(256 * 1024)
            m = validate_manifest(json.loads(raw.decode("utf-8")))
        except Exception as e:
            with self.lock:
                self.state, self.error = "error", _friendly(e)
                self.checked_at = time.time()
            return self.report()
        with self.lock:
            self.checked_at = time.time()
            if not newer(m["version"], self.current):
                self.manifest, self.state = None, "up_to_date"
                return self.report()
            self.manifest = m
            done = self._dest(m)
            if done.exists() and done.stat().st_size == m["installer"]["size"] \
                    and sha256(done) == m["installer"]["sha256"]:
                self.path, self.state = done, "ready"  # downloaded on an earlier run
            else:
                self.state = "available"
        return self.report()

    # ---------------------------------------------------------------- download
    def start_download(self):
        with self.lock:
            if self.state == "downloading" or self.state == "ready":
                return self.report()
            if self.manifest is None:
                raise ValueError("Check for updates first.")
            self.cancel_flag.clear()
            self.state, self.error = "downloading", None
            self.progress = {"fraction": 0.0, "done_mb": 0, "total_mb": self._total_mb(),
                             "speed_mbps": None, "eta_s": None}
            self.thread = threading.Thread(target=self._download, daemon=True, name="update-download")
            self.thread.start()
        return self.report()

    def cancel(self):
        self.cancel_flag.set()
        if self.thread is not None:
            self.thread.join(timeout=5)
        return self.report()

    def _total_mb(self):
        return round(self.manifest["installer"]["size"] / 1e6, 1)

    def _dest(self, m):
        return self.dir / m["installer"]["name"]

    def _download(self):
        m = self.manifest
        inst = m["installer"]
        dest = self._dest(m)
        part = dest.with_name(dest.name + ".part")
        try:
            self.dir.mkdir(parents=True, exist_ok=True)
            total = inst["size"]
            have = part.stat().st_size if part.exists() else 0
            if have > total:
                part.unlink()
                have = 0
            if have < total:
                self._fetch(inst["url"], part, have, total)
            if self.progress is not None:
                self.progress["message"] = "Checking the download…"
            if part.stat().st_size != total or sha256(part) != inst["sha256"]:
                part.unlink()
                raise RuntimeError("The download is damaged (checksum mismatch). Try again.")
            part.replace(dest)
            with self.lock:
                self.path, self.state, self.progress = dest, "ready", None
        except Cancelled:
            with self.lock:  # the partial file is kept, so the next download resumes
                self.state, self.progress = "available", None
        except Exception as e:
            with self.lock:
                self.state, self.error, self.progress = "available", _friendly(e), None

    def _fetch(self, url, part, have, total):
        req = urllib.request.Request(url, headers=_UA)
        if have:
            req.add_header("Range", f"bytes={have}-")
        t0, done0 = time.time(), have
        with urllib.request.urlopen(req, timeout=60) as r:
            if have and r.status != 206:  # the server ignored the range: start over
                have = done0 = 0
            with open(part, "ab" if have else "wb") as f:
                while True:
                    if self.cancel_flag.is_set():
                        raise Cancelled()
                    chunk = r.read(1 << 20)
                    if not chunk:
                        break
                    f.write(chunk)
                    have += len(chunk)
                    speed = (have - done0) / max(time.time() - t0, 1e-3)
                    self.progress = {
                        "fraction": min(have / total, 1.0), "done_mb": round(have / 1e6, 1),
                        "total_mb": round(total / 1e6, 1), "speed_mbps": round(speed / 1e6, 2),
                        "eta_s": round((total - have) / speed) if speed > 0 else None}
        if have < total:
            raise RuntimeError(f"The download stopped early ({have / 1e6:.0f} of {total / 1e6:.0f} MB). Try again to resume it.")

    # ------------------------------------------------------------------- clean
    def _clean_old(self):
        """Delete installers for this version or older (left after an update)."""
        if not self.dir.exists():
            return
        for p in self.dir.iterdir():
            m = re.search(r"_(\d+(?:\.\d+)+)_", p.name)
            try:
                if m and not newer(m.group(1), self.current):
                    p.unlink()
            except (OSError, ValueError):
                pass


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 22), b""):
            h.update(chunk)
    return h.hexdigest()


def _friendly(e):
    if isinstance(e, urllib.error.HTTPError):
        if e.code == 404:
            return ("No update information was found on GitHub. The newest release may not "
                    "publish it yet, or releases are not public.")
        return f"GitHub answered {e.code} {e.reason}. Try again later."
    if isinstance(e, (urllib.error.URLError, TimeoutError, ConnectionError)):
        return "Couldn't reach GitHub. Check the internet connection and try again."
    if isinstance(e, OSError) and getattr(e, "errno", None) == 28:
        return "The disk is full. Free some space and try again."
    if isinstance(e, (ValueError, json.JSONDecodeError)):
        return f"The update information is not valid: {e}"
    return f"{type(e).__name__}: {e}"
