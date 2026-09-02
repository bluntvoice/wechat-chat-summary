import { useEffect, useMemo, useState } from "react";
import RedactionEditor from "../components/RedactionEditor";
import { useReportGeneration } from "../hooks/useReportGeneration";
import { localDate } from "../services/dates";
import { filterAndSortChats, type ChatListFilter } from "../services/chatList";
import { bridge, openSystemPath } from "../services/desktopBridge";
import {
  INITIAL_SETTINGS,
  type Chat,
  type GenerationResult,
  type RedactionTarget,
  type Settings,
} from "../types/desktop";

function GeneratePage({ active, onOpenSettings }: { active: boolean; onOpenSettings: () => void }) {
  const [settings, setSettings] = useState<Settings>(INITIAL_SETTINGS);
  const [chats, setChats] = useState<Chat[]>([]);
  const [chatId, setChatId] = useState("");
  const [query, setQuery] = useState("");
  const [chatFilter, setChatFilter] = useState<ChatListFilter>("all");
  const [reportDate, setReportDate] = useState(localDate());
  const [startDate, setStartDate] = useState(localDate());
  const [endDate, setEndDate] = useState(localDate());
  const [wechatState, setWechatState] = useState<"idle" | "testing" | "ready" | "error">("idle");
  const [message, setMessage] = useState("先连接 WeChatDataAnalysis，再选择需要总结的群聊。");
  const [redactionTargets, setRedactionTargets] = useState<RedactionTarget[]>([]);
  const [selectedRedactions, setSelectedRedactions] = useState<string[]>([]);
  const [redactionEditorOpen, setRedactionEditorOpen] = useState(false);
  const [redactionBusy, setRedactionBusy] = useState(false);
  const { busy, setBusy, progress, result, setResult, runGeneration } = useReportGeneration({
    settings,
    setSettings,
    setMessage,
    saveSettings,
    beforeGeneration: () => {
      setRedactionEditorOpen(false);
      setRedactionTargets([]);
      setSelectedRedactions([]);
    },
  });

  useEffect(() => {
    if (!active) return;
    bridge<Settings>("get_state").then((saved) => {
      setSettings({ ...INITIAL_SETTINGS, ...saved });
    }).catch((error) => setMessage(String(error)));
  }, [active]);

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
  const filteredChats = useMemo(
    () => filterAndSortChats(chats, summarized, query, chatFilter),
    [chats, summarized, query, chatFilter],
  );
  useEffect(() => {
    if (filteredChats.some((chat) => chat.id === chatId)) return;
    setChatId(filteredChats[0]?.id || "");
  }, [filteredChats, chatId]);
  const selectedChat = chats.find((chat) => chat.id === chatId);
  const statusSettings = () => ({ ...settings });

  async function connectWeChat() {
    setWechatState("testing"); setMessage("正在读取本机群聊列表…");
    try {
      const data = await bridge<{ chats: Chat[]; account: string }>("list_chats", { settings: statusSettings() });
      const summarizedChatIds = data.chats.filter((chat) => chat.summarized).map((chat) => chat.id);
      setChats(data.chats);
      setSettings((current) => ({ ...current, summarized_chat_ids: summarizedChatIds }));
      setWechatState("ready"); setMessage(`已连接，读取到 ${data.chats.length} 个群聊。`);
      const remembered = data.chats.find((chat) => chat.id === settings.last_chat_id);
      if (remembered) setChatId(remembered.id); else if (data.chats.length && !chatId) setChatId(data.chats[0].id);
    } catch (error) { setWechatState("error"); setMessage(error instanceof Error ? error.message : String(error)); }
  }

  async function saveSettings(showNotice = true) {
    try {
      const saved = await bridge<Settings>("save_settings", { settings });
      setSettings((current) => ({ ...current, ...saved }));
      if (showNotice) setMessage("生成设置已保存。");
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
    if (settings.schedule_enabled && !settings.export_root.trim()) {
      setMessage("启用定时生成前，请先选择独立的报告根目录。");
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
        last_chat_id: settings.schedule_chat_id,
        last_chat_name: settings.schedule_chat_name,
        schedule_last_run_date: today,
        schedule_last_status: "success",
      };
      setSettings((current) => ({ ...current, ...completed }));
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
    try { await openSystemPath(path); } catch (error) { setMessage(error instanceof Error ? error.message : String(error)); }
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
      const updated = await bridge<GenerationResult>("redact_report", { json_path: result.json_path, target_ids: selectedRedactions });
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

  return <div className="workspace">
      <header className="topbar"><div><p className="eyebrow">WECHAT · LOCAL INSIGHT</p><h1>微信群聊总结</h1></div><div className={`system-state ${wechatState}`}><span />{wechatState === "ready" ? "数据源已连接" : "等待连接数据源"}</div></header>
      <section className="notice" aria-live="polite"><strong>{busy ? "处理中" : "当前状态"}</strong><span>{message}</span></section>
      <div className="grid">
        <section className="panel source-panel">
          <div className="panel-heading"><div><span className="step-tag">01</span><h2>连接微信数据</h2></div><button className="button secondary" onClick={connectWeChat} disabled={wechatState === "testing" || busy}>{wechatState === "testing" ? "连接中…" : "测试并读取群聊"}</button></div>
          <label><span>WeChatDataAnalysis API</span><input readOnly value={settings.wechat_api_url} /></label>
          <div className="chat-picker"><div className="chat-search-control"><span>搜索群聊</span><div className="chat-search-row"><input aria-label="搜索群聊" placeholder="输入群聊名称" value={query} onChange={(e) => setQuery(e.target.value)} disabled={!chats.length} /><div className="mini-segmented" role="group" aria-label="群聊筛选"><button className={chatFilter === "all" ? "selected" : ""} onClick={() => setChatFilter("all")}>全部</button><button className={chatFilter === "summarized" ? "selected" : ""} onClick={() => setChatFilter("summarized")}>已总结</button></div></div></div><label><span>选择群聊</span><select value={chatId} onChange={(e) => setChatId(e.target.value)} disabled={!filteredChats.length}>{!filteredChats.length && <option value="">没有符合条件的群聊</option>}{filteredChats.map((chat) => <option key={chat.id} value={chat.id}>{chat.name}{summarized.has(chat.id) ? " · 已总结" : ""}</option>)}</select></label></div>
          {selectedChat && <p className="selection-note">本次总结：<strong>{selectedChat.name}</strong>{summarized.has(selectedChat.id) && <em>　已有历史报告</em>}</p>}
        </section>
        <section className="panel range-panel">
          <div className="panel-heading compact"><div><span className="step-tag">02</span><h2>选择统计日期</h2></div></div>
          <div className="segmented"><button className={settings.range_mode === "single" ? "selected" : ""} onClick={() => setSettings({ ...settings, range_mode: "single" })}>单日</button><button className={settings.range_mode === "custom" ? "selected" : ""} onClick={() => setSettings({ ...settings, range_mode: "custom" })}>自定义区间</button></div>
          {settings.range_mode === "single" ? <label><span>报告日期</span><input type="date" value={reportDate} onChange={(e) => setReportDate(e.target.value)} /></label> : <div className="date-grid"><label><span>开始日期</span><input type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)} /></label><label><span>结束日期</span><input type="date" value={endDate} onChange={(e) => setEndDate(e.target.value)} /></label></div>}
          <div className="quick-dates"><button onClick={() => { setReportDate(localDate()); setStartDate(localDate()); setEndDate(localDate()); }}>今天</button><button onClick={() => { setReportDate(localDate(-1)); setStartDate(localDate(-1)); setEndDate(localDate(-1)); }}>昨天</button></div>
        </section>
        <section className="panel ai-panel">
          <div className="panel-heading"><div><span className="step-tag">03</span><h2>当前 AI 分析</h2></div><button className="button secondary" onClick={onOpenSettings}>打开设置</button></div>
          <div className="mode-summary"><div><span>API Provider</span><strong>{settings.provider === "deepseek" ? "DeepSeek" : "OpenAI Compatible"}</strong></div><div><span>模型</span><strong>{settings.model || "尚未配置"}</strong></div></div>
          <p className="privacy-copy">软件生成总结时直接调用已配置的 AI API；MCP Server 是独立的外部调用入口。</p>
        </section>
        <section className="panel output-panel">
          <div className="panel-heading compact"><div><span className="step-tag">04</span><h2>报告目录与定时</h2></div></div>
          <label><span>独立报告根目录</span><div className="path-control"><input readOnly value={settings.export_root || "尚未配置"} /><button className="button secondary" onClick={onOpenSettings}>打开设置</button></div></label>
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
      {result && redactionEditorOpen && <RedactionEditor targets={redactionTargets} selectedIds={selectedRedactions} busy={redactionBusy} onClose={() => setRedactionEditorOpen(false)} onToggle={toggleRedaction} onApply={applyRedactions} />}
  </div>;
}
export default GeneratePage;
