import { CheckCircle2, CircleHelp, Pencil, Plus, RefreshCw, Trash2 } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import RedactionEditor from "../components/RedactionEditor";
import { generationSourceLabel } from "../contexts/GenerationTaskContext";
import { useReportGeneration } from "../hooks/useReportGeneration";
import { inclusiveDateRange, localDate, scheduledReportDate } from "../services/dates";
import { filterAndSortChats, type ChatListFilter } from "../services/chatList";
import { bridge, openSystemPath } from "../services/desktopBridge";
import {
  createScheduleTask,
  dueScheduleTasks,
  refreshScheduleTaskNames,
  SerialGenerationQueue,
  upsertScheduleTask,
} from "../services/scheduleTasks";
import { generationTaskPresentation } from "../services/generationTasks";
import { DATA_SOURCE_UNAVAILABLE_MESSAGE } from "../services/wechatDataSource";
import {
  INITIAL_SETTINGS,
  type Chat,
  type GenerationResult,
  type RedactionTarget,
  type ScheduleTask,
  type Settings,
} from "../types/desktop";

type ScheduleDraft = Pick<ScheduleTask, "chat_id" | "time" | "date_mode">;

function GeneratePage({
  active,
  onOpenSettings,
  onOpenGuide,
  dataSourceRefreshVersion,
}: {
  active: boolean;
  onOpenSettings: () => void;
  onOpenGuide: () => void;
  dataSourceRefreshVersion: number;
}) {
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
  const [wechatErrorDetail, setWechatErrorDetail] = useState("");
  const [redactionTargets, setRedactionTargets] = useState<RedactionTarget[]>([]);
  const [selectedRedactions, setSelectedRedactions] = useState<string[]>([]);
  const [redactionEditorOpen, setRedactionEditorOpen] = useState(false);
  const [redactionBusy, setRedactionBusy] = useState(false);
  const [scheduleEditorOpen, setScheduleEditorOpen] = useState(false);
  const [editingScheduleTaskId, setEditingScheduleTaskId] = useState<string | null>(null);
  const [scheduleDraft, setScheduleDraft] = useState<ScheduleDraft>({ chat_id: "", time: "22:30", date_mode: "today" });
  const [pendingDeleteTaskId, setPendingDeleteTaskId] = useState<string | null>(null);
  const [scheduledPendingCount, setScheduledPendingCount] = useState(0);
  const scheduleQueue = useRef(new SerialGenerationQueue());
  const scheduleCheckGuard = useRef(false);
  const settingsRef = useRef(settings);
  settingsRef.current = settings;
  const { busy, setBusy, progress, currentTask, result, setResult, batchResults, runGeneration, runBatchGeneration } = useReportGeneration({
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
  const runGenerationRef = useRef(runGeneration);
  runGenerationRef.current = runGeneration;

  useEffect(() => {
    if (!active) return;
    bridge<Settings>("get_state").then((saved) => {
      setSettings({ ...INITIAL_SETTINGS, ...saved });
    }).catch((error) => setMessage(String(error)));
  }, [active]);

  useEffect(() => {
    if (!active || dataSourceRefreshVersion === 0) return;
    void connectWeChat();
  }, [active, dataSourceRefreshVersion]);

  useEffect(() => {
    const checkSchedule = async () => {
      if (busy || scheduleCheckGuard.current) return;
      const now = new Date();
      const today = localDate();
      const clock = `${String(now.getHours()).padStart(2, "0")}:${String(now.getMinutes()).padStart(2, "0")}`;
      const due = dueScheduleTasks(settingsRef.current.schedule_tasks || [], today, clock);
      const enqueued = due.filter((task) => scheduleQueue.current.enqueue({
        key: `${task.chat_id}:${scheduledReportDate(today, task.date_mode)}`,
        scheduleTaskId: task.task_id,
        chatId: task.chat_id,
        chatName: task.chat_name,
        reportDate: scheduledReportDate(today, task.date_mode),
      }));
      if (!enqueued.length) return;
      scheduleCheckGuard.current = true;
      try {
        await persistScheduleTasks(
          settingsRef.current.schedule_tasks.map((task) => enqueued.some((item) => item.task_id === task.task_id)
            ? { ...task, last_run_status: "pending" as const }
            : task),
        );
        await scheduleQueue.current.drain(
          async (item) => {
            const task = settingsRef.current.schedule_tasks.find((candidate) => candidate.task_id === item.scheduleTaskId);
            if (!task?.enabled) return;
            await runScheduledGeneration(item.scheduleTaskId, item.chatId, task.chat_name || item.chatName, item.reportDate, today);
          },
          (pending) => setScheduledPendingCount(pending),
        );
      } catch (error) {
        scheduleQueue.current.clearPending();
        setScheduledPendingCount(0);
        setMessage(`定时队列状态保存失败：${error instanceof Error ? error.message : String(error)}`);
      } finally {
        scheduleCheckGuard.current = false;
      }
    };
    void checkSchedule();
    const timer = window.setInterval(() => void checkSchedule(), 30_000);
    return () => window.clearInterval(timer);
  }, [settings.schedule_tasks, busy]);

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
    setWechatState("testing"); setWechatErrorDetail(""); setMessage("正在读取本机群聊列表…");
    try {
      const data = await bridge<{ chats: Chat[]; account: string }>("list_chats", { settings: statusSettings() });
      const summarizedChatIds = data.chats.filter((chat) => chat.summarized).map((chat) => chat.id);
      const oldTasks = settingsRef.current.schedule_tasks || [];
      const refreshedTasks = refreshScheduleTaskNames(oldTasks, data.chats);
      const namesChanged = refreshedTasks.some((task, index) => task.chat_name !== oldTasks[index]?.chat_name);
      setChats(data.chats);
      setSettings((current) => ({ ...current, summarized_chat_ids: summarizedChatIds, schedule_tasks: refreshedTasks }));
      settingsRef.current = { ...settingsRef.current, summarized_chat_ids: summarizedChatIds, schedule_tasks: refreshedTasks };
      if (namesChanged) {
        await persistScheduleTasks(refreshedTasks);
        settingsRef.current = { ...settingsRef.current, summarized_chat_ids: summarizedChatIds };
        setSettings((current) => ({ ...current, summarized_chat_ids: summarizedChatIds }));
      }
      setWechatState("ready"); setWechatErrorDetail(""); setMessage(`已读取 ${data.chats.length} 个群聊，请选择群聊和日期。`);
      const remembered = data.chats.find((chat) => chat.id === settings.last_chat_id);
      if (remembered) setChatId(remembered.id); else if (data.chats.length && !chatId) setChatId(data.chats[0].id);
    } catch (error) {
      setWechatState("error");
      setWechatErrorDetail(error instanceof Error ? error.message : String(error));
      setMessage("未检测到 WeChatDataAnalysis 本地服务。请先完成数据源配置后再生成群聊总结。");
    }
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

  async function persistScheduleTasks(tasks: ScheduleTask[], successMessage?: string) {
    try {
      const saved = await bridge<Settings>("save_settings", { settings: { schedule_tasks: tasks, schedule_config_version: 2 } });
      setSettings((current) => ({ ...current, ...saved }));
      settingsRef.current = { ...settingsRef.current, ...saved };
      if (successMessage) setMessage(successMessage);
      return saved;
    } catch (error) {
      if (successMessage) setMessage(`定时任务保存失败：${error instanceof Error ? error.message : String(error)}`);
      throw error;
    }
  }

  function openNewScheduleEditor() {
    setEditingScheduleTaskId(null);
    setScheduleDraft({ chat_id: selectedChat?.id || chats[0]?.id || "", time: "22:30", date_mode: "today" });
    setPendingDeleteTaskId(null);
    setScheduleEditorOpen(true);
  }

  function openScheduleEditor(task: ScheduleTask) {
    setEditingScheduleTaskId(task.task_id);
    setScheduleDraft({ chat_id: task.chat_id, time: task.time, date_mode: task.date_mode });
    setPendingDeleteTaskId(null);
    setScheduleEditorOpen(true);
  }

  async function saveScheduleTask() {
    const currentTasks = settingsRef.current.schedule_tasks || [];
    const existing = editingScheduleTaskId ? currentTasks.find((task) => task.task_id === editingScheduleTaskId) : undefined;
    const chat = chats.find((item) => item.id === scheduleDraft.chat_id)
      || (existing?.chat_id === scheduleDraft.chat_id ? { id: existing.chat_id, name: existing.chat_name } : undefined);
    if (!chat) return setMessage("请选择一个当前可用的群聊。");
    if (!settingsRef.current.export_root.trim()) return setMessage("添加定时任务前，请先选择独立的报告根目录。");
    const duplicate = currentTasks.find((task) => task.chat_id === chat.id && task.task_id !== editingScheduleTaskId);
    if (duplicate) {
      openScheduleEditor(duplicate);
      return setMessage("该群聊已设置定时总结，可直接修改现有任务。");
    }
    try {
      const base = existing || createScheduleTask(chat, scheduleDraft.time, scheduleDraft.date_mode);
      const task = { ...base, chat_id: chat.id, chat_name: chat.name, time: scheduleDraft.time, date_mode: scheduleDraft.date_mode };
      const next = upsertScheduleTask(currentTasks, task);
      await persistScheduleTasks(next, existing ? "定时总结任务已更新。" : "定时总结任务已添加；仅软件保持运行时执行。");
      setScheduleEditorOpen(false);
      setEditingScheduleTaskId(null);
    } catch (error) {
      setMessage(`定时任务保存失败：${error instanceof Error ? error.message : String(error)}`);
    }
  }

  async function toggleScheduleTask(task: ScheduleTask) {
    if (!settingsRef.current.export_root.trim() && !task.enabled) return setMessage("启用定时任务前，请先选择独立的报告根目录。");
    const next = settingsRef.current.schedule_tasks.map((item) => item.task_id === task.task_id ? { ...item, enabled: !item.enabled } : item);
    try {
      await persistScheduleTasks(next, task.enabled ? "定时总结任务已停用，配置仍保留。" : "定时总结任务已启用。");
    } catch {
      // persistScheduleTasks 已提供可读错误。
    }
  }

  async function deleteScheduleTask(task: ScheduleTask) {
    try {
      await persistScheduleTasks(
        settingsRef.current.schedule_tasks.filter((item) => item.task_id !== task.task_id),
        `已删除“${task.chat_name}”的定时总结任务。`,
      );
      setPendingDeleteTaskId(null);
      if (editingScheduleTaskId === task.task_id) setScheduleEditorOpen(false);
    } catch {
      // persistScheduleTasks 已提供可读错误。
    }
  }

  async function generate() {
    if (!chatId) return setMessage("请选择一个群聊。");
    if (!settings.export_root.trim()) return setMessage("请先选择独立的报告根目录。");
    const start = settings.range_mode === "single" ? reportDate : startDate;
    const end = settings.range_mode === "single" ? reportDate : endDate;
    if (end < start) return setMessage("结束日期不能早于开始日期。");
    try {
      if (settings.range_mode === "custom" && settings.range_output_mode === "daily") {
        await runBatchGeneration(chatId, selectedChat?.name || "", inclusiveDateRange(start, end, 7));
      } else {
        await runGeneration(chatId, selectedChat?.name || "", start, end, settings.range_mode);
      }
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error));
    }
  }

  async function retryBatchDate(date: string) {
    if (!chatId) return;
    try {
      await runBatchGeneration(chatId, selectedChat?.name || "", [date], true);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error));
    }
  }

  async function runScheduledGeneration(taskId: string, targetChatId: string, targetChatName: string, reportDate: string, triggerDate: string) {
    const mark = async (patch: Partial<ScheduleTask>) => {
      const tasks = settingsRef.current.schedule_tasks.map((task) => task.task_id === taskId ? { ...task, ...patch } : task);
      await persistScheduleTasks(tasks);
    };
    try {
      await mark({ last_attempt_date: triggerDate, last_run_status: "running" });
      await runGenerationRef.current(targetChatId, targetChatName, reportDate, reportDate, "single", { source: "scheduled" });
      await mark({ last_run_at: new Date().toISOString(), last_report_date: reportDate, last_run_status: "success" });
      setMessage(`定时报告已生成：${targetChatName} · ${reportDate}。`);
    } catch (error) {
      try {
        await mark({ last_attempt_date: triggerDate, last_run_at: new Date().toISOString(), last_run_status: "failed" });
      } catch {
        // 保留原始生成错误；下一次刷新仍可从任务列表看到最后状态。
      }
      setMessage(`定时日报执行失败：${error instanceof Error ? error.message : String(error)}`);
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

  async function openRedactionEditor(targetResult = result) {
    if (!targetResult?.json_path) return;
    setRedactionBusy(true);
    try {
      setResult(targetResult);
      const data = await loadRedactionTargets(targetResult.json_path);
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
  let selectedDayCount = 1;
  if (settings.range_mode === "custom" && settings.range_output_mode === "daily") {
    try { selectedDayCount = inclusiveDateRange(startDate, endDate, 7).length; } catch { selectedDayCount = 0; }
  }
  const isDailyBatch = settings.range_mode === "custom" && settings.range_output_mode === "daily";
  const dockTask = generationTaskPresentation(currentTask, {
    chat_name: selectedChat?.name || "尚未选择群聊",
    start_date: activeStart,
    end_date: activeEnd,
  });
  const dockChatName = dockTask.chat_name;
  const dockStart = dockTask.start_date;
  const dockEnd = dockTask.end_date;
  const scheduleStatusLabel = (status: ScheduleTask["last_run_status"]) => status === "success"
    ? "成功"
    : status === "failed"
      ? "失败"
      : status === "running"
        ? "执行中"
        : status === "pending"
          ? "等待中"
          : "尚未执行";

  return <div className="workspace">
      <header className="topbar"><div><h1>生成总结</h1></div></header>
      <section className="notice" aria-live="polite"><strong>{busy ? "处理中" : wechatState === "error" ? "数据源未就绪" : "当前状态"}</strong><span>{message}</span></section>
      <div className="grid">
        <section className="panel source-panel">
          <div className="panel-heading"><div><span className="step-tag">1</span><h2>连接微信数据</h2></div><div className="heading-actions">{wechatState === "error" && <button className="button ghost inline-icon" onClick={onOpenGuide}><CircleHelp size={14} aria-hidden="true" />如何配置？</button>}<button className="button secondary inline-icon" onClick={connectWeChat} disabled={wechatState === "testing" || busy}><RefreshCw size={14} className={wechatState === "testing" ? "spinning" : ""} aria-hidden="true" />{wechatState === "testing" ? "检测中…" : wechatState === "error" ? "重新检测" : "测试并读取群聊"}</button></div></div>
          <label><span>WeChatDataAnalysis API</span><input readOnly value={settings.wechat_api_url} /></label>
          {wechatState === "error" && <div className="data-source-guidance"><strong>数据源未就绪</strong><p>{DATA_SOURCE_UNAVAILABLE_MESSAGE} 请先完成数据源配置后再生成群聊总结。</p>{wechatErrorDetail && <details><summary>连接详情</summary><code>{wechatErrorDetail}</code></details>}</div>}
          <div className="chat-picker"><div className="chat-search-control"><span>搜索群聊</span><div className="chat-search-row"><input aria-label="搜索群聊" placeholder="输入群聊名称" value={query} onChange={(e) => setQuery(e.target.value)} disabled={!chats.length} /><div className="mini-segmented" role="group" aria-label="群聊筛选"><button className={chatFilter === "all" ? "selected" : ""} onClick={() => setChatFilter("all")}>全部</button><button className={chatFilter === "summarized" ? "selected" : ""} onClick={() => setChatFilter("summarized")}>已总结</button></div></div></div><label><span>选择群聊</span><select value={chatId} onChange={(e) => setChatId(e.target.value)} disabled={!filteredChats.length}>{!filteredChats.length && <option value="">没有符合条件的群聊</option>}{filteredChats.map((chat) => <option key={chat.id} value={chat.id}>{chat.name}{summarized.has(chat.id) ? " · 已总结" : ""}</option>)}</select></label></div>
          {selectedChat && <p className="selection-note">本次总结：<strong>{selectedChat.name}</strong>{summarized.has(selectedChat.id) && <em>　已有历史报告</em>}</p>}
        </section>
        <section className="panel range-panel">
          <div className="panel-heading compact"><div><span className="step-tag">2</span><h2>选择统计日期</h2></div></div>
          <div className="segmented"><button className={settings.range_mode === "single" ? "selected" : ""} onClick={() => setSettings({ ...settings, range_mode: "single" })}>单日</button><button className={settings.range_mode === "custom" ? "selected" : ""} onClick={() => setSettings({ ...settings, range_mode: "custom" })}>自定义区间</button></div>
          {settings.range_mode === "single" ? <label><span>报告日期</span><input type="date" value={reportDate} onChange={(e) => setReportDate(e.target.value)} /></label> : <><div className="date-grid"><label><span>开始日期</span><input type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)} /></label><label><span>结束日期</span><input type="date" value={endDate} onChange={(e) => setEndDate(e.target.value)} /></label></div><div className="range-output-mode"><span>生成方式</span><div className="mini-segmented" role="group" aria-label="区间生成方式"><button className={settings.range_output_mode === "daily" ? "selected" : ""} onClick={() => setSettings({ ...settings, range_output_mode: "daily" })}>每日分别生成</button><button className={settings.range_output_mode === "combined" ? "selected" : ""} onClick={() => setSettings({ ...settings, range_output_mode: "combined" })}>合并成一份</button></div><small>{settings.range_output_mode === "daily" ? "按自然日依次生成，单次最多 7 天" : "将整个区间的消息合并分析"}</small></div></>}
          <div className="quick-dates"><button onClick={() => { setReportDate(localDate()); setStartDate(localDate()); setEndDate(localDate()); }}>今天</button><button onClick={() => { setReportDate(localDate(-1)); setStartDate(localDate(-1)); setEndDate(localDate(-1)); }}>昨天</button></div>
        </section>
        <section className="panel ai-panel">
          <div className="panel-heading"><div><span className="step-tag">3</span><h2>AI 分析</h2></div><button className="button secondary" onClick={onOpenSettings}>打开设置</button></div>
          <div className="mode-summary"><div><span>AI 服务</span><strong>{settings.provider === "deepseek" ? "DeepSeek" : "OpenAI Compatible"}</strong></div><div><span>模型</span><strong>{settings.model || "尚未配置"}</strong></div></div>
          <p className="privacy-copy">软件生成总结时直接调用已配置的 AI API；MCP Server 是独立的外部调用入口。</p>
        </section>
        <section className="panel output-panel">
          <div className="panel-heading compact"><div><span className="step-tag">4</span><h2>报告目录与定时</h2></div></div>
          <label><span>独立报告根目录</span><div className="path-control"><input readOnly value={settings.export_root || "尚未配置"} /><button className="button secondary" onClick={onOpenSettings}>打开设置</button></div></label>
          <div className="archive-preview"><span>自动归档</span><code>群聊 / 导出图 / 年 / 月</code><code>群聊 / 报告数据 / 日期报告数据</code></div>
          <div className="schedule-box schedule-manager">
            <div className="schedule-title"><div><strong>定时总结管理</strong><small>每个群聊一项独立任务；仅软件保持运行时执行</small></div><button className="button secondary small inline-icon" disabled={busy || !chats.length} onClick={openNewScheduleEditor}><Plus size={14} aria-hidden="true" />添加定时总结</button></div>
            {scheduledPendingCount > 0 && <p className="schedule-queue-status">另有 {scheduledPendingCount} 项定时任务正在等待串行执行。</p>}
            <div className="schedule-task-list">
              {(settings.schedule_tasks || []).map((task) => <article className={`schedule-task-row ${task.enabled ? "enabled" : "disabled"}`} key={task.task_id}>
                <div className="schedule-task-main"><div><strong>{task.chat_name}</strong><span>每天 {task.time} · 生成{task.date_mode === "yesterday" ? "昨日" : "当日"}报告</span></div><label className="switch" title={task.enabled ? "停用任务" : "启用任务"}><input type="checkbox" checked={task.enabled} disabled={busy} onChange={() => void toggleScheduleTask(task)} /><span /></label></div>
                <div className="schedule-task-meta"><span>{task.enabled ? "已启用" : "已停用"}</span><span>{task.last_run_at ? `上次执行：${task.last_run_at.slice(0, 16).replace("T", " ")} · ${scheduleStatusLabel(task.last_run_status)}` : `上次执行：${scheduleStatusLabel(task.last_run_status)}`}</span>{task.last_report_date && <span>报告日期：{task.last_report_date}</span>}</div>
                <div className="schedule-task-actions"><button className="button ghost small inline-icon" disabled={busy} onClick={() => openScheduleEditor(task)}><Pencil size={13} aria-hidden="true" />编辑</button><button className="button ghost small inline-icon" disabled={busy} onClick={() => setPendingDeleteTaskId(task.task_id)}><Trash2 size={13} aria-hidden="true" />删除</button></div>
                {pendingDeleteTaskId === task.task_id && <div className="schedule-delete-confirm" role="alert"><div><strong>删除定时总结？</strong><span>删除后将不再自动生成该群聊的定时报告。</span></div><div><button className="button secondary small" onClick={() => setPendingDeleteTaskId(null)}>取消</button><button className="button danger small" onClick={() => void deleteScheduleTask(task)}>删除</button></div></div>}
              </article>)}
              {!settings.schedule_tasks?.length && <div className="schedule-empty">尚未设置定时总结。添加后，各群聊会按自己的时间依次生成。</div>}
            </div>
            {scheduleEditorOpen && <div className="schedule-editor" aria-label={editingScheduleTaskId ? "编辑定时总结" : "添加定时总结"}>
              <strong>{editingScheduleTaskId ? "编辑定时总结" : "添加定时总结"}</strong>
              <div className="schedule-fields"><label><span>群聊</span><select value={scheduleDraft.chat_id} disabled={Boolean(editingScheduleTaskId)} onChange={(event) => setScheduleDraft({ ...scheduleDraft, chat_id: event.target.value })}>{editingScheduleTaskId && !chats.some((chat) => chat.id === scheduleDraft.chat_id) && <option value={scheduleDraft.chat_id}>{settings.schedule_tasks.find((task) => task.task_id === editingScheduleTaskId)?.chat_name || scheduleDraft.chat_id}</option>}{chats.map((chat) => <option value={chat.id} key={chat.id}>{chat.name}</option>)}</select></label><label><span>每日时间</span><input type="time" value={scheduleDraft.time} onChange={(event) => setScheduleDraft({ ...scheduleDraft, time: event.target.value })} /></label></div>
              <div className="schedule-date-mode"><span>报告日期</span><div className="mini-segmented" role="group" aria-label="定时报告日期"><button className={scheduleDraft.date_mode === "today" ? "selected" : ""} onClick={() => setScheduleDraft({ ...scheduleDraft, date_mode: "today" })}>当日</button><button className={scheduleDraft.date_mode === "yesterday" ? "selected" : ""} onClick={() => setScheduleDraft({ ...scheduleDraft, date_mode: "yesterday" })}>昨日</button></div></div>
              <div className="schedule-actions"><button className="button secondary small" onClick={() => setScheduleEditorOpen(false)}>取消</button><button className="button primary small" onClick={() => void saveScheduleTask()}>保存任务</button></div>
            </div>}
          </div>
        </section>
      </div>
      <section className={`action-dock ${result || batchResults.length ? "has-result" : ""}`}><div><strong>{dockChatName}{currentTask ? ` · ${generationSourceLabel(currentTask.source)}` : ""}</strong><span>{dockStart === dockEnd ? dockStart : `${dockStart} 至 ${dockEnd}`}{!currentTask && isDailyBatch && selectedDayCount ? ` · ${selectedDayCount} 份单日报告` : ""} · PNG {settings.image_dpi} DPI</span>{progress && <div className="progress-wrap"><i><b style={{ width: `${progress.percent}%` }} /></i><small>{progress.percent}% · {progress.message} · 已用 {Math.round(progress.elapsed_seconds)} 秒</small></div>}</div><button className="button primary" onClick={generate} disabled={busy || !chatId}>{busy ? "正在生成…" : isDailyBatch && selectedDayCount ? `生成 ${selectedDayCount} 份单日报告` : "生成群聊总结"}</button></section>
      {batchResults.length > 0 && <section className="batch-result-panel"><div className="batch-result-heading"><div><h2>逐日生成结果</h2><p>每个日期均独立归档；失败日期可单独重试。</p></div><strong>{batchResults.filter((item) => item.status === "success").length}/{batchResults.length} 成功</strong></div><div className="batch-result-list">{batchResults.map((item) => <article key={item.date} className={`batch-result-row status-${item.status}`}><div><strong>{item.date}</strong><span>{item.status === "success" ? `已生成${item.result?.version ? ` · v${item.result.version}` : ""}` : item.status === "skipped" ? "无消息，已跳过" : "生成失败"}</span>{item.status === "failed" && item.message && <small title={item.message}>{item.message}</small>}</div><div>{item.status === "success" && <><button className="button secondary small" onClick={() => openPath(item.result?.png_path)}>打开图片</button><button className="button ghost small" onClick={() => openPath(item.result?.html_path)}>打开 HTML</button><button className="button ghost small" disabled={redactionBusy} onClick={() => openRedactionEditor(item.result)}>编辑内容</button></>}{item.status === "failed" && <button className="button secondary small" disabled={busy} onClick={() => retryBatchDate(item.date)}>重试</button>}</div></article>)}</div></section>}
      {result && batchResults.length === 0 && <section className="result-panel"><div className="result-copy"><CheckCircle2 className="result-check" size={36} aria-hidden="true" /><div><h2>报告生成完成{result.version ? ` · v${result.version}` : ""}</h2><p>PNG 与 HTML 已生成，旧版本不会被覆盖。</p></div></div><div className="result-actions"><button className="button primary small" onClick={() => openPath(result.png_path)}>打开图片</button><button className="button secondary" onClick={() => openPath(result.html_path)}>打开 HTML</button><button className="button secondary" onClick={() => openPath(result.chat_dir || result.data_dir)}>打开报告所在目录</button><button className="button ghost" disabled={redactionBusy} onClick={() => openRedactionEditor()}>{redactionBusy ? "读取中…" : "编辑并屏蔽内容"}</button></div></section>}
      {result && redactionEditorOpen && <RedactionEditor targets={redactionTargets} selectedIds={selectedRedactions} busy={redactionBusy} onClose={() => setRedactionEditorOpen(false)} onToggle={toggleRedaction} onApply={applyRedactions} />}
  </div>;
}
export default GeneratePage;
