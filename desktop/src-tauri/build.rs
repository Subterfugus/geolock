fn main() {
    // Declaring the app's own commands makes them permissions (allow-backend-info,
    // allow-backend-restart) that capabilities/default.json has to grant explicitly.
    let attributes = tauri_build::Attributes::new().app_manifest(
        tauri_build::AppManifest::new().commands(&["backend_info", "backend_restart"]),
    );
    tauri_build::try_build(attributes).expect("failed to run tauri-build");
}
