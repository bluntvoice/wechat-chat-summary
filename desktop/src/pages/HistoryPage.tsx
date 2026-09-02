import { useEffect, useMemo, useState } from "react";

import { bridge, openSystemPath } from "../services/desktopBridge";
import type {
  HistoryChat,
  HistoryModule,
  HistoryReport,
  HistoryReportDetail,
  HistorySearchHit,
  HistoryNavigationTarget,
  Paginated,
} from "../types/desktop";

type HistoryPageProps = { active: boolean; target?: HistoryNavigationTarget | null };

const MODULE_OPTIONS = [
  ["all", "全部"],
  ["topics", "主要话题"],
  ["ai_observations", "AI 今日观察"],
  ["member_activity", "成员 / 活跃情况"],
  ["outcome", "讨论结论"],
  ["action_items", "行动事项"],
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

function ModuleCard({ module, memberNames }: { module: HistoryModule; memberNames: Record<string, string> }) {
  const redacted = Boolean(module.content && typeof module.content === "object" && !Array.isArray(module.content) && (module.content as Record<string, unknown>).redacted);
  return <article className={`history-module module-${module.module_key}`}>
    <div className="history-module-heading"><span>{module.module_label}</span><h3>{redacted ? "已屏蔽内容" : module.title}</h3></div>
    <ValueView value={module.content} memberNames={memberNames} />
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
  }, [active, selectedChatId, startDate, endDate, moduleFilter, keyword]);

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

  const visibleModules = (detail?.modules || []).filter((module) => {
    if (module.module_key === "summary") return false;
    return detailModule === "all" || module.module_key === detailModule;
  });
  const memberNames = useMemo(() => Object.fromEntries(
    ((detail?.stats?.member_aliases as Array<Record<string, unknown>> | undefined) || [])
      .map((item) => [String(item.sender_id || ""), String(item.sender_name || "")])
      .filter(([senderId, senderName]) => senderId && senderName),
  ), [detail]);

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
            {Object.values(detail.exports).some((item) => !item.exists) && <small>灰色文件已移动或不存在</small>}
          </div>
          <div className="history-versions"><span>历史版本</span><div>{versions.map((version) => <button key={version.report_id} className={selectedReportId === version.report_id ? "selected" : ""} onClick={() => { setSelectedReportId(version.report_id); setDetailModule("all"); }}>v{version.version}<small>{version.generated_at.slice(5, 16)}</small></button>)}</div></div>
          {detailModule !== "all" && <div className="history-module-focus"><span>当前模块：{MODULE_OPTIONS.find(([key]) => key === detailModule)?.[1] || detailModule}</span><button onClick={() => setDetailModule("all")}>查看全部</button></div>}
          <div className="history-module-list">{visibleModules.map((module) => <ModuleCard key={`${module.module_key}-${module.ordinal}`} module={module} memberNames={memberNames} />)}{!visibleModules.length && <div className="history-empty compact">这份报告没有对应模块内容</div>}</div>
        </>}
      </section>
    </div>
  </div>;
}
