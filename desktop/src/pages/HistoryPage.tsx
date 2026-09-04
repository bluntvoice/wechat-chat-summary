import { EyeOff } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { RedactionTargetGroups } from "../components/RedactionEditor";
import { bridge, openSystemPath } from "../services/desktopBridge";
import type {
  GenerationResult,
  HistoryChat,
  HistoryModule,
  HistoryReport,
  HistoryReportDetail,
  HistorySearchHit,
  HistoryNavigationTarget,
  Paginated,
  RedactionTarget,
} from "../types/desktop";

type HistoryPageProps = { active: boolean; target?: HistoryNavigationTarget | null };

const MODULE_OPTIONS = [
  ["all", "全部"],
  ["topics", "主要话题"],
  ["ai_observations", "AI 今日观察"],
  ["member_activity", "成员 / 活跃情况"],
  ["outcome", "讨论结论"],
  ["open_questions", "开放问题"],
  ["risk_flags", "风险提示"],
  ["quotes", "代表性原话"],
  ["resources", "资源"],
] as const;

const FIELD_LABELS: Record<string, string> = {
  discussion_flow: "讨论脉络",
  content: "内容",
  summary: "摘要",
  task: "事项",
  question: "问题",
  quote: "原话",
  speaker: "发言人",
  owner: "负责人",
  name: "成员",
  insight: "观察",
  topic_title: "所属话题",
  topic: "资源主题",
  type: "类型",
  url: "链接",
  sender: "发送者",
  sent_at: "发送时间",
  context_summary: "上下文摘要",
  time_ranges: "讨论时段",
  start_time: "开始时间",
  end_time: "结束时间",
  time_label: "所属时间",
  notice: "说明",
  message_count: "消息数",
  effective_message_count: "有效消息数",
  participant_count: "参与人数",
  top_speakers: "发言排行",
  word_cloud: "群关键词",
  time_segment_breakdown: "活跃时段",
  count: "数量",
  rank: "排名",
  word: "关键词",
};

const HIDDEN_FIELDS = new Set([
  "id", "topic_id", "resource_id", "metadata", "redacted", "tone", "confidence",
  "sender_id", "sender_username", "username", "title", "start_time", "end_time",
  "redaction_id", "redaction_target_id", "message_id", "file_size", "source",
]);

function datePart(value: string) {
  return value.slice(0, 10);
}

function periodLabel(start: string, end: string) {
  const startDate = datePart(start);
  const endDate = datePart(end);
  return startDate === endDate ? startDate : `${startDate} 至 ${endDate}`;
}

function resolveMemberTokens(value: string, memberNames: Record<string, string> = {}) {
  return value.replace(/\[\[user:([^\]]+)\]\]/g, (_match, senderId: string) => memberNames[senderId] || "群成员");
}

function flattenText(value: unknown): string {
  if (value == null) return "";
  if (typeof value === "string") return resolveMemberTokens(value);
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  if (Array.isArray(value)) return value.map(flattenText).filter(Boolean).join(" · ");
  if (typeof value === "object") return Object.entries(value as Record<string, unknown>)
    .filter(([key]) => !HIDDEN_FIELDS.has(key))
    .map(([, item]) => flattenText(item)).filter(Boolean).join(" · ");
  return "";
}

function searchSnippet(value: string) {
  try {
    return flattenText(JSON.parse(value)).slice(0, 180);
  } catch {
    return value.slice(0, 180);
  }
}

function ValueView({ value, memberNames, fieldKey = "" }: { value: unknown; memberNames: Record<string, string>; fieldKey?: string }) {
  if (value == null || value === "") return null;
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") {
    const text = resolveMemberTokens(String(value), memberNames);
    return <span className={/^https?:\/\//i.test(text) ? "history-url" : ""}>{text}</span>;
  }
  if (Array.isArray(value)) {
    if (fieldKey === "time_ranges") {
      const ranges = value.map((item) => {
        if (!item || typeof item !== "object") return "";
        const range = item as Record<string, unknown>;
        const start = String(range.start || range.start_time || "").trim();
        const end = String(range.end || range.end_time || start).trim();
        return start && end && start !== end ? `${start} 至 ${end}` : start || end;
      }).filter(Boolean);
      return <div className="history-time-ranges">{ranges.map((range) => <span key={range}>{range}</span>)}</div>;
    }
    return <ul className="history-value-list">{value.map((item, index) => <li key={index}><ValueView value={item} memberNames={memberNames} /></li>)}</ul>;
  }
  const entries = Object.entries(value as Record<string, unknown>)
    .filter(([key, item]) => !HIDDEN_FIELDS.has(key) && item !== "" && item != null && !(Array.isArray(item) && !item.length));
  return <dl className="history-value-grid">{entries.map(([key, item]) => <div key={key}><dt>{FIELD_LABELS[key] || key}</dt><dd><ValueView value={item} memberNames={memberNames} fieldKey={key} /></dd></div>)}</dl>;
}

function ActivityStatsView({ value, memberNames }: { value: unknown; memberNames: Record<string, string> }) {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return <ValueView value={value} memberNames={memberNames} />;
  }
  const stats = value as Record<string, unknown>;
  const speakers = (Array.isArray(stats.top_speakers) ? stats.top_speakers : [])
    .filter((item): item is Record<string, unknown> => Boolean(item && typeof item === "object" && !Array.isArray(item)))
    .slice(0, 5);
  const keywords = (Array.isArray(stats.word_cloud) ? stats.word_cloud : [])
    .filter((item): item is Record<string, unknown> => Boolean(item && typeof item === "object" && !Array.isArray(item) && item.word))
    .slice(0, 12);
  const segments = (Array.isArray(stats.time_segment_breakdown) ? stats.time_segment_breakdown : [])
    .filter((item): item is Record<string, unknown> => Boolean(item && typeof item === "object" && !Array.isArray(item)));
  const metricCandidates: Array<[string, unknown]> = [
    ["消息数", stats.message_count],
    ["有效消息", stats.effective_message_count],
    ["参与人数", stats.participant_count],
  ];
  const metrics = metricCandidates.filter(([, count]) => count !== undefined && count !== null && count !== "");
  const speakerMax = Math.max(1, ...speakers.map((item) => Number(item.message_count) || 0));
  const segmentMax = Math.max(1, ...segments.map((item) => Number(item.count) || 0));

  return <div className="history-activity-stats">
    {metrics.length > 0 && <dl className="history-activity-metrics">{metrics.map(([label, count]) => <div key={String(label)}><dt>{label}</dt><dd>{String(count)}</dd></div>)}</dl>}
    {speakers.length > 0 && <section className="history-activity-block"><h4>发言排行</h4><ol className="history-speaker-list">{speakers.map((item, index) => {
      const count = Number(item.message_count) || 0;
      return <li key={`${String(item.name || "群成员")}-${index}`}><span>{Number(item.rank) || index + 1}</span><strong>{resolveMemberTokens(String(item.name || "群成员"), memberNames)}</strong><i aria-hidden="true"><b style={{ width: `${Math.max(3, Math.round(count / speakerMax * 100))}%` }} /></i><em>{count} 条</em></li>;
    })}</ol></section>}
    {keywords.length > 0 && <section className="history-activity-block"><h4>群关键词</h4><div className="history-keyword-list">{keywords.map((item, index) => <span key={`${String(item.word)}-${index}`}>{resolveMemberTokens(String(item.word), memberNames)}<small>{Number(item.count) || ""}</small></span>)}</div></section>}
    {segments.length > 0 && <section className="history-activity-block"><h4>活跃时段</h4><div className="history-segment-list">{segments.map((item, index) => {
      const count = Number(item.count) || 0;
      return <div key={`${String(item.label || "时段")}-${index}`}><span>{String(item.label || "时段")}</span><i aria-hidden="true"><b style={{ width: `${Math.max(3, Math.round(count / segmentMax * 100))}%` }} /></i><strong>{count}</strong></div>;
    })}</div></section>}
  </div>;
}

function isActivityStatsModule(module: HistoryModule) {
  if (module.module_key !== "member_activity" || !module.content || typeof module.content !== "object" || Array.isArray(module.content)) return false;
  const content = module.content as Record<string, unknown>;
  return ["top_speakers", "word_cloud", "time_segment_breakdown", "message_count", "participant_count"]
    .some((key) => key in content);
}

function resourceDomain(value: string) {
  try {
    return new URL(value).hostname.replace(/^www\./, "");
  } catch {
    return value.length > 54 ? `${value.slice(0, 51)}…` : value;
  }
}

function resourcePlatform(value: string, type: string) {
  if (type === "file") return { key: "file", label: "文件" };
  let host = "";
  try { host = new URL(value).hostname.replace(/^www\./, "").toLowerCase(); } catch { return { key: "web", label: "网页" }; }
  const matches = (...domains: string[]) => domains.some((domain) => host === domain || host.endsWith(`.${domain}`));
  if (matches("xiaohongshu.com", "xhslink.com")) return { key: "xiaohongshu", label: "小红书" };
  if (matches("taobao.com", "tmall.com", "tb.cn")) return { key: "taobao", label: "淘宝 / 天猫" };
  if (matches("mp.weixin.qq.com")) return { key: "wechat", label: "公众号" };
  if (matches("zhihu.com")) return { key: "zhihu", label: "知乎" };
  if (matches("jd.com", "3.cn")) return { key: "jd", label: "京东" };
  if (matches("douyin.com", "iesdouyin.com")) return { key: "douyin", label: "抖音" };
  if (matches("bilibili.com", "b23.tv")) return { key: "bilibili", label: "哔哩哔哩" };
  if (matches("weibo.com", "weibo.cn")) return { key: "weibo", label: "微博" };
  return { key: "web", label: "网页" };
}

function ResourcePreview({ value, memberNames }: { value: unknown; memberNames: Record<string, string> }) {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return <ValueView value={value} memberNames={memberNames} />;
  }
  const resource = value as Record<string, unknown>;
  const type = String(resource.type || "").toLowerCase() === "file" ? "file" : "link";
  const topic = String(resource.topic || "").trim();
  const context = resolveMemberTokens(String(resource.context_summary || "").trim(), memberNames);
  const senderId = String(resource.sender_id || "").trim();
  const sender = senderId
    ? memberNames[senderId] || resolveMemberTokens(String(resource.sender || "群成员").trim(), memberNames)
    : resolveMemberTokens(String(resource.sender || "").trim(), memberNames);
  const sentAt = String(resource.sent_at || "").trim().slice(0, 16);
  const url = String(resource.url || "").trim();
  const platform = resourcePlatform(url, type);
  const metadata = [sender, sentAt].filter(Boolean);
  const showTopic = topic && topic !== "其他 / 未归类" && topic !== "其他/未归类";

  return <div className="history-resource-preview">
    <div className="history-resource-tags"><span className={`platform-${platform.key}`}>{platform.label}</span>{showTopic && <small>{topic}</small>}</div>
    {context && <p>{context}</p>}
    {metadata.length > 0 && <div className="history-resource-meta">{metadata.join(" · ")}</div>}
    {url && <div className="history-resource-domain" title={url}>{resourceDomain(url)}</div>}
  </div>;
}

function ModuleCard({
  module,
  memberNames,
  redactionMode,
  target,
  selected,
  onToggle,
}: {
  module: HistoryModule;
  memberNames: Record<string, string>;
  redactionMode: boolean;
  target?: RedactionTarget;
  selected: boolean;
  onToggle: (target: RedactionTarget) => void;
}) {
  const redacted = Boolean(module.content && typeof module.content === "object" && !Array.isArray(module.content) && (module.content as Record<string, unknown>).redacted);
  const selectable = Boolean(redactionMode && target && !target.redacted);
  function toggle() {
    if (selectable && target) onToggle(target);
  }
  return <article
    className={`history-module module-${module.module_key}${redactionMode && target ? " redaction-selectable" : ""}${selected ? " redaction-selected" : ""}${target?.redacted ? " redaction-locked" : ""}`}
    role={selectable ? "checkbox" : undefined}
    aria-checked={selectable ? selected : undefined}
    tabIndex={selectable ? 0 : undefined}
    onClick={toggle}
    onKeyDown={(event) => {
      if (selectable && (event.key === "Enter" || event.key === " ")) {
        event.preventDefault();
        toggle();
      }
    }}
  >
    <div className="history-module-heading"><span>{module.module_label}</span><h3>{redacted ? "已屏蔽内容" : resolveMemberTokens(module.title, memberNames)}</h3>{redactionMode && target && <span className="history-redaction-state">{target.redacted ? "已屏蔽" : selected ? "已选择" : "选择屏蔽"}</span>}</div>
    {isActivityStatsModule(module)
      ? <ActivityStatsView value={module.content} memberNames={memberNames} />
      : module.module_key === "resources"
        ? <ResourcePreview value={module.content} memberNames={memberNames} />
        : <ValueView value={module.content} memberNames={memberNames} />}
  </article>;
}

export default function HistoryPage({ active, target }: HistoryPageProps) {
  const [chats, setChats] = useState<HistoryChat[]>([]);
  const [chatQuery, setChatQuery] = useState("");
  const [selectedChatId, setSelectedChatId] = useState("");
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [moduleFilter, setModuleFilter] = useState("all");
  const [keyword, setKeyword] = useState("");
  const [reports, setReports] = useState<HistoryReport[]>([]);
  const [searchHits, setSearchHits] = useState<HistorySearchHit[]>([]);
  const [resultTotal, setResultTotal] = useState(0);
  const [selectedReportId, setSelectedReportId] = useState("");
  const [detail, setDetail] = useState<HistoryReportDetail | null>(null);
  const [versions, setVersions] = useState<HistoryReport[]>([]);
  const [detailModule, setDetailModule] = useState("all");
  const [busy, setBusy] = useState(false);
  const [historyRevision, setHistoryRevision] = useState(0);
  const [redactionMode, setRedactionMode] = useState(false);
  const [redactionTargets, setRedactionTargets] = useState<RedactionTarget[]>([]);
  const [selectedRedactions, setSelectedRedactions] = useState<string[]>([]);
  const [redactionBusy, setRedactionBusy] = useState(false);
  const [message, setMessage] = useState("历史数据仅来自本机 SQLite，不搜索完整原始聊天正文。");

  const visibleChats = useMemo(() => {
    const needle = chatQuery.trim().toLocaleLowerCase("zh-CN");
    return needle ? chats.filter((chat) => chat.display_name.toLocaleLowerCase("zh-CN").includes(needle)) : chats;
  }, [chats, chatQuery]);

  async function refreshHistory(importReports = true) {
    setBusy(true);
    setMessage(importReports ? "正在索引报告目录并刷新历史状态…" : "正在刷新历史中心…");
    try {
      const state = await bridge<{ history_import?: { imported?: number; failed?: number } }>("refresh_history_state", {
        import_reports: importReports,
      });
      const response = await bridge<{ items: HistoryChat[] }>("list_history_chats");
      setChats(response.items);
      setSelectedChatId((current) => response.items.some((chat) => chat.chat_id === current) ? current : response.items[0]?.chat_id || "");
      const imported = state.history_import?.imported || 0;
      const failed = state.history_import?.failed || 0;
      setHistoryRevision((current) => current + 1);
      setMessage(failed ? `历史刷新完成，导入 ${imported} 份，${failed} 份无法读取。` : `历史刷新完成${imported ? `，新导入 ${imported} 份报告` : ""}。`);
    } catch (error) {
      setMessage(`历史刷新失败：${error instanceof Error ? error.message : String(error)}`);
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    if (active) void refreshHistory(true);
  }, [active]);

  useEffect(() => {
    if (!active || !target) return;
    setSelectedChatId(target.chatId);
    setStartDate(target.date);
    setEndDate(target.date);
    setKeyword("");
    setModuleFilter("all");
    setDetailModule("all");
    setSelectedReportId(target.reportId);
  }, [active, target?.requestId]);

  useEffect(() => {
    if (!active || !selectedChatId) {
      setReports([]);
      setSearchHits([]);
      setSelectedReportId("");
      return;
    }
    let cancelled = false;
    const timer = window.setTimeout(async () => {
      setBusy(true);
      try {
        const common = {
          chat_id: selectedChatId,
          start_date: startDate,
          end_date: endDate,
          module_filter: moduleFilter,
          version_strategy: "latest",
          limit: 100,
          offset: 0,
        };
        if (keyword.trim()) {
          const response = await bridge<Paginated<HistorySearchHit>>("search_history", { ...common, keyword: keyword.trim() });
          if (cancelled) return;
          setSearchHits(response.items);
          setReports([]);
          setResultTotal(response.total);
          setSelectedReportId(response.items[0]?.report_id || "");
          setDetailModule(response.items[0]?.module_key || moduleFilter);
        } else {
          const response = await bridge<Paginated<HistoryReport>>("list_history_reports", common);
          if (cancelled) return;
          setReports(response.items);
          setSearchHits([]);
          setResultTotal(response.total);
          const ids = response.items.map((item) => item.report_id);
          setSelectedReportId((current) => ids.includes(current) ? current : ids[0] || "");
          setDetailModule(moduleFilter);
        }
      } catch (error) {
        if (!cancelled) setMessage(`历史查询失败：${error instanceof Error ? error.message : String(error)}`);
      } finally {
        if (!cancelled) setBusy(false);
      }
    }, 220);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [active, selectedChatId, startDate, endDate, moduleFilter, keyword, historyRevision]);

  useEffect(() => {
    setRedactionMode(false);
    setRedactionTargets([]);
    setSelectedRedactions([]);
  }, [selectedReportId]);

  useEffect(() => {
    if (!active || !selectedReportId) {
      setDetail(null);
      setVersions([]);
      return;
    }
    let cancelled = false;
    Promise.all([
      bridge<HistoryReportDetail>("get_history_report", { report_id: selectedReportId }),
      bridge<{ items: HistoryReport[] }>("get_report_versions", { report_id: selectedReportId }),
    ]).then(([report, versionData]) => {
      if (!cancelled) {
        setDetail(report);
        setVersions(versionData.items);
      }
    }).catch((error) => {
      if (!cancelled) setMessage(`报告详情读取失败：${error instanceof Error ? error.message : String(error)}`);
    });
    return () => { cancelled = true; };
  }, [active, selectedReportId]);

  async function openExport(path: string) {
    try {
      await openSystemPath(path);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error));
    }
  }

  async function openRedactionMode() {
    if (!detail?.exports.json.exists) {
      setMessage("报告 JSON 已移动或不存在，无法进入屏蔽模式。");
      return;
    }
    setRedactionBusy(true);
    try {
      const data = await bridge<{ version: number; targets: RedactionTarget[] }>("get_redaction_targets", {
        json_path: detail.exports.json.path,
      });
      setRedactionTargets(data.targets);
      setSelectedRedactions(data.targets.filter((target) => target.redacted).map((target) => target.id));
      setDetailModule("all");
      setRedactionMode(true);
      setMessage(`已进入屏蔽模式，可直接选择报告条目；完整列表共 ${data.targets.length} 项。`);
    } catch (error) {
      setMessage(`无法进入屏蔽模式：${error instanceof Error ? error.message : String(error)}`);
    } finally {
      setRedactionBusy(false);
    }
  }

  function closeRedactionMode() {
    setRedactionMode(false);
    setRedactionTargets([]);
    setSelectedRedactions([]);
    setMessage("已退出屏蔽模式，报告未发生变化。");
  }

  function toggleRedaction(target: RedactionTarget) {
    if (target.redacted || redactionBusy) return;
    setSelectedRedactions((current) => current.includes(target.id)
      ? current.filter((targetId) => targetId !== target.id)
      : [...current, target.id]);
  }

  async function applyRedactions() {
    if (!detail?.exports.json.exists) return;
    const newSelections = selectedRedactions.filter((targetId) => !redactionTargets.find((target) => target.id === targetId)?.redacted);
    if (!newSelections.length) {
      setMessage("请至少新增选择一项需要屏蔽的内容。");
      return;
    }
    setRedactionBusy(true);
    setMessage("正在本机生成屏蔽版报告，不会读取群聊或调用 AI…");
    try {
      const updated = await bridge<GenerationResult>("redact_report", {
        json_path: detail.exports.json.path,
        target_ids: selectedRedactions,
      });
      setRedactionMode(false);
      setRedactionTargets([]);
      setSelectedRedactions([]);
      await refreshHistory(false);
      if (updated.report_id) setSelectedReportId(updated.report_id);
      setDetailModule("all");
      setMessage(`屏蔽版报告 v${updated.version || "新"} 已生成并加入历史；原报告保持不变。`);
    } catch (error) {
      setMessage(`屏蔽版报告生成失败：${error instanceof Error ? error.message : String(error)}`);
    } finally {
      setRedactionBusy(false);
    }
  }

  const visibleModules = (detail?.modules || []).filter((module) => {
    if (module.module_key === "summary") return false;
    return detailModule === "all" || module.module_key === detailModule;
  });
  const memberNames = useMemo(() => Object.fromEntries(
    ((detail?.stats?.member_aliases as Array<Record<string, unknown>> | undefined) || [])
      .map((item) => [String(item.sender_id || ""), String(item.sender_name || "")])
      .filter(([senderId, senderName]) => senderId && senderName),
  ), [detail]);
  const redactionTargetById = useMemo(() => new Map(redactionTargets.map((target) => [target.id, target])), [redactionTargets]);
  const newSelectionCount = selectedRedactions.filter((targetId) => !redactionTargetById.get(targetId)?.redacted).length;

  return <div className="workspace history-workspace">
    <header className="topbar history-topbar"><div><h1>历史中心</h1></div><button className="button secondary" disabled={busy} onClick={() => refreshHistory(true)}>{busy ? "刷新中…" : "刷新与导入"}</button></header>
    <section className="notice history-notice" aria-live="polite"><strong>本地历史</strong><span>{message}</span></section>
    <div className="history-layout">
      <aside className="history-chat-pane">
        <div className="history-pane-heading"><div><span>群聊</span><strong>{chats.length}</strong></div><input aria-label="搜索历史群聊" placeholder="搜索群聊" value={chatQuery} onChange={(event) => setChatQuery(event.target.value)} /></div>
        <div className="history-chat-list">
          {visibleChats.map((chat) => <button key={chat.chat_id} className={selectedChatId === chat.chat_id ? "selected" : ""} onClick={() => { setSelectedChatId(chat.chat_id); setDetailModule("all"); }}>
            <strong>{chat.display_name}</strong><span>{chat.report_count} 份报告</span><small>{chat.latest_report_date || "无日期"}</small>
          </button>)}
          {!visibleChats.length && <div className="history-empty compact">没有符合条件的历史群聊</div>}
        </div>
      </aside>

      <section className="history-report-pane">
        <div className="history-filters">
          <input className="history-keyword" aria-label="搜索历史总结" placeholder="搜索总结、成员、话题、资源…" value={keyword} onChange={(event) => setKeyword(event.target.value)} />
          <select aria-label="模块筛选" value={moduleFilter} onChange={(event) => { setModuleFilter(event.target.value); setDetailModule(event.target.value); }}>{MODULE_OPTIONS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select>
          <div className="history-date-filter"><input aria-label="开始日期" type="date" value={startDate} onChange={(event) => setStartDate(event.target.value)} /><span>—</span><input aria-label="结束日期" type="date" value={endDate} onChange={(event) => setEndDate(event.target.value)} /></div>
        </div>
        <div className="history-result-count">{keyword.trim() ? "搜索命中" : "最新版本"} · {resultTotal}</div>
        <div className="history-report-list">
          {searchHits.map((hit, index) => <button key={`${hit.report_id}-${hit.module_key}-${index}`} className={selectedReportId === hit.report_id && detailModule === hit.module_key ? "selected" : ""} onClick={() => { setSelectedReportId(hit.report_id); setDetailModule(hit.module_key); }}>
            <div><strong>{hit.title}</strong><em>v{hit.version}</em></div><span>{periodLabel(hit.period_start, hit.period_end)} · {hit.module_label}</span><p>{searchSnippet(hit.snippet)}</p>
          </button>)}
          {!keyword.trim() && reports.map((report) => <button key={report.report_id} className={selectedReportId === report.report_id ? "selected" : ""} onClick={() => { setSelectedReportId(report.report_id); setDetailModule(moduleFilter); }}>
            <div><strong>{report.one_line_summary || report.headline}</strong><em>v{report.version}</em></div><span>{periodLabel(report.period_start, report.period_end)} · {report.message_count} 条消息</span><p>{report.headline}</p>
          </button>)}
          {!searchHits.length && !reports.length && <div className="history-empty">当前筛选下没有历史报告</div>}
        </div>
      </section>

      <section className="history-detail-pane">
        {!detail && <div className="history-empty detail-empty"><strong>选择一份历史报告</strong><span>这里会显示报告模块、全部版本和导出文件。</span></div>}
        {detail && <>
          <div className="history-detail-head"><div><span>{periodLabel(detail.period_start, detail.period_end)}</span><h2>{detail.headline}</h2><p>{detail.one_line_summary}</p></div><div className="history-stat-row"><span>{detail.message_count} 条消息</span><span>{detail.participant_count} 人</span><span>{detail.resource_count} 项资源</span></div></div>
          <div className="history-export-row">
            <button className="button primary small" disabled={!detail.exports.png.exists} onClick={() => openExport(detail.exports.png.path)}>打开 PNG</button>
            <button className="button secondary" disabled={!detail.exports.html.exists} onClick={() => openExport(detail.exports.html.path)}>打开 HTML</button>
            <button className="button secondary" disabled={!detail.exports.json.exists} onClick={() => openExport(detail.exports.json.path)}>打开 JSON</button>
            {!redactionMode && <button className="button secondary inline-icon" disabled={redactionBusy || !detail.exports.json.exists} onClick={openRedactionMode}><EyeOff size={15} aria-hidden="true" />{redactionBusy ? "读取中…" : "屏蔽内容"}</button>}
            {Object.values(detail.exports).some((item) => !item.exists) && <small>灰色文件已移动或不存在</small>}
          </div>
          <div className="history-versions"><span>历史版本</span><div>{versions.map((version) => <button key={version.report_id} className={selectedReportId === version.report_id ? "selected" : ""} onClick={() => { setSelectedReportId(version.report_id); setDetailModule("all"); }}>v{version.version}<small>{version.generated_at.slice(5, 16)}</small></button>)}</div></div>
          {redactionMode && <div className="history-redaction-toolbar" aria-live="polite"><div><strong>选择要屏蔽的报告条目</strong><span>点击下方带边框的整项；未直接呈现的条目可在完整列表中补充。</span></div><div><span>已选择 {newSelectionCount} 项</span><button className="button secondary" disabled={redactionBusy} onClick={closeRedactionMode}>取消</button><button className="button primary small" disabled={redactionBusy || !newSelectionCount} onClick={applyRedactions}>{redactionBusy ? "正在生成…" : "生成屏蔽版"}</button></div></div>}
          {redactionMode && <details className="history-redaction-list"><summary>查看全部可屏蔽项 <span>{redactionTargets.length}</span></summary><RedactionTargetGroups targets={redactionTargets} selectedIds={selectedRedactions} busy={redactionBusy} onToggle={toggleRedaction} /></details>}
          {!redactionMode && detailModule !== "all" && <div className="history-module-focus"><span>当前模块：{MODULE_OPTIONS.find(([key]) => key === detailModule)?.[1] || detailModule}</span><button onClick={() => setDetailModule("all")}>查看全部</button></div>}
          <div className="history-module-list">{visibleModules.map((module) => {
            const target = module.redaction_target_id ? redactionTargetById.get(module.redaction_target_id) : undefined;
            return <ModuleCard key={`${module.module_key}-${module.ordinal}`} module={module} memberNames={memberNames} redactionMode={redactionMode} target={target} selected={Boolean(target && selectedRedactions.includes(target.id))} onToggle={toggleRedaction} />;
          })}{!visibleModules.length && <div className="history-empty compact">这份报告没有对应模块内容</div>}</div>
        </>}
      </section>
    </div>
  </div>;
}
