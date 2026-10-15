"""Write latest.json, the update information the desktop app reads (geolock/desktop/updater.py).

CI runs this after building the installer and uploads the result to the same release:

    python tools/update_manifest.py --installer GeoLock_0.5.0_x64-setup.exe --version 0.5.0 \
        --repo Subterfugus/geolock --notes docs/releases/v0.5.0.md --out latest.json
"""
import argparse
import hashlib
import json
import sys
import time
import urllib.parse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from geolock.desktop.updater import validate_manifest  # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--installer", required=True, type=Path)
    ap.add_argument("--version", required=True)
    ap.add_argument("--repo", required=True, help="owner/name the release is published on")
    ap.add_argument("--notes", type=Path, help="release notes (markdown)")
    ap.add_argument("--out", default="latest.json", type=Path)
    a = ap.parse_args(argv)

    h = hashlib.sha256()
    with open(a.installer, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 22), b""):
            h.update(chunk)
    name = a.installer.name
    tag = f"v{a.version}"
    # gh release upload stores the file under its own name; spaces would become dots.
    url = f"https://github.com/{a.repo}/releases/download/{tag}/{urllib.parse.quote(name)}"
    notes = a.notes.read_text(encoding="utf-8") if a.notes and a.notes.exists() else ""
    m = validate_manifest({
        "version": a.version,
        "published_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "notes": notes,
        "installer": {"name": name, "url": url, "size": a.installer.stat().st_size,
                      "sha256": h.hexdigest()},
    })
    a.out.write_text(json.dumps(m, indent=2), encoding="utf-8")
    print(json.dumps(dict(m, notes=f"{len(notes)} chars"), indent=2))


if __name__ == "__main__":
    main()
