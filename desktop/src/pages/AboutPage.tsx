import { useEffect, useState } from "react";
import { getName, getVersion } from "@tauri-apps/api/app";

import packageInfo from "../../package.json";

const PROJECT_URL = "https://github.com/bluntvoice/wechat-chat-summary";

export default function AboutPage() {
  const [appName, setAppName] = useState("WeChat Chat Summary");
  const [version, setVersion] = useState(packageInfo.version);
  const [versionSource, setVersionSource] = useState("构建版本");
  const [copyState, setCopyState] = useState("复制项目地址");

  useEffect(() => {
    Promise.all([getName(), getVersion()]).then(([name, runtimeVersion]) => {
      setAppName(name || "WeChat Chat Summary");
      setVersion(runtimeVersion || packageInfo.version);
      setVersionSource("安装包运行版本");
    }).catch(() => {
      // 普通浏览器开发预览没有 Tauri runtime，使用 package.json 构建版本。
    });
  }, []);

  async function copyProjectUrl() {
    try {
      await navigator.clipboard.writeText(PROJECT_URL);
      setCopyState("已复制");
      window.setTimeout(() => setCopyState("复制项目地址"), 1600);
    } catch {
      setCopyState("复制失败，请手动复制");
    }
  }

  return <div className="workspace about-workspace">
    <header className="topbar about-topbar"><div><p className="eyebrow">APPLICATION · ABOUT</p><h1>关于</h1></div></header>
    <section className="about-hero">
      <div className="about-monogram">群</div>
      <div><span>{appName}</span><h2>群聊拾遗</h2><p>把本地微信群聊整理成可回顾、可检索、可长期保存的结构化总结。</p></div>
      <div className="about-version"><small>{versionSource}</small><strong>v{version}</strong><code>{version}</code></div>
    </section>
    <div className="about-grid">
      <section className="about-card">
        <span>版本确认</span><h3>当前正在运行 v{version}</h3>
        <p>Release 安装包会从 Tauri 运行时读取实际版本。若这里显示的版本与准备发布的 Tag 不一致，请停止发布并检查版本同步。</p>
        <dl><div><dt>应用标识</dt><dd>com.bluntvoice.wechat-chat-summary</dd></div><div><dt>发布通道</dt><dd>Windows x64</dd></div></dl>
      </section>
      <section className="about-card">
        <span>项目地址</span><h3>bluntvoice/wechat-chat-summary</h3>
        <p className="about-url">{PROJECT_URL}</p>
        <button className="button secondary" onClick={copyProjectUrl}>{copyState}</button>
      </section>
      <section className="about-card about-privacy-card">
        <span>本地数据</span><h3>配置、历史与报告相互分离</h3>
        <p>软件数据使用 Windows 标准用户数据目录；报告只写入用户选择的导出目录。热力图只缓存每日聚合统计，不保存为统计而读取的原始消息正文。</p>
      </section>
    </div>
    <p className="about-footnote">本页暂不包含检查更新；正式更新能力将在后续阶段单独实现和验收。</p>
  </div>;
}
