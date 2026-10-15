//! Starts, watches and stops the Python backend (`geolock-backend.exe`).
//!
//! The contract is in `desktop/API.md`, section "How the shell starts the backend".

use std::fs::{self, OpenOptions};
use std::io::Write;
use std::path::{Path, PathBuf};
use std::process::{Child, ChildStdin, Command, Stdio};
use std::sync::Mutex;
use std::time::{SystemTime, UNIX_EPOCH};

use rand::distr::Alphanumeric;
use rand::Rng;
use serde::Serialize;
use tauri::{AppHandle, Manager};

/// Log file size above which it is moved to `backend.old.log` at each start.
const MAX_LOG_BYTES: u64 = 5 * 1024 * 1024;

/// Name of the bundled executable inside `resources/backend/`.
const BACKEND_EXE: &str = "geolock-backend.exe";

/// Everything the UI needs, returned by the `backend_info` command.
#[derive(Serialize, Clone, Debug)]
#[serde(rename_all = "camelCase")]
pub struct BackendInfo {
    pub url: String,
    pub token: String,
    pub data_dir: String,
    pub log_file: String,
    /// Set when the backend could not be started; the UI shows it.
    pub error: Option<String>,
}

/// Process state, kept in Tauri managed state.
pub struct BackendState {
    inner: Mutex<Backend>,
}

struct Backend {
    port: u16,
    token: String,
    data_dir: PathBuf,
    log_file: PathBuf,
    /// Where to run the backend from, if the bundled exe should not be used.
    /// Dev override: GEOLOCK_BACKEND_CMD (split on whitespace) and GEOLOCK_BACKEND_CWD.
    dev_command: Option<(String, Vec<String>)>,
    dev_cwd: Option<PathBuf>,
    resource_dir: Option<PathBuf>,
    child: Option<Child>,
    /// Kept open on purpose: the backend exits when its stdin reaches EOF,
    /// which happens when this shell dies. Never written to.
    stdin: Option<ChildStdin>,
    #[cfg(windows)]
    job: Option<win::JobHandle>,
    error: Option<String>,
}

impl BackendState {
    /// Picks the port and token and prepares paths. Does not start the backend.
    pub fn new(app: &AppHandle) -> Result<Self, String> {
        let data_dir = app
            .path()
            .app_local_data_dir()
            .map_err(|e| format!("cannot find the app data folder: {e}"))?;
        fs::create_dir_all(&data_dir)
            .map_err(|e| format!("cannot create {}: {e}", data_dir.display()))?;
        let logs_dir = data_dir.join("logs");
        fs::create_dir_all(&logs_dir)
            .map_err(|e| format!("cannot create {}: {e}", logs_dir.display()))?;

        let port = free_port().map_err(|e| format!("cannot pick a free port: {e}"))?;
        let token = random_token(32);

        let dev_command = std::env::var("GEOLOCK_BACKEND_CMD").ok().and_then(|cmd| {
            let mut parts = cmd.split_whitespace().map(str::to_owned);
            let program = parts.next()?;
            Some((program, parts.collect::<Vec<_>>()))
        });
        let dev_cwd = std::env::var("GEOLOCK_BACKEND_CWD")
            .ok()
            .filter(|s| !s.trim().is_empty())
            .map(PathBuf::from);

        Ok(Self {
            inner: Mutex::new(Backend {
                port,
                token,
                log_file: logs_dir.join("backend.log"),
                data_dir,
                dev_command,
                dev_cwd,
                resource_dir: app.path().resource_dir().ok(),
                child: None,
                stdin: None,
                #[cfg(windows)]
                job: None,
                error: None,
            }),
        })
    }

    /// Starts the backend. Errors are stored and reported through `info()`.
    pub fn start(&self) {
        let mut b = self.lock();
        b.spawn();
    }

    /// Stops the backend process, if one is running.
    pub fn stop(&self) {
        let mut b = self.lock();
        b.kill();
    }

    /// Stops and starts the backend again, with the same port and token.
    pub fn restart(&self) -> BackendInfo {
        let mut b = self.lock();
        b.kill();
        b.spawn();
        b.info()
    }

    pub fn info(&self) -> BackendInfo {
        self.lock().info()
    }

    /// The app data folder (the backend keeps downloaded updates in `updates/` there).
    pub fn data_dir(&self) -> PathBuf {
        self.lock().data_dir.clone()
    }

    fn lock(&self) -> std::sync::MutexGuard<'_, Backend> {
        // A poisoned lock only means a panic happened while holding it. The data is still usable.
        self.inner.lock().unwrap_or_else(|e| e.into_inner())
    }
}

impl Backend {
    fn info(&self) -> BackendInfo {
        BackendInfo {
            url: format!("http://127.0.0.1:{}", self.port),
            token: self.token.clone(),
            data_dir: self.data_dir.display().to_string(),
            log_file: self.log_file.display().to_string(),
            error: self.error.clone(),
        }
    }

    fn spawn(&mut self) {
        self.kill();
        match self.try_spawn() {
            Ok(()) => self.error = None,
            Err(e) => {
                eprintln!("geolock: backend did not start: {e}");
                self.error = Some(e);
            }
        }
    }

    fn try_spawn(&mut self) -> Result<(), String> {
        rotate_log(&self.log_file);

        let (program, args, cwd) = match &self.dev_command {
            Some((program, extra)) => (program.clone(), extra.clone(), self.dev_cwd.clone()),
            None => {
                let exe = self
                    .resource_dir
                    .as_ref()
                    .ok_or_else(|| "the app resource folder is not available".to_string())?
                    .join("backend")
                    .join(BACKEND_EXE);
                if !exe.is_file() {
                    return Err(format!("backend not found: {}", exe.display()));
                }
                (exe.display().to_string(), Vec::new(), None)
            }
        };

        let mut log = OpenOptions::new()
            .create(true)
            .append(true)
            .open(&self.log_file)
            .map_err(|e| format!("cannot open {}: {e}", self.log_file.display()))?;
        let _ = writeln!(
            log,
            "=== {} shell starting backend: {} --port {} --data-dir {} ===",
            unix_time(),
            program,
            self.port,
            self.data_dir.display()
        );
        let log_err = log
            .try_clone()
            .map_err(|e| format!("cannot duplicate the log handle: {e}"))?;

        let mut cmd = Command::new(&program);
        cmd.args(&args)
            .arg("--port")
            .arg(self.port.to_string())
            .arg("--token")
            .arg(&self.token)
            .arg("--data-dir")
            .arg(&self.data_dir)
            .stdin(Stdio::piped())
            .stdout(Stdio::from(log))
            .stderr(Stdio::from(log_err));
        if let Some(dir) = &cwd {
            cmd.current_dir(dir);
        }
        #[cfg(windows)]
        {
            use std::os::windows::process::CommandExt;
            const CREATE_NO_WINDOW: u32 = 0x0800_0000;
            cmd.creation_flags(CREATE_NO_WINDOW);
        }

        let mut child = cmd
            .spawn()
            .map_err(|e| format!("cannot start {program}: {e}"))?;

        // Put the backend in a job that kills it when the job handle closes,
        // so it dies even if the shell is killed without running its exit hooks.
        #[cfg(windows)]
        {
            match win::JobHandle::new_kill_on_close() {
                Ok(job) => {
                    if let Err(e) = job.assign(&child) {
                        eprintln!("geolock: could not put the backend in a job object: {e}");
                    }
                    self.job = Some(job);
                }
                Err(e) => eprintln!("geolock: could not create a job object: {e}"),
            }
        }

        self.stdin = child.stdin.take();
        self.child = Some(child);
        Ok(())
    }

    fn kill(&mut self) {
        // Dropping stdin first also makes the backend exit on EOF.
        self.stdin = None;
        if let Some(mut child) = self.child.take() {
            let _ = child.kill();
            let _ = child.wait();
        }
        #[cfg(windows)]
        {
            self.job = None;
        }
    }
}

/// Stops the backend. Call from the app's exit hook.
pub fn shutdown(app: &AppHandle) {
    if let Some(state) = app.try_state::<BackendState>() {
        state.stop();
    }
}

/// Asks the OS for a free TCP port on loopback, then releases it.
fn free_port() -> std::io::Result<u16> {
    let listener = std::net::TcpListener::bind("127.0.0.1:0")?;
    Ok(listener.local_addr()?.port())
}

fn random_token(len: usize) -> String {
    rand::rng()
        .sample_iter(&Alphanumeric)
        .take(len)
        .map(char::from)
        .collect()
}

/// Moves `backend.log` to `backend.old.log` once it grows past the limit.
fn rotate_log(log: &Path) {
    let too_big = fs::metadata(log)
        .map(|m| m.len() > MAX_LOG_BYTES)
        .unwrap_or(false);
    if too_big {
        let old = log.with_file_name("backend.old.log");
        if let Err(e) = fs::rename(log, &old) {
            eprintln!("geolock: could not rotate {}: {e}", log.display());
        }
    }
}

fn unix_time() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_secs())
        .unwrap_or(0)
}

#[cfg(windows)]
mod win {
    use std::os::windows::io::AsRawHandle;
    use std::process::Child;

    use windows_sys::Win32::Foundation::{CloseHandle, HANDLE};
    use windows_sys::Win32::System::JobObjects::{
        AssignProcessToJobObject, CreateJobObjectW, JobObjectExtendedLimitInformation,
        SetInformationJobObject, JOBOBJECT_EXTENDED_LIMIT_INFORMATION,
        JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE,
    };

    /// Owns a job object handle. Closing it (drop) kills every process in the job.
    pub struct JobHandle(HANDLE);

    // The handle is an opaque kernel object reference; it is only used under the
    // Backend mutex, so moving it between threads is fine.
    unsafe impl Send for JobHandle {}

    impl JobHandle {
        pub fn new_kill_on_close() -> Result<Self, String> {
            unsafe {
                let handle = CreateJobObjectW(std::ptr::null(), std::ptr::null());
                if handle.is_null() {
                    return Err(format!("CreateJobObjectW failed ({})", last_error()));
                }
                let job = JobHandle(handle);

                let mut info: JOBOBJECT_EXTENDED_LIMIT_INFORMATION = std::mem::zeroed();
                info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
                let ok = SetInformationJobObject(
                    job.0,
                    JobObjectExtendedLimitInformation,
                    &info as *const _ as *const core::ffi::c_void,
                    std::mem::size_of::<JOBOBJECT_EXTENDED_LIMIT_INFORMATION>() as u32,
                );
                if ok == 0 {
                    return Err(format!("SetInformationJobObject failed ({})", last_error()));
                }
                Ok(job)
            }
        }

        pub fn assign(&self, child: &Child) -> Result<(), String> {
            let ok = unsafe { AssignProcessToJobObject(self.0, child.as_raw_handle() as HANDLE) };
            if ok == 0 {
                Err(format!(
                    "AssignProcessToJobObject failed ({})",
                    last_error()
                ))
            } else {
                Ok(())
            }
        }
    }

    impl Drop for JobHandle {
        fn drop(&mut self) {
            unsafe {
                CloseHandle(self.0);
            }
        }
    }

    fn last_error() -> u32 {
        std::io::Error::last_os_error().raw_os_error().unwrap_or(0) as u32
    }
}
