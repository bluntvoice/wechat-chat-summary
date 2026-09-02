use serde_json::{json, Value};
use std::env;
use std::io::Write;
use std::net::{SocketAddr, TcpListener, TcpStream};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use std::thread;
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};
use tauri::{Manager, State};

#[cfg(windows)]
use std::os::windows::process::CommandExt;

const CREATE_NO_WINDOW: u32 = 0x08000000;

struct BridgeProgram {
    executable: PathBuf,
    arguments: Vec<String>,
    working_dir: PathBuf,
}

#[derive(Default)]
struct McpProcessState {
    child: Mutex<Option<Child>>,
}

fn mcp_status_value(child: Option<&Child>, port: u16) -> Value {
    json!({
        "running": child.is_some(),
        "pid": child.map(Child::id),
        "transport": "streamable-http",
        "host": "127.0.0.1",
        "port": port,
        "endpoint": format!("http://127.0.0.1:{port}/mcp"),
    })
}

fn stop_mcp_process(state: &McpProcessState) -> Result<(), String> {
    let mut guard = state.child.lock().map_err(|_| "MCP 进程状态锁已损坏。".to_string())?;
    if let Some(mut child) = guard.take() {
        if child.try_wait().map_err(|error| error.to_string())?.is_none() {
            child.kill().map_err(|error| format!("停止 MCP Server 失败: {error}"))?;
            child.wait().map_err(|error| format!("等待 MCP Server 退出失败: {error}"))?;
        }
    }
    Ok(())
}

fn repository_root() -> Result<PathBuf, String> {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .and_then(Path::parent)
        .map(Path::to_path_buf)
        .ok_or_else(|| "无法定位项目根目录。".to_string())
}

fn python_command(repo: &Path) -> (PathBuf, Vec<String>) {
    if let Ok(configured) = env::var("GROUP_INSIGHT_PYTHON") {
        if !configured.trim().is_empty() {
            return (PathBuf::from(configured), Vec::new());
        }
    }
    let local_python = repo.join(".venv").join("Scripts").join("python.exe");
    if local_python.exists() {
        return (local_python, Vec::new());
    }
    (PathBuf::from("python"), Vec::new())
}

fn installed_bridge_program() -> Result<BridgeProgram, String> {
    let executable = env::current_exe().map_err(|error| format!("无法定位桌面程序: {error}"))?;
    let program_dir = executable
        .parent()
        .ok_or_else(|| "无法定位桌面程序目录。".to_string())?;
    let candidates = [
        program_dir.join("engine").join("group-insight-sidecar.exe"),
        program_dir.join("group-insight-sidecar.exe"),
        program_dir.join("group-insight-sidecar-x86_64-pc-windows-msvc.exe"),
    ];
    let sidecar = candidates
        .into_iter()
        .find(|candidate| candidate.is_file())
        .ok_or_else(|| "安装目录中缺少分析引擎，请重新安装测试版本。".to_string())?;
    let working_dir = sidecar
        .parent()
        .map(Path::to_path_buf)
        .ok_or_else(|| "无法定位分析引擎目录。".to_string())?;
    Ok(BridgeProgram {
        executable: sidecar,
        arguments: Vec::new(),
        working_dir,
    })
}

fn bridge_program() -> Result<BridgeProgram, String> {
    if !cfg!(debug_assertions) {
        return installed_bridge_program();
    }
    let repo = repository_root()?;
    let (python, prefix_args) = python_command(&repo);
    let mut arguments = prefix_args;
    arguments.extend(["-m".to_string(), "group_insight.desktop_bridge".to_string()]);
    Ok(BridgeProgram {
        executable: python,
        arguments,
        working_dir: repo,
    })
}

fn run_bridge(
    command_name: String,
    payload: Value,
    app_local_data_dir: PathBuf,
) -> Result<Value, String> {
    let bridge = bridge_program()?;
    let request_id = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|error| error.to_string())?
        .as_millis()
        .to_string();
    let request = json!({"id": request_id, "command": command_name, "payload": payload});

    let mut process = Command::new(&bridge.executable);
    process
        .args(&bridge.arguments)
        .current_dir(&bridge.working_dir)
        .env("PYTHONUTF8", "1")
        .env("PYTHONIOENCODING", "utf-8")
        .env("WECHAT_CHAT_SUMMARY_APP_LOCAL_DATA_DIR", app_local_data_dir)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());
    #[cfg(windows)]
    process.creation_flags(CREATE_NO_WINDOW);
    let mut child = process
        .spawn()
        .map_err(|error| format!("无法启动分析服务 ({:?}): {error}", bridge.executable))?;
    if let Some(stdin) = child.stdin.as_mut() {
        writeln!(stdin, "{request}").map_err(|error| format!("写入分析请求失败: {error}"))?;
    }
    drop(child.stdin.take());
    let output = child
        .wait_with_output()
        .map_err(|error| error.to_string())?;
    if !output.status.success() {
        return Err(String::from_utf8_lossy(&output.stderr).trim().to_string());
    }
    let stdout = String::from_utf8(output.stdout).map_err(|error| error.to_string())?;
    let response_line = stdout
        .lines()
        .rev()
        .find(|line| !line.trim().is_empty())
        .ok_or_else(|| "Python 分析服务没有返回结果。".to_string())?;
    serde_json::from_str(response_line).map_err(|error| format!("解析分析结果失败: {error}"))
}

#[tauri::command]
async fn bridge_call(
    app: tauri::AppHandle,
    command: String,
    payload: Value,
) -> Result<Value, String> {
    let app_local_data_dir = app
        .path()
        .app_local_data_dir()
        .map_err(|error| format!("无法定位 Windows 用户数据目录: {error}"))?;
    tauri::async_runtime::spawn_blocking(move || {
        run_bridge(command, payload, app_local_data_dir)
    })
        .await
        .map_err(|error| error.to_string())?
}

#[tauri::command]
fn mcp_server_status(state: State<'_, McpProcessState>, port: u16) -> Result<Value, String> {
    let mut guard = state.child.lock().map_err(|_| "MCP 进程状态锁已损坏。".to_string())?;
    if let Some(child) = guard.as_mut() {
        if child.try_wait().map_err(|error| error.to_string())?.is_some() {
            *guard = None;
        }
    }
    Ok(mcp_status_value(guard.as_ref(), port))
}

#[tauri::command]
fn mcp_server_start(
    app: tauri::AppHandle,
    state: State<'_, McpProcessState>,
    port: u16,
) -> Result<Value, String> {
    if port < 1024 {
        return Err("MCP 端口必须在 1024 到 65535 之间。".to_string());
    }
    let mut guard = state.child.lock().map_err(|_| "MCP 进程状态锁已损坏。".to_string())?;
    if let Some(child) = guard.as_mut() {
        if child.try_wait().map_err(|error| error.to_string())?.is_none() {
            return Ok(mcp_status_value(guard.as_ref(), port));
        }
        *guard = None;
    }

    let bridge = bridge_program()?;
    let app_local_data_dir = app
        .path()
        .app_local_data_dir()
        .map_err(|error| format!("无法定位 Windows 用户数据目录: {error}"))?;
    let address = SocketAddr::from(([127, 0, 0, 1], port));
    let port_probe = TcpListener::bind(address)
        .map_err(|error| format!("MCP 本机端口 {port} 不可用: {error}"))?;
    drop(port_probe);
    let mut process = Command::new(&bridge.executable);
    let port_text = port.to_string();
    process
        .args(&bridge.arguments)
        .args(["--run-mcp-server", "--port", port_text.as_str()])
        .current_dir(&bridge.working_dir)
        .env("PYTHONUTF8", "1")
        .env("PYTHONIOENCODING", "utf-8")
        .env("WECHAT_CHAT_SUMMARY_APP_LOCAL_DATA_DIR", app_local_data_dir)
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null());
    #[cfg(windows)]
    process.creation_flags(CREATE_NO_WINDOW);
    let mut child = process
        .spawn()
        .map_err(|error| format!("无法启动 MCP Server ({:?}): {error}", bridge.executable))?;
    let deadline = Instant::now() + Duration::from_secs(5);
    loop {
        if let Some(status) = child.try_wait().map_err(|error| error.to_string())? {
            return Err(format!("MCP Server 启动后立即退出: {status}"));
        }
        if TcpStream::connect_timeout(&address, Duration::from_millis(100)).is_ok() {
            break;
        }
        if Instant::now() >= deadline {
            let _ = child.kill();
            let _ = child.wait();
            return Err("MCP Server 在 5 秒内未能监听本机端口。".to_string());
        }
        thread::sleep(Duration::from_millis(50));
    }
    *guard = Some(child);
    Ok(mcp_status_value(guard.as_ref(), port))
}

#[tauri::command]
fn mcp_server_stop(state: State<'_, McpProcessState>, port: u16) -> Result<Value, String> {
    stop_mcp_process(&state)?;
    Ok(mcp_status_value(None, port))
}

#[tauri::command]
fn open_system_path(path: String) -> Result<(), String> {
    let target = PathBuf::from(path);
    if !target.exists() {
        return Err(format!("文件或目录不存在: {}", target.display()));
    }
    open::that_detached(&target).map_err(|error| format!("无法打开路径: {error}"))
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .manage(McpProcessState::default())
        .invoke_handler(tauri::generate_handler![
            bridge_call,
            open_system_path,
            mcp_server_status,
            mcp_server_start,
            mcp_server_stop
        ])
        .build(tauri::generate_context!())
        .expect("error while building WeChat Chat Summary");
    app.run(|app_handle, event| {
        if matches!(event, tauri::RunEvent::ExitRequested { .. } | tauri::RunEvent::Exit) {
            let state = app_handle.state::<McpProcessState>();
            let _ = stop_mcp_process(&state);
        }
    });
}
