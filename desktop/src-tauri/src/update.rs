//! Runs an update installer that the backend downloaded and checked (SHA-256 against the
//! release's latest.json, see geolock/desktop/updater.py).

use std::path::{Path, PathBuf};

/// Only a `*-setup.exe` directly inside `<data dir>/updates/` may be run.
pub fn checked_installer(data_dir: &Path, path: &str) -> Result<PathBuf, String> {
    let updates = data_dir
        .join("updates")
        .canonicalize()
        .map_err(|e| format!("no downloaded update ({e})"))?;
    let file = Path::new(path)
        .canonicalize()
        .map_err(|e| format!("the downloaded update is missing ({e})"))?;
    let name = file
        .file_name()
        .and_then(|n| n.to_str())
        .unwrap_or_default()
        .to_ascii_lowercase();
    if file.parent() != Some(updates.as_path()) || !name.ends_with("-setup.exe") || !file.is_file() {
        return Err("that file is not a downloaded GeoLock update".into());
    }
    Ok(plain(file))
}

/// `\\?\C:\...` (what canonicalize returns on Windows) -> `C:\...`, which every program accepts.
fn plain(p: PathBuf) -> PathBuf {
    match p.to_str().and_then(|s| s.strip_prefix(r"\\?\")) {
        Some(rest) if !rest.starts_with("UNC") => PathBuf::from(rest),
        _ => p,
    }
}

/// Starts the installer: /P shows progress without questions, /UPDATE keeps the user's
/// shortcuts as they are, /R starts GeoLock again when it is done.
#[cfg(windows)]
pub fn launch(installer: &Path) -> Result<(), String> {
    use std::os::windows::process::CommandExt;
    // Not part of this app's job object or console, so it outlives the app.
    const DETACHED_PROCESS: u32 = 0x0000_0008;
    const CREATE_BREAKAWAY_FROM_JOB: u32 = 0x0100_0000;
    let run = |flags: u32| {
        std::process::Command::new(installer)
            .args(["/P", "/UPDATE", "/R"])
            .creation_flags(flags)
            .spawn()
    };
    run(DETACHED_PROCESS | CREATE_BREAKAWAY_FROM_JOB)
        // Breakaway is refused when an outer job forbids it; then start it normally.
        .or_else(|_| run(DETACHED_PROCESS))
        .map(|_| ())
        .map_err(|e| format!("could not start the installer: {e}"))
}

#[cfg(not(windows))]
pub fn launch(_installer: &Path) -> Result<(), String> {
    Err("updates install only on Windows".into())
}
