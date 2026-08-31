import { useEffect, useMemo, useRef, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { open } from "@tauri-apps/plugin-dialog";

type Settings = {
  wechat_api_url: string;
  provider: "deepseek" | "openai-compatible";
  api_url: string;
  model: string;
  thinking: boolean;
  export_root: string;
  image_dpi: number;
  range_mode: "single" | "custom";
  last_chat_id: string;
  last_chat_name: string;
  schedule_enabled: boolean;
  schedule_time: string;
  schedule_chat_id: string;
  schedule_chat_name: string;
  schedule_last_attempt_date: string;
  schedule_last_run_date: string;
  schedule_last_status: string;
  summarized_chat_ids?: string[];
  api_key_configured?: boolean;
};
type Chat = { id: string; name: string };
type BridgeResponse<T> = { id: string; ok: boolean; result?: T; error?: string };
type Result = { completed: boolean; version?: number; redaction_count?: number; chat_dir?: string; data_dir?: string; json_path?: string; html_path?: string; png_path?: string };
type Progress = { stage: string; percent: number; message: string; elapsed_seconds: number };
type RedactionTarget = { id: string; module_key: string; module_label: string; preview: string; time_label: string; redacted: boolean };

const initialSettings: Settings = {
  wechat_api_url: "http://127.0.0.1:10392", provider: "deepseek",
  api_url: "https://api.deepseek.com/chat/completions", model: "deepseek-v4-flash",
  thinking: false, export_root: "F:\\应用数据\\微信群聊总结", image_dpi: 300,
  range_mode: "single", last_chat_id: "", last_chat_name: "",
  schedule_enabled: false, schedule_time: "22:30", schedule_chat_id: "", schedule_chat_name: "",
  schedule_last_attempt_date: "", schedule_last_run_date: "", schedule_last_status: "",
};
const appIcon = new URL("../src-tauri/icons/icon.png", import.meta.url).href;

function localDate(offsetDays = 0) {
  const value = new Date(); value.setDate(value.getDate() + offsetDays);
  return `${value.getFullYear()}-${String(value.getMonth() + 1).padStart(2, "0")}-${String(value.getDate()).padStart(2, "0")}`;
}
async function bridge<T>(command: string, payload: Record<string, unknown> = {}) {
  const response = await invoke<BridgeResponse<T>>("bridge_call", { command, payload });
  if (!response.ok) throw new Error(response.error || "Python 分析服务未返回有效结果。");
  return response.result as T;
}

function App() {
  const [settings, setSettings] = useState<Settings>(initialSettings);
  const [apiKey, setApiKey] = useState("");
  const [chats, setChats] = useState<Chat[]>([]);
  const [chatId, setChatId] = useState("");
  const [query, setQuery] = useState("");
  const [reportDate, setReportDate] = useState(localDate());
  const [startDate, setStartDate] = useState(localDate());
  const [endDate, setEndDate] = useState(localDate());
  const [wechatState, setWechatState] = useState<"idle" | "testing" | "ready" | "error">("idle");
  const [aiState, setAiState] = useState<"idle" | "testing" | "ready" | "error">("idle");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("先连接 WeChatDataAnalysis，再选择需要总结的群聊。");
  const [progress, setProgress] = useState<Progress | null>(null);
  const [result, setResult] = useState<Result | null>(null);
  const [redactionTargets, setRedactionTargets] = useState<RedactionTarget[]>([]);
  const [selectedRedactions, setSelectedRedactions] = useState<string[]>([]);
  const [redactionEditorOpen, setRedactionEditorOpen] = useState(false);
  const [redactionBusy, setRedactionBusy] = useState(false);
  const progressTimer = useRef<number | null>(null);

  useEffect(() => {
    bridge<Settings>("get_state").then((saved) => setSettings({ ...initialSettings, ...saved })).catch((error) => setMessage(String(error)));
    return () => { if (progressTimer.current) window.clearInterval(progressTimer.current); };
  }, []);

  useEffect(() => {
    if (!settings.schedule_enabled) return;
    const checkSchedule = () => {
      if (busy || !settings.schedule_chat_id || !settings.schedule_time) return;
      const now = new Date();
      const today = localDate();
      const clock = `${String(now.getHours()).padStart(2, "0")}:${String(now.getMinutes()).padStart(2, "0")}`;
      if (clock < settings.schedule_time || settings.schedule_last_attempt_date === today) return;
      void runScheduledGeneration(today);
    };
    checkSchedule();
    const timer = window.setInterval(checkSchedule, 30_000);
    return () => window.clearInterval(timer);
  }, [settings.schedule_enabled, settings.schedule_time, settings.schedule_chat_id, settings.schedule_last_attempt_date, busy]);

  const summarized = useMemo(() => new Set(settings.summarized_chat_ids || []), [settings.summarized_chat_ids]);
  const filteredChats = useMemo(() => {
    const needle = query.trim().toLocaleLowerCase();
    return needle ? chats.filter((chat) => chat.name.toLocaleLowerCase().includes(needle)) : chats;
  }, [chats, query]);
  const selectedChat = chats.find((chat) => chat.id === chatId);
  const redactionGroups = useMemo(() => {
    const groups = new Map<string, RedactionTarget[]>();
    redactionTargets.forEach((target) => groups.set(target.module_label, [...(groups.get(target.module_label) || []), target]));
    return [...groups.entries()];
  }, [redactionTargets]);
  const statusSettings = () => ({ ...settings, ...(apiKey.trim() ? { api_key: apiKey.trim() } : {}) });

  async function connectWeChat() {
    setWechatState("testing"); setMessage("正在读取本机群聊列表…");
    try {
      const data = await bridge<{ chats: Chat[]; account: string }>("list_chats", { settings: statusSettings() });
      setChats(data.chats); setWechatState("ready"); setMessage(`已连接，读取到 ${data.chats.length} 个群聊。`);
      const remembered = data.chats.find((chat) => chat.id === settings.last_chat_id);
      if (remembered) setChatId(remembered.id); else if (data.chats.length && !chatId) setChatId(data.chats[0].id);
    } catch (error) { setWechatState("error"); setMessage(error instanceof Error ? error.message : String(error)); }
  }

  async function saveSettings(showNotice = true) {
    try {
      const payload: Record<string, unknown> = { ...settings };
      if (apiKey.trim()) payload.api_key = apiKey.trim();
      const saved = await bridge<Settings>("save_settings", { settings: payload });
      setSettings((current) => ({ ...current, ...saved })); setApiKey("");
      if (showNotice) setMessage(`AI 与导出设置已保存；当前模型：${saved.model}。`);
    } catch (error) {
      if (!showNotice) throw error;
      setMessage(`设置保存失败：${error instanceof Error ? error.message : String(error)}`);
    }
  }

  async function saveScheduleSettings() {
    let scheduleChatId = settings.schedule_chat_id;
    let scheduleChatName = settings.schedule_chat_name;
    if (settings.schedule_enabled && !scheduleChatId && selectedChat) {
      scheduleChatId = selectedChat.id;
      scheduleChatName = selectedChat.name;
    }
    if (settings.schedule_enabled && !scheduleChatId) {
      setMessage("启用定时生成前，请先连接并选择一个群聊。");
      return;
    }
    const next = { ...settings, schedule_chat_id: scheduleChatId, schedule_chat_name: scheduleChatName };
    try {
      const saved = await bridge<Settings>("save_settings", { settings: next });
      setSettings((current) => ({ ...current, ...saved }));
      setMessage(settings.schedule_enabled ? `已启用每日 ${settings.schedule_time} 定时生成；软件关闭时不会执行。` : "定时生成已关闭。");
    } catch (error) {
      setMessage(`定时设置保存失败：${error instanceof Error ? error.message : String(error)}`);
    }
  }

  async function testAi() {
    setAiState("testing"); setMessage("正在测试 AI API，仅发送最小测试内容…");
    try {
      const data = await bridge<{ model: string; response_model: string; model_verified: boolean }>("test_ai", { settings: statusSettings() });
      setAiState("ready");
      setMessage(data.response_model ? `AI API 连接成功，实际响应模型：${data.response_model}。` : `AI API 连接成功，请求模型：${data.model}。`);
    }
    catch (error) { setAiState("error"); setMessage(error instanceof Error ? error.message : String(error)); }
  }

  async function chooseExportRoot() {
    const selected = await open({ directory: true, multiple: false, defaultPath: settings.export_root || undefined, title: "选择群聊报告根目录" });
    if (typeof selected === "string") setSettings((current) => ({ ...current, export_root: selected }));
  }

  async function runGeneration(targetChatId: string, targetChatName: string, start: string, end: string, rangeMode: "single" | "custom", scheduled = false) {
    const jobId = crypto.randomUUID();
    const startedAt = Date.now();
    setBusy(true); setResult(null); setRedactionEditorOpen(false); setRedactionTargets([]); setSelectedRedactions([]); setProgress({ stage: "waiting", percent: 0, message: "等待分析引擎启动…", elapsed_seconds: 0 });
    setMessage(scheduled ? `正在执行 ${targetChatName || "已设群聊"} 的定时日报…` : "正在生成总结，进度会按真实处理阶段更新。");
    try {
      if (!scheduled) await saveSettings(false);
      progressTimer.current = window.setInterval(() => {
        bridge<Progress>("get_progress", { job_id: jobId }).then(setProgress).catch(() => undefined);
      }, 900);
      const generated = await bridge<Result>("generate", {
        job_id: jobId, chat: targetChatId, chat_name: targetChatName, range_mode: rangeMode,
        start: `${start} 00:00:00`, end: `${end} 23:59:59`, export_root: settings.export_root,
      });
      setResult(generated); setProgress({ stage: "completed", percent: 100, message: "报告生成完成", elapsed_seconds: Math.round((Date.now() - startedAt) / 1000) });
      setSettings((current) => ({ ...current, last_chat_id: targetChatId, last_chat_name: targetChatName }));
      setMessage(scheduled ? "定时日报已生成，图片与完整 HTML 分别可打开。" : "报告已生成，图片与完整 HTML 分别可打开。");
      return generated;
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error));
      throw error;
    }
    finally { if (progressTimer.current) window.clearInterval(progressTimer.current); progressTimer.current = null; setBusy(false); }
  }

  async function generate() {
    if (!chatId) return setMessage("请选择一个群聊。");
    if (!settings.export_root.trim()) return setMessage("请先选择独立的报告根目录。");
    const start = settings.range_mode === "single" ? reportDate : startDate;
    const end = settings.range_mode === "single" ? reportDate : endDate;
    if (end < start) return setMessage("结束日期不能早于开始日期。");
    try { await runGeneration(chatId, selectedChat?.name || "", start, end, settings.range_mode); } catch { /* 状态已在 runGeneration 中展示 */ }
  }

  async function runScheduledGeneration(today: string) {
    const claimed = { ...settings, schedule_last_attempt_date: today, schedule_last_status: "running" };
    setSettings(claimed);
    try {
      await bridge<Settings>("save_settings", { settings: claimed });
      await runGeneration(settings.schedule_chat_id, settings.schedule_chat_name, today, today, "single", true);
      const completed = {
        ...claimed,
        last_chat_id: settings.schedule_chat_id,
        last_chat_name: settings.schedule_chat_name,
        schedule_last_run_date: today,
        schedule_last_status: "success",
      };
      setSettings(completed);
      await bridge("save_settings", { settings: completed });
    } catch (error) {
      const failed = { ...claimed, schedule_last_status: "failed" };
      setSettings(failed);
      setMessage(`定时日报执行失败：${error instanceof Error ? error.message : String(error)}`);
      try {
        await bridge("save_settings", { settings: failed });
      } catch {
        setMessage(`定时任务状态保存失败：${error instanceof Error ? error.message : String(error)}`);
      }
    }
  }

  async function openPath(path?: string) {
    if (!path) return;
    try { await invoke("open_system_path", { path }); } catch (error) { setMessage(error instanceof Error ? error.message : String(error)); }
  }

  async function loadRedactionTargets(jsonPath: string) {
    const data = await bridge<{ version: number; targets: RedactionTarget[] }>("get_redaction_targets", { json_path: jsonPath });
    setRedactionTargets(data.targets);
    setSelectedRedactions(data.targets.filter((target) => target.redacted).map((target) => target.id));
    return data;
  }

  async function openRedactionEditor() {
    if (!result?.json_path) return;
    setRedactionBusy(true);
    try {
      const data = await loadRedactionTargets(result.json_path);
      setRedactionEditorOpen(true);
      setMessage(`已读取 ${data.targets.length} 个可屏蔽条目；屏蔽仅在本机重排报告，不会再次调用 AI。`);
    } catch (error) {
      setMessage(`无法打开屏蔽编辑器：${error instanceof Error ? error.message : String(error)}`);
    } finally {
      setRedactionBusy(false);
    }
  }

  function toggleRedaction(target: RedactionTarget) {
    if (target.redacted) return;
    setSelectedRedactions((current) => current.includes(target.id) ? current.filter((id) => id !== target.id) : [...current, target.id]);
  }

  async function applyRedactions() {
    if (!result?.json_path) return;
    const existingCount = redactionTargets.filter((target) => target.redacted).length;
    if (selectedRedactions.length <= existingCount) {
      setMessage("请至少新增选择一项需要屏蔽的内容。");
      return;
    }
    setBusy(true); setRedactionBusy(true); setMessage("正在本机生成屏蔽版报告，不会读取群聊或调用 AI…");
    try {
      const updated = await bridge<Result>("redact_report", { json_path: result.json_path, target_ids: selectedRedactions });
      setResult(updated);
      await loadRedactionTargets(updated.json_path || "");
      setMessage(`屏蔽版报告 v${updated.version || "新"} 已生成；原报告保持不变。`);
    } catch (error) {
      setMessage(`屏蔽版报告生成失败：${error instanceof Error ? error.message : String(error)}`);
    } finally {
      setBusy(false); setRedactionBusy(false);
    }
  }

  const activeStart = settings.range_mode === "single" ? reportDate : startDate;
  const activeEnd = settings.range_mode === "single" ? reportDate : endDate;

  return <main className="app-shell">
    <aside className="rail">
      <div className="brand-mark"><img src={appIcon} alt="群聊拾遗" /></div><div className="rail-line" aria-hidden="true" />
      <div className={`rail-node ${wechatState === "ready" ? "done" : "active"}`}><span>1</span><small>连接</small></div>
      <div className={`rail-node ${chatId ? "done" : ""}`}><span>2</span><small>选择</small></div>
      <div className={`rail-node ${result ? "done" : busy ? "active" : ""}`}><span>3</span><small>生成</small></div>
    </aside>
    <div className="workspace">
      <header className="topbar"><div><p className="eyebrow">WECHAT · LOCAL INSIGHT</p><h1>微信群聊总结</h1></div><div className={`system-state ${wechatState}`}><span />{wechatState === "ready" ? "数据源已连接" : "等待连接数据源"}</div></header>
      <section className="notice" aria-live="polite"><strong>{busy ? "处理中" : "当前状态"}</strong><span>{message}</span></section>
      <div className="grid">
        <section className="panel source-panel">
          <div className="panel-heading"><div><span className="step-tag">01</span><h2>连接微信数据</h2></div><button className="button secondary" onClick={connectWeChat} disabled={wechatState === "testing" || busy}>{wechatState === "testing" ? "连接中…" : "测试并读取群聊"}</button></div>
          <label><span>WeChatDataAnalysis API</span><input value={settings.wechat_api_url} onChange={(e) => setSettings({ ...settings, wechat_api_url: e.target.value })} /></label>
          <div className="chat-picker"><label><span>搜索群聊</span><input placeholder="输入群聊名称" value={query} onChange={(e) => setQuery(e.target.value)} disabled={!chats.length} /></label><label><span>选择群聊</span><select value={chatId} onChange={(e) => setChatId(e.target.value)} disabled={!filteredChats.length}>{!filteredChats.length && <option value="">连接后显示群聊</option>}{filteredChats.map((chat) => <option key={chat.id} value={chat.id}>{chat.name}{summarized.has(chat.id) ? " · 已总结" : ""}</option>)}</select></label></div>
          {selectedChat && <p className="selection-note">本次总结：<strong>{selectedChat.name}</strong>{summarized.has(selectedChat.id) && <em>　已有历史报告</em>}</p>}
        </section>
        <section className="panel range-panel">
          <div className="panel-heading compact"><div><span className="step-tag">02</span><h2>选择统计日期</h2></div></div>
          <div className="segmented"><button className={settings.range_mode === "single" ? "selected" : ""} onClick={() => setSettings({ ...settings, range_mode: "single" })}>单日</button><button className={settings.range_mode === "custom" ? "selected" : ""} onClick={() => setSettings({ ...settings, range_mode: "custom" })}>自定义区间</button></div>
          {settings.range_mode === "single" ? <label><span>报告日期</span><input type="date" value={reportDate} onChange={(e) => setReportDate(e.target.value)} /></label> : <div className="date-grid"><label><span>开始日期</span><input type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)} /></label><label><span>结束日期</span><input type="date" value={endDate} onChange={(e) => setEndDate(e.target.value)} /></label></div>}
          <div className="quick-dates"><button onClick={() => { setReportDate(localDate()); setStartDate(localDate()); setEndDate(localDate()); }}>今天</button><button onClick={() => { setReportDate(localDate(-1)); setStartDate(localDate(-1)); setEndDate(localDate(-1)); }}>昨天</button></div>
        </section>
        <section className="panel ai-panel">
          <div className="panel-heading"><div><span className="step-tag">03</span><h2>配置 AI 分析</h2></div><div className="heading-actions"><button className="button secondary" onClick={() => saveSettings()} disabled={busy}>保存设置</button><button className="button secondary" onClick={testAi} disabled={aiState === "testing" || busy}>{aiState === "testing" ? "测试中…" : "测试 API"}</button></div></div>
          <div className="field-grid"><label><span>服务类型</span><select value={settings.provider} onChange={(e) => { const provider = e.target.value as Settings["provider"]; setSettings({ ...settings, provider, model: provider === "deepseek" ? "deepseek-v4-flash" : settings.model }); }}><option value="deepseek">DeepSeek</option><option value="openai-compatible">OpenAI Compatible</option></select></label><label><span>模型</span>{settings.provider === "deepseek" ? <select value={settings.model} onChange={(e) => setSettings({ ...settings, model: e.target.value })}><option value="deepseek-v4-flash">DeepSeek V4 Flash</option><option value="deepseek-v4-pro">DeepSeek V4 Pro</option></select> : <input value={settings.model} onChange={(e) => setSettings({ ...settings, model: e.target.value })} />}</label><label className="wide"><span>API URL</span><input value={settings.api_url} onChange={(e) => setSettings({ ...settings, api_url: e.target.value })} /></label><label className="wide"><span>API Key {settings.api_key_configured && !apiKey ? <em>本机已保存</em> : null}</span><input type="password" autoComplete="off" placeholder={settings.api_key_configured ? "留空则继续使用已保存的 Key" : "输入 API Key"} value={apiKey} onChange={(e) => setApiKey(e.target.value)} /></label></div>
          <p className="privacy-copy">聊天文本仅在生成时发送给你配置的 AI 服务商；Key 只保存在本机软件数据目录。</p>
        </section>
        <section className="panel output-panel">
          <div className="panel-heading compact"><div><span className="step-tag">04</span><h2>报告目录与定时</h2></div></div>
          <label><span>独立报告根目录</span><div className="path-control"><input readOnly value={settings.export_root} /><button className="button secondary" onClick={chooseExportRoot}>选择目录</button></div></label>
          <div className="archive-preview"><span>自动归档</span><code>群聊 / 导出图 / 年 / 月</code><code>群聊 / 报告数据 / 日期报告数据</code></div>
          <div className="schedule-box">
            <div className="schedule-title"><div><strong>定时生成当日报告</strong><small>仅软件保持运行时执行，每天最多自动尝试一次</small></div><label className="switch"><input type="checkbox" checked={settings.schedule_enabled} onChange={(e) => setSettings({ ...settings, schedule_enabled: e.target.checked })} /><span /></label></div>
            <div className="schedule-fields">
              <label><span>每日时间</span><input type="time" value={settings.schedule_time} disabled={!settings.schedule_enabled} onChange={(e) => setSettings({ ...settings, schedule_time: e.target.value })} /></label>
              <label><span>定时群聊</span><input readOnly value={settings.schedule_chat_name || "尚未设置"} /></label>
            </div>
            <div className="schedule-actions"><button className="button ghost" disabled={!selectedChat || busy} onClick={() => setSettings({ ...settings, schedule_chat_id: selectedChat?.id || "", schedule_chat_name: selectedChat?.name || "" })}>设为当前群聊</button><button className="button secondary" disabled={busy} onClick={saveScheduleSettings}>保存定时设置</button></div>
            {settings.schedule_last_attempt_date && <p className="schedule-status">最近尝试：{settings.schedule_last_attempt_date} · {settings.schedule_last_status === "success" ? "成功" : settings.schedule_last_status === "failed" ? "失败" : "执行中"}{settings.schedule_last_run_date && settings.schedule_last_run_date !== settings.schedule_last_attempt_date ? ` · 最近成功 ${settings.schedule_last_run_date}` : ""}</p>}
          </div>
        </section>
      </div>
      <section className={`action-dock ${result ? "has-result" : ""}`}><div><strong>{selectedChat?.name || "尚未选择群聊"}</strong><span>{activeStart === activeEnd ? activeStart : `${activeStart} 至 ${activeEnd}`} · PNG 300 DPI</span>{progress && <div className="progress-wrap"><i><b style={{ width: `${progress.percent}%` }} /></i><small>{progress.percent}% · {progress.message} · 已用 {Math.round(progress.elapsed_seconds)} 秒</small></div>}</div><button className="button primary" onClick={generate} disabled={busy || !chatId}>{busy ? "正在生成…" : "生成群聊总结"}</button></section>
      {result && <section className="result-panel"><div className="result-copy"><span className="result-check">✓</span><div><h2>报告生成完成{result.version ? ` · v${result.version}` : ""}</h2><p>摘要长图与完整 HTML 已生成，旧版本不会被覆盖。</p></div></div><div className="result-actions"><button className="button primary small" onClick={() => openPath(result.png_path)}>打开图片</button><button className="button secondary" onClick={() => openPath(result.html_path)}>打开 HTML</button><button className="button secondary" onClick={() => openPath(result.chat_dir || result.data_dir)}>打开报告所在目录</button><button className="button ghost" disabled={redactionBusy} onClick={openRedactionEditor}>{redactionBusy ? "读取中…" : "编辑并屏蔽内容"}</button></div></section>}
      {result && redactionEditorOpen && <section className="redaction-panel">
        <div className="redaction-heading"><div><span className="step-tag">编辑</span><h2>人工屏蔽报告内容</h2><p>勾选后将生成本地新版本；不再次调用 AI。已屏蔽条目不能在当前版本取消，可回到原版本重新编辑。</p></div><button className="button ghost" onClick={() => setRedactionEditorOpen(false)}>收起</button></div>
        <div className="redaction-groups">{redactionGroups.map(([label, targets]) => <div className="redaction-group" key={label}><h3>{label}<span>{targets.length}</span></h3>{targets.map((target) => <label className={`redaction-row ${target.redacted ? "already" : ""}`} key={target.id}><input type="checkbox" checked={selectedRedactions.includes(target.id)} disabled={target.redacted || redactionBusy} onChange={() => toggleRedaction(target)} /><span><strong>{target.redacted ? "已屏蔽" : target.preview}</strong><small>{target.time_label}{target.redacted ? " · 已屏蔽，建议在群内查看" : ""}</small></span></label>)}</div>)}</div>
        <div className="redaction-footer"><span>已选择 {selectedRedactions.length} 项（含既有屏蔽）</span><button className="button primary" disabled={redactionBusy || selectedRedactions.length <= redactionTargets.filter((target) => target.redacted).length} onClick={applyRedactions}>{redactionBusy ? "正在生成…" : "生成屏蔽版新报告"}</button></div>
      </section>}
    </div>
  </main>;
}
export default App;
