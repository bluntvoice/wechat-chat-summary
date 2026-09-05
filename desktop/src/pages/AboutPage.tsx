import { useEffect, useState } from "react";
import { getVersion } from "@tauri-apps/api/app";
import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { Copy, Download, ExternalLink, RefreshCw } from "lucide-react";

import packageInfo from "../../package.json";
import { openExternalUrl } from "../services/desktopBridge";
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
  | "available"
  | "downloading"
  | "verified"
  | "error";

interface UpdateCheckResult {
  status: "latest" | "available";
  current_version: string;
  latest_version: string;
  release_url: string;
  published_at?: string | null;
  notes_summary: string;
  installer_size?: number | null;
}

interface DownloadProgress {
  downloaded_bytes: number;
  total_bytes?: number | null;
  percent?: number | null;
}

interface DownloadResult {
  version: string;
  bytes: number;
  sha256: string;
}

function megabytes(bytes: number) {
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

function releaseDate(value?: string | null) {
  if (!value) return "发布时间未知";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "发布时间未知";
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(date);
}

function downloadErrorMessage(error: unknown) {
  const detail = String(error ?? "");
  if (detail.includes("完整性校验失败")) return "安装包完整性校验失败，请重新下载。";
  if (detail.includes("取消")) return "已取消下载。";
  if (detail.includes("磁盘空间") || detail.includes("不可写")) {
    return "无法写入系统更新临时目录，请检查磁盘空间后重试。";
  }
  return "更新下载失败，请稍后重试。";
}

export default function AboutPage() {
  const [version, setVersion] = useState(packageInfo.version);
  const [copyState, setCopyState] = useState("复制项目地址");
  const [updateStatus, setUpdateStatus] = useState<UpdateStatus>("idle");
  const [update, setUpdate] = useState<UpdateCheckResult | null>(null);
  const [progress, setProgress] = useState<DownloadProgress | null>(null);
  const [verified, setVerified] = useState<DownloadResult | null>(null);
  const [message, setMessage] = useState("");
  const [dataSourceMessage, setDataSourceMessage] = useState("");
  const [confirmInstall, setConfirmInstall] = useState(false);

  useEffect(() => {
    getVersion()
      .then((runtimeVersion) => setVersion(runtimeVersion || packageInfo.version))
      .catch(() => {
        // 普通浏览器开发预览没有 Tauri runtime，使用 package.json 构建版本。
      });
  }, []);

  useEffect(() => {
    let unlisten: (() => void) | undefined;
    void listen<DownloadProgress>("update-download-progress", (event) => {
      setProgress(event.payload);
    }).then((dispose) => {
      unlisten = dispose;
    }).catch(() => {
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
    if (updateStatus === "checking" || updateStatus === "downloading") return;
    setUpdateStatus("checking");
    setMessage("");
    setUpdate(null);
    setVerified(null);
    setProgress(null);
    setConfirmInstall(false);
    try {
      const result = await invoke<UpdateCheckResult>("check_update");
      setUpdate(result);
      setUpdateStatus(result.status);
    } catch {
      setUpdateStatus("error");
      setMessage("检查更新失败，请稍后重试");
    }
  }

  async function downloadUpdate() {
    setUpdateStatus("downloading");
    setMessage("");
    setProgress({ downloaded_bytes: 0, total_bytes: null, percent: null });
    try {
      const result = await invoke<DownloadResult>("download_update");
      setVerified(result);
      setUpdateStatus("verified");
    } catch (error) {
      const nextMessage = downloadErrorMessage(error);
      setMessage(nextMessage);
      setUpdateStatus(nextMessage === "已取消下载。" ? "available" : "error");
    }
  }

  async function cancelDownload() {
    await invoke("cancel_update").catch(() => undefined);
  }

  async function openReleaseNotes() {
    if (!update?.release_url) return;
    await invoke("open_release_page", { url: update.release_url }).catch(() => {
      setMessage("无法打开完整更新说明。请稍后重试。");
    });
  }

  async function launchInstaller() {
    try {
      await invoke("launch_verified_update");
    } catch {
      setConfirmInstall(false);
      setMessage("安装程序启动失败，软件将继续运行。");
    }
  }

  const isBusy = updateStatus === "checking" || updateStatus === "downloading";

  return <div className="workspace about-workspace">
    <header className="topbar about-topbar"><div><h1>关于</h1></div></header>

    <section className="about-identity" aria-labelledby="about-product-name">
      <div className="about-app-icon"><img src={appIcon} alt="" /></div>
      <div className="about-product">
        <h2 id="about-product-name">群聊拾遗</h2>
        <p>把本地微信群聊整理成可回顾、可检索、可长期保存的结构化总结。</p>
      </div>
      <div className="about-version"><small>当前版本</small><strong>v{version}</strong></div>
    </section>

    <section className="about-row" aria-labelledby="project-heading">
      <div><p className="about-label">开源项目</p><h3 id="project-heading">bluntvoice/wechat-chat-summary</h3><p className="about-url">{PROJECT_URL}</p></div>
      <button className="button secondary about-action" onClick={copyProjectUrl}><Copy size={15} aria-hidden="true" />{copyState}</button>
    </section>

    <section className="about-row" aria-labelledby="data-source-heading">
      <div><p className="about-label">数据来源</p><h3 id="data-source-heading">WeChatDataAnalysis</h3><p>群聊拾遗通过 WeChatDataAnalysis 提供的本地 API 获取微信聊天数据。它是独立的开源项目，需要单独下载安装并运行。</p>{dataSourceMessage && <p className="about-error" role="status">{dataSourceMessage}</p>}</div>
      <div className="about-source-actions"><button className="button ghost about-action" onClick={() => openDataSourceLink(WECHAT_DATA_ANALYSIS_HOMEPAGE)}><ExternalLink size={15} aria-hidden="true" />项目主页</button><button className="button secondary about-action" onClick={() => openDataSourceLink(WECHAT_DATA_ANALYSIS_RELEASES)}><Download size={15} aria-hidden="true" />下载最新版</button></div>
    </section>

    <section className="about-row about-update" aria-labelledby="update-heading">
      <div className="about-update-main">
        <p className="about-label">软件更新</p>
        <h3 id="update-heading">
          {updateStatus === "checking" ? "正在检查…" :
            updateStatus === "latest" ? "已是最新版本" :
              updateStatus === "available" || updateStatus === "downloading" || updateStatus === "verified"
                ? `发现新版本 v${update?.latest_version ?? verified?.version ?? ""}` :
                updateStatus === "error" ? "更新未完成" : "检查正式版本"}
        </h3>
        {updateStatus === "idle" && <p>仅在点击检查更新后访问 GitHub，不会在启动时或后台自动联网检查。</p>}
        {updateStatus === "checking" && <p>正在读取本项目官方 GitHub Releases。</p>}
        {updateStatus === "latest" && <p>普通更新通道只接受正式版本，不提供降级。</p>}
        {update && update.status === "available" && <div className="about-release-detail">
          <p>{releaseDate(update.published_at)}{update.installer_size ? ` · 安装包 ${megabytes(update.installer_size)}` : ""}</p>
          <p>{update.notes_summary}</p>
          <button className="about-text-action" onClick={openReleaseNotes}>查看完整更新说明</button>
        </div>}
        {updateStatus === "downloading" && progress && <div className="about-progress" aria-live="polite">
          <div className="about-progress-track"><span style={{ width: progress.percent == null ? "100%" : `${progress.percent}%` }} className={progress.percent == null ? "indeterminate" : ""} /></div>
          <p>{progress.total_bytes
            ? `${megabytes(progress.downloaded_bytes)} / ${megabytes(progress.total_bytes)} · ${progress.percent ?? 0}%`
            : `已下载 ${megabytes(progress.downloaded_bytes)} · 正在下载…`}</p>
        </div>}
        {updateStatus === "verified" && verified && <p className="about-success">已从官方 Release 下载，并通过 SHA-256 文件完整性校验。</p>}
        {message && <p className="about-error" role="status">{message}</p>}
        {confirmInstall && <div className="about-confirm" role="alert">
          <p>确认启动安装程序？安装程序成功启动后，当前软件才会退出。</p>
          <div><button className="button primary about-action" onClick={launchInstaller}>确认更新</button><button className="button secondary about-action" onClick={() => setConfirmInstall(false)}>取消</button></div>
        </div>}
      </div>
      <div className="about-update-actions">
        {(updateStatus === "idle" || updateStatus === "latest" || updateStatus === "error") && <button className="button secondary about-action" disabled={isBusy} onClick={checkForUpdates}><RefreshCw size={15} aria-hidden="true" />检查更新</button>}
        {updateStatus === "checking" && <button className="button secondary about-action" disabled><RefreshCw size={15} className="spinning" aria-hidden="true" />正在检查…</button>}
        {updateStatus === "available" && <button className="button secondary about-action" onClick={downloadUpdate}>下载更新</button>}
        {updateStatus === "downloading" && <button className="button secondary about-action" onClick={cancelDownload}>取消下载</button>}
        {updateStatus === "verified" && !confirmInstall && <button className="button secondary about-action" onClick={() => setConfirmInstall(true)}>启动安装</button>}
      </div>
    </section>

    <section className="about-notes" aria-label="隐私与许可">
      <div><p className="about-label">隐私</p><p>更新检查只读取官方 GitHub Release 信息，不上传聊天、API Key、历史数据库、报告或群聊名称。配置和历史使用 Windows 用户数据目录，报告保存在用户选择的位置。</p></div>
      <div><p className="about-label">许可</p><p>项目当前未提供覆盖整个仓库的统一开源许可证。各第三方依赖继续遵循其各自许可证，当前 Windows 安装包尚未进行代码签名。</p></div>
    </section>
  </div>;
}
