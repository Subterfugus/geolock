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

from .clues import Clue
from .geodata import haversine_km
from .vlm import parse

TIMEOUT_S = int(os.environ.get("GEOLOCK_LLM_TIMEOUT", "240"))
MAX_SIDE = 1568  # Claude's largest useful image side; plenty for ChatGPT too

NAMES = {"claude": "Claude", "chatgpt": "ChatGPT"}

SYSTEM = ("You are a world-class photo geolocation analyst, as good as the best GeoGuessr "
          "players. You look for concrete evidence such as text and its language, road "
          "markings, signs, bollards, utility poles, licence plates, driving side, "
          "architecture, vegetation, soil, terrain and sun, and you reason carefully before "
          "committing. You answer only with the requested JSON.")

INSTRUCTIONS = """Where on Earth was this photo taken?

Study the photo first and form your own view. Then read the notes from GeoLock, an offline
model, if any are given below. GeoLock's visual guesses are often wrong by hundreds or
thousands of km on photos without text, so treat them as weak hints; text it read and
time zones are more reliable. Do not run commands or use tools; answer from the image.

Answer with JSON:
- reasoning: 3 to 6 sentences on how you got to your answer.
- clues: the concrete things you saw, each with what it suggests.
- driving_side: left, right or unknown.
- text_seen: any text you can read in the photo, or an empty string.
- guesses: 1 to 5 distinct locations, best first, each with place (as specific as you
  can justify), country, iso2 (ISO 3166-1 alpha-2), lat, lon, radius_km (how far off you
  might be) and confidence (probability from 0 to 1 that the photo is within radius_km;
  all guesses together at most 1)."""

SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["reasoning", "clues", "driving_side", "text_seen", "guesses"],
    "properties": {
        "reasoning": {"type": "string"},
        "clues": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["clue", "suggests"],
            "properties": {"clue": {"type": "string"}, "suggests": {"type": "string"}}}},
        "driving_side": {"type": "string", "enum": ["left", "right", "unknown"]},
        "text_seen": {"type": "string"},
        "guesses": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["place", "country", "iso2", "lat", "lon", "radius_km", "confidence"],
            "properties": {
                "place": {"type": "string"}, "country": {"type": "string"},
                "iso2": {"type": "string"}, "lat": {"type": "number"},
                "lon": {"type": "number"}, "radius_km": {"type": "number"},
                "confidence": {"type": "number"}}}},
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


def photo_jpeg(img):
    """The pixels only, as JPEG: no EXIF, so GPS and camera serials never leave the machine."""
    im = img.convert("RGB")
    s = min(1.0, MAX_SIDE / max(im.size))
    if s < 1:
        im = im.resize((round(im.width * s), round(im.height * s)))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=90)
    return buf.getvalue()


def prompt_text(briefing):
    if not briefing:
        return INSTRUCTIONS
    return INSTRUCTIONS + "\n\nNotes from GeoLock:\n" + briefing


# ------------------------------------------------------------------ detection
_detect_cache = {"t": 0.0, "value": None}


def _claude_status():
    exe = shutil.which("claude")
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
    exe = shutil.which("codex")
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
def _ask_claude_code(jpeg, briefing, model=None):
    exe = shutil.which("claude")
    msg = {"type": "user", "message": {"role": "user", "content": [
        {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                     "data": base64.b64encode(jpeg).decode()}},
        {"type": "text", "text": prompt_text(briefing)}]}}
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


def _ask_anthropic_api(jpeg, briefing, model=None):
    import anthropic
    client = anthropic.Anthropic()
    model = model or os.environ.get("GEOLOCK_CLAUDE_MODEL") or "claude-opus-5-5"
    r = client.messages.create(
        model=model, max_tokens=16000, system=SYSTEM,
        output_config={"format": {"type": "json_schema", "schema": SCHEMA}},
        messages=[{"role": "user", "content": [
            {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                         "data": base64.b64encode(jpeg).decode()}},
            {"type": "text", "text": prompt_text(briefing)}]}])
    if r.stop_reason == "refusal":
        raise RuntimeError("Claude declined to answer.")
    text = next((b.text for b in r.content if b.type == "text"), "")
    return parse(text), text, r.model


def _ask_codex(jpeg, briefing, model=None):
    exe = shutil.which("codex")
    model = model or os.environ.get("GEOLOCK_CODEX_MODEL")
    with tempfile.TemporaryDirectory(prefix="geolock-") as tmp:
        img, schema, out = (os.path.join(tmp, n) for n in ("photo.jpg", "schema.json", "answer.json"))
        with open(img, "wb") as f:
            f.write(jpeg)
        with open(schema, "w", encoding="utf-8") as f:
            json.dump(SCHEMA, f)
        base = [exe, "exec", "--skip-git-repo-check", "--sandbox", "read-only", "-C", tmp,
                "--image", img, "--output-last-message", out, "--color", "never"]
        if model:
            base += ["--model", model]
        prompt = SYSTEM + "\n\n" + prompt_text(briefing)
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
    """Keep well-formed guesses only, with numbers in range."""
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
                        "radius_km": rad, "confidence": conf})
    total = sum(g["confidence"] for g in guesses)
    if total > 1:
        for g in guesses:
            g["confidence"] /= total
    clues = [{"clue": str(c.get("clue", ""))[:160], "suggests": str(c.get("suggests", ""))[:200]}
             for c in data.get("clues") or [] if isinstance(c, dict) and c.get("clue")]
    side = str(data.get("driving_side", "unknown")).lower()
    return {"reasoning": str(data.get("reasoning", ""))[:2000], "clues": clues[:12],
            "driving_side": side if side in ("left", "right") else "unknown",
            "text_seen": str(data.get("text_seen", ""))[:400], "guesses": guesses[:5]}


def ask(provider, img, briefing=None, status=None):
    """One analyst's answer as a JSON-ready dict; never raises."""
    status = status or detect()[provider]
    out = {"provider": provider, "name": NAMES[provider], "via": status.get("detail"),
           "ok": False, "error": None, "model": None, "ms": None}
    if not status.get("available"):
        out["error"] = status.get("detail")
        return out
    t = time.perf_counter()
    try:
        data, raw, model = BACKENDS[status["via"]](photo_jpeg(img), briefing)
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


def ask_all(providers, img, briefing=None):
    providers = [p for p in dict.fromkeys(providers) if p in NAMES]
    if not providers:
        return []
    status = detect()
    with ThreadPoolExecutor(len(providers)) as ex:
        futs = [ex.submit(ask, p, img, briefing, status[p]) for p in providers]
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
    if a.get("driving_side") in ("left", "right"):
        clues.append(Clue(kind=kind, title=f"Traffic drives on the {a['driving_side']}",
                          detail=f"Seen by {name}."))
    if a.get("text_seen"):
        clues.append(Clue(kind=kind, title=f"Text {name} read", detail="“" + a["text_seen"][:200] + "”"))
    return clues
