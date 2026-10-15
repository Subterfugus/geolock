"""Desktop update check and download, against a local server instead of GitHub."""
import functools
import hashlib
import http.server
import json
import re
import threading
import time

import pytest

from geolock.desktop import updater as up


@pytest.fixture
def feed(tmp_path, monkeypatch):
    """A local 'GitHub': /latest.json and the installer (with Range support)."""
    site = tmp_path / "site"
    site.mkdir()
    data = bytes(range(256)) * 4000  # ~1 MB installer
    name = "GeoLock_9.9.0_x64-setup.exe"
    (site / name).write_bytes(data)

    class Handler(http.server.SimpleHTTPRequestHandler):
        hits = []
        manifest = None

        def log_message(self, *a):
            pass

        def do_GET(self):
            if self.path == "/latest.json":
                body = json.dumps(Handler.manifest).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            rng = self.headers.get("Range")
            start = int(rng.split("=")[1].split("-")[0]) if rng else 0
            Handler.hits.append(start)
            self.send_response(206 if rng else 200)
            self.send_header("Content-Length", str(len(data) - start))
            self.end_headers()
            self.wfile.write(data[start:])

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Handler, directory=str(site)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    monkeypatch.setattr(up, "_ALLOWED_URL", re.compile(r"^http://127\.0\.0\.1:\d+/"))
    Handler.manifest = {"version": "9.9.0", "published_at": "2026-10-15T12:00:00Z", "notes": "New things",
                        "installer": {"name": name, "url": f"{base}/{name}", "size": len(data),
                                      "sha256": hashlib.sha256(data).hexdigest()}}
    yield f"{base}/latest.json", Handler, data
    srv.shutdown()


def wait(cond, timeout=30):
    t = time.time()
    while time.time() - t < timeout:
        if cond():
            return
        time.sleep(0.05)
    raise AssertionError("timed out")


def test_versions():
    assert up.newer("0.10.0", "0.9.9") and up.newer("1.0", "0.99.1") and up.newer("v0.4.2", "0.4.1")
    assert not up.newer("0.4.1", "0.4.1") and not up.newer("0.4.0", "0.4.1") and not up.newer("0.4", "0.4.0")


def test_manifest_must_point_at_github():
    good = {"version": "1.0.0", "installer": {
        "name": "GeoLock_1.0.0_x64-setup.exe", "size": 10, "sha256": "a" * 64,
        "url": "https://github.com/Subterfugus/geolock/releases/download/v1.0.0/GeoLock_1.0.0_x64-setup.exe"}}
    assert up.validate_manifest(good)["version"] == "1.0.0"
    for bad in ({"url": "https://evil.example/GeoLock_1.0.0_x64-setup.exe"}, {"name": "..\\GeoLock.exe"},
                {"name": "GeoLock_1.0.0_x64-setup.bat"}, {"sha256": "abc"}, {"size": 0}):
        with pytest.raises(ValueError):
            up.validate_manifest(dict(good, installer=dict(good["installer"], **bad)))


def test_check_download_and_reuse(tmp_path, feed):
    url, handler, data = feed
    u = up.Updater(tmp_path, feed_url=url, current="0.4.1")
    rep = u.check()
    assert rep["state"] == "available" and rep["latest"] == "9.9.0" and rep["notes"] == "New things"
    assert rep["size_mb"] == 1 and rep["installer_path"] is None
    assert not handler.hits  # checking downloads nothing but the manifest
    u.start_download()
    wait(lambda: u.state == "ready")
    rep = u.report()
    assert rep["installer_path"].endswith("GeoLock_9.9.0_x64-setup.exe")
    assert (tmp_path / "updates" / "GeoLock_9.9.0_x64-setup.exe").read_bytes() == data
    # Next launch: the finished download is found again, nothing is fetched twice.
    u2 = up.Updater(tmp_path, feed_url=url, current="0.4.1")
    assert u2.check()["state"] == "ready" and handler.hits == [0]


def test_up_to_date_and_old_installers_removed(tmp_path, feed):
    url, _, _ = feed
    d = tmp_path / "updates"
    d.mkdir()
    (d / "GeoLock_9.9.0_x64-setup.exe").write_bytes(b"x")
    (d / "GeoLock_9.8.0_x64-setup.exe.part").write_bytes(b"x")
    u = up.Updater(tmp_path, feed_url=url, current="9.9.0")  # this is the update, installed
    assert not any(d.iterdir())
    assert u.check()["state"] == "up_to_date"


def test_resume_and_bad_checksum(tmp_path, feed):
    url, handler, data = feed
    u = up.Updater(tmp_path, feed_url=url, current="0.4.1")
    u.check()
    part = tmp_path / "updates" / "GeoLock_9.9.0_x64-setup.exe.part"
    part.parent.mkdir(exist_ok=True)
    part.write_bytes(data[:5000])
    u.start_download()
    wait(lambda: u.state == "ready")
    assert handler.hits == [5000]

    handler.manifest["version"] = "9.9.1"
    handler.manifest["installer"]["name"] = "GeoLock_9.9.1_x64-setup.exe"
    handler.manifest["installer"]["sha256"] = "0" * 64
    u = up.Updater(tmp_path, feed_url=url, current="0.4.1")
    u.check()
    u.start_download()
    wait(lambda: u.state != "downloading")
    rep = u.report()
    assert rep["state"] == "available" and "checksum" in rep["error"]
    assert not (tmp_path / "updates" / "GeoLock_9.9.1_x64-setup.exe").exists()


def test_unreachable_feed_is_a_friendly_error(tmp_path):
    u = up.Updater(tmp_path, feed_url="http://127.0.0.1:9/latest.json", current="0.4.1")
    rep = u.check()
    assert rep["state"] == "error" and "GitHub" in rep["error"] and rep["releases_url"].startswith("https://github.com/")


def test_api_endpoints(tmp_path, feed):
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient
    from geolock.desktop.server import Backend, create_app
    url, _, _ = feed
    b = Backend(tmp_path / "data")
    b.updater = up.Updater(tmp_path / "data", feed_url=url, current="0.4.1")
    c = TestClient(create_app(b, token="t" * 32), headers={"X-GeoLock-Token": "t" * 32})
    assert c.get("/api/update").json()["state"] == "idle"
    assert c.post("/api/update/check").json()["state"] == "available"
    c.post("/api/update/download")
    wait(lambda: c.get("/api/update").json()["state"] == "ready")
    assert c.get("/api/settings").json()["check_updates"] is True
