import { useEffect, useState } from "react";
import { open } from "@tauri-apps/plugin-dialog";

import { bridge, invokeDesktop } from "../services/desktopBridge";
import { INITIAL_SETTINGS, type McpServerStatus, type Settings } from "../types/desktop";

const DEEPSEEK_URL = "https://api.deepseek.com/chat/completions";

export default function SettingsPage({ active }: { active: boolean }) {
  const [settings, setSettings] = useState<Settings>(INITIAL_SETTINGS);
  const [apiKey, setApiKey] = useState("");
  const [mcpStatus, setMcpStatus] = useState<McpServerStatus | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("设置仅保存在本机；MCP Server 默认关闭。");

  useEffect(() => {
    void loadSettings();
  }, []);

  useEffect(() => {
    if (!active) return;
    void loadSettings();
  }, [active]);

  async function loadSettings() {
    try {
      const saved = await bridge<Settings>("get_state");
      const merged = { ...INITIAL_SETTINGS, ...saved };
      setSettings(merged);
      const status = merged.mcp_enabled
        ? await invokeDesktop<McpServerStatus>("mcp_server_start", { port: merged.mcp_port })
        : await invokeDesktop<McpServerStatus>("mcp_server_status", { port: merged.mcp_port });
      setMcpStatus(status);
    } catch (error) {
      setMessage(`读取设置失败：${error instanceof Error ? error.message : String(error)}`);
    }
  }

  function changeProvider(provider: Settings["provider"]) {
    setApiKey("");
    setSettings((current) => ({
      ...current,
      provider,
      api_url: provider === "deepseek" ? DEEPSEEK_URL : "",
      model: provider === "deepseek" ? "deepseek-v4-flash" : "",
      thinking: provider === "deepseek" ? current.thinking : false,
    }));
  }

  async function saveAll() {
    setBusy(true);
    try {
      const payload: Record<string, unknown> = { ...settings };
      if (apiKey.trim()) payload.api_key = apiKey.trim();
      const saved = await bridge<Settings>("save_settings", { settings: payload });
      setSettings((current) => ({ ...current, ...saved }));
      setApiKey("");
      setMessage(`设置已保存；当前 Provider：${saved.provider === "deepseek" ? "DeepSeek" : "OpenAI Compatible"}。`);
    } catch (error) {
      setMessage(`保存失败：${error instanceof Error ? error.message : String(error)}`);
    } finally {
      setBusy(false);
    }
  }

  async function testWeChat() {
    setBusy(true);
    setMessage("正在测试 WeChatDataAnalysis…");
    try {
      const result = await bridge<{ group_count: number }>("test_wechat", { settings });
      setMessage(`数据源连接成功，当前可读取 ${result.group_count} 个群聊。`);
    } catch (error) {
      setMessage(`数据源连接失败：${error instanceof Error ? error.message : String(error)}`);
    } finally {
      setBusy(false);
    }
  }

  async function testAi() {
    setBusy(true);
    setMessage("正在发送最小 JSON 连接测试…");
    try {
      const payload = { ...settings, ...(apiKey.trim() ? { api_key: apiKey.trim() } : {}) };
      const result = await bridge<{ model: string; response_model: string }>("test_ai", { settings: payload });
      setMessage(`AI API 连接成功；响应模型：${result.response_model || result.model}。`);
    } catch (error) {
      setMessage(`AI API 连接失败：${error instanceof Error ? error.message : String(error)}`);
    } finally {
      setBusy(false);
    }
  }

  async function chooseExportRoot() {
    const selected = await open({
      directory: true,
      multiple: false,
      defaultPath: settings.export_root || undefined,
      title: "选择群聊报告根目录",
    });
    if (typeof selected === "string") setSettings((current) => ({ ...current, export_root: selected }));
  }

  async function setMcpEnabled(enabled: boolean) {
    setBusy(true);
    try {
      await bridge<Settings>("save_settings", { settings: { mcp_enabled: enabled, mcp_port: settings.mcp_port } });
      const status = await invokeDesktop<McpServerStatus>(enabled ? "mcp_server_start" : "mcp_server_stop", {
        port: settings.mcp_port,
      });
      setSettings((current) => ({ ...current, mcp_enabled: enabled, mcp_endpoint: status.endpoint }));
      setMcpStatus(status);
      setMessage(enabled ? `MCP Server 已启动：${status.endpoint}` : "MCP Server 已停止。关闭状态已保存。");
    } catch (error) {
      await bridge("save_settings", { settings: { mcp_enabled: false } }).catch(() => undefined);
      setSettings((current) => ({ ...current, mcp_enabled: false }));
      setMessage(`MCP Server 操作失败：${error instanceof Error ? error.message : String(error)}`);
    } finally {
      setBusy(false);
    }
  }

  async function copyMcpConfig() {
    try {
      const endpoint = mcpStatus?.endpoint || `http://127.0.0.1:${settings.mcp_port}/mcp`;
      const config = JSON.stringify(
        { mcpServers: { "wechat-chat-summary": { type: "http", url: endpoint } } },
        null,
        2,
      );
      await navigator.clipboard.writeText(config);
      setMessage("MCP Host 配置已复制。不同 Host 的配置文件位置见项目 README。");
    } catch (error) {
      setMessage(`复制失败：${error instanceof Error ? error.message : String(error)}`);
    }
  }

  const keyConfigured = settings.provider === "deepseek"
    ? settings.deepseek_api_key_configured
    : settings.openai_compatible_api_key_configured;
  const endpoint = mcpStatus?.endpoint || `http://127.0.0.1:${settings.mcp_port}/mcp`;

  return <div className="workspace settings-workspace">
    <header className="topbar"><div><p className="eyebrow">LOCAL · CONTROL</p><h1>设置</h1></div><div className={`system-state ${mcpStatus?.running ? "ready" : "idle"}`}><span />{mcpStatus?.running ? "MCP 已运行" : "MCP 已关闭"}</div></header>
    <section className="notice" aria-live="polite"><strong>{busy ? "处理中" : "当前状态"}</strong><span>{message}</span></section>

    <div className="settings-sections">
      <section className="settings-section">
        <div className="settings-section-head"><div><span>01</span><h2>微信数据源</h2></div><button className="button secondary" disabled={busy} onClick={testWeChat}>测试连接</button></div>
        <label><span>WeChatDataAnalysis API</span><input value={settings.wechat_api_url} onChange={(event) => setSettings({ ...settings, wechat_api_url: event.target.value })} /></label>
      </section>

      <section className="settings-section">
        <div className="settings-section-head"><div><span>02</span><h2>AI API 模式</h2></div><div className="heading-actions"><button className="button secondary" disabled={busy} onClick={testAi}>测试 API</button><button className="button primary small" disabled={busy} onClick={saveAll}>保存设置</button></div></div>
        <div className="field-grid">
          <label><span>Provider</span><select value={settings.provider} onChange={(event) => changeProvider(event.target.value as Settings["provider"])}><option value="deepseek">DeepSeek</option><option value="openai-compatible">OpenAI Compatible</option></select></label>
          <label><span>Model</span>{settings.provider === "deepseek" ? <select value={settings.model} onChange={(event) => setSettings({ ...settings, model: event.target.value })}><option value="deepseek-v4-flash">DeepSeek V4 Flash</option><option value="deepseek-v4-pro">DeepSeek V4 Pro</option></select> : <input placeholder="例如 gpt-4.1-mini" value={settings.model} onChange={(event) => setSettings({ ...settings, model: event.target.value })} />}</label>
          <label className="wide"><span>{settings.provider === "deepseek" ? "API URL" : "Base URL / Chat Completions URL"}</span><input placeholder={settings.provider === "deepseek" ? DEEPSEEK_URL : "https://example.com/v1"} value={settings.api_url} onChange={(event) => setSettings({ ...settings, api_url: event.target.value })} /></label>
          <label className="wide"><span>API Key {keyConfigured && !apiKey ? <em>本机已保存</em> : null}</span><input type="password" autoComplete="off" placeholder={keyConfigured ? "留空则继续使用当前 Provider 已保存的 Key" : "输入 API Key"} value={apiKey} onChange={(event) => setApiKey(event.target.value)} /></label>
        </div>
        {settings.provider === "deepseek" && <div className="provider-options"><label className="switch-row"><span><strong>Thinking</strong><small>启用 DeepSeek 思考模式</small></span><label className="switch"><input type="checkbox" checked={settings.thinking} onChange={(event) => setSettings({ ...settings, thinking: event.target.checked })} /><span /></label></label><label><span>Reasoning Effort</span><select disabled={!settings.thinking} value={settings.reasoning_effort} onChange={(event) => setSettings({ ...settings, reasoning_effort: event.target.value as Settings["reasoning_effort"] })}><option value="high">High</option><option value="max">Max</option></select></label></div>}
        <p className="privacy-copy">API 模式下，软件会把完成分析所需的聊天文本发送给你配置的 AI 服务商。API Key 仅保存在本机私有配置，不写入 SQLite、日志或报告。</p>
      </section>

      <section className="settings-section">
        <div className="settings-section-head"><div><span>03</span><h2>报告导出</h2></div><button className="button primary small" disabled={busy} onClick={saveAll}>保存设置</button></div>
        <div className="field-grid"><label className="wide"><span>独立报告根目录</span><div className="path-control"><input readOnly value={settings.export_root} /><button className="button secondary" onClick={chooseExportRoot}>选择目录</button></div></label><label><span>PNG DPI</span><input type="number" min="72" max="600" value={settings.image_dpi} onChange={(event) => setSettings({ ...settings, image_dpi: Number(event.target.value) })} /></label></div>
      </section>

      <section className="settings-section mcp-settings">
        <div className="settings-section-head"><div><span>04</span><h2>MCP Server</h2></div><label className="switch"><input type="checkbox" checked={settings.mcp_enabled} disabled={busy} onChange={(event) => void setMcpEnabled(event.target.checked)} /><span /></label></div>
        <p className="mcp-explanation">群聊拾遗作为 MCP Server 提供数据与报告能力，实际 AI 分析由连接的软件 / AI 客户端完成。</p>
        <div className="mcp-status-grid"><div><span>状态</span><strong>{mcpStatus?.running ? "运行中" : "已关闭"}</strong></div><div><span>Transport</span><strong>Streamable HTTP</strong></div><div className="wide"><span>本机地址</span><code>{endpoint}</code></div></div>
        <div className="mcp-controls"><label><span>端口</span><input type="number" min="1024" max="65535" disabled={settings.mcp_enabled} value={settings.mcp_port} onChange={(event) => setSettings({ ...settings, mcp_port: Number(event.target.value) })} /></label><div className="heading-actions"><button className="button secondary" disabled={busy || settings.mcp_enabled} onClick={() => void setMcpEnabled(true)}>启动</button><button className="button secondary" disabled={busy || !settings.mcp_enabled} onClick={() => void setMcpEnabled(false)}>停止</button><button className="button secondary" disabled={busy || !settings.mcp_enabled || !mcpStatus?.running} onClick={copyMcpConfig}>复制配置</button></div></div>
        <p className="privacy-copy">仅监听 127.0.0.1，不创建 Windows Service。软件退出时 MCP 子进程随之终止；原始聊天只按明确时间范围临时读取，不写入历史库或报告目录。</p>
      </section>
    </div>
  </div>;
}
