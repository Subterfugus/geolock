"""The desktop app's backend: the engine behind a local HTTP API (see desktop/API.md).

Started by the Tauri shell as `geolock-backend --port P --token T --data-dir D`, or for
development as `python -m geolock.desktop --port 7861 --no-token`.
"""
import secrets
import threading
import time
import traceback
from pathlib import Path

from fastapi import Body, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response

from .. import __version__
from ..geodata import DATA
from .library import Library, Settings
from .modelsetup import ModelSetup, models_ready

ORIGINS = ["http://tauri.localhost", "https://tauri.localhost", "tauri://localhost",
           "http://localhost:1420", "http://127.0.0.1:1420"]


class Backend:
    """Owns the engine, its loading state, the library and the settings."""

    def __init__(self, data_dir, engine_factory=None):
        self.data_dir = Path(data_dir)
        self.models_dir = self.data_dir / "models"
        self.models_dir.mkdir(parents=True, exist_ok=True)
        self.settings = Settings(self.data_dir / "settings.json")
        self.library = Library(self.data_dir / "history")
        self.setup = ModelSetup(self.models_dir, on_ready=self.load_engine)
        self.engine_factory = engine_factory or self._default_factory
        self.engine = None
        self.state = "needs_setup"
        self.error = None
        self.lock = threading.Lock()        # one analysis at a time
        self.load_lock = threading.Lock()

    def _default_factory(self, device):
        from ..engine import Geolocator
        return Geolocator(self.models_dir, device=device)

    def start(self):
        if models_ready(self.models_dir):
            threading.Thread(target=self._load_safely, daemon=True, name="engine-load").start()
        _analysts_now()  # check the Claude / ChatGPT logins early

    def _load_safely(self):
        try:
            self.load_engine()
        except Exception:
            pass  # state and error are set by load_engine

    def load_engine(self):
        """Load (or reload) the engine on the configured device. Raises on failure."""
        with self.load_lock:
            self.state = "loading"
            self.error = None
            try:
                eng = self.engine_factory(self.settings["device"])
                eng.warmup()
                with self.lock:
                    self.engine = eng
                self.state = "ready"
            except Exception as e:
                self.engine = None
                self.state = "error"
                self.error = f"Could not load the models: {type(e).__name__}: {e}"
                traceback.print_exc()
                raise

    def current_state(self):
        if self.setup.running and self.state != "loading":
            return "setting_up"
        return self.state

    def status(self):
        eng = self.engine
        devices, name = [], None
        if eng is not None:
            devices = list(eng.core.available_devices)
            try:
                name = str(eng.core.get_property(eng.device, "FULL_DEVICE_NAME"))
            except Exception:
                name = None
        else:
            devices = _devices()
        return {"state": self.current_state(), "error": self.error, "version": __version__,
                "device": eng.device if eng else None, "device_name": name,
                "available_devices": devices, "analysts": _analysts_now(),
                "data_dir": str(self.data_dir), "models_dir": str(self.models_dir)}

    # --------------------------------------------------------------- analysis
    def analyse(self, rid, name, created, photo, ocr, exif_gps, ask, share_local, prior=()):
        eng = self.engine
        if eng is None:
            raise HTTPException(409, "The models are not loaded yet.")
        with self.lock:
            result = eng.locate(photo, use_ocr=ocr, use_exif_gps=exif_gps, ask=ask,
                                share_local=share_local, prior_analysts=prior)
        result.update(id=rid, name=name, created=created,
                      image_url=f"/api/history/{rid}/image", thumb_url=f"/api/history/{rid}/thumb",
                      options={"ocr": ocr, "exif_gps": exif_gps, "ask": list(ask),
                               "share_local": share_local})
        self.library.save(result, keep=self.settings["keep_history"])
        return result


_dev_cache = {}
_checker = threading.Event()  # set while a login check runs
_CHECKING = {"available": False, "via": None, "detail": "Checking…", "checking": True}


def _analysts_now():
    """The last login check, without waiting for a new one (that can take seconds)."""
    from .. import analyst
    cached = analyst._detect_cache["value"]
    stale = cached is None or time.time() - analyst._detect_cache["t"] > 300
    if stale and not _checker.is_set():
        _checker.set()

        def run():
            try:
                analyst.detect()
            finally:
                _checker.clear()
        threading.Thread(target=run, daemon=True).start()
    return cached or {"claude": dict(_CHECKING), "chatgpt": dict(_CHECKING)}


def _devices():
    if "v" not in _dev_cache:
        try:
            import openvino as ov
            _dev_cache["v"] = list(ov.Core().available_devices)
        except Exception:
            _dev_cache["v"] = ["CPU"]
    return _dev_cache["v"]


def _asks(s):
    return [x for x in dict.fromkeys((s or "").split(",")) if x in ("claude", "chatgpt")]


def create_app(backend, token=None):
    app = FastAPI(title="GeoLock desktop backend", docs_url=None, redoc_url=None, openapi_url=None)

    @app.middleware("http")
    async def check_token(request: Request, call_next):
        if token and request.url.path.startswith("/api/") and request.method != "OPTIONS":
            given = request.headers.get("x-geolock-token") or request.query_params.get("t") or ""
            if not secrets.compare_digest(given, token):
                return JSONResponse({"detail": "Not allowed."}, status_code=401)
        return await call_next(request)

    app.add_middleware(CORSMiddleware, allow_origins=ORIGINS, allow_methods=["*"],
                       allow_headers=["*"], allow_origin_regex=None if token else ".*")

    @app.get("/api/status")
    def status():
        return backend.status()

    # ------------------------------------------------------------------ setup
    @app.get("/api/setup")
    def setup_report():
        return backend.setup.report()

    @app.post("/api/setup/start")
    def setup_start():
        backend.setup.start()
        return backend.setup.report()

    @app.post("/api/setup/cancel")
    def setup_cancel():
        backend.setup.cancel()
        return backend.setup.report()

    @app.post("/api/setup/import")
    def setup_import(body: dict = Body(...)):
        try:
            backend.setup.import_folder(str(body.get("folder", "")).strip().strip('"'))
        except ValueError as e:
            raise HTTPException(400, str(e))
        return backend.setup.report()

    # ----------------------------------------------------------------- locate
    @app.post("/api/locate")
    def locate(file: UploadFile = File(...), name: str = Form(""), ocr: bool = Form(True),
               exif_gps: bool = Form(True), ask: str = Form(""), share_local: bool = Form(True)):
        data = file.file.read()
        if not data:
            raise HTTPException(400, "The file is empty.")
        rid = backend.library.new_id()
        try:
            photo = backend.library.add_photo(rid, data, keep=backend.settings["keep_history"])
        except Exception:
            raise HTTPException(415, "This file is not an image GeoLock can read.")
        created = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        try:
            return backend.analyse(rid, name or file.filename or "Photo", created, photo, ocr,
                                   exif_gps, _asks(ask), share_local)
        except HTTPException:
            backend.library.delete(rid)
            raise
        except Exception as e:
            backend.library.delete(rid)
            traceback.print_exc()
            raise HTTPException(422, f"{type(e).__name__}: {e}")

    # ---------------------------------------------------------------- history
    @app.get("/api/history")
    def history():
        return backend.library.list()

    @app.get("/api/history/{rid}")
    def history_item(rid: str):
        try:
            return backend.library.get(rid)
        except KeyError:
            raise HTTPException(404, "Not in the library.")

    @app.delete("/api/history/{rid}")
    def history_delete(rid: str):
        try:
            backend.library.delete(rid)
        except KeyError:
            raise HTTPException(404, "Not in the library.")
        return {"ok": True}

    @app.delete("/api/history")
    def history_clear():
        return {"ok": True, "deleted": backend.library.clear()}

    @app.post("/api/history/{rid}/rerun")
    def history_rerun(rid: str, ocr: bool = Form(True), exif_gps: bool = Form(True),
                      ask: str = Form(""), share_local: bool = Form(True)):
        try:
            old = backend.library.get(rid)
            photo = backend.library.file(rid, "photo")
        except KeyError:
            raise HTTPException(404, "Not in the library.")
        prior = [a for a in old.get("analysts", []) if a.get("ok")]
        try:
            return backend.analyse(rid, old.get("name"), old.get("created"), photo, ocr, exif_gps,
                                   _asks(ask), share_local, prior)
        except HTTPException:
            raise
        except Exception as e:
            traceback.print_exc()
            raise HTTPException(422, f"{type(e).__name__}: {e}")

    def _jpeg(rid, kind):
        try:
            data = backend.library.file(rid, kind)
        except KeyError:
            raise HTTPException(404, "Not in the library.")
        return Response(data, media_type="image/jpeg",
                        headers={"Cache-Control": "private, max-age=31536000, immutable"})

    @app.get("/api/history/{rid}/image")
    def history_image(rid: str):
        return _jpeg(rid, "photo")

    @app.get("/api/history/{rid}/thumb")
    def history_thumb(rid: str):
        return _jpeg(rid, "thumb")

    # --------------------------------------------------------------- settings
    @app.get("/api/settings")
    def settings_get():
        return dict(backend.settings.values)

    @app.put("/api/settings")
    def settings_put(body: dict = Body(...)):
        before = backend.settings["device"]
        try:
            values = backend.settings.update(body)
        except ValueError as e:
            raise HTTPException(400, str(e))
        if values["device"] != before and models_ready(backend.models_dir):
            threading.Thread(target=backend._load_safely, daemon=True, name="engine-reload").start()
        return values

    @app.post("/api/analysts/refresh")
    def analysts_refresh():
        from ..analyst import detect
        return detect(refresh=True)

    # ------------------------------------------------------------------- data
    @app.get("/data/{name}")
    def geodata(name: str):
        if name not in ("countries.geojson", "admin1.geojson"):
            raise HTTPException(404)
        return FileResponse(DATA / name, media_type="application/geo+json",
                            headers={"Cache-Control": "public, max-age=86400"})

    return app
