//! GeoLock desktop shell: opens the window, runs the Python backend next to it,
//! and stops the backend when the app exits.

mod backend;
mod update;

use std::time::Duration;

use tauri::webview::PageLoadEvent;
use tauri::{AppHandle, Manager, RunEvent, State, WebviewWindow};

use backend::{BackendInfo, BackendState};

/// Label of the one window (see tauri.conf.json).
const MAIN_WINDOW: &str = "main";

/// The UI calls this to learn where the backend is and how to authenticate.
#[tauri::command]
fn backend_info(state: State<'_, BackendState>) -> BackendInfo {
    state.info()
}

/// Stops and respawns the backend (same port and token), then returns the new info.
#[tauri::command]
fn backend_restart(state: State<'_, BackendState>) -> BackendInfo {
    state.restart()
}

/// Runs a downloaded update installer and closes the app so it can replace the files.
/// The installer shows its progress and starts GeoLock again when it is done.
#[tauri::command]
fn install_update(app: AppHandle, state: State<'_, BackendState>, path: String) -> Result<(), String> {
    let installer = update::checked_installer(&state.data_dir(), &path)?;
    // Stop the backend first so the installer can replace its files.
    state.stop();
    if let Err(e) = update::launch(&installer) {
        state.start();
        return Err(e);
    }
    app.exit(0);
    Ok(())
}

/// Brings the window to the front. Used when a second launch is attempted.
fn focus_main(window: &WebviewWindow) {
    let _ = window.unminimize();
    let _ = window.show();
    let _ = window.set_focus();
}

pub fn run() {
    tauri::Builder::default()
        // Must be registered first so a second launch exits before it starts a backend.
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
            if let Some(window) = app.get_webview_window(MAIN_WINDOW) {
                focus_main(&window);
            }
        }))
        // Remember size, position and maximized state, but not visibility: the
        // plugin would show the window before the page has loaded (a white flash).
        .plugin(
            tauri_plugin_window_state::Builder::default()
                .with_state_flags(
                    tauri_plugin_window_state::StateFlags::all()
                        & !tauri_plugin_window_state::StateFlags::VISIBLE,
                )
                .build(),
        )
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_opener::init())
        .invoke_handler(tauri::generate_handler![backend_info, backend_restart, install_update])
        .on_page_load(|webview, payload| {
            // The window starts hidden so there is no blank white frame.
            if payload.event() == PageLoadEvent::Finished {
                if let Some(window) = webview.app_handle().get_webview_window(MAIN_WINDOW) {
                    let _ = window.show();
                }
            }
        })
        .setup(|app| {
            // Fallback: if the page never reports Finished (for example the Vite
            // dev server is down), show the window anyway so the error is visible.
            let handle: AppHandle = app.handle().clone();
            std::thread::spawn(move || {
                std::thread::sleep(Duration::from_secs(10));
                if let Some(window) = handle.get_webview_window(MAIN_WINDOW) {
                    let _ = window.show();
                }
            });

            let state = BackendState::new(app.handle())?;
            state.start();
            app.manage(state);
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building the GeoLock desktop shell")
        .run(|app, event| {
            if let RunEvent::ExitRequested { .. } | RunEvent::Exit = event {
                backend::shutdown(app);
            }
        });
}
