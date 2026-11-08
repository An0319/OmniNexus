//! 桌面壳 F · 进程桥（骨架；本机尚未安装 Rust，未经编译验证）。
//!
//! 契约来源：`desktop/ui/bridge.js`（`mnx-shell-bridge/v1`）。
//!
//! 三条硬约束：
//! 1. 桥只搬运。`exitCode` / `stdout` / `stderr` / 产物路径原样回传，不做「友好化」；
//!    `status`、`verdict`、`reason_code` 的判定只允许发生在 `ui/status-map.js`。
//! 2. `failed` 时照样回传产物路径，界面自己决定拦不拦；桥不吞产物、不下结论。
//! 3. `--at` 必须由壳显式传入；本文件不读系统时钟、不给默认时刻。

use std::io::{BufRead, BufReader};
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::sync::{Arc, Mutex};
use std::thread;

use serde::{Deserialize, Serialize};
use serde_json::Value;
use tauri::{AppHandle, Emitter};

/// 系统解释器（作者已拍板：先用系统 Python312，运行时冻结属打包阶段）。
const PYTHON_FALLBACK: &str = r"C:\Users\24063\AppData\Local\Programs\Python\Python312\python.exe";
/// 进度事件名，与 `bridge.js` 的 `onTimelineProgress` 对齐。
const PROGRESS_EVENT: &str = "timeline-progress";
/// 隐藏子进程控制台窗口（Windows）。
#[cfg(windows)]
const CREATE_NO_WINDOW: u32 = 0x0800_0000;

/// 统一返回形状：字段名与 `bridge.js` 的 `normalize()` 对齐。
#[derive(Debug, Serialize, Clone)]
struct Outcome {
    #[serde(rename = "exitCode")]
    exit_code: Option<i32>,
    stdout: String,
    stderr: String,
    data: Option<Value>,
}

#[derive(Debug, Deserialize, Clone)]
#[serde(rename_all = "camelCase")]
struct TimelineRequest {
    mode: String,
    topic: Option<String>,
    entity: Option<String>,
    start: String,
    end: String,
    sources: Option<Vec<String>>,
    max_per_source: Option<u32>,
    out_dir: Option<String>,
    python_path: Option<String>,
}

#[derive(Debug, Deserialize, Clone)]
#[serde(rename_all = "camelCase")]
struct RegisterRequest {
    payload: Value,
    at: String,
    ledger: String,
    python_path: Option<String>,
}

#[derive(Debug, Deserialize, Clone)]
#[serde(rename_all = "camelCase")]
struct VerifyRequest {
    at: String,
    id: Option<String>,
    ledger: String,
    python_path: Option<String>,
}

#[derive(Debug, Deserialize, Clone)]
#[serde(rename_all = "camelCase")]
struct LedgerRequest {
    ledger: String,
    python_path: Option<String>,
}

/* ── 校验 ──────────────────────────────────────────────────────── */

fn is_iso_date(text: &str) -> bool {
    let bytes = text.as_bytes();
    if bytes.len() != 10 {
        return false;
    }
    bytes.iter().enumerate().all(|(i, b)| {
        if i == 4 || i == 7 {
            *b == b'-'
        } else {
            b.is_ascii_digit()
        }
    })
}

/// `YYYY-MM-DDTHH:MM:SS(.fff)?Z`；与 `bridge.js` 的 ISO_AT 同一口径。
fn is_iso_at(text: &str) -> bool {
    let Some(core) = text.strip_suffix('Z') else {
        return false;
    };
    let Some((date, rest)) = core.split_once('T') else {
        return false;
    };
    if !is_iso_date(date) {
        return false;
    }
    let mut parts = rest.splitn(2, '.');
    let hms = parts.next().unwrap_or("");
    let frac = parts.next();
    let cells: Vec<&str> = hms.split(':').collect();
    if cells.len() != 3 {
        return false;
    }
    if !cells
        .iter()
        .all(|c| c.len() == 2 && c.bytes().all(|b| b.is_ascii_digit()))
    {
        return false;
    }
    if let Some(f) = frac {
        if f.is_empty() || !f.bytes().all(|b| b.is_ascii_digit()) {
            return false;
        }
    }
    true
}

fn require_non_empty(value: &str, field: &str) -> Result<(), String> {
    if value.trim().is_empty() {
        return Err(format!("{field} 不能为空"));
    }
    Ok(())
}

/* ── 路径 / 进程 ───────────────────────────────────────────────── */

/// 仓库根：优先 `MNX_REPO_ROOT`，否则从当前目录向上找 `phase0/timeline/timeline.py`。
fn repo_root() -> Result<PathBuf, String> {
    if let Ok(raw) = std::env::var("MNX_REPO_ROOT") {
        if !raw.trim().is_empty() {
            return Ok(PathBuf::from(raw));
        }
    }
    let mut dir = std::env::current_dir().map_err(|e| format!("取当前目录失败：{e}"))?;
    loop {
        if dir
            .join("phase0")
            .join("timeline")
            .join("timeline.py")
            .is_file()
        {
            return Ok(dir);
        }
        match dir.parent() {
            Some(parent) => dir = parent.to_path_buf(),
            None => break,
        }
    }
    Err("找不到仓库根（缺 phase0/timeline/timeline.py）；可用 MNX_REPO_ROOT 显式指定".into())
}

/// 相对路径一律按仓库根解析；绝对路径原样使用。
fn resolve_path(raw: &str) -> Result<PathBuf, String> {
    let path = PathBuf::from(raw.trim());
    if path.is_absolute() {
        Ok(path)
    } else {
        Ok(repo_root()?.join(path))
    }
}

fn python_binary(requested: Option<String>) -> Result<String, String> {
    let chosen = requested
        .filter(|s| !s.trim().is_empty())
        .unwrap_or_else(|| PYTHON_FALLBACK.to_string());
    if !Path::new(&chosen).is_file() {
        return Err(format!("Python 解释器不存在：{chosen}"));
    }
    Ok(chosen)
}

fn base_command(python: &str) -> Command {
    let mut cmd = Command::new(python);
    // 子进程输出按 UTF-8 解释；这是传输层设置，不改写任何内容。
    cmd.env("PYTHONIOENCODING", "utf-8")
        .env("PYTHONUTF8", "1");
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        cmd.creation_flags(CREATE_NO_WINDOW);
    }
    cmd
}

fn join_lines(lines: &[String]) -> String {
    lines.join("\n")
}

/// 一次性执行的命令（注册 / 核验 / 列表 / 链校验 / 对账）。
/// script 是相对仓库根的脚本路径，必须作为第一个参数传给 Python。
fn run_once(python: &str, root: &Path, script: &str, args: &[String]) -> Result<Outcome, String> {
    let script_path = root.join(script);
    if !script_path.is_file() {
        return Err(format!("脚本不存在：{}", script_path.to_string_lossy()));
    }
    let output = base_command(python)
        .arg(&script_path)
        .args(args)
        .current_dir(root)
        .output()
        .map_err(|e| format!("启动 Python 失败：{e}"))?;
    let stdout = String::from_utf8_lossy(&output.stdout).to_string();
    let stderr = String::from_utf8_lossy(&output.stderr).to_string();
    // stdout 若是合法 JSON，原样解析进 data；字段不改写、状态不重算。
    let data = serde_json::from_str::<Value>(stdout.trim()).ok();
    Ok(Outcome {
        exit_code: output.status.code(),
        stdout,
        stderr,
        data,
    })
}

/* ── 时间线 ────────────────────────────────────────────────────── */

fn run_timeline_blocking(app: AppHandle, request: TimelineRequest) -> Result<Outcome, String> {
    let mode = request.mode.trim();
    if mode != "topic" && mode != "entity" {
        return Err(format!("mode 只能是 topic 或 entity，收到 {mode:?}"));
    }
    let query = if mode == "entity" {
        request.entity.clone().unwrap_or_default()
    } else {
        request.topic.clone().unwrap_or_default()
    };
    let query = query.trim().to_string();
    require_non_empty(&query, if mode == "entity" { "实体词" } else { "主题词" })?;

    let start = request.start.trim().to_string();
    let end = request.end.trim().to_string();
    if !is_iso_date(&start) || !is_iso_date(&end) {
        return Err("start / end 必须是 YYYY-MM-DD".into());
    }
    if start > end {
        return Err("start 不能晚于 end".into());
    }

    let max_per_source = request.max_per_source.unwrap_or(60);
    if !(1..=200).contains(&max_per_source) {
        return Err("maxPerSource 必须在 1–200".into());
    }

    let out_dir_raw = request
        .out_dir
        .clone()
        .unwrap_or_else(|| "phase0/timeline/out".to_string());
    require_non_empty(&out_dir_raw, "输出目录")?;
    let out_dir = resolve_path(&out_dir_raw)?;
    let root = repo_root()?;
    let python = python_binary(request.python_path.clone())?;

    let mut args: Vec<String> = Vec::new();
    args.push(if mode == "entity" { "--entity" } else { "--topic" }.to_string());
    args.push(query);
    args.push("--start".into());
    args.push(start);
    args.push("--end".into());
    args.push(end);
    if let Some(sources) = request.sources.as_ref().filter(|v| !v.is_empty()) {
        args.push("--sources".into());
        args.push(sources.join(","));
    }
    args.push("--max-per-source".into());
    args.push(max_per_source.to_string());
    args.push("--out-dir".into());
    args.push(out_dir.to_string_lossy().to_string());

    let mut child = base_command(&python)
        .arg(root.join("phase0/timeline/timeline.py"))
        .args(&args)
        .current_dir(&root)
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .map_err(|e| format!("启动 timeline.py 失败：{e}"))?;

    let stdout_pipe = child.stdout.take();
    let stderr_pipe = child.stderr.take();
    let out_lines: Arc<Mutex<Vec<String>>> = Arc::new(Mutex::new(Vec::new()));
    let err_lines: Arc<Mutex<Vec<String>>> = Arc::new(Mutex::new(Vec::new()));

    // 逐行转发 stdout：长任务（几百条 × 1.2–1.8 秒）要能看到在跑，而不是像卡死。
    let stdout_thread = {
        let app = app.clone();
        let buffer = Arc::clone(&out_lines);
        thread::spawn(move || {
            if let Some(pipe) = stdout_pipe {
                let mut seq: u64 = 0;
                for line in BufReader::new(pipe).lines() {
                    let Ok(line) = line else { break };
                    seq += 1;
                    let _ = app.emit(
                        PROGRESS_EVENT,
                        serde_json::json!({ "kind": "line", "seq": seq, "line": line }),
                    );
                    if let Ok(mut guard) = buffer.lock() {
                        guard.push(line);
                    }
                }
            }
        })
    };

    let stderr_thread = {
        let buffer = Arc::clone(&err_lines);
        thread::spawn(move || {
            if let Some(pipe) = stderr_pipe {
                for line in BufReader::new(pipe).lines() {
                    let Ok(line) = line else { break };
                    if let Ok(mut guard) = buffer.lock() {
                        guard.push(line);
                    }
                }
            }
        })
    };

    let status = child
        .wait()
        .map_err(|e| format!("等待 timeline.py 结束失败：{e}"))?;
    let _ = stdout_thread.join();
    let _ = stderr_thread.join();

    let exit_code = status.code();
    let _ = app.emit(
        PROGRESS_EVENT,
        serde_json::json!({ "kind": "exit", "exitCode": exit_code }),
    );

    let stdout_text = out_lines
        .lock()
        .map(|g| join_lines(&g))
        .unwrap_or_default();
    let stderr_text = err_lines
        .lock()
        .map(|g| join_lines(&g))
        .unwrap_or_default();

    // failed 也照样回传产物路径：桥不替界面决定拦不拦。
    let events_json = out_dir.join("events.json");
    let events_md = out_dir.join("events.md");
    let raw_items_json = out_dir.join("raw_items.json");
    let data = {
        let mut data = serde_json::json!({
            "outDir": out_dir.to_string_lossy(),
            "eventsJson": events_json.to_string_lossy(),
            "eventsMd": events_md.to_string_lossy(),
            "rawItemsJson": raw_items_json.to_string_lossy(),
            "eventsJsonExists": events_json.is_file(),
            "rawItemsJsonExists": raw_items_json.is_file(),
        });
        // 界面要渲染必须拿到文档本身；路径照旧回传，桥不改写产物内容。
        if events_json.is_file() {
            if let Ok(text) = std::fs::read_to_string(&events_json) {
                if let Ok(doc) = serde_json::from_str::<serde_json::Value>(&text) {
                    data["eventsDoc"] = doc;
                }
            }
        }
        data
    };

    Ok(Outcome {
        exit_code,
        stdout: stdout_text,
        stderr: stderr_text,
        data: Some(data),
    })
}

/* ── Tauri 命令：全部只搬运 ────────────────────────────────────── */

#[tauri::command]
async fn run_timeline(app: AppHandle, request: TimelineRequest) -> Result<Outcome, String> {
    tauri::async_runtime::spawn_blocking(move || run_timeline_blocking(app, request))
        .await
        .map_err(|e| format!("run_timeline 线程异常：{e}"))?
}

#[tauri::command]
async fn registry_register(request: RegisterRequest) -> Result<Outcome, String> {
    tauri::async_runtime::spawn_blocking(move || {
        if !request.payload.is_object() {
            return Err("payload 必须是 JSON 对象".to_string());
        }
        if !is_iso_at(request.at.trim()) {
            return Err("--at 必须是 ISO-8601 UTC 时刻，且带 Z（如 2026-11-08T09:00:00Z）".into());
        }
        require_non_empty(&request.ledger, "账本路径")?;
        let root = repo_root()?;
        let python = python_binary(request.python_path)?;
        let ledger = resolve_path(&request.ledger)?;
        let payload_text = serde_json::to_string(&request.payload)
            .map_err(|e| format!("payload 序列化失败：{e}"))?;
        let args: Vec<String> = vec![
            "--ledger".into(),
            ledger.to_string_lossy().to_string(),
            "register".into(),
            "--payload".into(),
            payload_text,
            "--at".into(),
            request.at.trim().to_string(),
        ];
        run_once(&python, &root, "phase0/registry/cli.py", &args)
    })
    .await
    .map_err(|e| format!("registry_register 线程异常：{e}"))?
}

#[tauri::command]
async fn registry_verify(request: VerifyRequest) -> Result<Outcome, String> {
    tauri::async_runtime::spawn_blocking(move || {
        if !is_iso_at(request.at.trim()) {
            return Err("--at 必须是 ISO-8601 UTC 时刻，且带 Z（如 2026-11-08T09:05:00Z）".into());
        }
        require_non_empty(&request.ledger, "账本路径")?;
        let root = repo_root()?;
        let python = python_binary(request.python_path)?;
        let ledger = resolve_path(&request.ledger)?;
        let mut args: Vec<String> = vec![
            "--ledger".into(),
            ledger.to_string_lossy().to_string(),
            "verify".into(),
            "--at".into(),
            request.at.trim().to_string(),
        ];
        if let Some(id) = request.id.as_deref().map(str::trim).filter(|s| !s.is_empty()) {
            args.push("--id".into());
            args.push(id.to_string());
        }
        run_once(&python, &root, "phase0/registry/cli.py", &args)
    })
    .await
    .map_err(|e| format!("registry_verify 线程异常：{e}"))?
}

#[tauri::command]
async fn registry_list(request: LedgerRequest) -> Result<Outcome, String> {
    tauri::async_runtime::spawn_blocking(move || {
        require_non_empty(&request.ledger, "账本路径")?;
        let root = repo_root()?;
        let python = python_binary(request.python_path)?;
        let ledger = resolve_path(&request.ledger)?;
        let args: Vec<String> = vec![
            "--ledger".into(),
            ledger.to_string_lossy().to_string(),
            "list".into(),
        ];
        run_once(&python, &root, "phase0/registry/cli.py", &args)
    })
    .await
    .map_err(|e| format!("registry_list 线程异常：{e}"))?
}

#[tauri::command]
async fn registry_chain_check(request: LedgerRequest) -> Result<Outcome, String> {
    tauri::async_runtime::spawn_blocking(move || {
        require_non_empty(&request.ledger, "账本路径")?;
        let root = repo_root()?;
        let python = python_binary(request.python_path)?;
        let ledger = resolve_path(&request.ledger)?;
        let args: Vec<String> = vec![
            "--ledger".into(),
            ledger.to_string_lossy().to_string(),
            "chain-check".into(),
        ];
        run_once(&python, &root, "phase0/registry/cli.py", &args)
    })
    .await
    .map_err(|e| format!("registry_chain_check 线程异常：{e}"))?
}

#[tauri::command]
async fn registry_reconcile(request: LedgerRequest) -> Result<Outcome, String> {
    tauri::async_runtime::spawn_blocking(move || {
        require_non_empty(&request.ledger, "账本路径")?;
        let root = repo_root()?;
        let python = python_binary(request.python_path)?;
        let ledger = resolve_path(&request.ledger)?;
        let args: Vec<String> = vec![
            "--ledger".into(),
            ledger.to_string_lossy().to_string(),
            "reconcile".into(),
            "--json".into(),
        ];
        run_once(&python, &root, "phase0/registry/cli.py", &args)
    })
    .await
    .map_err(|e| format!("registry_reconcile 线程异常：{e}"))?
}

fn main() {
    tauri::Builder::default()
        .invoke_handler(tauri::generate_handler![
            run_timeline,
            registry_register,
            registry_verify,
            registry_list,
            registry_chain_check,
            registry_reconcile
        ])
        .run(tauri::generate_context!())
        .expect("桌面壳启动失败");
}
