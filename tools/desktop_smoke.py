"""Smoke test of the frozen desktop backend (CI): start geolock-backend, run the real
first-run setup (downloads the CLIP model from Hugging Face), locate a photo, check the
library, then make sure the backend exits when its stdin closes (as when the app quits).

    python tools/desktop_smoke.py desktop/backend-dist/geolock-backend/geolock-backend.exe
"""
import io
import os
import json
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
import uuid
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

TOKEN = uuid.uuid4().hex


def call(port, path, method="GET", data=None, ctype=None, timeout=600):
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=data, method=method,
                                 headers={"X-GeoLock-Token": TOKEN, **({"Content-Type": ctype} if ctype else {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        body = r.read()
        return json.loads(body) if r.headers.get_content_type() == "application/json" else body


def photo():
    im = Image.new("RGB", (1024, 768), (110, 150, 200))
    d = ImageDraw.Draw(im)
    d.rectangle([0, 450, 1024, 768], fill=(90, 90, 85))
    d.rectangle([300, 200, 700, 300], fill=(250, 250, 250))
    d.text((320, 225), "BOULANGERIE", fill=(10, 10, 10), font=ImageFont.load_default(size=56))
    buf = io.BytesIO()
    im.save(buf, "JPEG")
    return buf.getvalue()


def multipart(fields, file_name, file_bytes):
    b = uuid.uuid4().hex
    out = io.BytesIO()
    for k, v in fields.items():
        out.write(f'--{b}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
    out.write(f'--{b}\r\nContent-Disposition: form-data; name="file"; filename="{file_name}"\r\n'
              f"Content-Type: image/jpeg\r\n\r\n".encode() + file_bytes + b"\r\n")
    out.write(f"--{b}--\r\n".encode())
    return out.getvalue(), f"multipart/form-data; boundary={b}"


def main():
    exe = Path(sys.argv[1]).resolve()
    data_dir = Path(tempfile.mkdtemp(prefix="geolock-smoke-"))
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    log = open(data_dir / "backend.log", "w")
    env = dict(os.environ, GEOLOCK_TRACE="45")
    proc = subprocess.Popen([str(exe), "--port", str(port), "--token", TOKEN, "--data-dir", str(data_dir)],
                            stdin=subprocess.PIPE, stdout=log, stderr=subprocess.STDOUT, env=env)
    ok = False
    try:
        t0 = time.time()
        while True:
            try:
                st = call(port, "/api/status", timeout=5)
                break
            except Exception:
                if proc.poll() is not None or time.time() - t0 > 300:
                    raise SystemExit("backend did not start")
                time.sleep(0.5)
        print(f"started in {time.time() - t0:.1f}s: state={st['state']} devices={st['available_devices']}", flush=True)
        assert st["state"] == "needs_setup", st
        rep = call(port, "/api/setup")
        print(f"setup: {rep['download_mb']} MB from {rep['source']}", flush=True)
        call(port, "/api/setup/start", "POST", b"")
        t0, last = time.time(), ""
        while True:
            st = call(port, "/api/status", timeout=10)
            rep = call(port, "/api/setup", timeout=10)
            msg = (rep.get("progress") or {}).get("message") or st["state"]
            if msg != last and (time.time() % 10 < 1 or "Download" not in msg):
                print(f"  {time.time() - t0:5.0f}s {msg}", flush=True)
                last = msg
            if st["state"] == "ready":
                break
            if rep.get("error") or st["state"] == "error":
                raise SystemExit(f"setup failed: {rep.get('error') or st.get('error')}")
            if time.time() - t0 > 1500:
                raise SystemExit("setup timed out")
            time.sleep(1)
        print(f"ready on {st['device']} after {time.time() - t0:.0f}s", flush=True)
        body, ctype = multipart({"name": "smoke.jpg", "ocr": "true"}, "smoke.jpg", photo())
        t = time.time()
        res = call(port, "/api/locate", "POST", body, ctype)
        g = res["guesses"][0]
        print(f"locate: {time.time() - t:.1f}s, top guess {g['country']} {g['confidence']:.0%}, "
              f"{len(res['clues'])} clues, OCR lines {len(res['ocr'])}, timings {res['timings']}", flush=True)
        assert res["guesses"] and res["heat"] and res["countries"]
        assert any(c["kind"] == "ocr" for c in res["clues"]), "OCR did not read the sign"
        assert call(port, "/api/history")[0]["id"] == res["id"]
        assert call(port, res["thumb_url"])[:2] == b"\xff\xd8"
        ok = True
    finally:
        proc.stdin.close()  # what happens when the app quits or crashes
        try:
            proc.wait(20)
            print(f"backend exited on stdin EOF (code {proc.returncode})")
        except subprocess.TimeoutExpired:
            proc.kill()
            print("backend did NOT exit on stdin EOF")
            ok = False
        log.close()
        print((data_dir / "backend.log").read_text(errors="replace")[-4000:])
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
