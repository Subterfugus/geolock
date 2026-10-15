"""PyInstaller entry point for geolock-backend.exe (see geolock/desktop/__main__.py)."""
import multiprocessing

if __name__ == "__main__":
    multiprocessing.freeze_support()
    from geolock.desktop.__main__ import main
    main()
