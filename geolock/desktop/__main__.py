"""Entry point of the desktop backend: python -m geolock.desktop (frozen: geolock-backend.exe)."""
import argparse
import os
import sys
import threading
from pathlib import Path


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
    if not a.token and not a.no_token:
        ap.error("pass --token (the desktop shell does) or --no-token for development")

    if sys.stdout is None:  # frozen without a console: keep print() and tracebacks working
        sys.stdout = open(os.devnull, "w")
    if sys.stderr is None:
        sys.stderr = sys.stdout
    data_dir = a.data_dir or default_data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("GEOLOCK_MODELS", str(data_dir / "models"))

    if a.token and not a.no_stdin_watch and sys.stdin is not None:
        threading.Thread(target=_exit_when_parent_goes, daemon=True).start()

    import uvicorn
    from .server import Backend, create_app
    backend = Backend(data_dir)
    backend.start()
    print(f"GeoLock backend on http://{a.host}:{a.port}, data in {data_dir}", flush=True)
    uvicorn.run(create_app(backend, token=a.token), host=a.host, port=a.port, log_level="warning",
                access_log=False)


if __name__ == "__main__":
    main()
