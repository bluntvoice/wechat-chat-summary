import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { getVersion } from "@tauri-apps/api/app";
import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { Copy, Download, ExternalLink, RefreshCw, X } from "lucide-react";

import packageInfo from "../../package.json";
import { openExternalUrl } from "../services/desktopBridge";
import { parseReleaseNotes, type ReleaseNoteInline } from "../services/releaseNotes";
import {
  WECHAT_DATA_ANALYSIS_HOMEPAGE,
  WECHAT_DATA_ANALYSIS_RELEASES,
} from "../services/wechatDataSource";

const PROJECT_URL = "https://github.com/bluntvoice/wechat-chat-summary";
const appIcon = new URL("../../src-tauri/icons/icon.png", import.meta.url).href;

type UpdateStatus =
  | "idle"
  | "checking"
  | "latest"
  | "update_available"
  | "downloading"
  | "verifying"
  | "ready_to_install"
  | "installing"
  | "check_failed"
  | "download_failed"
  | "verify_failed"
  | "install_failed";

interface UpdateCheckResult {
  status: "latest" | "available";
  current_version: string;
  latest_version: string;
  current_channel: "stable" | "prerelease" | "test";
  latest_channel: "stable";
  release_url: string;
  published_at?: string | null;
  notes_summary: string;
  release_notes: string;
  installer_size?: number | null;
}

interface DownloadProgress {
  phase: "downloading" | "verifying";
  downloaded_bytes: number;
  total_bytes?: number | null;
  percent?: number | null;
}

interface DownloadResult {
  version: string;
  bytes: number;
  sha256: string;
}

function bytesLabel(bytes: number) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

function releaseDate(value?: string | null) {
  if (!value) return "发布时间未知";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "发布时间未知";
  return new Intl.DateTimeFormat("zh-CN", { year: "numeric", month: "2-digit", day: "2-digit" }).format(date);
}

function channelLabel(channel?: string) {
  if (channel === "test") return "测试版";
  if (channel === "prerelease") return "预发布版";
  return "正式版";
}

function renderInline(parts: ReleaseNoteInline[]): ReactNode {
  return parts.map((part, index) => part.kind === "strong"
    ? <strong key={index}>{part.text}</strong>
    : <span key={index}>{part.text}</span>);
}

function ReleaseNotes({ value }: { value: string }) {
  const blocks = useMemo(() => parseReleaseNotes(value), [value]);
  if (!blocks.length) return <p>本次 Release 未提供更新说明。</p>;
  return <div className="update-release-notes">
    {blocks.map((block, index) => {
      if (block.kind === "heading") return <h4 className={`level-${block.level}`} key={index}>{renderInline(block.content)}</h4>;
      if (block.kind === "paragraph") return <p key={index}>{renderInline(block.content)}</p>;
      const List = block.kind === "ordered-list" ? "ol" : "ul";
      return <List key={index}>{block.items.map((item, itemIndex) => <li key={itemIndex}>{renderInline(item)}</li>)}</List>;
    })}
  </div>;
}

function isVerifyFailure(error: unknown) {
  return /完整性|SHA-256|校验/.test(String(error ?? ""));
}

export default function AboutPage() {
  const [version, setVersion] = useState(packageInfo.version);
  const [copyState, setCopyState] = useState("复制项目地址");
  const [updateStatus, setUpdateStatus] = useState<UpdateStatus>("idle");
  const [update, setUpdate] = useState<UpdateCheckResult | null>(null);
  const [progress, setProgress] = useState<DownloadProgress | null>(null);
  const [verified, setVerified] = useState<DownloadResult | null>(null);
  const [message, setMessage] = useState("");
  const [errorDetail, setErrorDetail] = useState("");
  const [dataSourceMessage, setDataSourceMessage] = useState("");
  const [dialogOpen, setDialogOpen] = useState(false);
  const [confirmInstall, setConfirmInstall] = useState(false);
  const actionGuard = useRef(false);

  useEffect(() => {
    getVersion().then((runtimeVersion) => setVersion(runtimeVersion || packageInfo.version)).catch(() => {
      // 普通浏览器开发预览没有 Tauri runtime，使用 package.json 构建版本。
    });
  }, []);

  useEffect(() => {
    let unlisten: (() => void) | undefined;
    void listen<DownloadProgress>("update-download-progress", (event) => {
      setProgress(event.payload);
      setUpdateStatus(event.payload.phase === "verifying" ? "verifying" : "downloading");
    }).then((dispose) => { unlisten = dispose; }).catch(() => {
      // 浏览器预览没有 Tauri event runtime。
    });
    return () => unlisten?.();
  }, []);

  async function copyProjectUrl() {
    try {
      await navigator.clipboard.writeText(PROJECT_URL);
      setCopyState("已复制");
      window.setTimeout(() => setCopyState("复制项目地址"), 1600);
    } catch {
      setCopyState("复制失败");
    }
  }

  async function openDataSourceLink(url: string) {
    try {
      await openExternalUrl(url);
      setDataSourceMessage("");
    } catch (error) {
      setDataSourceMessage(`无法打开网页：${error instanceof Error ? error.message : String(error)}`);
    }
  }

  async function checkForUpdates() {
    if (actionGuard.current) return;
    actionGuard.current = true;
    setUpdateStatus("checking");
    setMessage("");
    setErrorDetail("");
    setUpdate(null);
    setVerified(null);
    setProgress(null);
    setConfirmInstall(false);
    try {
      const result = await invoke<UpdateCheckResult>("check_update");
      setUpdate(result);
      setUpdateStatus(result.status === "available" ? "update_available" : "latest");
      setDialogOpen(result.status === "available");
    } catch (error) {
      setUpdateStatus("check_failed");
      setMessage("检查更新失败，可直接重新检查。");
      setErrorDetail(String(error ?? ""));
    } finally {
      actionGuard.current = false;
    }
  }

  async function downloadUpdate() {
    if (actionGuard.current || !update) return;
    actionGuard.current = true;
    setDialogOpen(true);
    setUpdateStatus("downloading");
    setMessage("");
    setErrorDetail("");
    setVerified(null);
    setConfirmInstall(false);
    setProgress({ phase: "downloading", downloaded_bytes: 0, total_bytes: null, percent: null });
    try {
      const result = await invoke<DownloadResult>("download_update");
      setVerified(result);
      setUpdateStatus("ready_to_install");
      setMessage("下载完成，并已通过 SHA-256 文件完整性校验。");
    } catch (error) {
      const detail = String(error ?? "");
      if (detail.includes("取消")) {
        setUpdateStatus("update_available");
        setMessage("已取消下载，可随时重新开始。");
      } else if (isVerifyFailure(error)) {
        setUpdateStatus("verify_failed");
        setMessage("安装包校验失败，损坏文件已废弃，请重新下载。");
      } else {
        setUpdateStatus("download_failed");
        setMessage("更新下载失败，已清理不完整文件，可直接重新下载。");
      }
      setErrorDetail(detail);
    } finally {
      actionGuard.current = false;
    }
  }

  async function cancelDownload() {
    await invoke("cancel_update").catch(() => undefined);
  }

  async function openReleasePage() {
    if (!update?.release_url) return;
    await invoke("open_release_page", { url: update.release_url }).catch((error) => {
      setMessage("无法打开 GitHub Release 页面。请稍后重试。");
      setErrorDetail(String(error ?? ""));
    });
  }

  async function launchInstaller() {
    if (actionGuard.current || !verified) return;
    actionGuard.current = true;
    setUpdateStatus("installing");
    setConfirmInstall(false);
    setMessage("正在启动已校验的安装程序…");
    setErrorDetail("");
    try {
      await invoke("launch_verified_update");
      setMessage("安装程序已启动，当前软件即将退出。");
    } catch (error) {
      const detail = String(error ?? "");
      if (isVerifyFailure(error) || /不存在|重新下载/.test(detail)) {
        setVerified(null);
        setUpdateStatus("verify_failed");
        setMessage("已校验安装包已失效，请重新下载。");
      } else {
        setUpdateStatus("install_failed");
        setMessage("安装程序启动失败；已校验安装包仍保留，可直接重新安装。");
      }
      setErrorDetail(detail);
    } finally {
      actionGuard.current = false;
    }
  }

  const busy = ["checking", "downloading", "verifying", "installing"].includes(updateStatus);
  const progressPercent = progress?.percent == null ? null : Math.max(0, Math.min(100, progress.percent));
  const updateTitle = updateStatus === "downloading" ? "正在下载更新"
    : updateStatus === "verifying" ? "正在校验安装包"
      : updateStatus === "ready_to_install" ? "已准备安装"
        : updateStatus === "installing" ? "正在启动安装程序"
          : updateStatus === "download_failed" ? "下载未完成"
            : updateStatus === "verify_failed" ? "校验未通过"
              : updateStatus === "install_failed" ? "安装程序未启动"
                : "发现可用更新";

  return <div className="workspace about-workspace">
    <header className="topbar about-topbar"><div><h1>关于</h1></div></header>
    <section className="about-identity" aria-labelledby="about-product-name"><div className="about-app-icon"><img src={appIcon} alt="" /></div><div className="about-product"><h2 id="about-product-name">群聊拾遗</h2><p>把本地微信群聊整理成可回顾、可检索、可长期保存的结构化总结。</p></div><div className="about-version"><small>当前版本</small><strong>v{version}</strong>{update?.current_channel && <span>{channelLabel(update.current_channel)}</span>}</div></section>
    <section className="about-row" aria-labelledby="project-heading"><div><p className="about-label">开源项目</p><h3 id="project-heading">bluntvoice/wechat-chat-summary</h3><p className="about-url">{PROJECT_URL}</p></div><button className="button secondary about-action" onClick={copyProjectUrl}><Copy size={15} aria-hidden="true" />{copyState}</button></section>
    <section className="about-row" aria-labelledby="data-source-heading"><div><p className="about-label">数据来源</p><h3 id="data-source-heading">WeChatDataAnalysis</h3><p>群聊拾遗通过 WeChatDataAnalysis 提供的本地 API 获取微信聊天数据。它是独立的开源项目，需要单独下载安装并运行。</p>{dataSourceMessage && <p className="about-error" role="status">{dataSourceMessage}</p>}</div><div className="about-source-actions"><button className="button ghost about-action" onClick={() => openDataSourceLink(WECHAT_DATA_ANALYSIS_HOMEPAGE)}><ExternalLink size={15} aria-hidden="true" />项目主页</button><button className="button secondary about-action" onClick={() => openDataSourceLink(WECHAT_DATA_ANALYSIS_RELEASES)}><Download size={15} aria-hidden="true" />下载最新版</button></div></section>

    <section className="about-row about-update" aria-labelledby="update-heading"><div className="about-update-main"><p className="about-label">软件更新</p><h3 id="update-heading">{updateStatus === "checking" ? "正在检查…" : updateStatus === "latest" ? "已是最新正式版本" : updateStatus === "check_failed" ? "检查更新失败" : update ? `v${update.latest_version} ${channelLabel(update.latest_channel)}` : "检查正式版本"}</h3>
      {updateStatus === "idle" && <p>仅在点击检查更新后访问本项目官方 GitHub Stable Release，不会在启动时或后台自动联网检查。</p>}
      {updateStatus === "checking" && <p>正在读取本项目官方 GitHub Releases。</p>}
      {updateStatus === "latest" && <p>当前构建无需更新；不会自动降级，也不会向普通通道推送预发布版本。</p>}
      {update && update.status === "available" && <p>{releaseDate(update.published_at)}{update.installer_size ? ` · 安装包 ${bytesLabel(update.installer_size)}` : ""} · {channelLabel(update.current_channel)}可更新至{channelLabel(update.latest_channel)}</p>}
      {message && <p className={updateStatus === "ready_to_install" ? "about-success" : "about-error"} role="status">{message}</p>}
      {errorDetail && <details className="update-error-detail"><summary>错误详情</summary><code>{errorDetail}</code></details>}
    </div><div className="about-update-actions">{(updateStatus === "idle" || updateStatus === "latest" || updateStatus === "check_failed") && <button className="button secondary about-action" disabled={busy} onClick={checkForUpdates}><RefreshCw size={15} aria-hidden="true" />{updateStatus === "check_failed" ? "重新检查" : "检查更新"}</button>}{updateStatus === "checking" && <button className="button secondary about-action" disabled><RefreshCw size={15} className="spinning" aria-hidden="true" />正在检查…</button>}{update && !["idle", "checking", "latest", "check_failed"].includes(updateStatus) && <button className="button secondary about-action" onClick={() => setDialogOpen(true)}>查看更新</button>}</div></section>

    <section className="about-notes" aria-label="隐私与许可"><div><p className="about-label">隐私</p><p>更新检查只读取官方 GitHub Release 信息，不上传聊天、API Key、历史数据库、报告或群聊名称。配置和历史使用 Windows 用户数据目录，报告保存在用户选择的位置。</p></div><div><p className="about-label">许可</p><p>项目当前未提供覆盖整个仓库的统一开源许可证。各第三方依赖继续遵循其各自许可证，当前 Windows 安装包尚未进行代码签名。</p></div></section>

    {dialogOpen && update && <div className="dialog-backdrop update-dialog-backdrop"><section className="update-dialog" role="dialog" aria-modal="true" aria-labelledby="update-dialog-title"><header><div><small>群聊拾遗软件更新</small><h2 id="update-dialog-title">{updateTitle}</h2><p>v{update.current_version} {channelLabel(update.current_channel)} → v{update.latest_version} {channelLabel(update.latest_channel)}</p></div><button className="update-dialog-close" aria-label="关闭更新窗口" disabled={busy} onClick={() => setDialogOpen(false)}><X size={18} /></button></header><div className="update-dialog-body">
      <div className="update-release-meta"><span>{releaseDate(update.published_at)}</span>{update.installer_size ? <span>安装包 {bytesLabel(update.installer_size)}</span> : null}<button onClick={openReleasePage}>在 GitHub 查看</button></div>
      <section className="update-notes-panel"><h3>更新内容</h3><ReleaseNotes value={update.release_notes} /></section>
      {["downloading", "verifying"].includes(updateStatus) && progress && <section className="update-download-state" aria-live="polite"><div className="update-progress-heading"><strong>{updateStatus === "verifying" ? "正在进行 SHA-256 校验" : "正在下载安装包"}</strong><span>{progressPercent == null ? "进行中" : `${progressPercent}%`}</span></div><div className="about-progress-track"><span style={{ width: progressPercent == null ? "100%" : `${progressPercent}%` }} className={progressPercent == null ? "indeterminate" : ""} /></div><p>{progress.total_bytes ? `${bytesLabel(progress.downloaded_bytes)} / ${bytesLabel(progress.total_bytes)}` : `已下载 ${bytesLabel(progress.downloaded_bytes)}`}</p></section>}
      {message && updateStatus !== "downloading" && updateStatus !== "verifying" && <div className={`update-stage-message status-${updateStatus}`}>{message}</div>}
      {errorDetail && ["download_failed", "verify_failed", "install_failed"].includes(updateStatus) && <details className="update-error-detail"><summary>错误详情</summary><code>{errorDetail}</code></details>}
      {confirmInstall && <div className="about-confirm" role="alert"><p>确认启动安装程序？安装程序成功启动后，当前软件才会退出。</p><div><button className="button primary about-action" onClick={launchInstaller}>确认更新</button><button className="button secondary about-action" onClick={() => setConfirmInstall(false)}>取消</button></div></div>}
    </div><footer>{updateStatus === "update_available" && <button className="button primary" onClick={downloadUpdate}>立即更新</button>}{updateStatus === "downloading" && <button className="button secondary" onClick={cancelDownload}>取消下载</button>}{updateStatus === "verifying" && <button className="button secondary" disabled>正在校验…</button>}{(updateStatus === "download_failed" || updateStatus === "verify_failed") && <button className="button primary" onClick={downloadUpdate}>重新下载</button>}{updateStatus === "ready_to_install" && !confirmInstall && <button className="button primary" onClick={() => setConfirmInstall(true)}>启动安装</button>}{updateStatus === "installing" && <button className="button secondary" disabled>正在启动…</button>}{updateStatus === "install_failed" && <button className="button primary" onClick={launchInstaller}>重新安装</button>}{!busy && <button className="button ghost" onClick={() => setDialogOpen(false)}>稍后处理</button>}</footer></section></div>}
  </div>;
}
