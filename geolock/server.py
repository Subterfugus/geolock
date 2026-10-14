"""Local web app: http://127.0.0.1:7860 (nothing leaves the machine)."""
import threading

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .config import WEB_DIR
from .geodata import DATA


def create_app(engine):
    app = FastAPI(title="GeoLock", docs_url=None, redoc_url=None)
    lock = threading.Lock()

    @app.get("/api/status")
    def status():
        return {"device": engine.device, "vlm": engine.has_vlm, "manifest": engine.manifest,
                "available_devices": engine.core.available_devices}

    @app.post("/api/locate")
    def locate(file: UploadFile = File(...), ocr: bool = Form(True), vlm: bool = Form(False),
               exif_gps: bool = Form(True)):
        data = file.file.read()
        if not data:
            raise HTTPException(400, "empty upload")
        try:
            with lock:
                return JSONResponse(engine.locate(data, use_ocr=ocr, use_vlm=vlm,
                                                  use_exif_gps=exif_gps))
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
