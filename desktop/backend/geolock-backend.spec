# PyInstaller spec for the desktop backend:  pyinstaller desktop/backend/geolock-backend.spec
# Output: desktop/backend-dist/geolock-backend/ (geolock-backend.exe + _internal/), which the
# Tauri shell bundles as a resource folder. Run from the repository root.
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_submodules

root = Path(SPECPATH).resolve().parent.parent
datas, binaries, hidden = [], [], []
for pkg in ("openvino", "rapidocr", "lingua", "pillow_heif", "shapely"):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hidden += h
# OpenVINO frontends GeoLock never uses (it reads IR and, once, ONNX)
unused = ("tensorflow_frontend", "tensorflow_lite_frontend", "paddle_frontend", "pytorch_frontend",
          "jax_frontend", "gguf_frontend")
binaries = [b for b in binaries if not any(u in Path(b[0]).name for u in unused)]
datas = [d for d in datas if not any(u in Path(d[0]).name for u in unused)]
datas += collect_data_files("reverse_geocoder")
datas += collect_data_files("geolock", includes=["data/*.geojson", "desktop/bundled/*"])
hidden += collect_submodules("uvicorn") + collect_submodules("geolock")
hidden += ["scipy.spatial", "scipy.special"]

a = Analysis(
    [str(root / "desktop" / "backend" / "entry.py")],
    pathex=[str(root)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hidden,
    excludes=["torch", "torchvision", "transformers", "tensorflow", "jax", "matplotlib",
              "tkinter", "IPython", "pytest", "nncf", "optimum", "openvino_genai", "pandas"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="geolock-backend",
          console=True,  # needs real stdio; the shell starts it with CREATE_NO_WINDOW
          upx=False)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="geolock-backend")
