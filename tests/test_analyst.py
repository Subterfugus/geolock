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

ANSWER = {"reasoning": "German text and a green motorway-style sign.",
          "clues": [{"clue": "Hauptbahnhof", "suggests": "Germany"}],
          "driving_side": "right", "text_seen": "Hauptbahnhof 2 km",
          "guesses": [{"place": "Cologne", "country": "Germany", "iso2": "DE", "lat": 50.94,
                       "lon": 6.96, "radius_km": 50, "confidence": 0.5},
                      {"place": "Vienna", "country": "Austria", "iso2": "AT", "lat": 48.21,
                       "lon": 16.37, "radius_km": 80, "confidence": 0.2}]}


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
msg = json.loads(sys.stdin.readline())
content = msg["message"]["content"]
assert content[0]["type"] == "image" and content[0]["source"]["media_type"] == "image/jpeg"
assert "--json-schema" in args and "--tools" in args
open(__import__("os").path.join(__import__("os").path.dirname(sys.argv[0]), "claude.prompt"), "w").write(content[1]["text"])
print(json.dumps({"type": "assistant", "message": {"model": "claude-test", "content": []}}))
print(json.dumps({"type": "result", "is_error": False, "result": "ok",
                  "structured_output": ANSWER}))
"""

FAKE_CODEX = """
import json, sys
args = sys.argv[1:]
if args[:2] == ["login", "status"]:
    print("Logged in using ChatGPT"); sys.exit(0)
assert args[0] == "exec" and "--image" in args and "--output-schema" in args
img = args[args.index("--image") + 1]
assert open(img, "rb").read(2) == b"\\xff\\xd8"
prompt = sys.stdin.read()
assert "Where on Earth" in prompt
out = args[args.index("--output-last-message") + 1]
open(out, "w").write(json.dumps(ANSWER))
"""


@pytest.fixture
def fake_clis(tmp_path, monkeypatch):
    answer = f"ANSWER = {json.dumps(ANSWER)!r}\nANSWER = __import__('json').loads(ANSWER)\n"
    _fake(tmp_path, "claude", answer + FAKE_CLAUDE)
    _fake(tmp_path, "codex", answer + FAKE_CODEX)
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
    assert "Notes from GeoLock" in (fake_clis / "claude.prompt").read_text()


def test_photo_is_resized_and_has_no_exif():
    im = Image.new("RGB", (4000, 3000))
    exif = Image.Exif()
    exif[0x8825] = {2: (48.0, 51.0, 0.0)}  # GPSInfo
    im.info["exif"] = exif.tobytes()
    data = analyst.photo_jpeg(im)
    out = Image.open(__import__("io").BytesIO(data))
    assert max(out.size) == analyst.MAX_SIDE and not out.getexif()


def test_missing_cli_reports_why(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", str(tmp_path))
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
