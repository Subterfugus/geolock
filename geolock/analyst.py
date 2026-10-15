"""Optional second opinion from Claude or ChatGPT, using the user's own subscription.

Subscriptions don't come with API keys, so GeoLock drives the official command-line
tools the user is already signed in to:

- Claude: Claude Code (``claude -p``), signed in with a Claude Pro/Max account
  (``claude auth login``). The photo goes in as an image block over stream-json input.
- ChatGPT: OpenAI Codex CLI (``codex exec``), signed in with a ChatGPT account
  (``codex login``). The photo goes in with ``--image``.

Fallbacks: with no Claude Code installed, ``ANTHROPIC_API_KEY`` plus the ``anthropic``
package calls the API directly (billed per use). Codex can itself be signed in with an
API key (``codex login --with-api-key``).

What is sent: the photo re-encoded from pixels (no EXIF, so no GPS or camera serial) and,
unless turned off, a short text summary of GeoLock's own findings. Nothing is sent
unless the user asks for it on that photo.

Web search (on unless turned off): the analysts may search the web with words they choose,
such as a shop name read off a sign, to check a candidate place. The photo is never searched.
"""
import base64
import io
import json
import os
import shutil
import subprocess
import sys
import re
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np
from PIL import Image

from .clues import Clue
from .geodata import haversine_km
from .vlm import parse

TIMEOUT_S = int(os.environ.get("GEOLOCK_LLM_TIMEOUT", "240"))
MAX_SIDE = 1568  # Claude's largest useful image side; plenty for ChatGPT too
MAX_CROPS = int(os.environ.get("GEOLOCK_LLM_CROPS", "4"))  # zoomed sign crops sent along
CROP_SIDE = 768  # crops are small; this keeps them cheap
CROP_MIN_SIDE = 384  # smaller crops are enlarged to this
# Close-up tiles of the road band (plates, bollards, poles, road lines): only for photos big
# enough that a tile at full size shows clearly more than the downscaled whole photo.
MAX_TILES = int(os.environ.get("GEOLOCK_LLM_TILES", "2"))
TILE_MIN_PHOTO = int(1.6 * MAX_SIDE)  # long side below this: the whole photo is detailed enough

NAMES = {"claude": "Claude", "chatgpt": "ChatGPT"}

SYSTEM = ("You are a world-class photo geolocation analyst, as good as the best GeoGuessr "
          "players. You work like they do: go through a fixed checklist of evidence, note what "
          "each item rules in and rules out, then combine it into ranked guesses. You never "
          "invent evidence that is not visible, and you answer only with the requested JSON.")

# The checklist, in the order a strong player goes through it. Keys are the categories the
# answer uses; the text tells the model what to look at for each.
CHECKLIST = {
    "driving_side": "Driving side: which side cars drive or park on, steering wheel side, "
                    "which way signs face.",
    "road_markings": "Road lines: colour of centre and edge lines (white, yellow, double "
                     "yellow), dashed or solid, kerb paint, road surface and width.",
    "signs": "Signs: shape, colour and border of road signs, direction signs (colour, font), "
             "street name plates, chevrons, pedestrian crossings.",
    "bollards": "Bollards and roadside posts: shape, colour, reflector colour and layout.",
    "plates": "Licence plates: shape, colour, EU band, front plate present or not, text.",
    "poles": "Utility poles: wood, concrete or metal, cross-section, crossbars, insulators, "
             "pole plates and markings, street lights.",
    "script_language": "Text: script, language and spelling, diacritics, domain names, phone "
                       "numbers, currency, brands and shop chains. Read any zoomed crops closely.",
    "architecture": "Buildings: roof shape and material, walls, windows, fences, gates, "
                    "walls around houses, churches, mosques, temples.",
    "vegetation": "Vegetation: tree and crop species, palms, eucalyptus, conifers, rice, "
                  "how green or dry it is.",
    "terrain_soil": "Terrain and soil: mountains, flat land, coast, soil colour (red, black, "
                    "sandy), rocks.",
    "sun_climate": "Sun and climate: sun direction and height (hemisphere, latitude), "
                   "shadows, snow, haze, season, clothing.",
    "other": "Anything else: cars and their models, the camera or car if it is a Street "
             "View style photo, people, animals, infrastructure.",
}

INSTRUCTIONS = """Where on Earth was this photo taken?
{images}
Work through this checklist in order. For each item you can actually see, write what you
saw and what it suggests (countries or regions it fits, and ones it rules out). Leave out
items that are not visible; do not guess at them.
{checklist}

Then read the notes from GeoLock, an offline model, if any are given below. GeoLock's
visual guesses are often wrong by hundreds or thousands of km on photos without text, so
treat them as weak hints; text it read and time zones are more reliable. Its OCR can
misread characters, so trust your own reading of the crops when they differ.
{tools}

Answer with JSON:
- checklist: the items you could see, each with category (one of {categories}), seen
  (what you saw, concretely) and suggests (what it points to or rules out).
- reasoning: 3 to 6 sentences on how the evidence combines into your answer.
- ruled_out: up to 4 plausible-looking countries or regions you rejected, each with
  place and why (the evidence against it). Empty if none.
- driving_side: left, right or unknown.
- text_seen: any text you can read in the photo or crops, or an empty string.
- web_checks: each web search you ran, with query and found (what it confirmed or
  ruled out, one sentence). Empty if you did not search.
- countries: the countries it could be, most likely first (up to 6), each with iso2 and
  probability (0 to 1, all together at most 1; leave the rest for "somewhere else").
  These are your odds for the country alone, separate from how precisely you can place it.
- guesses: 1 to 5 distinct locations, best first, each with place (most specific first:
  road or landmark, then the town or city by its usual English name, then the region,
  separated by commas, e.g. "Hohe Straße, Cologne, North Rhine-Westphalia"), country, iso2 (ISO 3166-1 alpha-2), lat, lon,
  radius_km (how far off you might be), confidence (probability from 0 to 1 that the
  photo is within radius_km; all guesses together at most 1) and why (one sentence:
  the evidence for this guess over the others)."""

# With web search on (the default), the analyst checks what it read against the web
# instead of answering from memory: a shop name, phone prefix or street name often pins a
# photo to one town, which no amount of looking at vegetation will.
WEB_TOOLS = """You can search the web, and you should use it to check your evidence rather than
answer from memory. Good searches:
- Exact text you read: business and shop names (with the town if visible), street and
  place names, phone numbers, web addresses, route numbers, company names on vehicles.
  Searching a business name together with your candidate town confirms or rules it out.
- Your leading candidates: confirm a road, town or landmark really exists there and
  matches what you see (for example that a chain operates in that country, or that a
  route number belongs to that region), and look up its coordinates.
Search with words only; you cannot search with the image. Stop after about {max_searches}
searches or once a place is confirmed. Do not run commands. Put coordinates you confirmed
online in your guesses, and lower your confidence when searches contradict a guess."""

NO_TOOLS = "Do not run commands or use tools; answer from the images."
MAX_SEARCHES = int(os.environ.get("GEOLOCK_LLM_SEARCHES", "8"))
WEB_EXTRA_S = 180  # searching takes longer; added to the time limit

CATEGORY_LABELS = {
    "driving_side": "Driving side", "road_markings": "Road lines", "signs": "Signs",
    "bollards": "Bollards", "plates": "Licence plates", "poles": "Poles",
    "script_language": "Text and language", "architecture": "Architecture",
    "vegetation": "Vegetation", "terrain_soil": "Terrain and soil",
    "sun_climate": "Sun and climate", "other": "Other",
}

_STR = {"type": "string"}
SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["checklist", "reasoning", "ruled_out", "driving_side", "text_seen",
                 "web_checks", "countries", "guesses"],
    "properties": {
        "checklist": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["category", "seen", "suggests"],
            "properties": {"category": {"type": "string", "enum": list(CHECKLIST)},
                           "seen": _STR, "suggests": _STR}}},
        "reasoning": _STR,
        "ruled_out": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["place", "why"],
            "properties": {"place": _STR, "why": _STR}}},
        "driving_side": {"type": "string", "enum": ["left", "right", "unknown"]},
        "text_seen": _STR,
        "web_checks": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["query", "found"],
            "properties": {"query": _STR, "found": _STR}}},
        "countries": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["iso2", "probability"],
            "properties": {"iso2": _STR, "probability": {"type": "number"}}}},
        "guesses": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["place", "country", "iso2", "lat", "lon", "radius_km", "confidence",
                         "why"],
            "properties": {
                "place": _STR, "country": _STR, "iso2": _STR,
                "lat": {"type": "number"}, "lon": {"type": "number"},
                "radius_km": {"type": "number"}, "confidence": {"type": "number"},
                "why": _STR}}},
    },
}

# ------------------------------------------------------------------ live progress
EFFORTS = ("minimal", "low", "medium", "high", "xhigh", "max")
_FINISHED = ("done", "error", "stopped")


class Stopped(Exception):
    """The user pressed Stop while an analyst was working."""


class Progress:
    """What each analyst is doing right now (for the app's progress card), and a Stop switch.

    Stages: preparing (cutting crops) -> starting (CLI launched, waiting for the model)
    -> thinking -> writing (the answer) -> done | error | stopped."""

    def __init__(self):
        self.lock = threading.Lock()
        self.state = {}
        self.stop = threading.Event()
        self.procs = set()
        self.armed = False  # begin() ran at the start of the request; keep a Stop pressed since

    def begin(self, providers, options=None, request_start=False):
        """Reset for a new ask. The desktop backend calls it with request_start=True when the
        request arrives (before GeoLock's own analysis), so Stop works from the first moment;
        ask_all() then keeps a Stop pressed in between instead of clearing it."""
        options = options or {}
        now = time.time()
        with self.lock:
            if request_start or not self.armed:
                self.stop.clear()
            self.armed = request_start
            self.state = {p: {"stage": "preparing", "started": now, "updated": now,
                              "model": (options.get(p) or {}).get("model") or None,
                              "effort": (options.get(p) or {}).get("effort") or None,
                              "note": "", "chars": 0, "searches": 0, "error": None}
                          for p in providers}

    def set(self, provider, **kw):
        with self.lock:
            st = self.state.get(provider)
            if st is None or st["stage"] in _FINISHED:
                return
            if kw.get("note"):
                kw["note"] = _last_thought(kw["note"])
            st.update({k: v for k, v in kw.items() if v is not None}, updated=time.time())

    def add_chars(self, provider, n):
        with self.lock:
            st = self.state.get(provider)
            if st is not None:
                st["chars"] += n

    def finish(self, provider, stage, error=None):
        with self.lock:
            st = self.state.get(provider)
            if st is not None:
                st.update(stage=stage, error=error, updated=time.time())

    def snapshot(self):
        with self.lock:
            prov = {p: dict(v) for p, v in self.state.items()}
        return {"running": any(v["stage"] not in _FINISHED for v in prov.values()),
                "now": time.time(), "providers": prov}

    def cancel(self):
        """Stop every running analyst. Returns how many were still working."""
        self.stop.set()
        with self.lock:
            procs = list(self.procs)
        for proc in procs:
            _kill(proc)
        return sum(1 for v in self.snapshot()["providers"].values() if v["stage"] not in _FINISHED)


PROGRESS = Progress()


def _last_thought(text):
    """The latest complete line of a model's thinking, short enough for one line of UI."""
    lines = [l.strip(" *#-\t") for l in str(text).splitlines() if l.strip(" *#-\t")]
    line = lines[-1] if lines else ""
    return line if len(line) <= 160 else "…" + line[-159:]


def _kill(proc):
    """End a CLI and everything it started (Codex and Claude Code spawn helpers)."""
    try:
        if sys.platform == "win32":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True,
                           creationflags=0x08000000, timeout=10)
        else:
            import signal
            os.killpg(proc.pid, signal.SIGKILL)  # the CLI's whole process group
        proc.kill()
    except Exception:
        pass


def _run_live(cmd, stdin=None, cwd=None, timeout=TIMEOUT_S, on_line=None):
    """Like _run, but hands each stdout line to on_line as it arrives and honours Stop."""
    kw = {}
    if sys.platform == "win32":
        kw["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
    else:
        kw["start_new_session"] = True  # own process group, so Stop can end its helpers too
    if PROGRESS.stop.is_set():
        raise Stopped()
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, cwd=cwd, text=True, encoding="utf-8",
                            errors="replace", **kw)
    with PROGRESS.lock:
        PROGRESS.procs.add(proc)
    out, err = [], []

    def feed():
        try:
            if stdin:
                proc.stdin.write(stdin)
            proc.stdin.close()
        except (OSError, ValueError):
            pass

    def read_out():
        for line in proc.stdout:
            out.append(line)
            if on_line:
                try:
                    on_line(line)
                except Exception:
                    pass  # progress is best-effort; the answer is what matters

    threads = [threading.Thread(target=f, daemon=True) for f in
               (feed, read_out, lambda: err.append(proc.stderr.read()))]
    for t in threads:
        t.start()
    deadline = time.monotonic() + timeout
    try:
        while proc.poll() is None:
            if PROGRESS.stop.is_set():
                _kill(proc)
                raise Stopped()
            if time.monotonic() > deadline:
                _kill(proc)
                raise subprocess.TimeoutExpired(cmd, timeout)
            time.sleep(0.1)
        for t in threads:
            t.join(timeout=5)
        if PROGRESS.stop.is_set() and proc.returncode != 0:
            raise Stopped()  # killed by cancel() between two polls
    finally:
        with PROGRESS.lock:
            PROGRESS.procs.discard(proc)
    return subprocess.CompletedProcess(cmd, proc.returncode, "".join(out), "".join(err))


# ------------------------------------------------------------------ helpers
def _run(cmd, stdin=None, cwd=None, timeout=TIMEOUT_S):
    kw = {}
    if sys.platform == "win32":
        kw["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
    return subprocess.run(cmd, input=stdin, cwd=cwd, timeout=timeout, capture_output=True,
                          text=True, encoding="utf-8", errors="replace", **kw)


def _unknown_flag(proc):
    err = (proc.stderr or "") + (proc.stdout or "")
    return proc.returncode != 0 and any(s in err for s in (
        "unknown option", "unexpected argument", "Unknown option", "unrecognized"))


def _jpeg(im, max_side, min_side=0):
    im = im.convert("RGB")
    s = min(1.0, max_side / max(im.size))
    if min_side and max(im.size) < min_side:  # tiny crops: enlarge so the model can see them
        s = min_side / max(im.size)
    if s != 1:
        im = im.resize((max(1, round(im.width * s)), max(1, round(im.height * s))), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=90)
    return buf.getvalue()


def photo_jpeg(img):
    """The pixels only, as JPEG: no EXIF, so GPS and camera serials never leave the machine."""
    return _jpeg(img, MAX_SIDE)


def sign_crops(img, ocr_lines, max_crops=MAX_CROPS):
    """Zoomed crops of the places where OCR found text (signs, plates, shop fronts).

    Nearby text lines are grouped into one region (one sign), padded so the sign's shape
    and colours show, and cut from the full-resolution photo, which keeps detail the
    downscaled whole photo loses. Regions are ranked by how much confident text they hold.
    Returns [{"box": [x0, y0, x1, y1], "text": str, "jpeg": bytes}], best first."""
    W, H = img.size
    regions = []
    for l in ocr_lines or []:
        try:
            b = np.asarray(l["box"], dtype=float).reshape(-1, 2)
        except (KeyError, TypeError, ValueError):
            continue
        x0, y0 = b.min(0)
        x1, y1 = b.max(0)
        if x1 <= x0 or y1 <= y0 or (x1 - x0) * (y1 - y0) > 0.25 * W * H:
            continue  # empty, or so big that a crop would not zoom in
        regions.append({"box": [x0, y0, x1, y1], "lines": [l],
                        "score": float(l.get("score", 0.5)) * len(str(l.get("text", ""))) ** 0.5})
    # merge regions closer than about two text heights (lines of the same sign)
    merged = True
    while merged:
        merged = False
        for i in range(len(regions)):
            for j in range(i + 1, len(regions)):
                a, b = regions[i]["box"], regions[j]["box"]
                gap = 1.5 * max(min(a[3] - a[1], b[3] - b[1]), 4)
                if (a[0] - gap <= b[2] and b[0] - gap <= a[2]
                        and a[1] - gap <= b[3] and b[1] - gap <= a[3]):
                    regions[i] = {"box": [min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3])],
                                  "lines": regions[i]["lines"] + regions[j]["lines"],
                                  "score": regions[i]["score"] + regions[j]["score"]}
                    del regions[j]
                    merged = True
                    break
            if merged:
                break
    out = []
    min_side = max(64, 0.08 * max(W, H))
    for r in sorted(regions, key=lambda r: -r["score"]):
        x0, y0, x1, y1 = r["box"]
        h = y1 - y0
        pad = max(0.6 * h, 0.15 * max(x1 - x0, h))
        x0, y0, x1, y1 = x0 - pad, y0 - pad, x1 + pad, y1 + pad
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        w, h = max(x1 - x0, min_side), max(y1 - y0, min_side)
        x0, x1 = max(0, cx - w / 2), min(W, cx + w / 2)
        y0, y1 = max(0, cy - h / 2), min(H, cy + h / 2)
        if (x1 - x0) * (y1 - y0) > 0.5 * W * H:  # no real zoom: the whole photo shows it
            continue
        box = [int(x0), int(y0), int(round(x1)), int(round(y1))]
        if any(_overlap(box, o["box"]) > 0.6 for o in out):
            continue
        lines = sorted(r["lines"], key=lambda l: np.asarray(l["box"], dtype=float).reshape(-1, 2)[:, 1].min())
        text = " / ".join(str(l.get("text", "")) for l in lines)[:160]
        out.append({"box": box, "text": text,
                    "jpeg": _jpeg(img.crop(box), CROP_SIDE, min_side=CROP_MIN_SIDE)})
        if len(out) >= max_crops:
            break
    return out


def detail_tiles(img, n=MAX_TILES):
    """Close-ups of the band where roads, plates, bollards and poles usually are (30% to 90%
    of the height), split side by side and sent at full size: about twice the detail of
    the downscaled whole photo on a 12 MP picture. None for smaller photos.
    Returns [{"box", "text": "", "kind": "tile", "jpeg"}], left to right."""
    W, H = img.size
    if n <= 0 or max(W, H) < TILE_MIN_PHOTO:
        return []
    y0, y1 = int(0.3 * H), int(0.9 * H)
    out = []
    for i in range(n):
        box = [int(i * W / n), y0, int((i + 1) * W / n), y1]
        out.append({"box": box, "text": "", "kind": "tile",
                    "jpeg": _jpeg(img.crop(box), MAX_SIDE)})
    return out


def _overlap(a, b):
    """Intersection over the smaller box."""
    ix = max(0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    small = min((a[2] - a[0]) * (a[3] - a[1]), (b[2] - b[0]) * (b[3] - b[1])) or 1
    return ix * iy / small


def prompt_text(briefing, crops=(), web=False):
    if crops:
        which = "Image 2 is a close-up" if len(crops) == 1 else \
            f"Images 2 to {len(crops) + 1} are close-ups"
        lines = [f"You get {len(crops) + 1} images. Image 1 is the whole photo. {which} of it, "
                 "cut at full resolution: zoomed crops where GeoLock found text (signs, "
                 "plates, shop fronts) and tiles of the road area (look there for licence "
                 "plates, bollards, poles, road lines and small signs):"]
        for i, c in enumerate(crops, 2):  # the OCR reading is a GeoLock finding: only if shared
            what = "tile" if c.get("kind") == "tile" else "text crop"
            lines.append(f"- Image {i}: {what}, region x {c['box'][0]}-{c['box'][2]}, y {c['box'][1]}-"
                         f"{c['box'][3]} of the photo"
                         + (f"; OCR read “{c['text']}”" if briefing and c.get("text") else ""))
        images = "\n" + "\n".join(lines) + "\n"
    else:
        images = ""
    text = INSTRUCTIONS.format(
        images=images,
        checklist="\n".join(f"{i}. {t}" for i, t in enumerate(CHECKLIST.values(), 1)),
        categories=", ".join(CHECKLIST),
        tools=WEB_TOOLS.format(max_searches=MAX_SEARCHES) if web else NO_TOOLS)
    if not briefing:
        return text
    return text + "\n\nNotes from GeoLock:\n" + briefing


# ------------------------------------------------------------------ detection
_detect_cache = {"t": 0.0, "value": None}


def _cli_dirs():
    """Where the CLIs install themselves when that folder is not on PATH. On Windows,
    Claude Code's native installer puts claude.exe in ~/.local/bin and only suggests
    adding it to PATH; npm -g puts codex in %APPDATA%\\npm."""
    home = os.path.expanduser("~")
    dirs = [os.path.join(home, ".local", "bin"), os.path.join(home, ".claude", "local")]
    if os.environ.get("APPDATA"):
        dirs.append(os.path.join(os.environ["APPDATA"], "npm"))
    return [d for d in dirs if os.path.isdir(d)]


def _find_cli(name):
    """Path to the `claude` or `codex` executable: PATH first, then the usual install folders."""
    dirs = _cli_dirs()
    return shutil.which(name) or (shutil.which(name, path=os.pathsep.join(dirs)) if dirs else None)


def _claude_status():
    exe = _find_cli("claude")
    if exe:
        try:
            p = _run([exe, "auth", "status", "--json"], timeout=30)
            info = json.loads(p.stdout or "{}") if p.stdout.strip().startswith("{") else {}
            if info.get("loggedIn"):
                how = "Claude Code, API key" if "api" in str(info.get("authMethod", "")).lower() \
                    else "Claude Code, your Claude login"
                return {"available": True, "via": "claude-code", "detail": how}
            note = "Claude Code is installed but not signed in. Run: claude auth login"
        except Exception as e:  # old versions without `auth status`: try it at use time
            return {"available": True, "via": "claude-code",
                    "detail": f"Claude Code (sign-in not checked: {type(e).__name__})"}
    else:
        note = "Install Claude Code and sign in (claude auth login) to use your Claude plan."
    if os.environ.get("ANTHROPIC_API_KEY"):
        try:
            import anthropic  # noqa: F401
            return {"available": True, "via": "anthropic-api",
                    "detail": "Anthropic API key (billed per use)"}
        except ImportError:
            note += " (ANTHROPIC_API_KEY is set, but the anthropic package is not installed.)"
    return {"available": False, "via": None, "detail": note}


def _chatgpt_status():
    exe = _find_cli("codex")
    if not exe:
        return {"available": False, "via": None,
                "detail": "Install the Codex CLI (npm i -g @openai/codex) and run: codex login"}
    try:
        p = _run([exe, "login", "status"], timeout=30)
    except Exception as e:
        return {"available": False, "via": None, "detail": f"codex login status failed: {e}"}
    if p.returncode == 0:
        out = (p.stdout + p.stderr).lower()
        how = "Codex CLI, API key" if "api key" in out else "Codex CLI, your ChatGPT login"
        return {"available": True, "via": "codex", "detail": how}
    return {"available": False, "via": None,
            "detail": "Codex CLI is installed but not signed in. Run: codex login"}


def detect(refresh=False):
    """Which analysts can be used here: {"claude": {...}, "chatgpt": {...}}. Cached 5 min."""
    if refresh or _detect_cache["value"] is None or time.time() - _detect_cache["t"] > 300:
        with ThreadPoolExecutor(2) as ex:
            c, g = ex.submit(_claude_status), ex.submit(_chatgpt_status)
            _detect_cache["value"] = {"claude": c.result(), "chatgpt": g.result()}
        _detect_cache["t"] = time.time()
    return _detect_cache["value"]


# ------------------------------------------------------------------ backends
def _image_blocks(jpegs):
    return [{"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                         "data": base64.b64encode(j).decode()}} for j in jpegs]


def _searched(provider, query):
    """Count a web search and show its query as the live note."""
    with PROGRESS.lock:
        st = PROGRESS.state.get(provider)
        if st is not None:
            st["searches"] = st.get("searches", 0) + 1
    PROGRESS.set(provider, stage="thinking",
                 note=f"Searching the web: {query}"[:300] if query else "Searching the web")


def _ask_claude_code(jpegs, prompt, model=None, effort=None, provider="claude", web=False):
    exe = _find_cli("claude")
    msg = {"type": "user", "message": {"role": "user", "content":
           _image_blocks(jpegs) + [{"type": "text", "text": prompt}]}}
    base = [exe, "-p", "--input-format", "stream-json", "--output-format", "stream-json",
            "--verbose"]
    # Web search: WebSearch/WebFetch are the only tools, pre-approved because -p cannot ask.
    tools = ["--tools", "WebSearch,WebFetch", "--allowedTools", "WebSearch,WebFetch"] \
        if web else ["--tools", ""]
    extra = ["--no-session-persistence", *tools, "--setting-sources", "",
             "--strict-mcp-config", "--system-prompt", SYSTEM,
             "--json-schema", json.dumps(SCHEMA, separators=(",", ":")),
             "--include-partial-messages"]
    model = model or os.environ.get("GEOLOCK_CLAUDE_MODEL")
    if model:
        base += ["--model", model]
    if effort:
        extra += ["--effort", effort]
    thinking = []

    def on_line(line):
        ev = json.loads(line)
        kind = ev.get("type")
        if kind == "system" and ev.get("subtype") == "init":
            PROGRESS.set(provider, stage="starting", model=ev.get("model"))
        elif kind == "assistant":
            m = ev.get("message") or {}
            PROGRESS.set(provider, model=m.get("model"))
            for b in m.get("content") or []:
                if isinstance(b, dict) and b.get("type") == "tool_use":
                    inp = b.get("input") or {}
                    _searched(provider, inp.get("query") or inp.get("url") or b.get("name", ""))
        elif kind == "stream_event":
            e = ev.get("event") or {}
            if e.get("type") == "message_start":
                PROGRESS.set(provider, stage="thinking", model=(e.get("message") or {}).get("model"))
            elif e.get("type") == "content_block_start":
                block = (e.get("content_block") or {}).get("type")
                PROGRESS.set(provider, stage="thinking" if block in ("thinking", "redacted_thinking") else "writing")
            elif e.get("type") == "content_block_delta":
                d = e.get("delta") or {}
                piece = d.get("thinking") or d.get("text") or d.get("partial_json") or ""
                PROGRESS.add_chars(provider, len(piece))
                if d.get("type") == "thinking_delta":
                    thinking.append(piece)
                    PROGRESS.set(provider, stage="thinking", note="".join(thinking)[-600:])
                elif piece:
                    PROGRESS.set(provider, stage="writing")

    with tempfile.TemporaryDirectory(prefix="geolock-") as tmp:  # no CLAUDE.md to pick up
        limit = TIMEOUT_S + (WEB_EXTRA_S if web else 0)
        p = _run_live(base + extra, stdin=json.dumps(msg) + "\n", cwd=tmp, on_line=on_line,
                      timeout=limit)
        if _unknown_flag(p):  # older Claude Code: plain run, JSON from the text
            p = _run_live(base, stdin=json.dumps(msg) + "\n", cwd=tmp, on_line=on_line,
                          timeout=limit)
    result, used_model = None, None
    for line in p.stdout.splitlines():
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        if ev.get("type") == "assistant":
            used_model = (ev.get("message") or {}).get("model") or used_model
        elif ev.get("type") == "result":
            result = ev
    if not result:
        raise RuntimeError((p.stderr or p.stdout or f"claude exited with {p.returncode}").strip()[-400:])
    if result.get("is_error"):
        raise RuntimeError(str(result.get("result") or result.get("subtype"))[:400])
    data = result.get("structured_output") or parse(result.get("result") or "")
    return data, result.get("result") or "", used_model


def _ask_anthropic_api(jpegs, prompt, model=None, effort=None, provider="claude", web=False):
    # Billed per use, so no web search here; ask() words the prompt to match.
    import anthropic
    client = anthropic.Anthropic()
    model = model or os.environ.get("GEOLOCK_CLAUDE_MODEL") or "claude-opus-5-5"
    model = {"opus": "claude-opus-5-5", "sonnet": "claude-sonnet-5-5",
             "haiku": "claude-haiku-5-5", "fable": "claude-fable-5-1"}.get(model, model)
    PROGRESS.set(provider, stage="thinking", model=model)
    r = client.messages.create(
        model=model, max_tokens=16000, system=SYSTEM,
        output_config={"format": {"type": "json_schema", "schema": SCHEMA}},
        messages=[{"role": "user", "content":
                   _image_blocks(jpegs) + [{"type": "text", "text": prompt}]}])
    if r.stop_reason == "refusal":
        raise RuntimeError("Claude declined to answer.")
    text = next((b.text for b in r.content if b.type == "text"), "")
    return parse(text), text, r.model


def _ask_codex(jpegs, prompt, model=None, effort=None, provider="chatgpt", web=False):
    exe = _find_cli("codex")
    model = model or os.environ.get("GEOLOCK_CODEX_MODEL")
    seen = {}

    def on_line(line):
        ev = json.loads(line)
        kind = str(ev.get("type", ""))
        if kind in ("thread.started", "turn.started"):
            PROGRESS.set(provider, stage="thinking")
        elif kind.startswith("item."):
            item = ev.get("item") or {}
            text = str(item.get("text") or "")
            if item.get("type") == "web_search":  # started, then completed with the query
                query = str(item.get("query") or "")
                if item.get("id") not in seen:
                    seen[item.get("id")] = True
                    _searched(provider, query)
                elif query:
                    PROGRESS.set(provider, note=f"Searching the web: {query}"[:300])
            elif item.get("type") == "reasoning":
                PROGRESS.set(provider, stage="thinking", note=text)
                if kind == "item.completed":
                    PROGRESS.add_chars(provider, len(text))
            elif item.get("type") == "agent_message":
                PROGRESS.set(provider, stage="writing")
                if kind == "item.completed":
                    PROGRESS.add_chars(provider, len(text))
        elif kind == "error":
            PROGRESS.set(provider, note=str(ev.get("message") or ""))

    with tempfile.TemporaryDirectory(prefix="geolock-") as tmp:
        schema, out = (os.path.join(tmp, n) for n in ("schema.json", "answer.json"))
        imgs = []
        for i, j in enumerate(jpegs):  # photo.jpg, then crop1.jpg ...; order matches the prompt
            imgs.append(os.path.join(tmp, f"crop{i}.jpg" if i else "photo.jpg"))
            with open(imgs[-1], "wb") as f:
                f.write(j)
        with open(schema, "w", encoding="utf-8") as f:
            json.dump(SCHEMA, f)
        base = [exe, "exec", "--skip-git-repo-check", "--sandbox", "read-only", "-C", tmp]
        for im in imgs:
            base += ["--image", im]
        base += ["--output-last-message", out, "--color", "never"]
        if model:
            base += ["--model", model]
        if effort:
            base += ["-c", f'model_reasoning_effort="{effort}"']
        # `codex exec` has no --search flag; the web_search config key does the same job.
        base += ["-c", f'web_search="{"live" if web else "disabled"}"']
        prompt = SYSTEM + "\n\n" + prompt
        PROGRESS.set(provider, stage="starting")
        limit = TIMEOUT_S + (WEB_EXTRA_S if web else 0)
        p = _run_live(base + ["--ephemeral", "--json", "-c", 'model_reasoning_summary="auto"',
                              "--output-schema", schema, "-"], stdin=prompt, cwd=tmp,
                      on_line=on_line, timeout=limit)
        if _unknown_flag(p):  # older Codex CLI
            p = _run_live(base + ["-"], stdin=prompt, cwd=tmp, on_line=on_line, timeout=limit)
        text = open(out, encoding="utf-8").read() if os.path.exists(out) else ""
    if not text.strip():
        raise RuntimeError((p.stderr or p.stdout or f"codex exited with {p.returncode}").strip()[-400:])
    return parse(text), text, model


BACKENDS = {"claude-code": _ask_claude_code, "anthropic-api": _ask_anthropic_api,
            "codex": _ask_codex}


def clean(data):
    """Keep well-formed guesses only, with numbers in range. Also accepts the older answer
    shape (a flat "clues" list instead of the checklist), so saved answers still load."""
    if not isinstance(data, dict):
        return None
    guesses = []
    for g in data.get("guesses") or []:
        try:
            lat, lon = float(g["lat"]), float(g["lon"])
            conf = min(max(float(g.get("confidence", 0)), 0.0), 1.0)
            rad = min(max(float(g.get("radius_km", 100)), 1.0), 3000.0)
        except (KeyError, TypeError, ValueError):
            continue
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            continue
        guesses.append({"place": str(g.get("place", ""))[:120], "country": str(g.get("country", ""))[:60],
                        "iso2": str(g.get("iso2", "")).upper()[:2], "lat": lat, "lon": lon,
                        "radius_km": rad, "confidence": conf, "why": str(g.get("why") or "")[:300]})
    total = sum(g["confidence"] for g in guesses)
    if total > 1:
        for g in guesses:
            g["confidence"] /= total
    checklist = []
    for c in data.get("checklist") or []:
        if not isinstance(c, dict) or not str(c.get("seen") or "").strip():
            continue
        cat = str(c.get("category", "other"))
        checklist.append({"category": cat if cat in CHECKLIST else "other",
                          "label": CATEGORY_LABELS.get(cat, "Other"),
                          "seen": str(c["seen"])[:200], "suggests": str(c.get("suggests") or "")[:200]})
    order = list(CHECKLIST)
    checklist.sort(key=lambda c: order.index(c["category"]))
    clues = [{"clue": str(c.get("clue", ""))[:160], "suggests": str(c.get("suggests", ""))[:200]}
             for c in data.get("clues") or [] if isinstance(c, dict) and c.get("clue")]
    if not clues:  # older readers (the CLI, saved results) use the flat list
        clues = [{"clue": f"{c['label']}: {c['seen']}", "suggests": c["suggests"]} for c in checklist]
    ruled_out = [{"place": str(r.get("place", ""))[:80], "why": str(r.get("why") or "")[:200]}
                 for r in data.get("ruled_out") or [] if isinstance(r, dict) and r.get("place")]
    web_checks = [{"query": str(w.get("query", ""))[:160], "found": str(w.get("found") or "")[:300]}
                  for w in data.get("web_checks") or [] if isinstance(w, dict) and w.get("query")]
    countries = {}
    for c in data.get("countries") or []:
        try:
            code, p = str(c["iso2"]).strip().upper(), min(max(float(c["probability"]), 0.0), 1.0)
        except (KeyError, TypeError, ValueError):
            continue
        if len(code) == 2 and code.isalpha() and p > 0:
            countries[code] = countries.get(code, 0.0) + p
    total = sum(countries.values())
    if total > 1:
        countries = {k: v / total for k, v in countries.items()}
    countries = [{"iso2": k, "probability": round(v, 4)}
                 for k, v in sorted(countries.items(), key=lambda kv: -kv[1])[:6]]
    side = str(data.get("driving_side", "unknown")).lower()
    return {"reasoning": str(data.get("reasoning", ""))[:2000], "checklist": checklist[:14],
            "clues": clues[:14], "ruled_out": ruled_out[:4],
            "driving_side": side if side in ("left", "right") else "unknown",
            "text_seen": str(data.get("text_seen", ""))[:400], "web_checks": web_checks[:10],
            "countries": countries,
            "guesses": guesses[:5]}


def ask(provider, img, briefing=None, status=None, crops=None, model=None, effort=None,
        web=True):
    """One analyst's answer as a JSON-ready dict; never raises.
    crops: from sign_crops(); sent after the whole photo as zoomed views of the text.
    model, effort: passed to the CLI (empty = the CLI's own default).
    web: let it search the web to check what it read (CLI sign-ins only)."""
    status = status or detect()[provider]
    crops = crops or []
    effort = effort if effort in EFFORTS else None
    out = {"provider": provider, "name": NAMES[provider], "via": status.get("detail"),
           "ok": False, "error": None, "model": None, "effort": effort, "ms": None,
           "web": False,
           "crops": [{"box": c["box"], "text": c["text"], "kind": c.get("kind", "text")}
                     for c in crops]}
    if not status.get("available"):
        out["error"] = status.get("detail")
        PROGRESS.finish(provider, "error", out["error"])
        return out
    t = time.perf_counter()
    try:
        jpegs = [photo_jpeg(img)] + [c["jpeg"] for c in crops]
        PROGRESS.set(provider, stage="starting")
        web = bool(web) and status["via"] != "anthropic-api"
        out["web"] = web
        data, raw, used = BACKENDS[status["via"]](jpegs, prompt_text(briefing, crops, web),
                                                  model=model or None, effort=effort,
                                                  provider=provider, web=web)
        data = clean(data)
        out["model"] = used or model or None
        if not data or not data["guesses"]:
            out["error"] = "No usable answer. " + (raw or "")[:300]
        else:
            out.update(data, ok=True)
    except Stopped:
        out["error"], out["stopped"] = "Stopped before it answered.", True
    except subprocess.TimeoutExpired:
        out["error"] = f"No answer within {TIMEOUT_S} s."
    except Exception as e:
        out["error"] = f"{type(e).__name__}: {e}"[:500]
    out["ms"] = round((time.perf_counter() - t) * 1000)
    PROGRESS.finish(provider, "done" if out["ok"] else "stopped" if out.get("stopped") else "error",
                    out["error"])
    return out


def ask_all(providers, img, briefing=None, ocr_lines=None, options=None):
    """Ask each provider in parallel. ocr_lines: GeoLock's OCR result, used to cut zoomed
    crops of the signs (sent whether or not the briefing is shared: they are the photo).
    options: {"claude": {"model": "opus", "effort": "high", "web": True}, ...}"""
    providers = [p for p in dict.fromkeys(providers) if p in NAMES]
    if not providers:
        return []
    options = options or {}
    PROGRESS.begin(providers, options)
    status = detect()
    try:
        crops = sign_crops(img, ocr_lines) if ocr_lines and MAX_CROPS > 0 else []
    except Exception:  # a bad box must never cost the user their answer
        crops = []
    try:
        crops += detail_tiles(img)
    except Exception:
        pass
    with ThreadPoolExecutor(len(providers)) as ex:
        futs = [ex.submit(ask, p, img, briefing, status[p], crops,
                          (options.get(p) or {}).get("model"), (options.get(p) or {}).get("effort"),
                          (options.get(p) or {}).get("web", True))
                for p in providers]
        return [f.result() for f in futs]


# ------------------------------------------------------------------ model lists
_models_cache = {"t": 0.0, "value": None}
CLAUDE_ALIASES = {"fable": "Fable", "opus": "Opus", "sonnet": "Sonnet", "haiku": "Haiku"}


def _claude_models():
    """Model aliases and effort levels the installed Claude Code accepts (from its --help)."""
    models = [{"id": "", "name": "Default", "description": "What Claude Code uses for your plan"}]
    efforts = ["low", "medium", "high", "xhigh", "max"]
    aliases = ["opus", "sonnet", "haiku"]
    exe = _find_cli("claude")
    if exe:
        try:
            text = " ".join(_run([exe, "--help"], timeout=30).stdout.split())
            m = re.search(r"--effort <level> [^(]*\(([a-z, ]+)\)", text)
            if m:
                efforts = [e.strip() for e in m.group(1).split(",") if e.strip()]
            m = re.search(r"--model <model> .*?\(e\.g\. ([^)]*)\)", text)
            if m:
                named = re.findall(r"'([a-z][a-z0-9-]*)'", m.group(1))
                aliases = list(dict.fromkeys(named + aliases))
        except Exception:
            pass
    for a in aliases:
        name = CLAUDE_ALIASES.get(a, a.capitalize())
        models.append({"id": a, "name": name, "description": f"The latest {name} model"})
    return {"models": models, "efforts": [e for e in efforts if e in EFFORTS],
            "installed": bool(exe)}


def _chatgpt_models():
    """The models the installed Codex CLI lists (its own catalogue), with their effort levels."""
    models = [{"id": "", "name": "Default", "description": "What your Codex settings pick"}]
    efforts = ["low", "medium", "high", "xhigh"]
    exe = _find_cli("codex")
    if exe:
        catalogue = None
        for extra in ([], ["--bundled"]):
            try:
                p = _run([exe, "debug", "models", *extra], timeout=30)
                catalogue = json.loads(p.stdout).get("models")
                if catalogue:
                    break
            except Exception:
                continue
        for m in sorted(catalogue or [], key=lambda m: m.get("priority", 999)):
            if m.get("visibility") not in (None, "list") or not m.get("slug"):
                continue
            if "image" not in (m.get("input_modalities") or ["image"]):
                continue  # GeoLock sends a photo
            levels = [l.get("effort") for l in m.get("supported_reasoning_levels") or []]
            models.append({"id": m["slug"], "name": m.get("display_name") or m["slug"],
                           "description": m.get("description") or "",
                           "efforts": [l for l in levels if l in EFFORTS],
                           "default_effort": m.get("default_reasoning_level")})
        all_levels = [l for m in models[1:] for l in m.get("efforts", [])]
        if all_levels:
            efforts = [e for e in EFFORTS if e in all_levels]
    return {"models": models, "efforts": efforts, "installed": bool(exe)}


def model_options(refresh=False):
    """{"claude": {"models": [...], "efforts": [...]}, "chatgpt": {...}}. Cached 10 min."""
    if refresh or _models_cache["value"] is None or time.time() - _models_cache["t"] > 600:
        with ThreadPoolExecutor(2) as ex:
            c, g = ex.submit(_claude_models), ex.submit(_chatgpt_models)
            _models_cache["value"] = {"claude": c.result(), "chatgpt": g.result()}
        _models_cache["t"] = time.time()
    return _models_cache["value"]


# ------------------------------------------------------------------ fusion
SNAP_KM = 150  # an analyst's coordinates may be this far from the town it names
SNAP_SLACK_KM = 15  # closer than this (or half its radius) to the named town: left as given


def snap_guesses(a, find_town):
    """Analysts often name the right town but give coordinates tens of km off. Move each
    guess onto the town it names, looked up in GeoLock's own list of 140k places
    (find_town(name, iso2, lat, lon) -> {"name", "admin1", "lat", "lon", "km"} or None).
    The place parts are tried most specific first; a match farther than SNAP_KM (or the
    guess's own radius, if larger) is a different town of the same name and is skipped.
    A guess already near its town (SNAP_SLACK_KM, or half its radius) is left alone, so a
    street-level point an analyst confirmed online is not pulled to the town centre.
    Each moved guess keeps its original point in "snapped". Changes `a` in place."""
    for g in a.get("guesses") or []:
        if g.get("snapped") or not g.get("iso2") or g.get("radius_km", 0) > 400:
            continue  # done before, or a guess too vague to pin to one town
        for part in re.split(r"[,;/()]", g.get("place") or ""):
            part = part.strip()
            if len(part) < 3:
                continue
            town = find_town(part, g["iso2"], g["lat"], g["lon"])
            if not town or town["km"] > max(SNAP_KM, g.get("radius_km", 0)):
                continue
            if town["km"] <= max(SNAP_SLACK_KM, 0.5 * g.get("radius_km", 0)):
                break  # consistent with the town already (it may be a precise street point)
            g["snapped"] = {"to": town["name"], "region": town["admin1"],
                            "km": round(town["km"], 1), "lat": g["lat"], "lon": g["lon"]}
            g["lat"], g["lon"] = town["lat"], town["lon"]
            break
    return a


def analyst_clues(a, codes, name_fn=None):
    """Turn one analyst's answer into clues. Its location guesses become one clue that the
    engine blends in as a mixture (Geolocator.mix_analysts); its country, driving side,
    observations and the text it read are shown but carry no extra weight, since they are
    already part of its location answer."""
    if not a.get("ok"):
        return []
    name, kind = a["name"], a["provider"]
    gs = a["guesses"]
    if a.get("checklist"):
        clues = [Clue(kind=kind, title=f"{c['label']}: {c['seen']}", detail=c["suggests"])
                 for c in a["checklist"][:10]]
    else:  # answers saved before the checklist
        clues = [Clue(kind=kind, title=c["clue"], detail=c["suggests"]) for c in a.get("clues", [])[:8]]
    spots = [(g["lat"], g["lon"], g["radius_km"], g["confidence"]) for g in gs]
    top = max(g["confidence"] for g in gs) or 1e-3

    def point_fn(plat, plon, spots=spots, top=top):
        """How strongly the analyst points at a place, 0..1 (for the explanations)."""
        plat, plon = np.asarray(plat, dtype=np.float64), np.asarray(plon, dtype=np.float64)
        best = np.zeros(np.broadcast(plat, plon).shape)
        for la, lo, r, p in spots:
            sg = min(max(r, 25.0), 1500.0)
            d = haversine_km(la, lo, plat, plon)
            best = np.maximum(best, max(p, 1e-3) / top * np.exp(-0.5 * (d / sg) ** 2))
        return best

    g0 = gs[0]
    where = ", ".join(x for x in (g0["place"], g0["country"]) if x) or f"{g0['lat']:.2f}, {g0['lon']:.2f}"
    clues.append(Clue(kind=kind, title=f"{name} places it in {where}",
                      detail=f"{g0['confidence']:.0%} sure, within about {g0['radius_km']:.0f} km."
                             + (f" {g0['why']}" if g0.get("why") else "")
                             + (f" {len(gs) - 1} other guess(es)." if len(gs) > 1 else ""),
                      mix=1.0, spots=spots, point_fn=point_fn))
    valid = set(codes)
    odds = {c["iso2"]: c["probability"] for c in a.get("countries") or [] if c["iso2"] in valid}
    if odds:
        # Country odds: the probability the analyst left outside its pinned guesses follows
        # these instead of GeoLock's own country split (Geolocator.mix_analysts).
        clues[-1].country_odds = odds
        countries = dict(odds)
    else:  # older answers: the countries of its guesses
        countries = {}
        for g in gs:
            if g["iso2"] in valid:
                countries[g["iso2"]] = countries.get(g["iso2"], 0) + g["confidence"]
    if len(countries) > 1:
        ctop = max(countries.values())
        names = ", ".join(f"{name_fn(c) if name_fn else c} {p:.0%}"
                          for c, p in sorted(countries.items(), key=lambda kv: -kv[1])[:4])
        clues.append(Clue(kind=kind, title=f"{name}'s country guesses", detail=names,
                          countries={c: p / ctop for c, p in countries.items()}))
    seen_side = any(c["category"] == "driving_side" for c in a.get("checklist") or [])
    if a.get("driving_side") in ("left", "right") and not seen_side:
        clues.append(Clue(kind=kind, title=f"Traffic drives on the {a['driving_side']}",
                          detail=f"Seen by {name}."))
    if a.get("text_seen"):
        clues.append(Clue(kind=kind, title=f"Text {name} read", detail="“" + a["text_seen"][:200] + "”"))
    return clues
