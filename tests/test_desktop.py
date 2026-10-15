"""Desktop backend: first-run setup (download, convert, gallery), library, settings, token.

Uses tiny random models of the right shapes and a local HTTP server in place of Hugging
Face, so nothing is downloaded and no Claude / ChatGPT plan is used (fake CLIs).
"""
import functools
import hashlib
import http.server
import io
import json
import threading
import time

import numpy as np
import pytest
from PIL import Image

pytest.importorskip("openvino")
onnx = pytest.importorskip("onnx")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402

from geolock import prompts  # noqa: E402
from geolock.geodata import GeoData  # noqa: E402
from test_analyst import fake_clis  # noqa: E402,F401  (fixture)

TOKEN = "t" * 32


def tiny_onnx(path, fp16_io=False):
    """A CLIPVisionModelWithProjection-shaped ONNX model: pixel_values -> image_embeds
    (plus last_hidden_state, which the converter must drop), dynamic batch."""
    from onnx import TensorProto, helper, numpy_helper
    rng = np.random.default_rng(1)
    dt = TensorProto.FLOAT16 if fp16_io else TensorProto.FLOAT
    w = rng.normal(size=(3, 768)).astype(np.float16 if fp16_io else np.float32)
    nodes = [helper.make_node("ReduceMean", ["pixel_values", "axes"], ["pooled"], keepdims=0),
             helper.make_node("MatMul", ["pooled", "W"], ["image_embeds"]),
             helper.make_node("Identity", ["pixel_values"], ["last_hidden_state"])]
    g = helper.make_graph(
        nodes, "clip_vision",
        [helper.make_tensor_value_info("pixel_values", dt, ["batch", 3, "h", "w"])],
        [helper.make_tensor_value_info("image_embeds", dt, ["batch", 768]),
         helper.make_tensor_value_info("last_hidden_state", dt, ["batch", 3, "h", "w"])],
        [numpy_helper.from_array(w, "W"), numpy_helper.from_array(np.array([2, 3], dtype=np.int64), "axes")])
    m = helper.make_model(g, opset_imports=[helper.make_opsetid("", 18)])
    m.ir_version = 9
    onnx.save(m, path)


def make_bundle(root, onnx_url, onnx_path):
    from geolock.locenc import normalize
    rng = np.random.default_rng(0)
    root.mkdir(parents=True, exist_ok=True)
    loc = {"LocEnc0.capsule.0.b": rng.normal(size=(64, 2)) * 0.05,
           "LocEnc0.capsule.1.weight": rng.normal(size=(64, 128)) * 0.1, "LocEnc0.capsule.1.bias": np.zeros(64),
           "LocEnc0.capsule.3.weight": rng.normal(size=(64, 64)) * 0.1, "LocEnc0.capsule.3.bias": np.zeros(64),
           "LocEnc0.capsule.5.weight": rng.normal(size=(64, 64)) * 0.1, "LocEnc0.capsule.5.bias": np.zeros(64),
           "LocEnc0.head.0.weight": rng.normal(size=(512, 64)) * 0.1, "LocEnc0.head.0.bias": np.zeros(512)}
    np.savez(root / "geoclip.npz", **{"mlp.w1": rng.normal(size=(64, 768)) * 0.05, "mlp.b1": np.zeros(64),
                                      "mlp.w2": rng.normal(size=(512, 64)) * 0.1, "mlp.b2": np.zeros(512),
                                      "logit_scale": np.float32(20.0)},
             **{f"loc.{k}": v for k, v in loc.items()})
    geo = GeoData()
    gps = np.stack([rng.uniform(-60, 70, 12000), rng.uniform(-180, 180, 12000)], 1).astype(np.float32)
    np.save(root / "gallery_gps.npy", gps[geo.countries.lookup(gps[:, 0], gps[:, 1]) >= 0])
    groups = prompts.all_prompt_lists(geo.country_names)
    np.savez(root / "prompts.npz", keys=np.array(list(groups)),
             embs=normalize(rng.normal(size=(len(groups), 768))).astype(np.float32),
             clip_logit_scale=np.float32(100.0), country_codes=np.array(geo.country_codes))
    (root / "calibration.json").write_text(json.dumps({"temperature": 1.5, "country_weight": 0.5}))
    data = onnx_path.read_bytes()
    (root / "assets.json").write_text(json.dumps({"clip_vision_onnx": {
        "url": onnx_url, "size": len(data), "sha256": hashlib.sha256(data).hexdigest(),
        "source": "test server"}}))


@pytest.fixture
def served(tmp_path):
    """A local HTTP server with the tiny ONNX model, supporting Range like Hugging Face."""
    site = tmp_path / "site"
    site.mkdir()
    tiny_onnx(site / "vision.onnx")

    class Handler(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            data = (site / "vision.onnx").read_bytes()
            rng = self.headers.get("Range")
            start = int(rng.split("=")[1].split("-")[0]) if rng else 0
            self.send_response(206 if rng else 200)
            self.send_header("Content-Length", str(len(data) - start))
            self.end_headers()
            self.wfile.write(data[start:])
            Handler.hits.append(start)

    Handler.hits = []
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Handler, directory=str(site)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}/vision.onnx", site / "vision.onnx", Handler.hits
    srv.shutdown()


@pytest.fixture
def backend(tmp_path, served, monkeypatch):
    from geolock.desktop.server import Backend, create_app
    from geolock.engine import Geolocator
    url, path, hits = served
    make_bundle(tmp_path / "bundled", url, path)
    monkeypatch.setenv("GEOLOCK_BUNDLED", str(tmp_path / "bundled"))

    def factory(device):
        eng = Geolocator(tmp_path / "data" / "models", device="CPU")
        eng.reader.__dict__["ocr"] = None  # no OCR models in the test environment
        return eng

    b = Backend(tmp_path / "data", engine_factory=factory)
    b.start()
    client = TestClient(create_app(b, token=TOKEN), headers={"X-GeoLock-Token": TOKEN})
    client.hits = hits
    return b, client


def wait(cond, timeout=120):
    t = time.time()
    while time.time() - t < timeout:
        if cond():
            return
        time.sleep(0.1)
    raise TimeoutError


def jpeg_with_gps(lat=48.8566, lon=2.3522):
    im = Image.new("RGB", (800, 600), (120, 140, 160))
    ex = Image.Exif()
    ex[0x010F] = "TestCam"

    def dms(v):
        v = abs(v)
        d = int(v)
        m = int((v - d) * 60)
        return (d, m, round(((v - d) * 60 - m) * 60, 2))
    ex[0x8825] = {1: "N" if lat >= 0 else "S", 2: dms(lat), 3: "E" if lon >= 0 else "W", 4: dms(lon)}
    buf = io.BytesIO()
    im.save(buf, "JPEG", exif=ex)
    return buf.getvalue()


def test_token_is_required(backend):
    b, client = backend
    from geolock.desktop.server import create_app
    bare = TestClient(create_app(b, token=TOKEN))
    assert bare.get("/api/status").status_code == 401
    assert bare.get("/api/status?t=" + TOKEN).status_code == 200
    assert bare.get("/data/countries.geojson").status_code == 200  # public data
    pre = bare.options("/api/status", headers={"Origin": "http://tauri.localhost",
                                               "Access-Control-Request-Method": "GET",
                                               "Access-Control-Request-Headers": "x-geolock-token"})
    assert pre.status_code == 200 and pre.headers["access-control-allow-origin"] == "http://tauri.localhost"
    evil = bare.get("/api/status?t=" + TOKEN, headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in evil.headers


def test_first_run_setup_then_locate_and_library(backend, fake_clis):
    b, client = backend
    s = client.get("/api/status").json()
    assert s["state"] == "needs_setup"
    rep = client.get("/api/setup").json()
    assert not rep["ready"] and rep["download_mb"] is not None and rep["free_disk_mb"] > 0
    client.post("/api/setup/start")
    wait(lambda: client.get("/api/status").json()["state"] == "ready")
    rep = client.get("/api/setup").json()
    assert rep["ready"] and all(st["state"] == "done" for st in rep["steps"]) and rep["error"] is None
    md = b.models_dir
    assert (md / "clip_vision.xml").exists() and (md / "gallery.npz").exists()
    assert not (md / ".download" / "clip_vision.onnx").exists()  # ONNX deleted after conversion
    assert b.engine.temperature == 1.5  # bundled calibration copied

    r = client.post("/api/locate", files={"file": ("paris.jpg", jpeg_with_gps(), "image/jpeg")},
                    data={"ocr": "true", "exif_gps": "true"})
    assert r.status_code == 200, r.text
    res = r.json()
    assert res["name"] == "paris.jpg" and res["guesses"] and res["exif_gps"]["lat"] == pytest.approx(48.8566, abs=1e-3)
    assert res["analysts"] == [] and res["options"]["ask"] == []
    rid = res["id"]
    lst = client.get("/api/history").json()
    assert [x["id"] for x in lst] == [rid] and lst[0]["has_exif_gps"] and lst[0]["top"]["country"]
    img = client.get(res["image_url"])
    assert img.status_code == 200 and img.headers["content-type"] == "image/jpeg"
    assert Image.open(io.BytesIO(img.content)).getexif().get_ifd(0x8825)  # GPS kept in the copy
    assert client.get(res["thumb_url"]).status_code == 200

    # second opinion on an existing photo, then a plain re-run keeps that answer
    r2 = client.post(f"/api/history/{rid}/rerun", data={"ask": "claude"}).json()
    assert [a["provider"] for a in r2["analysts"]] == ["claude"] and r2["analysts"][0]["ok"]
    assert r2["exif_gps"] is not None  # EXIF survived the stored copy
    (fake_clis / "claude.prompt").unlink()
    r3 = client.post(f"/api/history/{rid}/rerun", data={"ocr": "false"}).json()
    assert [a["provider"] for a in r3["analysts"]] == ["claude"]
    assert not (fake_clis / "claude.prompt").exists()  # Claude was not asked again
    assert client.get("/api/history").json()[0]["analysts"] == ["claude"]

    assert client.delete(f"/api/history/{rid}").json()["ok"]
    assert client.get("/api/history").json() == []
    assert client.get(f"/api/history/{rid}").status_code == 404
    assert client.get("/api/history/..%2F..%2Fsettings").status_code == 404


def test_settings_and_session_only_history(backend):
    b, client = backend
    s = client.get("/api/settings").json()
    assert s["device"] == "AUTO" and s["keep_history"] is True
    assert client.put("/api/settings", json={"device": "potato"}).status_code == 400
    s = client.put("/api/settings", json={"theme": "Dark", "keep_history": False, "nope": 1}).json()
    assert s["theme"] == "dark" and s["keep_history"] is False and "nope" not in s
    assert json.loads((b.data_dir / "settings.json").read_text())["theme"] == "dark"
    client.post("/api/setup/start")
    wait(lambda: b.state == "ready")
    res = client.post("/api/locate", files={"file": ("a.png", jpeg_with_gps(), "image/png")}).json()
    assert client.get("/api/history").json()[0]["id"] == res["id"]
    assert not any((b.data_dir / "history").iterdir())  # nothing written to disk
    assert client.post("/api/locate", files={"file": ("x.jpg", b"not an image", "image/jpeg")}).status_code == 415


def test_download_resumes(backend, served):
    b, client = backend
    _, path, hits = served
    part = b.models_dir / ".download" / "clip_vision.onnx.part"
    part.parent.mkdir(parents=True)
    part.write_bytes(path.read_bytes()[:1000])
    client.post("/api/setup/start")
    wait(lambda: b.state == "ready")
    assert hits == [1000]


def test_bad_download_is_rejected(backend):
    b, client = backend
    info = b.setup.assets["clip_vision_onnx"]
    info["sha256"] = "0" * 64
    client.post("/api/setup/start")
    wait(lambda: not b.setup.running)
    rep = client.get("/api/setup").json()
    assert "checksum" in rep["error"] and rep["steps"][0]["state"] == "error"
    assert client.get("/api/status").json()["state"] == "needs_setup"


def test_import_existing_models_folder(backend, tmp_path):
    b, client = backend
    assert client.post("/api/setup/import", json={"folder": str(tmp_path)}).status_code == 400
    # an older install: models/ with clip_vision + geoclip, no gallery
    old = tmp_path / "old-install" / "models"
    old.mkdir(parents=True)
    from geolock.desktop.modelsetup import convert_onnx
    tiny_onnx(tmp_path / "v.onnx", fp16_io=True)  # also checks FP16 inputs/outputs become FP32
    convert_onnx(tmp_path / "v.onnx", old)
    import shutil
    shutil.copy(tmp_path / "bundled" / "geoclip.npz", old / "geoclip.npz")
    r = client.post("/api/setup/import", json={"folder": str(old.parent)})
    assert r.status_code == 200, r.text
    wait(lambda: b.state == "ready")
    assert client.hits == []  # nothing downloaded
    assert b.engine.vision.inputs[0].get_element_type().get_type_name() == "f32"
