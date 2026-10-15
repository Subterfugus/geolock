"""Entry point of the desktop backend: python -m geolock.desktop (frozen: geolock-backend.exe)."""
import argparse
import os
import sys
import threading
import time
from pathlib import Path

# Single-threaded BLAS, set before numpy loads. GeoLock's matrix work is small, and
# OpenBLAS's thread pool hung here twice: at DLL load on Windows (frozen) and inside a
# matmul in the model-setup thread on Linux, after OpenVINO had run in the same process.
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")


def default_data_dir():
    base = os.environ.get("LOCALAPPDATA") or os.path.join(Path.home(), ".local", "share")
    return Path(base) / "com.geolock.desktop"


def _exit_when_parent_goes():
    """The shell keeps our stdin open; EOF means it has exited (or crashed)."""
    try:
        while sys.stdin.buffer.read(1024):
            pass
    except Exception:
        pass
    os._exit(0)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="geolock-backend", description=__doc__)
    ap.add_argument("--port", type=int, default=7861)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--token", default=None, help="required in the X-GeoLock-Token header")
    ap.add_argument("--no-token", action="store_true", help="development: no token, any origin")
    ap.add_argument("--data-dir", type=Path, default=None)
    ap.add_argument("--no-stdin-watch", action="store_true",
                    help="keep running when stdin closes (default when there is no token)")
    a = ap.parse_args(argv)
    t0 = time.perf_counter()
    if os.environ.get("GEOLOCK_TRACE"):  # CI: show where a slow or stuck start is
        import faulthandler
        faulthandler.dump_traceback_later(float(os.environ["GEOLOCK_TRACE"]), repeat=True)
    if not a.token and not a.no_token:
        ap.error("pass --token (the desktop shell does) or --no-token for development")

    if sys.stdout is None:  # frozen without a console: keep print() and tracebacks working
        sys.stdout = open(os.devnull, "w")
    if sys.stderr is None:
        sys.stderr = sys.stdout
    data_dir = a.data_dir or default_data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("GEOLOCK_MODELS", str(data_dir / "models"))

    print(f"GeoLock backend {a.port}: starting", flush=True)
    # Load the native libraries here, on the main thread, before any worker thread exists.
    # Frozen on Windows, scipy's OpenBLAS DLL first loaded from the model-loading thread
    # (after OpenVINO had started its thread pool) deadlocked in the loader (CI, 2026-10-15).
    import numpy  # noqa: F401
    import scipy.spatial  # noqa: F401
    import shapely  # noqa: F401
    import openvino  # noqa: F401
    import uvicorn
    from .server import Backend, create_app
    print(f"  imports done in {time.perf_counter() - t0:.1f}s", flush=True)
    backend = Backend(data_dir)
    backend.start()
    if a.token and not a.no_stdin_watch and sys.stdin is not None:
        threading.Thread(target=_exit_when_parent_goes, daemon=True).start()
    print(f"GeoLock backend on http://{a.host}:{a.port}, data in {data_dir} "
          f"({time.perf_counter() - t0:.1f}s)", flush=True)
    uvicorn.run(create_app(backend, token=a.token), host=a.host, port=a.port, log_level="warning",
                access_log=False)


if __name__ == "__main__":
    main()
