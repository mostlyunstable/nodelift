//! Nodecraft desktop shell.
//!
//! Its job is process lifecycle, not features: start the bundled Python backend on a random loopback
//! port with a random per-launch token, tell the UI when it is ready (or why it is not), restart it if it
//! crashes, and stop it cleanly on quit. Everything else is the web app in the window.

use std::{
    fs::{self, File},
    net::TcpListener,
    path::{Path, PathBuf},
    process::{Child, Command, Stdio},
    sync::{Arc, Mutex},
    thread,
    time::{Duration, Instant},
};

use rand::RngCore;
use serde::Serialize;
use tauri::{AppHandle, Emitter, Manager, RunEvent, State};

#[cfg(unix)]
use std::os::unix::process::CommandExt;

const READY_TIMEOUT: Duration = Duration::from_secs(25);
const MAX_RESTARTS: u32 = 3;

#[derive(Default)]
struct Inner {
    pid: Option<u32>,
    port: u16,
    token: String,
    /// Set when the backend cannot be (re)started; shown to the user.
    gave_up: Option<String>,
    shutting_down: bool,
    /// Bumped on every manual restart so an older supervisor thread retires quietly.
    generation: u64,
}

struct Shared(Arc<Mutex<Inner>>);

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct BackendInfo {
    base_url: String,
    token: String,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct StartupFailure {
    message: String,
    log_tail: Vec<String>,
    log_path: Option<String>,
}

// ----------------------------------------------------------------------------- paths

fn home() -> PathBuf {
    PathBuf::from(std::env::var("HOME").unwrap_or_else(|_| ".".into()))
}
fn data_dir() -> PathBuf {
    home().join("Library/Application Support/Nodecraft")
}
fn log_dir() -> PathBuf {
    home().join("Library/Logs/Nodecraft")
}
/// Where earlier (browser-era) builds kept their database; imported once, never modified.
fn legacy_dir() -> PathBuf {
    home().join(".nodecraft")
}

fn tail(path: &Path, lines: usize) -> Vec<String> {
    let Ok(text) = fs::read_to_string(path) else { return vec![] };
    let all: Vec<&str> = text.lines().collect();
    all[all.len().saturating_sub(lines)..].iter().map(|s| s.to_string()).collect()
}

fn failure(message: impl Into<String>) -> StartupFailure {
    let mut log_tail = tail(&log_dir().join("backend-stderr.log"), 30);
    log_tail.extend(tail(&log_dir().join("backend.log"), 30));
    StartupFailure {
        message: message.into(),
        log_tail,
        log_path: Some(log_dir().display().to_string()),
    }
}

// ----------------------------------------------------------------------------- launching

struct Launch {
    program: PathBuf,
    args: Vec<String>,
    cwd: PathBuf,
    env: Vec<(String, String)>,
    clear_env: bool,
}

fn find_python(runtime: &Path) -> Option<PathBuf> {
    let bin = runtime.join("python/bin");
    fs::read_dir(bin).ok()?.filter_map(Result::ok).map(|e| e.path()).find(|p| {
        p.file_name()
            .and_then(|n| n.to_str())
            .map(|n| n.starts_with("python3.") && n[8..].chars().all(|c| c.is_ascii_digit()))
            .unwrap_or(false)
    })
}

fn launch_spec(app: &AppHandle, port: u16, token: &str) -> Result<Launch, String> {
    let mut env: Vec<(String, String)> = vec![
        ("NODECRAFT_PORT".into(), port.to_string()),
        ("NODECRAFT_API_TOKEN".into(), token.into()),
        ("NODECRAFT_DATA_DIR".into(), data_dir().display().to_string()),
        ("NODECRAFT_LOG_DIR".into(), log_dir().display().to_string()),
        ("NODECRAFT_LEGACY_DATA_DIR".into(), legacy_dir().display().to_string()),
        ("NODECRAFT_SHUTDOWN_ENDPOINT".into(), "1".into()),
        ("NODECRAFT_PARENT_PID".into(), std::process::id().to_string()),
        (
            "NODECRAFT_ALLOWED_ORIGINS".into(),
            "tauri://localhost,http://tauri.localhost,http://localhost:5173,http://127.0.0.1:5173".into(),
        ),
        ("PYTHONUTF8".into(), "1".into()),
    ];
    let runtime = app.path().resource_dir().ok().map(|d| d.join("runtime"));
    if let Some(runtime) = runtime.filter(|r| r.join("python").exists()) {
        // Packaged app: a private Python with the full standard library, started with a minimal environment.
        let python = find_python(&runtime).ok_or("the bundled Python is missing from the app")?;
        env.push(("PYTHONPATH".into(), runtime.join("site-packages").display().to_string()));
        env.push(("PATH".into(), "/usr/bin:/bin:/usr/sbin:/sbin".into()));
        env.push(("HOME".into(), home().display().to_string()));
        if let Ok(tmp) = std::env::var("TMPDIR") {
            env.push(("TMPDIR".into(), tmp));
        }
        return Ok(Launch {
            program: python,
            args: vec!["-s".into(), "-m".into(), "app.desktop_main".into()],
            cwd: data_dir(),
            env,
            clear_env: true,
        });
    }
    // Development (`pnpm tauri dev`): run the backend from the repository with uv.
    let backend = Path::new(env!("CARGO_MANIFEST_DIR")).join("../../../backend");
    let backend = backend.canonicalize().map_err(|e| format!("no bundled runtime and no backend checkout: {e}"))?;
    Ok(Launch {
        program: "uv".into(),
        args: vec!["run".into(), "python".into(), "-m".into(), "app.desktop_main".into()],
        cwd: backend,
        env,
        clear_env: false,
    })
}

fn spawn_backend(app: &AppHandle, shared: &Arc<Mutex<Inner>>) -> Result<Child, String> {
    fs::create_dir_all(log_dir()).map_err(|e| format!("cannot create the log folder: {e}"))?;
    fs::create_dir_all(data_dir()).map_err(|e| format!("cannot create the data folder: {e}"))?;
    let (port, token) = {
        let inner = shared.lock().unwrap();
        (inner.port, inner.token.clone())
    };
    let spec = launch_spec(app, port, &token)?;
    let out = File::create(log_dir().join("backend-stderr.log")).map_err(|e| e.to_string())?;
    let mut cmd = Command::new(&spec.program);
    cmd.args(&spec.args).current_dir(&spec.cwd);
    if spec.clear_env {
        cmd.env_clear();
    }
    cmd.envs(spec.env);
    cmd.stdin(Stdio::null())
        .stdout(Stdio::from(out.try_clone().map_err(|e| e.to_string())?))
        .stderr(Stdio::from(out));
    #[cfg(unix)]
    cmd.process_group(0); // its own group, so the whole tree can be stopped together
    let child = cmd
        .spawn()
        .map_err(|e| format!("could not start the background service ({}): {e}", spec.program.display()))?;
    shared.lock().unwrap().pid = Some(child.id());
    Ok(child)
}

/// Watches the backend; restarts it (same port and token) if it dies unexpectedly.
fn supervise(app: AppHandle, shared: Arc<Mutex<Inner>>, mut child: Child, generation: u64) {
    thread::spawn(move || {
        let mut restarts = 0u32;
        let mut started = Instant::now();
        loop {
            let status = loop {
                match child.try_wait() {
                    Ok(Some(s)) => break s.to_string(),
                    Ok(None) => thread::sleep(Duration::from_millis(400)),
                    Err(e) => break format!("wait failed: {e}"),
                }
            };
            {
                let mut inner = shared.lock().unwrap();
                if inner.shutting_down || inner.generation != generation {
                    return; // quitting, or replaced by a manual restart
                }
                inner.pid = None;
            }
            let reason = format!("The background service exited ({status})");
            let _ = app.emit("backend-exited", reason.clone());
            if started.elapsed() > Duration::from_secs(60) {
                restarts = 0; // it ran fine for a while; this is a fresh failure
            }
            restarts += 1;
            if restarts > MAX_RESTARTS {
                shared.lock().unwrap().gave_up = Some(format!("{reason}. It kept failing, so it was not restarted again."));
                return;
            }
            thread::sleep(Duration::from_secs(1 << (restarts - 1)));
            match spawn_backend(&app, &shared) {
                Ok(c) => {
                    child = c;
                    started = Instant::now();
                }
                Err(e) => {
                    shared.lock().unwrap().gave_up = Some(e);
                    return;
                }
            }
        }
    });
}

fn start_backend(app: &AppHandle) {
    let shared = app.state::<Shared>().0.clone();
    {
        let mut inner = shared.lock().unwrap();
        inner.port = TcpListener::bind("127.0.0.1:0").and_then(|l| l.local_addr()).map(|a| a.port()).unwrap_or(0);
        let mut bytes = [0u8; 32];
        rand::thread_rng().fill_bytes(&mut bytes);
        inner.token = bytes.iter().map(|b| format!("{b:02x}")).collect();
        inner.gave_up = None;
    }
    let generation = shared.lock().unwrap().generation;
    match spawn_backend(app, &shared) {
        Ok(child) => supervise(app.clone(), shared, child, generation),
        Err(e) => shared.lock().unwrap().gave_up = Some(e),
    }
}

// ----------------------------------------------------------------------------- process control

#[cfg(unix)]
fn alive(pid: u32) -> bool {
    unsafe { libc::kill(pid as i32, 0) == 0 }
}
#[cfg(unix)]
fn signal_group(pid: u32, sig: i32) {
    unsafe {
        libc::kill(-(pid as i32), sig);
    }
}

fn wait_gone(pid: u32, timeout: Duration) -> bool {
    let end = Instant::now() + timeout;
    while Instant::now() < end {
        if !alive(pid) {
            return true;
        }
        thread::sleep(Duration::from_millis(100));
    }
    !alive(pid)
}

fn health_ok(port: u16) -> bool {
    ureq::get(&format!("http://127.0.0.1:{port}/api/v1/health"))
        .timeout(Duration::from_millis(800))
        .call()
        .is_ok()
}

/// Ask the backend to stop itself, then insist if it does not.
fn stop_backend(shared: &Arc<Mutex<Inner>>) {
    let (pid, port, token) = {
        let mut inner = shared.lock().unwrap();
        inner.shutting_down = true;
        (inner.pid, inner.port, inner.token.clone())
    };
    let Some(pid) = pid else { return };
    let _ = ureq::post(&format!("http://127.0.0.1:{port}/api/v1/system/shutdown"))
        .set("Authorization", &format!("Bearer {token}"))
        .timeout(Duration::from_secs(2))
        .send_string("");
    if wait_gone(pid, Duration::from_secs(6)) {
        return;
    }
    signal_group(pid, libc::SIGTERM);
    if wait_gone(pid, Duration::from_secs(2)) {
        return;
    }
    signal_group(pid, libc::SIGKILL);
    let _ = wait_gone(pid, Duration::from_secs(2));
}

// ----------------------------------------------------------------------------- commands

fn wait_ready(shared: &Arc<Mutex<Inner>>) -> Result<BackendInfo, StartupFailure> {
    let deadline = Instant::now() + READY_TIMEOUT;
    loop {
        let (port, token, gave_up) = {
            let inner = shared.lock().unwrap();
            (inner.port, inner.token.clone(), inner.gave_up.clone())
        };
        if let Some(message) = gave_up {
            return Err(failure(message));
        }
        if port != 0 && health_ok(port) {
            return Ok(BackendInfo { base_url: format!("http://127.0.0.1:{port}"), token });
        }
        if Instant::now() > deadline {
            return Err(failure(format!(
                "The background service did not become ready within {} seconds.",
                READY_TIMEOUT.as_secs()
            )));
        }
        thread::sleep(Duration::from_millis(150));
    }
}

#[tauri::command]
async fn wait_for_backend(state: State<'_, Shared>) -> Result<BackendInfo, StartupFailure> {
    let shared = state.0.clone();
    tauri::async_runtime::spawn_blocking(move || wait_ready(&shared))
        .await
        .map_err(|e| failure(format!("internal error: {e}")))?
}

#[tauri::command]
async fn restart_backend(app: AppHandle, state: State<'_, Shared>) -> Result<(), StartupFailure> {
    let shared = state.0.clone();
    tauri::async_runtime::spawn_blocking(move || {
        let old = {
            let mut inner = shared.lock().unwrap();
            inner.generation += 1; // retires the old supervisor
            inner.pid.take()
        };
        if let Some(pid) = old {
            signal_group(pid, libc::SIGTERM);
            if !wait_gone(pid, Duration::from_secs(5)) {
                signal_group(pid, libc::SIGKILL);
                let _ = wait_gone(pid, Duration::from_secs(2));
            }
        }
        start_backend(&app);
    })
    .await
    .map_err(|e| failure(format!("internal error: {e}")))
}

#[tauri::command]
fn reveal_logs() -> Result<(), String> {
    Command::new("open").arg(log_dir()).spawn().map(|_| ()).map_err(|e| e.to_string())
}

// ----------------------------------------------------------------------------- app

pub fn run() {
    let shared = Shared(Arc::new(Mutex::new(Inner::default())));
    let for_exit = shared.0.clone();
    tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
            if let Some(window) = app.get_webview_window("main") {
                let _ = window.unminimize();
                let _ = window.set_focus();
            }
        }))
        .manage(shared)
        .invoke_handler(tauri::generate_handler![wait_for_backend, restart_backend, reveal_logs])
        .setup(|app| {
            start_backend(app.handle());
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("failed to build the Nodecraft app")
        .run(move |_app, event| {
            if let RunEvent::Exit = event {
                stop_backend(&for_exit);
            }
        });
}
