use reqwest::blocking::{Client, Response};
use semver::Version;
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::fs::{self, File, OpenOptions};
use std::io::{self, Read, Write};
use std::path::{Path, PathBuf};
use std::process::Command;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::time::Duration;
use tauri::{AppHandle, Emitter, State};

const RELEASE_API_URL: &str =
    "https://api.github.com/repos/bluntvoice/wechat-chat-summary/releases/latest";
const RELEASE_PAGE_PREFIX: &str = "https://github.com/bluntvoice/wechat-chat-summary/releases/tag/";
const USER_AGENT: &str = "wechat-chat-summary-updater";
const MAX_CHECKSUM_BYTES: u64 = 64 * 1024;
const MAX_INSTALLER_BYTES: u64 = 1024 * 1024 * 1024;
const CHECK_TIMEOUT: Duration = Duration::from_secs(30);
const DOWNLOAD_TIMEOUT: Duration = Duration::from_secs(30 * 60);

#[derive(Clone, Debug, Deserialize)]
struct GitHubAsset {
    name: String,
    browser_download_url: String,
    size: u64,
    state: String,
}

#[derive(Clone, Debug, Deserialize)]
struct GitHubRelease {
    tag_name: String,
    html_url: String,
    body: Option<String>,
    published_at: Option<String>,
    draft: bool,
    prerelease: bool,
    assets: Vec<GitHubAsset>,
}

#[derive(Clone, Debug)]
struct AvailableUpdate {
    version: String,
    release_url: String,
    installer: GitHubAsset,
    checksum: GitHubAsset,
}

#[derive(Clone, Debug)]
struct VerifiedUpdate {
    version: String,
    installer_path: PathBuf,
    sha256: String,
    bytes: u64,
}

#[derive(Default)]
struct UpdateInner {
    available: Mutex<Option<AvailableUpdate>>,
    verified: Mutex<Option<VerifiedUpdate>>,
    cancel_requested: AtomicBool,
    downloading: AtomicBool,
}

#[derive(Clone, Default)]
pub struct UpdateProcessState {
    inner: Arc<UpdateInner>,
}

#[derive(Clone, Debug, Serialize)]
pub struct UpdateCheckResult {
    status: String,
    current_version: String,
    latest_version: String,
    release_url: String,
    published_at: Option<String>,
    notes_summary: String,
    installer_size: Option<u64>,
}

#[derive(Clone, Debug, Serialize)]
pub struct DownloadProgress {
    downloaded_bytes: u64,
    total_bytes: Option<u64>,
    percent: Option<u8>,
}

#[derive(Clone, Debug, Serialize)]
pub struct DownloadResult {
    version: String,
    bytes: u64,
    sha256: String,
}

struct DownloadGuard {
    inner: Arc<UpdateInner>,
}

impl Drop for DownloadGuard {
    fn drop(&mut self) {
        self.inner.downloading.store(false, Ordering::SeqCst);
    }
}

fn http_client(timeout: Duration) -> Result<Client, String> {
    Client::builder()
        .user_agent(USER_AGENT)
        .connect_timeout(Duration::from_secs(10))
        .timeout(timeout)
        .redirect(reqwest::redirect::Policy::custom(|attempt| {
            const ALLOWED_HOSTS: [&str; 4] = [
                "api.github.com",
                "github.com",
                "objects.githubusercontent.com",
                "release-assets.githubusercontent.com",
            ];
            if attempt.previous().len() >= 5 {
                return attempt.error("too many redirects");
            }
            let target = attempt.url();
            if target.scheme() == "https"
                && target
                    .host_str()
                    .is_some_and(|host| ALLOWED_HOSTS.contains(&host))
            {
                attempt.follow()
            } else {
                attempt.stop()
            }
        }))
        .build()
        .map_err(|error| format!("无法初始化更新连接: {error}"))
}

fn parse_release_version(tag_name: &str) -> Result<Version, String> {
    let value = tag_name
        .strip_prefix('v')
        .ok_or_else(|| "Stable Release Tag 必须使用 vX.Y.Z。".to_string())?;
    let version =
        Version::parse(value).map_err(|_| "Stable Release 版本号格式无效。".to_string())?;
    if !version.pre.is_empty() {
        return Err("普通更新通道不接受预发布版本。".to_string());
    }
    Ok(version)
}

fn exact_asset(assets: &[GitHubAsset], name: &str) -> Result<GitHubAsset, String> {
    let matches = assets
        .iter()
        .filter(|asset| asset.name == name && asset.state == "uploaded")
        .cloned()
        .collect::<Vec<_>>();
    match matches.as_slice() {
        [asset] => Ok(asset.clone()),
        [] => Err(format!("Release 缺少正式更新资产: {name}")),
        _ => Err(format!("Release 包含重复更新资产: {name}")),
    }
}

fn summarize_release_notes(body: Option<&str>) -> String {
    let mut summary = String::new();
    for raw_line in body.unwrap_or_default().lines() {
        let line = raw_line
            .trim()
            .trim_start_matches('#')
            .trim_start_matches(['-', '*'])
            .trim();
        if line.is_empty() {
            continue;
        }
        if !summary.is_empty() {
            summary.push_str(" · ");
        }
        summary.push_str(line);
        if summary.chars().count() >= 280 {
            break;
        }
    }
    if summary.is_empty() {
        return "本次 Release 未提供简短更新说明。".to_string();
    }
    let shortened = summary.chars().take(280).collect::<String>();
    if summary.chars().count() > 280 {
        format!("{shortened}…")
    } else {
        shortened
    }
}

fn resolve_release(
    release: GitHubRelease,
    current_version: &str,
) -> Result<(UpdateCheckResult, Option<AvailableUpdate>), String> {
    if release.draft || release.prerelease {
        return Err("普通更新通道只接受已发布的 Stable Release。".to_string());
    }
    let current = Version::parse(current_version)
        .map_err(|_| "当前应用版本不是有效的语义化版本。".to_string())?;
    let remote = parse_release_version(&release.tag_name)?;
    validate_release_page_url(&release.html_url, &remote.to_string())?;
    let latest_version = remote.to_string();
    let notes_summary = summarize_release_notes(release.body.as_deref());
    let base = UpdateCheckResult {
        status: "latest".to_string(),
        current_version: current.to_string(),
        latest_version: latest_version.clone(),
        release_url: release.html_url.clone(),
        published_at: release.published_at.clone(),
        notes_summary: notes_summary.clone(),
        installer_size: None,
    };
    if remote <= current {
        return Ok((base, None));
    }

    let installer_name = format!("WeChat-Chat-Summary_{latest_version}_x64-setup.exe");
    let checksum_name = format!("{installer_name}.sha256");
    let installer = exact_asset(&release.assets, &installer_name)?;
    if installer.size == 0 || installer.size > MAX_INSTALLER_BYTES {
        return Err("Release 安装包大小无效。".to_string());
    }
    let checksum = exact_asset(&release.assets, &checksum_name)?;
    if checksum.size == 0 || checksum.size > MAX_CHECKSUM_BYTES {
        return Err("Release SHA-256 文件大小无效。".to_string());
    }
    let available = AvailableUpdate {
        version: latest_version.clone(),
        release_url: release.html_url.clone(),
        installer: installer.clone(),
        checksum,
    };
    Ok((
        UpdateCheckResult {
            status: "available".to_string(),
            installer_size: Some(installer.size),
            ..base
        },
        Some(available),
    ))
}

fn fetch_latest_release(client: &Client) -> Result<GitHubRelease, String> {
    let response = client
        .get(RELEASE_API_URL)
        .header("Accept", "application/vnd.github+json")
        .header("X-GitHub-Api-Version", "2022-11-28")
        .send()
        .map_err(|_| "无法连接 GitHub，请检查网络后重试。".to_string())?;
    if response.status().as_u16() == 404 {
        return Err("项目暂未发布可用的 Stable Release。".to_string());
    }
    if response.status().as_u16() == 403 || response.status().as_u16() == 429 {
        return Err("GitHub 暂时限制了更新检查，请稍后重试。".to_string());
    }
    response
        .error_for_status()
        .map_err(|_| "GitHub 更新服务暂时不可用。".to_string())?
        .json::<GitHubRelease>()
        .map_err(|_| "GitHub Release 数据格式无效。".to_string())
}

fn check_update_inner(
    inner: &Arc<UpdateInner>,
    current_version: &str,
) -> Result<UpdateCheckResult, String> {
    if inner.downloading.load(Ordering::SeqCst) {
        return Err("更新正在下载，请稍后再检查。".to_string());
    }
    *inner
        .available
        .lock()
        .map_err(|_| "更新状态锁已损坏。".to_string())? = None;
    *inner
        .verified
        .lock()
        .map_err(|_| "更新状态锁已损坏。".to_string())? = None;
    let release = fetch_latest_release(&http_client(CHECK_TIMEOUT)?)?;
    let (result, available) = resolve_release(release, current_version)?;
    *inner
        .available
        .lock()
        .map_err(|_| "更新状态锁已损坏。".to_string())? = available;
    Ok(result)
}

fn validate_release_page_url(value: &str, version: &str) -> Result<(), String> {
    let parsed = reqwest::Url::parse(value).map_err(|_| "Release 页面地址无效。".to_string())?;
    let expected_path = format!("/bluntvoice/wechat-chat-summary/releases/tag/v{version}");
    if parsed.scheme() != "https"
        || parsed.host_str() != Some("github.com")
        || parsed.path() != expected_path
        || parsed.port().is_some()
        || parsed.username() != ""
        || parsed.password().is_some()
        || parsed.query().is_some()
        || parsed.fragment().is_some()
    {
        return Err("Release 页面地址不属于官方仓库。".to_string());
    }
    Ok(())
}

fn validate_download_url(value: &str, version: &str, asset_name: &str) -> Result<(), String> {
    let parsed = reqwest::Url::parse(value).map_err(|_| "Release 下载地址无效。".to_string())?;
    let expected_path =
        format!("/bluntvoice/wechat-chat-summary/releases/download/v{version}/{asset_name}");
    if parsed.scheme() != "https"
        || parsed.host_str() != Some("github.com")
        || parsed.path() != expected_path
        || parsed.port().is_some()
        || parsed.username() != ""
        || parsed.password().is_some()
        || parsed.query().is_some()
        || parsed.fragment().is_some()
    {
        return Err("Release 下载地址不属于官方仓库。".to_string());
    }
    Ok(())
}

fn read_small_text(mut response: Response) -> Result<String, String> {
    response = response
        .error_for_status()
        .map_err(|_| "无法下载官方 SHA-256 文件。".to_string())?;
    if response.content_length().unwrap_or(0) > MAX_CHECKSUM_BYTES {
        return Err("SHA-256 文件异常过大。".to_string());
    }
    let mut bytes = Vec::new();
    response
        .take(MAX_CHECKSUM_BYTES + 1)
        .read_to_end(&mut bytes)
        .map_err(|_| "SHA-256 文件下载中断。".to_string())?;
    if bytes.len() as u64 > MAX_CHECKSUM_BYTES {
        return Err("SHA-256 文件异常过大。".to_string());
    }
    String::from_utf8(bytes).map_err(|_| "SHA-256 文件不是 UTF-8 文本。".to_string())
}

fn parse_checksum(text: &str, installer_name: &str) -> Result<String, String> {
    let lines = text
        .lines()
        .filter(|line| !line.trim().is_empty())
        .collect::<Vec<_>>();
    if lines.len() != 1 {
        return Err("SHA-256 文件格式异常。".to_string());
    }
    let parts = lines[0].split_whitespace().collect::<Vec<_>>();
    if parts.len() != 2 || parts[1].trim_start_matches('*') != installer_name {
        return Err("SHA-256 文件与安装包名称不匹配。".to_string());
    }
    let hash = parts[0];
    if hash.len() != 64 || !hash.bytes().all(|byte| byte.is_ascii_hexdigit()) {
        return Err("SHA-256 文件格式异常。".to_string());
    }
    Ok(hash.to_ascii_lowercase())
}

fn hash_hex(hasher: Sha256) -> String {
    hasher
        .finalize()
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect()
}

fn verify_hash(expected: &str, actual: &str) -> Result<(), String> {
    if expected == actual {
        Ok(())
    } else {
        Err("安装包完整性校验失败，请重新下载。".to_string())
    }
}

fn copy_download<R: Read, W: Write>(
    reader: &mut R,
    writer: &mut W,
    expected_total: Option<u64>,
    cancel_requested: &AtomicBool,
    mut progress: impl FnMut(DownloadProgress),
) -> Result<(u64, String), String> {
    let mut buffer = vec![0_u8; 128 * 1024];
    let mut downloaded = 0_u64;
    let mut hasher = Sha256::new();
    progress(DownloadProgress {
        downloaded_bytes: 0,
        total_bytes: expected_total,
        percent: expected_total.map(|_| 0),
    });
    loop {
        if cancel_requested.load(Ordering::SeqCst) {
            return Err("用户已取消更新下载。".to_string());
        }
        let count = reader
            .read(&mut buffer)
            .map_err(|_| "安装包下载中断，请重新下载。".to_string())?;
        if count == 0 {
            break;
        }
        writer
            .write_all(&buffer[..count])
            .map_err(|_| "无法写入更新临时目录，请检查磁盘空间和目录权限。".to_string())?;
        hasher.update(&buffer[..count]);
        downloaded += count as u64;
        if downloaded > MAX_INSTALLER_BYTES {
            return Err("安装包超过允许的大小。".to_string());
        }
        let percent = expected_total
            .filter(|total| *total > 0)
            .map(|total| ((downloaded.saturating_mul(100) / total).min(100)) as u8);
        progress(DownloadProgress {
            downloaded_bytes: downloaded,
            total_bytes: expected_total,
            percent,
        });
    }
    if let Some(total) = expected_total {
        if downloaded != total {
            return Err("安装包下载不完整，请重新下载。".to_string());
        }
    }
    writer
        .flush()
        .map_err(|_| "无法完成更新文件写入。".to_string())?;
    Ok((downloaded, hash_hex(hasher)))
}

fn update_temp_root() -> PathBuf {
    std::env::temp_dir().join("wechat-chat-summary-update")
}

fn safe_version_dir(version: &str) -> Result<PathBuf, String> {
    let parsed = Version::parse(version).map_err(|_| "更新版本号无效。".to_string())?;
    if !parsed.pre.is_empty() {
        return Err("普通更新通道不接受预发布版本。".to_string());
    }
    Ok(update_temp_root().join(parsed.to_string()))
}

fn prepare_target_dir(version: &str) -> Result<PathBuf, String> {
    let root = update_temp_root();
    fs::create_dir_all(&root).map_err(|_| "系统更新临时目录不可写。".to_string())?;
    let root_metadata =
        fs::symlink_metadata(&root).map_err(|_| "无法校验系统更新临时目录。".to_string())?;
    if !root_metadata.is_dir() || root_metadata.file_type().is_symlink() {
        return Err("系统更新临时目录不安全。".to_string());
    }

    let target = safe_version_dir(version)?;
    if target.exists() {
        let metadata =
            fs::symlink_metadata(&target).map_err(|_| "无法校验更新临时目录。".to_string())?;
        if !metadata.is_dir() || metadata.file_type().is_symlink() {
            return Err("更新临时目录不安全。".to_string());
        }
    } else {
        fs::create_dir(&target).map_err(|_| "系统更新临时目录不可写。".to_string())?;
    }

    let canonical_root =
        fs::canonicalize(&root).map_err(|_| "无法校验系统更新临时目录。".to_string())?;
    let canonical_target =
        fs::canonicalize(&target).map_err(|_| "无法校验更新临时目录。".to_string())?;
    if canonical_target.parent() != Some(canonical_root.as_path()) {
        return Err("更新临时目录超出允许范围。".to_string());
    }
    Ok(target)
}

fn remove_owned_file(path: &Path) -> Result<(), String> {
    match fs::symlink_metadata(path) {
        Ok(metadata) if metadata.is_file() || metadata.file_type().is_symlink() => {
            fs::remove_file(path).map_err(|_| "无法清理旧的更新临时文件。".to_string())
        }
        Ok(_) => Err("更新临时文件路径类型异常。".to_string()),
        Err(error) if error.kind() == io::ErrorKind::NotFound => Ok(()),
        Err(_) => Err("无法检查更新临时文件。".to_string()),
    }
}

fn cleanup_owned_files(target_dir: &Path, paths: &[&Path]) {
    for path in paths {
        let _ = remove_owned_file(path);
    }
    let _ = fs::remove_dir(target_dir);
}

fn open_download(client: &Client, asset: &GitHubAsset) -> Result<Response, String> {
    client
        .get(&asset.browser_download_url)
        .send()
        .map_err(|_| "无法连接 GitHub 下载更新。".to_string())?
        .error_for_status()
        .map_err(|_| "GitHub 更新资产下载失败。".to_string())
}

fn download_update_inner(
    app: &AppHandle,
    inner: Arc<UpdateInner>,
) -> Result<DownloadResult, String> {
    if inner.downloading.swap(true, Ordering::SeqCst) {
        return Err("更新正在下载，请勿重复操作。".to_string());
    }
    let _guard = DownloadGuard {
        inner: inner.clone(),
    };
    inner.cancel_requested.store(false, Ordering::SeqCst);
    let update = inner
        .available
        .lock()
        .map_err(|_| "更新状态锁已损坏。".to_string())?
        .clone()
        .ok_or_else(|| "请先检查更新。".to_string())?;
    validate_download_url(
        &update.installer.browser_download_url,
        &update.version,
        &update.installer.name,
    )?;
    validate_download_url(
        &update.checksum.browser_download_url,
        &update.version,
        &update.checksum.name,
    )?;

    let target_dir = prepare_target_dir(&update.version)?;

    let client = http_client(DOWNLOAD_TIMEOUT)?;
    let checksum_text = read_small_text(open_download(&client, &update.checksum)?)?;
    let expected_hash = parse_checksum(&checksum_text, &update.installer.name)?;
    let part_path = target_dir.join(format!("{}.part", update.installer.name));
    let installer_path = target_dir.join(&update.installer.name);
    remove_owned_file(&part_path)?;
    remove_owned_file(&installer_path)?;
    let result = (|| {
        let mut response = open_download(&client, &update.installer)?;
        let content_length = response.content_length();
        if content_length.unwrap_or(update.installer.size) > MAX_INSTALLER_BYTES {
            return Err("安装包超过允许的大小。".to_string());
        }
        let mut output = OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&part_path)
            .map_err(|_| "系统更新临时目录不可写。".to_string())?;
        let (bytes, actual_hash) = copy_download(
            &mut response,
            &mut output,
            content_length,
            &inner.cancel_requested,
            |payload| {
                let _ = app.emit("update-download-progress", payload);
            },
        )?;
        verify_hash(&expected_hash, &actual_hash)?;
        fs::rename(&part_path, &installer_path)
            .map_err(|_| "无法完成更新临时文件写入。".to_string())?;
        Ok((bytes, actual_hash))
    })();
    let (bytes, actual_hash) = match result {
        Ok(value) => value,
        Err(error) => {
            cleanup_owned_files(&target_dir, &[&part_path, &installer_path]);
            return Err(error);
        }
    };
    *inner
        .verified
        .lock()
        .map_err(|_| "更新状态锁已损坏。".to_string())? = Some(VerifiedUpdate {
        version: update.version.clone(),
        installer_path,
        sha256: actual_hash.clone(),
        bytes,
    });
    Ok(DownloadResult {
        version: update.version,
        bytes,
        sha256: actual_hash,
    })
}

fn sha256_file(path: &Path) -> Result<String, String> {
    let mut file =
        File::open(path).map_err(|_| "已校验的安装包不存在，请重新下载。".to_string())?;
    let mut hasher = Sha256::new();
    let mut buffer = vec![0_u8; 128 * 1024];
    loop {
        let count = file
            .read(&mut buffer)
            .map_err(|_| "无法重新校验安装包。".to_string())?;
        if count == 0 {
            break;
        }
        hasher.update(&buffer[..count]);
    }
    Ok(hash_hex(hasher))
}

fn validate_verified_installer(verified: &VerifiedUpdate) -> Result<(), String> {
    let expected_dir = prepare_target_dir(&verified.version)?;
    let metadata = fs::symlink_metadata(&verified.installer_path)
        .map_err(|_| "已校验的安装包不存在，请重新下载。".to_string())?;
    if verified.installer_path.parent() != Some(expected_dir.as_path())
        || !metadata.is_file()
        || metadata.file_type().is_symlink()
        || metadata.len() != verified.bytes
    {
        return Err("安装包完整性校验失败，请重新下载。".to_string());
    }
    let canonical_dir =
        fs::canonicalize(&expected_dir).map_err(|_| "无法重新校验安装包目录。".to_string())?;
    let canonical_installer = fs::canonicalize(&verified.installer_path)
        .map_err(|_| "无法重新校验安装包。".to_string())?;
    if canonical_installer.parent() != Some(canonical_dir.as_path()) {
        return Err("安装包完整性校验失败，请重新下载。".to_string());
    }
    verify_hash(&verified.sha256, &sha256_file(&verified.installer_path)?)
}

fn launch_and_exit(
    spawn_installer: impl FnOnce() -> io::Result<()>,
    exit_app: impl FnOnce(),
) -> Result<(), String> {
    spawn_installer().map_err(|_| "安装程序启动失败，软件将继续运行。".to_string())?;
    exit_app();
    Ok(())
}

#[tauri::command]
pub async fn check_update(
    app: AppHandle,
    state: State<'_, UpdateProcessState>,
) -> Result<UpdateCheckResult, String> {
    let current_version = app.package_info().version.to_string();
    let inner = state.inner.clone();
    tauri::async_runtime::spawn_blocking(move || check_update_inner(&inner, &current_version))
        .await
        .map_err(|_| "检查更新任务异常结束。".to_string())?
}

#[tauri::command]
pub async fn download_update(
    app: AppHandle,
    state: State<'_, UpdateProcessState>,
) -> Result<DownloadResult, String> {
    let inner = state.inner.clone();
    tauri::async_runtime::spawn_blocking(move || download_update_inner(&app, inner))
        .await
        .map_err(|_| "更新下载任务异常结束。".to_string())?
}

#[tauri::command]
pub fn cancel_update(state: State<'_, UpdateProcessState>) {
    state.inner.cancel_requested.store(true, Ordering::SeqCst);
}

#[tauri::command]
pub fn open_release_page(url: String, state: State<'_, UpdateProcessState>) -> Result<(), String> {
    let available = state
        .inner
        .available
        .lock()
        .map_err(|_| "更新状态锁已损坏。".to_string())?
        .clone()
        .ok_or_else(|| "请先检查更新。".to_string())?;
    validate_release_page_url(&url, &available.version)?;
    if url != available.release_url || !url.starts_with(RELEASE_PAGE_PREFIX) {
        return Err("Release 页面地址无效。".to_string());
    }
    open::that_detached(url).map_err(|_| "无法打开 GitHub Release 页面。".to_string())
}

#[tauri::command]
pub fn launch_verified_update(
    app: AppHandle,
    state: State<'_, UpdateProcessState>,
) -> Result<(), String> {
    let verified = state
        .inner
        .verified
        .lock()
        .map_err(|_| "更新状态锁已损坏。".to_string())?
        .clone()
        .ok_or_else(|| "请先下载并校验更新。".to_string())?;
    if verified.bytes == 0 {
        return Err("安装包完整性校验失败，请重新下载。".to_string());
    }
    validate_verified_installer(&verified)?;
    let path = verified.installer_path.clone();
    launch_and_exit(
        move || Command::new(path).spawn().map(|_| ()),
        move || app.exit(0),
    )
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::cell::Cell;
    use std::io::Cursor;

    fn asset(name: &str, version: &str, size: u64) -> GitHubAsset {
        GitHubAsset {
            name: name.to_string(),
            browser_download_url: format!(
                "https://github.com/bluntvoice/wechat-chat-summary/releases/download/v{version}/{name}"
            ),
            size,
            state: "uploaded".to_string(),
        }
    }

    fn release(version: &str) -> GitHubRelease {
        let installer = format!("WeChat-Chat-Summary_{version}_x64-setup.exe");
        GitHubRelease {
            tag_name: format!("v{version}"),
            html_url: format!(
                "https://github.com/bluntvoice/wechat-chat-summary/releases/tag/v{version}"
            ),
            body: Some("## 版本亮点\n\n- 新增更新闭环".to_string()),
            published_at: Some("2026-09-02T00:00:00Z".to_string()),
            draft: false,
            prerelease: false,
            assets: vec![
                asset(&installer, version, 10_000),
                asset(&format!("{installer}.sha256"), version, 128),
                asset("portable.exe", version, 999),
            ],
        }
    }

    #[test]
    fn semver_comparison_handles_double_digit_minor_and_no_downgrade() {
        assert_eq!(
            resolve_release(release("1.10.0"), "1.9.0")
                .unwrap()
                .0
                .status,
            "available"
        );
        assert_eq!(
            resolve_release(release("1.9.0"), "1.10.0")
                .unwrap()
                .0
                .status,
            "latest"
        );
        assert_eq!(
            resolve_release(release("1.10.0"), "1.10.0")
                .unwrap()
                .0
                .status,
            "latest"
        );
    }

    #[test]
    fn draft_and_prerelease_are_rejected() {
        let mut draft = release("1.0.0");
        draft.draft = true;
        assert!(resolve_release(draft, "0.9.0").is_err());
        let mut prerelease = release("1.0.0");
        prerelease.prerelease = true;
        assert!(resolve_release(prerelease, "0.9.0").is_err());
        assert!(parse_release_version("v1.0.0-rc.1").is_err());
    }

    #[test]
    fn installer_selection_requires_exact_unique_assets() {
        let mut missing = release("1.0.0");
        missing.assets.clear();
        assert!(resolve_release(missing, "0.9.0").is_err());

        let mut missing_checksum = release("1.0.0");
        missing_checksum
            .assets
            .retain(|asset| !asset.name.ends_with(".sha256"));
        assert!(resolve_release(missing_checksum, "0.9.0").is_err());

        let mut duplicated = release("1.0.0");
        duplicated.assets.push(duplicated.assets[0].clone());
        assert!(resolve_release(duplicated, "0.9.0").is_err());
        let resolved = resolve_release(release("1.0.0"), "0.9.0")
            .unwrap()
            .1
            .unwrap();
        assert_eq!(
            resolved.installer.name,
            "WeChat-Chat-Summary_1.0.0_x64-setup.exe"
        );
    }

    #[test]
    fn checksum_parser_accepts_current_release_format_only() {
        let name = "WeChat-Chat-Summary_1.0.0_x64-setup.exe";
        let hash = "a".repeat(64);
        assert_eq!(
            parse_checksum(&format!("{hash}  {name}"), name).unwrap(),
            hash
        );
        assert!(parse_checksum("invalid", name).is_err());
        assert!(parse_checksum(&format!("{}  other.exe", "a".repeat(64)), name).is_err());
    }

    #[test]
    fn sha256_mismatch_blocks_the_installer() {
        let hash = "a".repeat(64);
        assert!(verify_hash(&hash, &hash).is_ok());
        assert_eq!(
            verify_hash(&hash, &"b".repeat(64)).unwrap_err(),
            "安装包完整性校验失败，请重新下载。"
        );
    }

    #[test]
    fn release_urls_are_restricted_to_the_exact_official_paths() {
        let version = "1.2.3";
        let name = "WeChat-Chat-Summary_1.2.3_x64-setup.exe";
        assert!(validate_release_page_url(
            "https://github.com/bluntvoice/wechat-chat-summary/releases/tag/v1.2.3",
            version,
        )
        .is_ok());
        assert!(validate_release_page_url(
            "https://github.com/bluntvoice/wechat-chat-summary/releases/tag/v1.2.3?next=evil",
            version,
        )
        .is_err());
        assert!(validate_download_url(
            &format!(
                "https://github.com/bluntvoice/wechat-chat-summary/releases/download/v{version}/{name}"
            ),
            version,
            name,
        )
        .is_ok());
        assert!(
            validate_download_url("https://example.com/installer.exe", version, name,).is_err()
        );
    }

    #[test]
    fn download_copy_reports_real_progress_with_and_without_total() {
        let payload = b"installer-bytes";
        let cancel = AtomicBool::new(false);
        let mut progress = Vec::new();
        let mut output = Vec::new();
        let (bytes, _) = copy_download(
            &mut Cursor::new(payload),
            &mut output,
            Some(payload.len() as u64),
            &cancel,
            |item| progress.push(item),
        )
        .unwrap();
        assert_eq!(bytes, payload.len() as u64);
        assert_eq!(progress.last().unwrap().percent, Some(100));

        progress.clear();
        output.clear();
        copy_download(
            &mut Cursor::new(payload),
            &mut output,
            None,
            &cancel,
            |item| progress.push(item),
        )
        .unwrap();
        assert_eq!(progress.last().unwrap().percent, None);
    }

    struct InterruptedReader {
        sent: bool,
    }

    impl Read for InterruptedReader {
        fn read(&mut self, buffer: &mut [u8]) -> io::Result<usize> {
            if self.sent {
                return Err(io::Error::new(io::ErrorKind::UnexpectedEof, "interrupted"));
            }
            self.sent = true;
            buffer[..4].copy_from_slice(b"part");
            Ok(4)
        }
    }

    #[test]
    fn interrupted_and_cancelled_downloads_fail() {
        let cancel = AtomicBool::new(false);
        assert!(copy_download(
            &mut InterruptedReader { sent: false },
            &mut Vec::new(),
            None,
            &cancel,
            |_| {},
        )
        .is_err());
        cancel.store(true, Ordering::SeqCst);
        assert!(copy_download(
            &mut Cursor::new(b"data"),
            &mut Vec::new(),
            None,
            &cancel,
            |_| {},
        )
        .is_err());
    }

    #[test]
    fn update_files_use_the_system_temporary_directory() {
        let target = safe_version_dir("1.2.3").unwrap();
        assert!(target.starts_with(std::env::temp_dir()));
        assert!(target.ends_with(Path::new("wechat-chat-summary-update").join("1.2.3")));
    }

    #[test]
    fn application_exits_only_after_installer_spawn_succeeds() {
        let exited = Cell::new(false);
        let result = launch_and_exit(
            || Err(io::Error::new(io::ErrorKind::Other, "failed")),
            || exited.set(true),
        );
        assert!(result.is_err());
        assert!(!exited.get());

        launch_and_exit(|| Ok(()), || exited.set(true)).unwrap();
        assert!(exited.get());
    }
}
