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
"""
import base64
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
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
misread characters, so trust your own reading of the crops when they differ. Do not run
commands or use tools; answer from the images.

Answer with JSON:
- checklist: the items you could see, each with category (one of {categories}), seen
  (what you saw, concretely) and suggests (what it points to or rules out).
- reasoning: 3 to 6 sentences on how the evidence combines into your answer.
- ruled_out: up to 4 plausible-looking countries or regions you rejected, each with
  place and why (the evidence against it). Empty if none.
- driving_side: left, right or unknown.
- text_seen: any text you can read in the photo or crops, or an empty string.
- guesses: 1 to 5 distinct locations, best first, each with place (as specific as you
  can justify: city, region or road), country, iso2 (ISO 3166-1 alpha-2), lat, lon,
  radius_km (how far off you might be), confidence (probability from 0 to 1 that the
  photo is within radius_km; all guesses together at most 1) and why (one sentence:
  the evidence for this guess over the others)."""

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
    "required": ["checklist", "reasoning", "ruled_out", "driving_side", "text_seen", "guesses"],
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


def _overlap(a, b):
    """Intersection over the smaller box."""
    ix = max(0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    small = min((a[2] - a[0]) * (a[3] - a[1]), (b[2] - b[0]) * (b[3] - b[1])) or 1
    return ix * iy / small


def prompt_text(briefing, crops=()):
    if crops:
        which = "Image 2 is a zoomed crop" if len(crops) == 1 else \
            f"Images 2 to {len(crops) + 1} are zoomed crops"
        lines = [f"You get {len(crops) + 1} images. Image 1 is the whole photo. {which} of it, "
                 "cut at full resolution where GeoLock found text, so you can read signs, "
                 "plates and shop fronts:"]
        for i, c in enumerate(crops, 2):  # the OCR reading is a GeoLock finding: only if shared
            lines.append(f"- Image {i}: region x {c['box'][0]}-{c['box'][2]}, y {c['box'][1]}-"
                         f"{c['box'][3]} of the photo"
                         + (f"; OCR read “{c['text']}”" if briefing else ""))
        images = "\n" + "\n".join(lines) + "\n"
    else:
        images = ""
    text = INSTRUCTIONS.format(
        images=images,
        checklist="\n".join(f"{i}. {t}" for i, t in enumerate(CHECKLIST.values(), 1)),
        categories=", ".join(CHECKLIST))
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


def _ask_claude_code(jpegs, prompt, model=None):
    exe = _find_cli("claude")
    msg = {"type": "user", "message": {"role": "user", "content":
           _image_blocks(jpegs) + [{"type": "text", "text": prompt}]}}
    base = [exe, "-p", "--input-format", "stream-json", "--output-format", "stream-json",
            "--verbose"]
    extra = ["--no-session-persistence", "--tools", "", "--setting-sources", "",
             "--strict-mcp-config", "--system-prompt", SYSTEM,
             "--json-schema", json.dumps(SCHEMA, separators=(",", ":"))]
    model = model or os.environ.get("GEOLOCK_CLAUDE_MODEL")
    if model:
        base += ["--model", model]
    with tempfile.TemporaryDirectory(prefix="geolock-") as tmp:  # no CLAUDE.md to pick up
        p = _run(base + extra, stdin=json.dumps(msg) + "\n", cwd=tmp)
        if _unknown_flag(p):  # older Claude Code: plain run, JSON from the text
            p = _run(base, stdin=json.dumps(msg) + "\n", cwd=tmp)
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


def _ask_anthropic_api(jpegs, prompt, model=None):
    import anthropic
    client = anthropic.Anthropic()
    model = model or os.environ.get("GEOLOCK_CLAUDE_MODEL") or "claude-opus-5-5"
    r = client.messages.create(
        model=model, max_tokens=16000, system=SYSTEM,
        output_config={"format": {"type": "json_schema", "schema": SCHEMA}},
        messages=[{"role": "user", "content":
                   _image_blocks(jpegs) + [{"type": "text", "text": prompt}]}])
    if r.stop_reason == "refusal":
        raise RuntimeError("Claude declined to answer.")
    text = next((b.text for b in r.content if b.type == "text"), "")
    return parse(text), text, r.model


def _ask_codex(jpegs, prompt, model=None):
    exe = _find_cli("codex")
    model = model or os.environ.get("GEOLOCK_CODEX_MODEL")
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
        prompt = SYSTEM + "\n\n" + prompt
        p = _run(base + ["--ephemeral", "--output-schema", schema, "-"], stdin=prompt, cwd=tmp)
        if _unknown_flag(p):  # older Codex CLI
            p = _run(base + ["-"], stdin=prompt, cwd=tmp)
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
    side = str(data.get("driving_side", "unknown")).lower()
    return {"reasoning": str(data.get("reasoning", ""))[:2000], "checklist": checklist[:14],
            "clues": clues[:14], "ruled_out": ruled_out[:4],
            "driving_side": side if side in ("left", "right") else "unknown",
            "text_seen": str(data.get("text_seen", ""))[:400], "guesses": guesses[:5]}


def ask(provider, img, briefing=None, status=None, crops=None):
    """One analyst's answer as a JSON-ready dict; never raises.
    crops: from sign_crops(); sent after the whole photo as zoomed views of the text."""
    status = status or detect()[provider]
    crops = crops or []
    out = {"provider": provider, "name": NAMES[provider], "via": status.get("detail"),
           "ok": False, "error": None, "model": None, "ms": None,
           "crops": [{"box": c["box"], "text": c["text"]} for c in crops]}
    if not status.get("available"):
        out["error"] = status.get("detail")
        return out
    t = time.perf_counter()
    try:
        jpegs = [photo_jpeg(img)] + [c["jpeg"] for c in crops]
        data, raw, model = BACKENDS[status["via"]](jpegs, prompt_text(briefing, crops))
        data = clean(data)
        out["model"] = model
        if not data or not data["guesses"]:
            out["error"] = "No usable answer. " + (raw or "")[:300]
        else:
            out.update(data, ok=True)
    except subprocess.TimeoutExpired:
        out["error"] = f"No answer within {TIMEOUT_S} s."
    except Exception as e:
        out["error"] = f"{type(e).__name__}: {e}"[:500]
    out["ms"] = round((time.perf_counter() - t) * 1000)
    return out


def ask_all(providers, img, briefing=None, ocr_lines=None):
    """Ask each provider in parallel. ocr_lines: GeoLock's OCR result, used to cut zoomed
    crops of the signs (sent whether or not the briefing is shared: they are the photo)."""
    providers = [p for p in dict.fromkeys(providers) if p in NAMES]
    if not providers:
        return []
    status = detect()
    try:
        crops = sign_crops(img, ocr_lines) if ocr_lines and MAX_CROPS > 0 else []
    except Exception:  # a bad box must never cost the user their answer
        crops = []
    with ThreadPoolExecutor(len(providers)) as ex:
        futs = [ex.submit(ask, p, img, briefing, status[p], crops) for p in providers]
        return [f.result() for f in futs]


# ------------------------------------------------------------------ fusion
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
