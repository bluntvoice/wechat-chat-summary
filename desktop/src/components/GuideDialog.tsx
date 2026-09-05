import { Download, RefreshCw, X } from "lucide-react";
import { useState } from "react";

import { bridge, openExternalUrl } from "../services/desktopBridge";
import {
  DATA_SOURCE_UNAVAILABLE_MESSAGE,
  WECHAT_DATA_ANALYSIS_RELEASES,
  type DataSourceCheckResult,
} from "../services/wechatDataSource";
import { INITIAL_SETTINGS, type Settings } from "../types/desktop";

type GuideDialogProps = {
  onClose: () => void;
  onOpenSettings: () => void;
  onDataSourceConnected: () => void;
};

type GuideStatus = "idle" | "testing" | "ready" | "error";

export default function GuideDialog({ onClose, onOpenSettings, onDataSourceConnected }: GuideDialogProps) {
  const [status, setStatus] = useState<GuideStatus>("idle");
  const [detail, setDetail] = useState("");

  async function openDownload() {
    try {
      await openExternalUrl(WECHAT_DATA_ANALYSIS_RELEASES);
      setDetail("");
    } catch (error) {
      setDetail(`无法打开下载页面：${error instanceof Error ? error.message : String(error)}`);
    }
  }

  async function checkDataSource() {
    setStatus("testing");
    setDetail("");
    try {
      const saved = await bridge<Settings>("get_state");
      const result = await bridge<DataSourceCheckResult>("test_wechat", {
        settings: { ...INITIAL_SETTINGS, ...saved },
      });
      if (result.connected) {
        setStatus("ready");
        onDataSourceConnected();
        return;
      }
      setStatus("error");
      setDetail(result.detail || "本地 API 当前不可用。");
    } catch (error) {
      setStatus("error");
      setDetail(error instanceof Error ? error.message : String(error));
    }
  }

  return <div className="guide-backdrop" role="presentation" onMouseDown={(event) => {
    if (event.target === event.currentTarget) onClose();
  }}>
    <section className="guide-dialog" role="dialog" aria-modal="true" aria-labelledby="guide-title">
      <header className="guide-heading">
        <div><h2 id="guide-title">使用前准备</h2><p>群聊拾遗本身不直接读取微信数据库，需要通过 WeChatDataAnalysis 提供的本地 API 获取聊天数据。</p></div>
        <button className="icon-button" onClick={onClose} aria-label="关闭使用指南" title="关闭"><X size={18} aria-hidden="true" /></button>
      </header>

      <ol className="guide-steps guide-data-source-steps">
        <li><span>1</span><div><strong>安装 WeChatDataAnalysis</strong><p>如果尚未安装，请先从官方 Releases 页面下载安装。</p><button className="button secondary guide-step-action inline-icon" onClick={openDownload}><Download size={14} aria-hidden="true" />前往下载安装</button></div></li>
        <li><span>2</span><div><strong>启动并准备微信数据</strong><p>打开 WeChatDataAnalysis，根据其界面提示完成微信数据加载或相关准备，并保持程序运行。</p></div></li>
        <li><span>3</span><div><strong>返回群聊拾遗</strong><p>完成上述操作后，无需重启群聊拾遗，直接重新检测数据源。</p><button className="button primary guide-step-action inline-icon" disabled={status === "testing"} onClick={checkDataSource}><RefreshCw size={14} className={status === "testing" ? "spinning" : ""} aria-hidden="true" />{status === "testing" ? "正在检测…" : "重新检测数据源"}</button></div></li>
      </ol>

      {status === "ready" && <div className="guide-status ready" role="status"><strong>已连接 WeChatDataAnalysis</strong><p>现在可以选择群聊并生成总结。</p></div>}
      {status === "error" && <div className="guide-status pending" role="status"><strong>暂未检测到服务</strong><p>{DATA_SOURCE_UNAVAILABLE_MESSAGE} 请确认软件已经启动并完成数据准备。</p>{detail && <details><summary>连接详情</summary><code>{detail}</code></details>}</div>}
      {status === "idle" && detail && <div className="guide-status pending" role="status"><p>{detail}</p></div>}

      <footer className="guide-actions"><button className="button secondary" onClick={onClose}>稍后再看</button><button className="button primary small" onClick={onOpenSettings}>打开设置</button></footer>
    </section>
  </div>;
}
