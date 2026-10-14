"""Local web app: http://127.0.0.1:7860 (nothing leaves the machine)."""
import base64
import io
import threading

from PIL import Image, ImageOps

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .config import WEB_DIR
from .geodata import DATA


BROWSER_FORMATS = {"JPEG", "PNG", "WEBP", "GIF", "BMP"}


def _preview(data):
    """A JPEG preview for formats browsers can't show (HEIC from iPhones, TIFF)."""
    try:
        im = Image.open(io.BytesIO(data))
        if im.format in BROWSER_FORMATS:
            return None
        im = ImageOps.exif_transpose(im).convert("RGB")
        im.thumbnail((1280, 1280))
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=85)
        return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()
    except Exception:
        return None


def create_app(engine):
    app = FastAPI(title="GeoLock", docs_url=None, redoc_url=None)
    lock = threading.Lock()
    from .analyst import detect
    threading.Thread(target=detect, daemon=True).start()  # check the Claude / ChatGPT logins early

    @app.get("/api/status")
    def status():
        from .analyst import detect
        return {"device": engine.device, "vlm": engine.has_vlm, "manifest": engine.manifest,
                "available_devices": engine.core.available_devices, "analysts": detect()}

    @app.post("/api/locate")
    def locate(file: UploadFile = File(...), ocr: bool = Form(True), vlm: bool = Form(False),
               exif_gps: bool = Form(True), ask: str = Form(""), share_local: bool = Form(True)):
        data = file.file.read()
        if not data:
            raise HTTPException(400, "empty upload")
        try:
            with lock:
                result = engine.locate(data, use_ocr=ocr, use_vlm=vlm, use_exif_gps=exif_gps,
                                       ask=[x for x in ask.split(",") if x], share_local=share_local)
            result["preview"] = _preview(data)
            return JSONResponse(result)
        except Exception as e:  # surface model errors in the UI instead of a bare 500
            raise HTTPException(422, f"{type(e).__name__}: {e}")

    @app.get("/data/{name}")
    def geodata(name: str):
        if name not in ("countries.geojson", "admin1.geojson"):
            raise HTTPException(404)
        return FileResponse(DATA / name, media_type="application/geo+json")

    @app.get("/")
    def index():
        return FileResponse(WEB_DIR / "index.html")

    app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")
    return app
