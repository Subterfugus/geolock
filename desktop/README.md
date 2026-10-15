# GeoLock desktop app

A Windows app (Tauri 2) that wraps the GeoLock engine. Three parts:

| Part | Folder | Stack | What it does |
|---|---|---|---|
| Shell | `desktop/src-tauri/` | Rust, Tauri 2 | Opens the window, starts the backend on a free local port with a random token, stops it on exit. Ships the installer. |
| UI | `desktop/ui/` | React, TypeScript, Vite, MapLibre GL | The app's screens. Talks to the backend over HTTP on 127.0.0.1. |
| Backend | `geolock/desktop/` | Python, FastAPI, PyInstaller | The engine. Frozen into `desktop/backend-dist/geolock-backend/geolock-backend.exe`. |

The HTTP contract between the UI and the backend is in `desktop/API.md`.

## How the pieces fit

1. The shell starts. It picks a free port on 127.0.0.1 and a random 32-character token.
2. It runs the backend as `geolock-backend.exe --port <port> --token <token> --data-dir <dir>`,
   with no console window. The backend's stdin is a pipe, so the backend exits when the shell
   dies. The shell also puts the backend in a Windows Job Object that kills it on close.
3. The UI calls the Tauri command `backend_info` (`{url, token, dataDir, logFile, error}`) and
   polls `GET /api/status` until the backend answers.
4. Backend stdout and stderr go to `%LOCALAPPDATA%\com.geolock.desktop\logs\backend.log`.
   At 5 MB the file is moved to `backend.old.log`.
5. `backend_restart` stops and restarts the backend on the same port and token.
   On exit the shell stops the backend.

Window: starts hidden and is shown once the page has loaded (or after 10 s as a fallback), so
there is no white flash. Window size and position are remembered. A second launch focuses the
running window.

## Run in development

You need Node 22, Rust (stable), and the Python engine dependencies.

Install the UI's dependencies once: `npm --prefix desktop/ui ci`, and the shell's CLI once:
`cd desktop/src-tauri && npm ci`.

**Option A: fake data, no Python.** Use the mock backend for UI work:

```
node desktop/ui/mock/server.mjs          # fake backend on port 7861
npm --prefix desktop/ui run dev           # UI on http://localhost:1420, open it in a browser
```

**Option B: real engine in a browser.** No shell, no token:

```
python -m geolock.desktop --port 7861 --no-token
npm --prefix desktop/ui run dev
```

**Option C: the full desktop shell with the real engine.** The shell starts the backend itself.
Point it at the Python command with `GEOLOCK_BACKEND_CMD` (split on spaces, the shell adds
`--port`, `--token` and `--data-dir`) and run the engine from the repo root with
`GEOLOCK_BACKEND_CWD`. Do not add `--no-token` here.

PowerShell:

```
$env:GEOLOCK_BACKEND_CMD = "python -m geolock.desktop"
$env:GEOLOCK_BACKEND_CWD = "C:\path\to\geolock"
cd desktop\src-tauri
npm run dev
```

`npm run dev` runs `tauri dev`, which starts the UI's Vite server through `beforeDevCommand`
(port 1420). Without `GEOLOCK_BACKEND_CMD` the shell looks for the bundled exe, which does not
exist in development. The app then shows the backend error (the UI reads `error` from
`backend_info`), and the log file is not written.

## Build the installer

Tauri's relative paths in `tauri.conf.json` are resolved from `desktop/src-tauri`. The CLI can
be run from `desktop/src-tauri` or from `desktop/` (it finds that folder). Commands:

```
npm --prefix desktop/ui ci                  # UI dependencies (beforeBuildCommand builds the UI)
cd desktop/src-tauri
npm ci
npm run build                               # = tauri build --config tauri.bundle.conf.json
```

Output: `desktop/src-tauri/target/release/bundle/nsis/GeoLock_0.2.0_x64-setup.exe`.

Two configs:

- `tauri.conf.json` is the base, used by `tauri dev`. It does not mention the backend, so dev
  works without `backend-dist`.
- `tauri.bundle.conf.json` adds the `resources` entry that copies
  `desktop/backend-dist/geolock-backend/` into the installer as `backend/`. It is merged with
  `--config`. Only the release build needs it. Run the freeze step first, so
  `backend-dist/geolock-backend/` exists.

The installer is per-user (`%LOCALAPPDATA%\GeoLock`, no admin prompt). WebView2 is installed
by a bootstrapper if it is missing.

CI: `.github/workflows/desktop.yml` freezes the backend, runs the smoke test, runs the commands
above on `windows-latest`, and uploads the installer. Pushes to `main` also publish it as a
GitHub release `v<version>`.

## Things to know

- Icons: `src-tauri/icons/source.svg` is the UI's logo (`desktop/ui/public/logo-1024.svg`).
  Regenerate with `rsvg-convert -w 1024 -h 1024 icons/source.svg -o app-icon.png` and
  `npx tauri icon app-icon.png -o icons`, then delete `icons/android` and `icons/ios`.
- Capabilities: `src-tauri/capabilities/default.json` is the only capability file. The app's
  own commands (`backend_info`, `backend_restart`) must be listed there. Opening links is
  limited to `https://*`. Reveal-in-folder is allowed.
- `src-tauri/gen/schemas` is committed on purpose. Tauri rewrites it on every build.
  `src-tauri/permissions/` is generated from `build.rs`.
- Dev build vs release: `windows_subsystem = "windows"` is set only for release builds, so the
  dev build keeps its console for stderr.
