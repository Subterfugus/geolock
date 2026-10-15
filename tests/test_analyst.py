"""Claude / ChatGPT second opinions, tested against fake `claude` and `codex` commands."""
import json
import os
import stat
import sys

import numpy as np
import pytest
from PIL import Image

from geolock import analyst
from geolock.geodata import GeoData

ANSWER = {"checklist": [{"category": "script_language", "seen": "Hauptbahnhof 2 km",
                          "suggests": "German: Germany, Austria or Switzerland"},
                         {"category": "signs", "seen": "yellow direction sign",
                          "suggests": "Germany; Austria uses blue or green"},
                         {"category": "driving_side", "seen": "cars on the right",
                          "suggests": "not UK or Ireland"}],
          "reasoning": "German text and a yellow direction sign.",
          "ruled_out": [{"place": "Switzerland", "why": "Swiss direction signs are white on blue"}],
          "driving_side": "right", "text_seen": "Hauptbahnhof 2 km",
          "countries": [{"iso2": "de", "probability": 0.7}, {"iso2": "AT", "probability": 0.2}],
          "guesses": [{"place": "Cologne", "country": "Germany", "iso2": "DE", "lat": 50.94,
                       "lon": 6.96, "radius_km": 50, "confidence": 0.5,
                       "why": "Yellow German direction sign"},
                      {"place": "Vienna", "country": "Austria", "iso2": "AT", "lat": 48.21,
                       "lon": 16.37, "radius_km": 80, "confidence": 0.2, "why": "German text"}]}


def _fake(tmp_path, name, body):
    """Write a fake CLI as a Python script (plus a .cmd shim on Windows)."""
    script = tmp_path / f"{name}.py"
    script.write_text(body)
    if sys.platform == "win32":
        (tmp_path / f"{name}.cmd").write_text(f'@"{sys.executable}" "{script}" %*\n')
    else:
        exe = tmp_path / name
        exe.write_text(f"#!{sys.executable}\n" + body)
        exe.chmod(exe.stat().st_mode | stat.S_IEXEC)


FAKE_CLAUDE = """
import json, sys
args = sys.argv[1:]
if args[:2] == ["auth", "status"]:
    print(json.dumps({"loggedIn": True, "authMethod": "oauth_token"})); sys.exit(0)
if args == ["--help"]:
    print("  --effort <level>     Effort level for the current session\\n"
          "                       (low, medium, high, xhigh, max)\\n"
          "  --model <model>      Model for the current session. Provide\\n"
          "                       an alias for the latest model (e.g.\\n"
          "                       'fable', 'opus', or 'sonnet') or a\\n"
          "                       model's full name."); sys.exit(0)
msg = json.loads(sys.stdin.readline())
content = msg["message"]["content"]
images = [c for c in content if c["type"] == "image"]
assert images and all(c["source"]["media_type"] == "image/jpeg" for c in images)
assert content[-1]["type"] == "text"
assert "--json-schema" in args and "--tools" in args
here = __import__("os").path.dirname(sys.argv[0])
open(__import__("os").path.join(here, "claude.prompt"), "w").write(content[-1]["text"])
open(__import__("os").path.join(here, "claude.images"), "w").write(str(len(images)))
open(__import__("os").path.join(here, "claude.args"), "w").write(json.dumps(args))
if "--include-partial-messages" in args:
    ev = lambda e: print(json.dumps({"type": "stream_event", "event": e}), flush=True)
    print(json.dumps({"type": "system", "subtype": "init", "model": "claude-test"}), flush=True)
    ev({"type": "message_start", "message": {"model": "claude-test"}})
    ev({"type": "content_block_start", "content_block": {"type": "thinking"}})
    ev({"type": "content_block_delta", "delta": {"type": "thinking_delta", "thinking": "Looking at the signs.\\nYellow sign: Germany"}})
    ev({"type": "content_block_start", "content_block": {"type": "text"}})
    ev({"type": "content_block_delta", "delta": {"type": "text_delta", "text": "{}"}})
if "slow" in open(__import__("os").path.join(here, "mode")).read():
    __import__("time").sleep(60)
if "WebSearch,WebFetch" in args:
    print(json.dumps({"type": "assistant", "message": {"model": "claude-test", "content": [
        {"type": "tool_use", "name": "WebSearch", "input": {"query": "Bäckerei Schmitz Köln"}}]}}), flush=True)
print(json.dumps({"type": "assistant", "message": {"model": "claude-test", "content": []}}))
print(json.dumps({"type": "result", "is_error": False, "result": "ok",
                  "structured_output": ANSWER}))
"""

FAKE_CODEX = """
import json, sys
args = sys.argv[1:]
if args[:2] == ["login", "status"]:
    print("Logged in using ChatGPT"); sys.exit(0)
if args[:2] == ["debug", "models"]:
    lv = lambda *ls: [{"effort": l, "description": ""} for l in ls]
    print(json.dumps({"models": [
        {"slug": "gpt-b", "display_name": "GPT-B", "visibility": "list", "priority": 2,
         "input_modalities": ["text", "image"], "supported_reasoning_levels": lv("low", "high", "ultra"),
         "default_reasoning_level": "low"},
        {"slug": "gpt-a", "display_name": "GPT-A", "visibility": "list", "priority": 1,
         "input_modalities": ["text", "image"], "supported_reasoning_levels": lv("low", "medium", "xhigh")},
        {"slug": "gpt-text", "display_name": "Text only", "visibility": "list", "priority": 3,
         "input_modalities": ["text"]},
        {"slug": "secret", "display_name": "Hidden", "visibility": "hide", "priority": 0}]})); sys.exit(0)
assert args[0] == "exec" and "--image" in args and "--output-schema" in args
imgs = [args[i + 1] for i, a in enumerate(args) if a == "--image"]
assert all(open(img, "rb").read(2) == b"\\xff\\xd8" for img in imgs)
assert args[-1] == "-"  # the prompt comes from stdin, not eaten by --image
prompt = sys.stdin.read()
assert "Where on Earth" in prompt
here = __import__("os").path.dirname(sys.argv[0])
open(__import__("os").path.join(here, "codex.images"), "w").write(str(len(imgs)))
open(__import__("os").path.join(here, "codex.args"), "w").write(json.dumps(args))
if "--json" in args:
    print(json.dumps({"type": "turn.started"}), flush=True)
    print(json.dumps({"type": "item.completed", "item": {"type": "reasoning", "text": "**Reading the sign**"}}), flush=True)
    if 'web_search="live"' in args:
        for kind in ("item.started", "item.completed"):  # one search, reported twice
            print(json.dumps({"type": kind, "item": {"id": "ws1", "type": "web_search", "query": "Hauptbahnhof sign"}}), flush=True)
out = args[args.index("--output-last-message") + 1]
open(out, "w").write(json.dumps(ANSWER))
"""


@pytest.fixture
def fake_clis(tmp_path, monkeypatch):
    answer = f"ANSWER = {json.dumps(ANSWER)!r}\nANSWER = __import__('json').loads(ANSWER)\n"
    _fake(tmp_path, "claude", answer + FAKE_CLAUDE)
    _fake(tmp_path, "codex", answer + FAKE_CODEX)
    (tmp_path / "mode").write_text("fast")
    monkeypatch.setenv("PATH", str(tmp_path) + os.pathsep + os.environ["PATH"])
    analyst._detect_cache["value"] = None
    yield tmp_path
    analyst._detect_cache["value"] = None


def test_detects_signed_in_clis(fake_clis):
    st = analyst.detect(refresh=True)
    assert st["claude"]["available"] and st["claude"]["via"] == "claude-code"
    assert st["chatgpt"]["available"] and st["chatgpt"]["via"] == "codex"


def test_asks_both_and_strips_metadata(fake_clis):
    img = Image.new("RGB", (3000, 2000), (20, 90, 40))
    res = analyst.ask_all(["claude", "chatgpt"], img, briefing="Top guesses: 1. Germany")
    assert [r["provider"] for r in res] == ["claude", "chatgpt"]
    for r in res:
        assert r["ok"], r["error"]
        assert r["guesses"][0]["iso2"] == "DE" and r["driving_side"] == "right"
    assert res[0]["model"] == "claude-test"
    prompt = (fake_clis / "claude.prompt").read_text()
    assert "Notes from GeoLock" in prompt and "Bollards and roadside posts" in prompt
    assert "Images 2 to 3 are close-ups" in prompt and "Image 2: tile" in prompt
    assert (fake_clis / "claude.images").read_text() == "3"
    r = res[0]
    assert [c["category"] for c in r["checklist"]] == ["driving_side", "signs", "script_language"]
    assert r["checklist"][1]["label"] == "Signs" and r["guesses"][0]["why"]
    assert r["ruled_out"][0]["place"] == "Switzerland"
    # a 3000 px photo also gets two close-up tiles of the road band, sent at full size
    assert [c["kind"] for c in r["crops"]] == ["tile", "tile"]
    assert r["countries"] == [{"iso2": "DE", "probability": 0.7}, {"iso2": "AT", "probability": 0.2}]
    assert r["clues"][0]["clue"].startswith("Driving side: ")  # flat list for older readers


def test_model_and_effort_reach_the_clis(fake_clis):
    img = Image.new("RGB", (800, 600), (20, 90, 40))
    res = analyst.ask_all(["claude", "chatgpt"], img, options={
        "claude": {"model": "opus", "effort": "high"}, "chatgpt": {"model": "gpt-a", "effort": "xhigh"}})
    assert all(r["ok"] for r in res), [r["error"] for r in res]
    cargs = json.loads((fake_clis / "claude.args").read_text())
    assert cargs[cargs.index("--model") + 1] == "opus" and cargs[cargs.index("--effort") + 1] == "high"
    gargs = json.loads((fake_clis / "codex.args").read_text())
    assert gargs[gargs.index("--model") + 1] == "gpt-a"
    assert 'model_reasoning_effort="xhigh"' in gargs and gargs[-1] == "-"
    assert res[0]["effort"] == "high" and res[1]["model"] == "gpt-a"
    # no choice: no flags, the CLI's own defaults
    analyst.ask_all(["claude"], img)
    cargs = json.loads((fake_clis / "claude.args").read_text())
    assert "--model" not in cargs and "--effort" not in cargs


def test_progress_follows_the_stream(fake_clis):
    img = Image.new("RGB", (800, 600), (20, 90, 40))
    analyst.ask_all(["claude", "chatgpt"], img, options={"claude": {"effort": "low", "web": False},
                                                         "chatgpt": {"web": False}})
    snap = analyst.PROGRESS.snapshot()
    assert not snap["running"]
    c, g = snap["providers"]["claude"], snap["providers"]["chatgpt"]
    assert c["stage"] == g["stage"] == "done"
    assert c["model"] == "claude-test" and c["effort"] == "low" and c["chars"] > 10
    assert c["note"] == "Yellow sign: Germany"  # the latest line of its thinking
    assert g["note"] == "Reading the sign"


def test_web_search_is_on_by_default_and_can_be_turned_off(fake_clis):
    img = Image.new("RGB", (800, 600), (20, 90, 40))
    ans = dict(ANSWER, web_checks=[{"query": "Bäckerei Schmitz Köln", "found": "A bakery on Aachener Str., Cologne"}])
    assert analyst.clean(ans)["web_checks"][0]["found"].startswith("A bakery")
    res = analyst.ask_all(["claude", "chatgpt"], img)
    assert all(r["ok"] and r["web"] for r in res), [r["error"] for r in res]
    cargs = json.loads((fake_clis / "claude.args").read_text())
    assert cargs[cargs.index("--tools") + 1] == "WebSearch,WebFetch"
    assert cargs[cargs.index("--allowedTools") + 1] == "WebSearch,WebFetch"
    assert "You can search the web" in (fake_clis / "claude.prompt").read_text()
    gargs = json.loads((fake_clis / "codex.args").read_text())
    assert 'web_search="live"' in gargs
    snap = analyst.PROGRESS.snapshot()["providers"]
    assert snap["claude"]["searches"] == 1 and snap["chatgpt"]["searches"] == 1

    res = analyst.ask_all(["claude", "chatgpt"], img, options={"claude": {"web": False},
                                                                "chatgpt": {"web": False}})
    assert all(r["ok"] and not r["web"] for r in res)
    cargs = json.loads((fake_clis / "claude.args").read_text())
    assert cargs[cargs.index("--tools") + 1] == "" and "--allowedTools" not in cargs
    assert "Do not run commands or use tools" in (fake_clis / "claude.prompt").read_text()
    assert 'web_search="disabled"' in json.loads((fake_clis / "codex.args").read_text())
    assert analyst.PROGRESS.snapshot()["providers"]["claude"]["searches"] == 0


def test_stop_ends_a_running_analyst(fake_clis):
    import threading
    (fake_clis / "mode").write_text("slow")
    img = Image.new("RGB", (800, 600), (20, 90, 40))
    out = {}
    t = threading.Thread(target=lambda: out.setdefault("r", analyst.ask_all(["claude"], img)))
    t.start()
    for _ in range(100):  # wait until the fake CLI is thinking
        if analyst.PROGRESS.snapshot()["providers"].get("claude", {}).get("stage") == "writing":
            break
        __import__("time").sleep(0.1)
    assert analyst.PROGRESS.snapshot()["running"]
    assert analyst.PROGRESS.cancel() == 1
    t.join(timeout=15)
    assert not t.is_alive()
    (r,) = out["r"]
    assert not r["ok"] and r["stopped"] and r["ms"] < 30000
    assert analyst.PROGRESS.snapshot()["providers"]["claude"]["stage"] == "stopped"
    (fake_clis / "mode").write_text("fast")
    assert analyst.ask_all(["claude"], img)[0]["ok"]  # the next ask is not stopped


def test_stop_before_the_analyst_starts_is_kept(fake_clis):
    """Stop pressed while GeoLock's own analysis still runs: the analyst is never launched."""
    img = Image.new("RGB", (800, 600), (20, 90, 40))
    (fake_clis / "claude.args").unlink(missing_ok=True)
    analyst.PROGRESS.begin(["claude"], request_start=True)  # the backend, as the request arrives
    analyst.PROGRESS.cancel()
    (r,) = analyst.ask_all(["claude"], img)
    assert r["stopped"] and not (fake_clis / "claude.args").exists()
    assert analyst.ask_all(["claude"], img)[0]["ok"]  # a later ask starts fresh


def test_model_lists_come_from_the_clis(fake_clis):
    opts = analyst.model_options(refresh=True)
    c, g = opts["claude"], opts["chatgpt"]
    assert [m["id"] for m in c["models"]] == ["", "fable", "opus", "sonnet", "haiku"]
    assert c["efforts"] == ["low", "medium", "high", "xhigh", "max"]
    assert [m["id"] for m in g["models"]] == ["", "gpt-a", "gpt-b"]  # by priority; listed, takes images
    assert g["models"][2]["efforts"] == ["low", "high"] and g["models"][2]["default_effort"] == "low"
    assert g["efforts"] == ["low", "medium", "high", "xhigh"]


def _sign_photo():
    """A 2000x1500 photo with a two-line sign at the top left and a plate at the bottom right."""
    img = Image.new("RGB", (2000, 1500), (70, 120, 60))
    lines = [{"text": "Hauptbahnhof", "score": 0.95, "box": [[200, 200], [600, 200], [600, 250], [200, 250]]},
             {"text": "2 km", "score": 0.9, "box": [[220, 270], [400, 270], [400, 320], [220, 320]]},
             {"text": "K AB 123", "score": 0.7, "box": [[1600, 1300], [1750, 1300], [1750, 1330], [1600, 1330]]},
             {"text": "huge", "score": 0.99, "box": [[0, 0], [2000, 0], [2000, 1400], [0, 1400]]}]
    return img, lines


def test_sign_crops_group_lines_and_zoom_in():
    img, lines = _sign_photo()
    crops = analyst.sign_crops(img, lines)
    assert len(crops) == 2  # the two sign lines become one crop; the whole-photo box is no zoom
    sign, plate = crops
    assert sign["text"] == "Hauptbahnhof / 2 km"
    x0, y0, x1, y1 = sign["box"]
    assert x0 < 200 and y0 < 200 and x1 > 600 and y1 > 320 and (x1 - x0) < 1000
    assert plate["text"] == "K AB 123" and plate["box"][0] < 1600 < plate["box"][2]
    for c in crops:
        im = Image.open(__import__("io").BytesIO(c["jpeg"]))
        assert analyst.CROP_MIN_SIDE <= max(im.size) <= analyst.CROP_SIDE and not im.getexif()
    assert analyst.sign_crops(img, []) == [] and analyst.sign_crops(img, [{"box": "bad"}]) == []
    assert len(analyst.sign_crops(img, lines, max_crops=1)) == 1


def test_tiles_only_for_big_photos():
    assert analyst.detail_tiles(Image.new("RGB", (2000, 1500))) == []  # already detailed
    tiles = analyst.detail_tiles(Image.new("RGB", (4000, 3000)))
    assert [t["box"] for t in tiles] == [[0, 900, 2000, 2700], [2000, 900, 4000, 2700]]
    im = Image.open(__import__("io").BytesIO(tiles[0]["jpeg"]))
    assert max(im.size) == analyst.MAX_SIDE  # about twice the detail of the whole photo
    assert analyst.detail_tiles(Image.new("RGB", (4000, 3000)), n=0) == []


def test_country_odds_are_cleaned():
    d = analyst.clean(dict(ANSWER, countries=[
        {"iso2": "de", "probability": 0.9}, {"iso2": "AT", "probability": 0.6},
        {"iso2": "XYZ", "probability": 0.5}, {"iso2": "CH"}, {"iso2": "FR", "probability": 0}]))
    assert [c["iso2"] for c in d["countries"]] == ["DE", "AT"]
    assert sum(c["probability"] for c in d["countries"]) == pytest.approx(1, abs=1e-3)
    assert analyst.clean({"guesses": ANSWER["guesses"]})["countries"] == []  # older answers


def _towns(rows):
    """find_town over a small list of (name, iso2, lat, lon)."""
    from geolock.geodata import haversine_km, norm_name

    def find(name, cc, lat, lon):
        hits = [(float(haversine_km(lat, lon, la, lo)), n, la, lo) for n, c, la, lo in rows
                if c == cc and norm_name(n) == norm_name(name)]
        if not hits:
            return None
        km, n, la, lo = min(hits)
        return {"name": n, "admin1": "", "lat": la, "lon": lo, "km": km}
    return find


def test_guesses_snap_to_the_town_they_name():
    find = _towns([("Cologne", "IT", 45.58, 9.94), ("Koln", "DE", 50.94, 6.96),
                   ("Saint-Etienne", "FR", 45.43, 4.39), ("Hof", "DE", 50.31, 11.91)])
    a = {"guesses": [
        # right town, coordinates 45 km off: moved
        {"place": "Hohe Strasse, Köln, NRW", "iso2": "DE", "lat": 50.6, "lon": 7.3, "radius_km": 20},
        # a street point 3 km from the centre it names: kept as given
        {"place": "Saint-Étienne", "iso2": "FR", "lat": 45.45, "lon": 4.42, "radius_km": 5},
        # same name in another country, or too far: not moved
        {"place": "Cologne", "iso2": "DE", "lat": 45.6, "lon": 9.9, "radius_km": 30},
        {"place": "Hof", "iso2": "DE", "lat": 53.5, "lon": 10.0, "radius_km": 30},
        # a whole-region guess: not pinned to a town
        {"place": "Köln", "iso2": "DE", "lat": 51.5, "lon": 9.0, "radius_km": 600}]}
    analyst.snap_guesses(a, find)
    g = a["guesses"]
    assert (g[0]["lat"], g[0]["lon"]) == (50.94, 6.96)
    assert g[0]["snapped"]["to"] == "Koln" and g[0]["snapped"]["lat"] == 50.6
    assert 40 < g[0]["snapped"]["km"] < 50
    assert all("snapped" not in x for x in g[1:])
    assert (g[1]["lat"], g[3]["lat"]) == (45.45, 53.5)
    analyst.snap_guesses(a, find)  # a second pass changes nothing
    assert g[0]["snapped"]["lat"] == 50.6


def test_crops_are_sent_after_the_photo(fake_clis):
    img, lines = _sign_photo()
    res = analyst.ask_all(["claude", "chatgpt"], img, briefing="Top guesses: 1. Germany", ocr_lines=lines)
    assert all(r["ok"] for r in res), [r["error"] for r in res]
    assert (fake_clis / "claude.images").read_text() == "3"
    assert (fake_clis / "codex.images").read_text() == "3"
    prompt = (fake_clis / "claude.prompt").read_text()
    assert "Image 1 is the whole photo" in prompt and "Image 3:" in prompt
    assert "OCR read “Hauptbahnhof / 2 km”" in prompt
    assert [c["text"] for c in res[0]["crops"]] == ["Hauptbahnhof / 2 km", "K AB 123"]
    assert "jpeg" not in res[0]["crops"][0]  # the answer stays JSON-ready
    # a blind second opinion still gets the crops (they are the photo), not GeoLock's reading
    analyst.ask_all(["claude"], img, briefing=None, ocr_lines=lines)
    prompt = (fake_clis / "claude.prompt").read_text()
    assert "Image 2:" in prompt and "OCR read" not in prompt and "Notes from GeoLock" not in prompt


def test_old_answers_still_load():
    old = {"reasoning": "x", "clues": [{"clue": "Hauptbahnhof", "suggests": "Germany"}],
           "driving_side": "right", "text_seen": "",
           "guesses": [{"lat": 50, "lon": 7, "confidence": 0.5, "radius_km": 50, "iso2": "de"}]}
    d = analyst.clean(old)
    assert d["checklist"] == [] and d["clues"][0]["clue"] == "Hauptbahnhof"
    assert d["guesses"][0]["why"] == "" and d["ruled_out"] == []


def test_photo_is_resized_and_has_no_exif():
    im = Image.new("RGB", (4000, 3000))
    exif = Image.Exif()
    exif[0x8825] = {2: (48.0, 51.0, 0.0)}  # GPSInfo
    im.info["exif"] = exif.tobytes()
    data = analyst.photo_jpeg(im)
    out = Image.open(__import__("io").BytesIO(data))
    assert max(out.size) == analyst.MAX_SIDE and not out.getexif()


def _isolate_home(tmp_path, monkeypatch):
    for var in ("HOME", "USERPROFILE", "APPDATA"):
        monkeypatch.setenv(var, str(tmp_path))


def test_finds_claude_in_local_bin_when_not_on_path(tmp_path, monkeypatch):
    # Claude Code's native Windows installer puts claude.exe in ~/.local/bin and leaves
    # PATH alone, so the app must look there too (seen on the Yoga, 2026-10-15).
    _isolate_home(tmp_path, monkeypatch)
    bin_dir = tmp_path / ".local" / "bin"
    bin_dir.mkdir(parents=True)
    answer = f"ANSWER = {json.dumps(ANSWER)!r}\nANSWER = __import__('json').loads(ANSWER)\n"
    _fake(bin_dir, "claude", answer + FAKE_CLAUDE)
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    found = analyst._find_cli("claude")
    assert found and os.path.dirname(found) == str(bin_dir)
    st = analyst.detect(refresh=True)
    assert st["claude"]["available"] and st["claude"]["via"] == "claude-code"
    analyst._detect_cache["value"] = None


def test_missing_cli_reports_why(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", str(tmp_path))
    _isolate_home(tmp_path, monkeypatch)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    st = analyst.detect(refresh=True)
    assert not st["claude"]["available"] and "claude auth login" in st["claude"]["detail"]
    r = analyst.ask("chatgpt", Image.new("RGB", (10, 10)), status=st["chatgpt"])
    assert not r["ok"] and "codex" in r["error"]
    analyst._detect_cache["value"] = None


def test_clean_drops_bad_guesses_and_normalises():
    d = analyst.clean({"reasoning": "x", "guesses": [
        {"lat": 10, "lon": 10, "confidence": 0.9, "radius_km": 5, "iso2": "ng"},
        {"lat": 200, "lon": 10, "confidence": 0.5},
        {"lat": "n/a", "lon": 3},
        {"lat": -5, "lon": 20, "confidence": 0.6}]})
    assert len(d["guesses"]) == 2 and d["guesses"][0]["iso2"] == "NG"
    assert sum(g["confidence"] for g in d["guesses"]) == pytest.approx(1)


def test_clues_favour_the_analysts_places():
    geo = GeoData()
    a = dict(analyst.clean(ANSWER), ok=True, provider="claude", name="Claude")
    clues = analyst.analyst_clues(a, geo.country_codes, geo.country_name)
    point = next(c for c in clues if c.mix > 0)
    near, far = point.point_fn(np.array([50.9, 37.6]), np.array([7.0, -122.4]))
    assert near > 0.9 and far < 1e-6
    assert point.spots[0] == (50.94, 6.96, 50.0, 0.5)  # lat, lon, radius_km, prob
    # only the mixture carries weight; the rest is shown for context
    assert all(c.strength == 0 for c in clues)
    assert any(c.title == "Claude's country guesses" for c in clues)
    assert point.country_odds == {"DE": 0.7, "AT": 0.2}
    assert analyst.analyst_clues({"ok": False}, geo.country_codes) == []


@pytest.fixture(scope="module")
def tiny_engine(tmp_path_factory):
    """A Geolocator on small random models of the right shapes (no downloads needed)."""
    ov = pytest.importorskip("openvino")
    from openvino import opset13 as ops
    from geolock import prompts
    from geolock.engine import Geolocator
    from geolock.locenc import LocationEncoder, normalize
    md = tmp_path_factory.mktemp("models")
    rng = np.random.default_rng(0)
    x = ops.parameter([4, 3, 224, 224], np.float32, name="pixel_values")
    pooled = ops.reduce_mean(x, ops.constant(np.array([2, 3])), keep_dims=False)
    emb = ops.matmul(pooled, ops.constant(rng.normal(size=(3, 768)).astype(np.float32)), False, False)
    ov.save_model(ov.Model([emb], [x]), md / "clip_vision.xml")
    loc = {"LocEnc0.capsule.0.b": rng.normal(size=(64, 2)) * 0.05,
           "LocEnc0.capsule.1.weight": rng.normal(size=(64, 128)) * 0.1, "LocEnc0.capsule.1.bias": np.zeros(64),
           "LocEnc0.capsule.3.weight": rng.normal(size=(64, 64)) * 0.1, "LocEnc0.capsule.3.bias": np.zeros(64),
           "LocEnc0.capsule.5.weight": rng.normal(size=(64, 64)) * 0.1, "LocEnc0.capsule.5.bias": np.zeros(64),
           "LocEnc0.head.0.weight": rng.normal(size=(512, 64)) * 0.1, "LocEnc0.head.0.bias": np.zeros(512)}
    np.savez(md / "geoclip.npz", **{"mlp.w1": rng.normal(size=(64, 768)) * 0.05, "mlp.b1": np.zeros(64),
                                    "mlp.w2": rng.normal(size=(512, 64)) * 0.1, "mlp.b2": np.zeros(512),
                                    "logit_scale": np.float32(20.0)},
             **{f"loc.{k}": v for k, v in loc.items()})
    geo = GeoData()
    gps = np.stack([rng.uniform(-60, 70, 20000), rng.uniform(-180, 180, 20000)], 1).astype(np.float32)
    gps = gps[geo.countries.lookup(gps[:, 0], gps[:, 1]) >= 0]  # land only
    feats = normalize(LocationEncoder(loc)(gps)).astype(np.float16)
    np.savez(md / "gallery.npz", gps=gps, feats=feats,
             country=geo.countries.lookup(gps[:, 0], gps[:, 1]).astype(np.int16))
    groups = prompts.all_prompt_lists(geo.country_names)
    np.savez(md / "prompts.npz", keys=np.array(list(groups)),
             embs=normalize(rng.normal(size=(len(groups), 768))).astype(np.float32),
             clip_logit_scale=np.float32(100.0), country_codes=np.array(geo.country_codes))
    return Geolocator(md, device="CPU")


def test_analyst_answer_moves_the_fused_guess(tiny_engine, fake_clis):
    img = Image.new("RGB", (640, 480), (90, 130, 170))
    plain = tiny_engine.locate(img, use_ocr=False)
    asked = tiny_engine.locate(img, use_ocr=False, ask=["claude"])
    from geolock.geodata import haversine_km
    (a,) = asked["analysts"]
    assert a["ok"] and a["name"] == "Claude"
    top = asked["guesses"][0]
    assert top["country_code"] == "DE" and haversine_km(top["lat"], top["lon"], 50.94, 6.96) < 30
    assert "llm_ms" not in plain["timings"] and not plain["analysts"]
    # stated 50 % on Cologne, 75 % trust: about 0.375 of the mass lands there
    assert 0.3 < top["confidence"] < 0.6
    assert any(g["country_code"] == "AT" for g in asked["guesses"][:3])
    assert any("Claude places it in Cologne" in w["text"] for w in top["why"])
    brief = (fake_clis / "claude.prompt").read_text()
    assert "Top guesses" in brief and "GPS" not in brief


def test_find_town_uses_the_shipped_place_list():
    geo = GeoData()
    if geo._cities is None:
        pytest.skip("reverse_geocoder is not installed")
    vienna = geo.find_town("vienna", "AT", 48.0, 16.0)
    assert vienna and abs(vienna["lat"] - 48.21) < 0.05
    us = geo.find_town("Vienna", "US", 38.9, -77.3)  # the one in Virginia, not Austria's
    assert us and us["admin1"] == "Virginia" and us["km"] < 10
    assert geo.find_town("Saint Étienne", "FR", 45.4, 4.4)["name"].startswith("Saint")
    assert geo.find_town("Nowhere-on-Earth", "DE", 50, 7) is None


def test_country_odds_reshape_the_unpinned_probability(tiny_engine):
    eng = tiny_engine
    post = np.full(len(eng.gps), 1.0 / len(eng.gps))
    shaped = eng._odds_shape(post, {"DE": 0.6, "AT": 0.1})
    codes = eng.geo.country_codes
    de, at = codes.index("DE"), codes.index("AT")
    assert shaped.sum() == pytest.approx(1)
    assert shaped[eng.gal_country == de].sum() == pytest.approx(0.6, abs=0.01)
    assert shaped[eng.gal_country == at].sum() == pytest.approx(0.1, abs=0.01)
    assert np.allclose(eng._odds_shape(post, {}), post)
