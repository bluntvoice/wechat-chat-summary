import { EyeOff, RefreshCw, Image, UserRoundMinus, Trash2, FolderOpen, ListX } from "lucide-react";
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";

import { useReportGeneration } from "../hooks/useReportGeneration";
import { RedactionTargetGroups } from "../components/RedactionEditor";
import { ReportRedactionControls } from "../components/ReportRedactionControls";
import { toggleKeywordSelection } from "../services/textRedaction";
import { bridge, openSystemPath } from "../services/desktopBridge";
import type {
  Settings,
  GenerationResult,
  HistoryChat,
  HistoryModule,
  HistoryReport,
  HistoryReportDetail,
  HistorySearchHit,
  HistoryNavigationTarget,
  Paginated,
  RedactionTarget,
  TextRedaction,
} from "../types/desktop";

type HistoryPageProps = { active: boolean; target?: HistoryNavigationTarget | null };

const MODULE_OPTIONS = [
  ["all", "全部"],
  ["themes", "今日速览"],
  ["topics", "今日主要话题"],
  ["ai_observations", "AI 今日观察"],
  ["member_activity", "今日活跃情况"],
] as const;

const REPORT_SECTION_KEYS = ["themes", "topics", "ai_observations", "member_activity"] as const;

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
  time: "时间",
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
  outcome: "讨论落点",
  result: "讨论落点",
  open_questions: "开放问题",
  risk_flags: "风险提示",
  quotes: "相关原话",
  related_resources: "相关资源",
  count: "数量",
  rank: "排名",
  word: "关键词",
};

const HIDDEN_FIELDS = new Set([
  "id", "topic_id", "resource_id", "metadata", "redacted", "tone", "confidence",
  "sender_id", "sender_username", "username", "title", "start_time", "end_time",
  "redaction_id", "redaction_target_id", "message_id", "file_size", "source",
  "resource_ids", "action_items", "status", "kind",
]);

function datePart(value: string) {
  return value.slice(0, 10);
}

function periodLabel(start: string, end: string) {
  const startDate = datePart(start);
  const endDate = datePart(end);
  return startDate === endDate ? startDate : `${startDate} 至 ${endDate}`;
}

function resolveMemberTokensText(value: string, memberNames: Record<string, string> = {}) {
  return value.replace(/\[\[user:([^\]]+)\]\]/g, (_match, senderId: string) => memberNames[senderId] || "群成员");
}

function memberTokenNodes(value: string, memberNames: Record<string, string> = {}): ReactNode[] {
  const nodes: ReactNode[] = [];
  const pattern = /\[\[user:([^\]]+)\]\]|群友\d{2,}|■+/g;
  let cursor = 0;
  let match: RegExpExecArray | null;
  while ((match = pattern.exec(value)) !== null) {
    if (match.index > cursor) nodes.push(value.slice(cursor, match.index));
    nodes.push(match[0].startsWith("■")
      ? <span className="history-redaction-mask" key={match.index}>{match[0]}</span>
      : <strong className="history-member-name" key={`${match.index}-${match[1]}`}>{match[1] ? memberNames[match[1]] || "群成员" : match[0]}</strong>);
    cursor = match.index + match[0].length;
  }
  if (cursor < value.length) nodes.push(value.slice(cursor));
  return nodes;
}

function MemberText({ value, memberNames }: { value: string; memberNames: Record<string, string> }) {
  return <>{memberTokenNodes(value, memberNames)}</>;
}

function flattenText(value: unknown): string {
  if (value == null) return "";
  if (typeof value === "string") return resolveMemberTokensText(value);
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
    const raw = String(value);
    const text = resolveMemberTokensText(raw, memberNames);
    return <span className={/^https?:\/\//i.test(text) ? "history-url" : ""}><MemberText value={raw} memberNames={memberNames} /></span>;
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

function ActivityStatsView({ value, memberNames, editMode, targetById, selectedIds, onToggle }: {
  value: unknown; memberNames: Record<string, string>;
  editMode: "redact" | "delete" | null;
  targetById: Map<string, RedactionTarget>; selectedIds: string[];
  onToggle: (target: RedactionTarget) => void;
}) {
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
  const speakerMax = Math.max(1, ...speakers.map((item) => Number(item.message_count) || 0));
  const segmentMax = Math.max(1, ...segments.map((item) => Number(item.count) || 0));

  return <div className="history-activity-stats">
    {speakers.length > 0 && <section className="history-activity-block"><h4>发言排行</h4><ol className="history-speaker-list">{speakers.map((item, index) => {
      const count = Number(item.message_count) || 0;
      return <li key={`${String(item.name || "群成员")}-${index}`}><span>{Number(item.rank) || index + 1}</span><div className="history-speaker-name"><MemberText value={String(item.name || "群成员")} memberNames={memberNames} /></div><i aria-hidden="true"><b style={{ width: `${Math.max(3, Math.round(count / speakerMax * 100))}%` }} /></i><em>{count} 条</em></li>;
    })}</ol></section>}
    {keywords.length > 0 && <section className="history-activity-block"><h4>群关键词</h4><div className="history-keyword-list">{keywords.map((item, index) => {
      const target = targetById.get(`word_cloud:${(stats.word_cloud as unknown[]).indexOf(item)}`);
      return editMode === "redact" && target
        ? <label key={target.id}><input type="checkbox" checked={selectedIds.includes(target.id) || selectedIds.includes("word_cloud")} onChange={() => onToggle(target)} />{resolveMemberTokensText(String(item.word), memberNames)}<small>{Number(item.count) || ""}</small></label>
        : <span key={`${String(item.word)}-${index}`}>{resolveMemberTokensText(String(item.word), memberNames)}<small>{Number(item.count) || ""}</small></span>;
    })}</div></section>}
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

function MemberObservationView({
  value,
  title,
  memberNames,
}: {
  value: unknown;
  title: string;
  memberNames: Record<string, string>;
}) {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return <ValueView value={value} memberNames={memberNames} />;
  }
  const content = value as Record<string, unknown>;
  const memberName = resolveMemberTokensText(String(content.name || "").trim(), memberNames);
  const resolvedTitle = resolveMemberTokensText(title.trim(), memberNames);
  const visibleContent = memberName && memberName === resolvedTitle
    ? Object.fromEntries(Object.entries(content).filter(([key]) => key !== "name"))
    : content;
  return <ValueView value={visibleContent} memberNames={memberNames} />;
}

function resourceDomain(value: string) {
  try {
    return new URL(value).hostname.replace(/^www\./, "");
  } catch {
    return value.length > 54 ? `${value.slice(0, 51)}…` : value;
  }
}

function TopicPreview({
  value,
  memberNames,
  editMode,
  targetById,
  selectedIds,
  onToggle,
}: {
  value: unknown;
  memberNames: Record<string, string>;
  editMode: "redact" | "delete" | null;
  targetById: Map<string, RedactionTarget>;
  selectedIds: string[];
  onToggle: (target: RedactionTarget) => void;
}) {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return <ValueView value={value} memberNames={memberNames} />;
  }
  const topic = value as Record<string, unknown>;
  const flow = String(topic.discussion_flow || topic.summary || "").trim();
  const outcome = topic.outcome || topic.result || topic.takeaway;
  const detailRows = ([
    ["讨论落点", outcome],
    ["开放问题", topic.open_questions],
    ["风险提示", topic.risk_flags],
    ["相关原话", topic.quotes],
  ] as Array<[string, unknown]>).filter(([, item]) => item !== undefined && item !== null && item !== "" && !(Array.isArray(item) && item.length === 0));
  const resources = Array.isArray(topic.related_resources)
    ? topic.related_resources.filter((item): item is Record<string, unknown> => Boolean(item && typeof item === "object" && !Array.isArray(item)))
    : [];

  return <div className="history-topic-preview">
    {Boolean(topic.time_ranges) && <ValueView value={topic.time_ranges} memberNames={memberNames} fieldKey="time_ranges" />}
    {flow && <p className="history-topic-flow"><MemberText value={flow} memberNames={memberNames} /></p>}
    {detailRows.map(([label, item]) => <section className="history-topic-extra" key={label}><h4>{label}</h4><ValueView value={item} memberNames={memberNames} /></section>)}
    {resources.length > 0 && <section className="history-topic-extra"><h4>相关资源</h4><div className="history-topic-resources">{resources.map((item, index) => {
      const target = targetById.get(String(item.redaction_target_id || ""));
      return <ResourcePreview key={`${String(item.id || item.url || item.title || "resource")}-${index}`} value={item} memberNames={memberNames} editMode={editMode} target={target} selected={Boolean(target && selectedIds.includes(target.id))} onToggle={onToggle} />;
    })}</div></section>}
  </div>;
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

function ResourcePreview({
  value,
  memberNames,
  editMode = null,
  target,
  selected = false,
  onToggle,
}: {
  value: unknown;
  memberNames: Record<string, string>;
  editMode?: "redact" | "delete" | null;
  target?: RedactionTarget;
  selected?: boolean;
  onToggle?: (target: RedactionTarget) => void;
}) {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return <ValueView value={value} memberNames={memberNames} />;
  }
  const resource = value as Record<string, unknown>;
  const type = String(resource.type || "").toLowerCase() === "file" ? "file" : "link";
  const topic = String(resource.topic || "").trim();
  const context = String(resource.context_summary || "").trim();
  const senderId = String(resource.sender_id || "").trim();
  const sender = senderId && memberNames[senderId]
    ? `[[user:${senderId}]]`
    : String(resource.sender || "").trim();
  const sentAt = String(resource.sent_at || "").trim().slice(0, 16);
  const url = String(resource.url || "").trim();
  const platform = resourcePlatform(url, type);
  const showTopic = topic && topic !== "其他 / 未归类" && topic !== "其他/未归类";
  const selectable = Boolean(editMode && target && onToggle && (editMode === "delete" || !target.redacted));

  return <div
    className={`history-resource-preview${selectable ? " resource-edit-selectable" : ""}${selected ? " resource-edit-selected" : ""}`}
    role={selectable ? "checkbox" : undefined}
    aria-checked={selectable ? selected : undefined}
    tabIndex={selectable ? 0 : undefined}
    onClick={(event) => {
      if (editMode) event.stopPropagation();
      if (selectable && target && onToggle) onToggle(target);
    }}
    onKeyDown={(event) => {
      if (editMode) event.stopPropagation();
      if (selectable && target && onToggle && (event.key === "Enter" || event.key === " ")) {
        event.preventDefault();
        onToggle(target);
      }
    }}
  >
    <div className="history-resource-tags"><span className={`platform-${platform.key}`}>{platform.label}</span>{showTopic && <small>{topic}</small>}{selectable && <em className="history-resource-edit-state">{selected ? "已选择" : editMode === "delete" ? "选择删除" : "选择屏蔽"}</em>}</div>
    {context && <p><MemberText value={context} memberNames={memberNames} /></p>}
    {(sender || sentAt) && <div className="history-resource-meta">{sender && <MemberText value={sender} memberNames={memberNames} />}{sender && sentAt ? " · " : ""}{sentAt}</div>}
    {url && <div className="history-resource-domain" title={url}>{resourceDomain(url)}</div>}
  </div>;
}

function ModuleCard({
  module,
  memberNames,
  editMode,
  target,
  selected,
  onToggle,
  targetById,
  selectedIds,
  showSectionLabel = true,
}: {
  module: HistoryModule;
  memberNames: Record<string, string>;
  editMode: "redact" | "delete" | null;
  target?: RedactionTarget;
  selected: boolean;
  onToggle: (target: RedactionTarget) => void;
  targetById: Map<string, RedactionTarget>;
  selectedIds: string[];
  showSectionLabel?: boolean;
}) {
  const redacted = Boolean(module.content && typeof module.content === "object" && !Array.isArray(module.content) && (module.content as Record<string, unknown>).redacted);
  const selectable = Boolean(editMode && target && (editMode === "delete" || !target.redacted));
  function toggle() {
    if (selectable && target) onToggle(target);
  }
  return <article
    className={`history-module module-${module.module_key}${editMode && target ? " redaction-selectable" : ""}${selected ? " redaction-selected" : ""}${editMode === "redact" && target?.redacted ? " redaction-locked" : ""}`}
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
    <div className="history-module-heading">{showSectionLabel && <span>{module.module_label}</span>}<h3>{redacted ? "已屏蔽内容" : <MemberText value={module.title} memberNames={memberNames} />}</h3>{editMode && target && <span className="history-redaction-state">{selected ? "已选择" : editMode === "delete" ? "选择删除" : target.redacted ? "已屏蔽" : "选择屏蔽"}</span>}</div>
    {isActivityStatsModule(module)
      ? <ActivityStatsView value={module.content} memberNames={memberNames} editMode={editMode} targetById={targetById} selectedIds={selectedIds} onToggle={onToggle} />
      : module.module_key === "member_activity"
        ? <MemberObservationView value={module.content} title={module.title} memberNames={memberNames} />
        : module.module_key === "topics"
        ? <TopicPreview value={module.content} memberNames={memberNames} editMode={editMode} targetById={targetById} selectedIds={selectedIds} onToggle={onToggle} />
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
  const [editMode, setEditMode] = useState<"redact" | "delete" | null>(null);
  const [redactionTargets, setRedactionTargets] = useState<RedactionTarget[]>([]);
  const [selectedRedactions, setSelectedRedactions] = useState<string[]>([]);
  const [textRedactions, setTextRedactions] = useState<TextRedaction[]>([]);
  const [redactionBusy, setRedactionBusy] = useState(false);
  const [message, setMessage] = useState("历史数据仅来自本机 SQLite，不搜索完整原始聊天正文。");

  const [operation, setOperation] = useState<"anonymous" | "regenerate" | "image" | "delete" | null>(null);
  const [operationBusy, setOperationBusy] = useState(false);
  const [activeOperation, setActiveOperation] = useState<"anonymous" | "regenerate" | "image" | "delete" | null>(null);
  const operationGuard = useRef(false);
  const pendingReport = useRef("");
  const generation = useReportGeneration({
    settings: {} as Settings, setSettings: () => undefined, setMessage,
    saveSettings: async () => undefined, beforeGeneration: () => undefined,
  });

  async function performOperation() {
    if (!detail || !operation || operationGuard.current) return;
    const selected = detail;
    const action = operation;
    operationGuard.current = true;
    setOperationBusy(true);
    setActiveOperation(action);
    setOperation(null);
    let imageCompleted = false;
    try {
      let updated: GenerationResult;
      if (action === "regenerate") {
        updated = await generation.runGeneration(selected.chat_id, selected.display_name,
          selected.period_start.slice(0, 10), selected.period_end.slice(0, 10), "single",
          { source: "regenerate", reportId: selected.report_id });
      } else if (action === "image") {
        updated = await bridge<GenerationResult>("regenerate_report_image", { report_id: selected.report_id });
        imageCompleted = true;
        setDetail((current) => current?.report_id === selected.report_id
          ? { ...current, exports: { ...current.exports, png: { path: updated.png_path || current.exports.png.path, exists: true } } }
          : current);
        const refreshed = await bridge<HistoryReportDetail>("get_history_report", { report_id: selected.report_id });
        setDetail(refreshed);
        setMessage("导出图已重新生成，报告内容和版本未发生变化。");
        return;
      } else {
        updated = await bridge<GenerationResult>(action === "anonymous" ? "anonymous_report" : "delete_report", {report_id: selected.report_id});
      }
      pendingReport.current = updated.report_id || "";
      await refreshHistory(false);
      if (updated.report_id) setSelectedReportId(updated.report_id);
      else setSelectedReportId("");
      setDetailModule("all");
      setMessage(action === "anonymous" ? "匿名版已生成，未调用 AI，原报告保持不变。" : action === "delete" ? "报告已删除。" : `已生成新版本 v${updated.version}`);
    } catch (error) {
      const reason = error instanceof Error ? error.message : String(error);
      setMessage(action === "image" && imageCompleted
        ? `导出图已生成，但历史详情刷新失败：${reason}`
        : action === "image" && !reason.includes("原导出图未被修改")
          ? `${reason} 原导出图未被修改。` : reason);
    } finally {
      operationGuard.current = false;
      setOperationBusy(false);
      setActiveOperation(null);
    }
  }

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
          setSelectedReportId((current) => {
            if (pendingReport.current) { const id = pendingReport.current; pendingReport.current = ""; return id; }
            return ids.includes(current) ? current : ids[0] || "";
          });
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
    setEditMode(null);
    setRedactionTargets([]);
    setSelectedRedactions([]);
    setTextRedactions([]);
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
  }, [active, selectedReportId, historyRevision]);

  async function openExport(path: string) {
    try {
      await openSystemPath(path);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error));
    }
  }

  async function openContentEditMode(mode: "redact" | "delete") {
    if (!detail?.exports.json.exists) {
      setMessage(`报告 JSON 已移动或不存在，无法进入${mode === "delete" ? "删除" : "屏蔽"}模式。`);
      return;
    }
    setRedactionBusy(true);
    try {
      const data = await bridge<{ version: number; targets: RedactionTarget[] }>("get_redaction_targets", {
        json_path: detail.exports.json.path,
      });
      setRedactionTargets(mode === "delete" ? data.targets.filter((target) => !target.redact_only) : data.targets);
      setTextRedactions([]);
      setSelectedRedactions(mode === "redact" ? data.targets.filter((target) => target.redacted).map((target) => target.id) : []);
      setDetailModule("all");
      setEditMode(mode);
      setMessage(`已进入${mode === "delete" ? "删除" : "屏蔽"}模式，可直接选择报告条目；共 ${data.targets.filter((target) => mode !== "delete" || !target.redact_only).length} 项可编辑内容。`);
    } catch (error) {
      setMessage(`无法进入${mode === "delete" ? "删除" : "屏蔽"}模式：${error instanceof Error ? error.message : String(error)}`);
    } finally {
      setRedactionBusy(false);
    }
  }

  function closeContentEditMode() {
    const action = editMode === "delete" ? "删除" : "屏蔽";
    setEditMode(null);
    setRedactionTargets([]);
    setSelectedRedactions([]);
    setTextRedactions([]);
    setMessage(`已退出${action}模式，报告未发生变化。`);
  }

  function toggleRedaction(target: RedactionTarget) {
    if ((editMode === "redact" && target.redacted) || redactionBusy) return;
    if (target.id === "word_cloud") {
      toggleAllKeywords();
      return;
    }
    setSelectedRedactions((current) => current.includes(target.id)
      ? current.filter((targetId) => targetId !== target.id)
      : [...current, target.id]);
  }

  function toggleAllKeywords() {
    if (redactionBusy) return;
    setSelectedRedactions((current) => toggleKeywordSelection(current, redactionTargets));
  }

  function updateTextRedactions(targetId: string, edits: TextRedaction[]) {
    setTextRedactions((current) => [...current.filter((edit) => edit.target_id !== targetId), ...edits]);
  }

  async function applyContentEdit() {
    if (!detail?.exports.json.exists || !editMode) return;
    const action = editMode;
    const actionSelections = action === "redact"
      ? selectedRedactions.filter((targetId) => !redactionTargets.find((target) => target.id === targetId)?.redacted)
      : selectedRedactions;
    const textSelections = action === "redact" ? textRedactions.filter((edit) => !actionSelections.includes(edit.target_id)) : [];
    if (!actionSelections.length && !textSelections.length) {
      setMessage(`请至少${action === "delete" ? "选择一项需要删除" : "新增选择一项需要屏蔽"}的内容。`);
      return;
    }
    setRedactionBusy(true);
    setMessage(`正在本机生成${action === "delete" ? "内容删除版" : "屏蔽版"}报告，不会读取群聊或调用 AI…`);
    try {
      const updated = await bridge<GenerationResult>(action === "delete" ? "delete_report_content" : "redact_report", {
        json_path: detail.exports.json.path,
        target_ids: actionSelections,
        ...(action === "redact" ? { text_redactions: textSelections } : {}),
      });
      setEditMode(null);
      setRedactionTargets([]);
      setSelectedRedactions([]);
      setTextRedactions([]);
      await refreshHistory(false);
      if (updated.report_id) setSelectedReportId(updated.report_id);
      setDetailModule("all");
      setMessage(`${action === "delete" ? "内容删除版" : "屏蔽版"}报告 v${updated.version || "新"} 已生成并加入历史；原报告保持不变。`);
    } catch (error) {
      setMessage(`${action === "delete" ? "内容删除版" : "屏蔽版"}报告生成失败：${error instanceof Error ? error.message : String(error)}`);
    } finally {
      setRedactionBusy(false);
    }
  }

  const visibleModules = (detail?.modules || []).filter((module) => {
    if (module.module_key === "summary") return false;
    return detailModule === "all"
      ? REPORT_SECTION_KEYS.includes(module.module_key as typeof REPORT_SECTION_KEYS[number])
      : module.module_key === detailModule;
  });
  const reportSections = REPORT_SECTION_KEYS.map((key) => ({
    key,
    label: MODULE_OPTIONS.find(([value]) => value === key)?.[1] || key,
    modules: visibleModules.filter((module) => module.module_key === key),
  })).filter((section) => section.modules.length > 0);
  const memberNames = useMemo(() => Object.fromEntries(
    ((detail?.stats?.member_aliases as Array<Record<string, unknown>> | undefined) || [])
      .map((item) => [String(item.sender_id || ""), String(item.sender_name || "")])
      .filter(([senderId, senderName]) => senderId && senderName),
  ), [detail]);
  const redactionTargetById = useMemo(() => new Map(redactionTargets.map((target) => [target.id, target])), [redactionTargets]);
  const actionSelectionCount = editMode === "delete"
    ? selectedRedactions.length
    : selectedRedactions.filter((targetId) => !redactionTargetById.get(targetId)?.redacted).length
      + textRedactions.filter((edit) => !selectedRedactions.includes(edit.target_id)).length;

  return <div className="workspace history-workspace">
    <header className="topbar history-topbar"><div><h1>历史中心</h1></div><button className="button secondary" disabled={busy} onClick={() => refreshHistory(true)}>{busy ? "刷新中…" : "刷新与导入"}</button></header>
    <section className="notice history-notice" aria-live="polite"><strong>本地历史</strong><span>{message}</span></section>
    {operationBusy && activeOperation === "regenerate" && generation.progress && <section className="notice" aria-live="polite"><progress max={100} value={generation.progress.percent} /><span>{generation.progress.message} · {generation.progress.percent}% · {generation.progress.elapsed_seconds} 秒</span></section>}
    {operationBusy && activeOperation !== "regenerate" && <section className="notice" role="status">{activeOperation === "image" ? "正在重新生成导出图…" : "正在处理本地报告…"}</section>}
    {operation && detail && <div className="dialog-backdrop"><section className="dialog-card" role="dialog" aria-modal="true" aria-labelledby="history-operation-title">
      <h2 id="history-operation-title">{operation === "anonymous" ? "生成匿名版" : operation === "regenerate" ? "重新生成报告" : operation === "image" ? "重新生成导出图" : "删除报告"}</h2>
      {operation === "anonymous" ? <><p>匿名版会将可识别成员显示为“群友01、群友02……”并移除成员级活跃统计，不会修改原报告。</p><p>匿名处理仅针对成员身份，聊天正文中自行出现的姓名、联系方式或其他敏感信息不会自动删除。分享前仍需自行确认。</p></> : operation === "regenerate" ? <p>将重新读取该时间范围的群聊数据，并使用当前 AI 配置重新分析和生成报告。该操作会调用 AI，并创建新的报告版本，当前版本不会被删除。</p> : operation === "image" ? <p>将根据当前报告内容重新生成 PNG 导出图。不会重新读取群聊，不会调用 AI，也不会创建新的报告版本。当前报告 JSON 和 HTML 保持不变。</p> : <p>{versions.some(v => v.source_report_id === detail.report_id) ? "该报告存在匿名版，删除原报告将同时删除关联匿名版。" : "将删除该报告文件和历史记录。其他正常版本不受影响。"}</p>}
      <div className="dialog-actions"><button className="button secondary" onClick={() => setOperation(null)}>取消</button><button className="button primary" onClick={performOperation}>{operation === "anonymous" ? "生成匿名版" : operation === "regenerate" ? "重新生成报告" : operation === "image" ? "重新生成导出图" : "确认删除"}</button></div>
    </section></div>}
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
            <div><strong>{hit.title}</strong><em>{hit.report_variant === "anonymous" ? "匿名版 · " : ""}v{hit.version}</em></div><span>{periodLabel(hit.period_start, hit.period_end)} · {hit.module_label}</span><p>{searchSnippet(hit.snippet)}</p>
          </button>)}
          {!keyword.trim() && reports.map((report) => <button key={report.report_id} className={selectedReportId === report.report_id || (detail?.period_start === report.period_start && detail?.period_end === report.period_end) ? "selected" : ""} onClick={() => { setSelectedReportId(report.report_id); setDetailModule(moduleFilter); }}>
            <div><strong>{report.one_line_summary || report.headline}</strong><em>{report.report_variant === "anonymous" ? "匿名版 · " : ""}v{report.version}</em></div><span>{periodLabel(report.period_start, report.period_end)} · {report.message_count} 条消息</span><p>{report.headline}</p>
          </button>)}
          {!searchHits.length && !reports.length && <div className="history-empty">当前筛选下没有历史报告</div>}
        </div>
      </section>

      <section className="history-detail-pane">
        {!detail && <div className="history-empty detail-empty"><strong>选择一份历史报告</strong><span>这里会显示报告模块、全部版本和导出文件。</span></div>}
        {detail && <>
          <div className="history-detail-head"><div><span>{periodLabel(detail.period_start, detail.period_end)} · {detail.report_variant === "anonymous" ? `匿名版（来源正常版 v${detail.version}）` : `正常版 v${detail.version}`}</span><h2>{detail.headline}</h2><p><MemberText value={detail.one_line_summary} memberNames={memberNames} /></p></div><div className="history-stat-row"><span>今日消息 {detail.message_count} 条</span><span>今日字数 {Number(detail.stats.effective_char_count) || 0} 字</span><span>参与人数 {detail.participant_count} 人</span>{detail.resource_count > 0 && <span>整理资源 {detail.resource_count} 项</span>}</div></div>
          <div className="history-export-row">
            <button className="button primary small" disabled={!detail.exports.png.exists} onClick={() => openExport(detail.exports.png.path)}>打开 PNG</button>
            <button className="button secondary" disabled={!detail.exports.html.exists} onClick={() => openExport(detail.exports.html.path)}>打开 HTML</button>
            <button className="button secondary" disabled={!detail.exports.json.exists} onClick={() => openExport(detail.exports.json.path)}>打开 JSON</button>
            {!editMode && detail.report_variant !== "anonymous" && <button className="button secondary inline-icon" disabled={redactionBusy || !detail.exports.json.exists} onClick={() => openContentEditMode("redact")}><EyeOff size={15} aria-hidden="true" />{redactionBusy ? "读取中…" : "屏蔽内容"}</button>}
            {!editMode && detail.report_variant !== "anonymous" && <button className="button secondary inline-icon" disabled={redactionBusy || !detail.exports.json.exists} onClick={() => openContentEditMode("delete")}><ListX size={15} aria-hidden="true" />{redactionBusy ? "读取中…" : "删除内容"}</button>}
            {!editMode && detail.report_variant !== "anonymous" && detail.period_start.slice(0, 10) === detail.period_end.slice(0, 10) && <button className="button secondary inline-icon" disabled={operationBusy || redactionBusy} onClick={() => setOperation("regenerate")}><RefreshCw size={15} />重新生成报告</button>}
            {!editMode && <button className="button secondary inline-icon" title={!detail.exports.json.exists ? "报告 JSON 已移动或不存在，无法重新生成导出图。" : undefined} disabled={operationBusy || redactionBusy || !detail.exports.json.exists} onClick={() => setOperation("image")}><Image size={15} />重新生成导出图</button>}
            {!editMode && detail.report_variant !== "anonymous" && <button className="button secondary inline-icon" disabled={operationBusy || redactionBusy || !detail.exports.json.exists} onClick={() => setOperation("anonymous")}><UserRoundMinus size={15} />{versions.some(v => v.source_report_id === detail.report_id) ? "重新生成匿名版" : "生成匿名版"}</button>}
            {detail.report_variant === "anonymous" && <button className="button secondary" onClick={() => setSelectedReportId(detail.source_report_id || "")}>查看原报告 · v{detail.version}</button>}
            <button className="button secondary inline-icon" disabled={operationBusy} onClick={() => openExport(detail.exports.json.path.replace(/[\\/][^\\/]+$/, ""))}><FolderOpen size={15} />所在目录</button>
            <button className="button secondary inline-icon" disabled={operationBusy || redactionBusy || Boolean(editMode)} onClick={() => setOperation("delete")}><Trash2 size={15} />删除报告</button>
            {Object.values(detail.exports).some((item) => !item.exists) && <small>灰色文件已移动或不存在</small>}
          </div>
          <div className="history-versions"><span>历史版本</span><div>{versions.map((version) => <button key={version.report_id} className={selectedReportId === version.report_id ? "selected" : ""} onClick={() => { setSelectedReportId(version.report_id); setDetailModule("all"); }}>{version.report_variant === "anonymous" ? `匿名版 · 来源 v${version.version}` : `正常版 v${version.version}`}<small>{version.generated_at.slice(5, 16)}</small></button>)}</div></div>
          {editMode && <div className="history-redaction-toolbar" aria-live="polite"><div><strong>选择要{editMode === "delete" ? "删除" : "屏蔽"}的报告条目</strong><span>{editMode === "redact" ? "开头和结尾支持选中文字或整段屏蔽，群关键词可逐个选择或全选；其他内容点击整项选择。" : "点击下方带边框的整项；新版本中将不再保留所选条目。"}</span></div><div><span>已选择 {actionSelectionCount} 项</span><button className="button secondary" disabled={redactionBusy} onClick={closeContentEditMode}>取消</button><button className="button primary small" disabled={redactionBusy || !actionSelectionCount} onClick={applyContentEdit}>{redactionBusy ? "正在生成…" : editMode === "delete" ? "生成内容删除版" : "生成屏蔽版"}</button></div></div>}
          {editMode === "redact" && <ReportRedactionControls targets={redactionTargets} selectedIds={selectedRedactions} textRedactions={textRedactions} busy={redactionBusy} onToggle={toggleRedaction} onTextChange={updateTextRedactions} onToggleKeywords={toggleAllKeywords} />}
          {editMode && <details className="history-redaction-list"><summary>查看{editMode === "redact" ? "其他" : "全部"}可{editMode === "delete" ? "删除" : "屏蔽"}项 <span>{redactionTargets.filter((target) => !target.redact_only).length}</span></summary><RedactionTargetGroups targets={redactionTargets.filter((target) => !target.redact_only)} selectedIds={selectedRedactions} busy={redactionBusy} onToggle={toggleRedaction} mode={editMode} /></details>}
          {!editMode && detailModule !== "all" && <div className="history-module-focus"><span>当前模块：{MODULE_OPTIONS.find(([key]) => key === detailModule)?.[1] || detailModule}</span><button onClick={() => setDetailModule("all")}>查看全部</button></div>}
          {detailModule === "all"
            ? <div className="history-report-sections">{reportSections.map((section) => <section className="history-report-section" key={section.key}><h3>{section.label}</h3><div className="history-module-list">{section.modules.map((module) => {
              const target = module.redaction_target_id ? redactionTargetById.get(module.redaction_target_id) : undefined;
              return <ModuleCard key={`${module.module_key}-${module.ordinal}`} module={module} memberNames={memberNames} editMode={editMode} target={target} selected={Boolean(target && selectedRedactions.includes(target.id))} onToggle={toggleRedaction} targetById={redactionTargetById} selectedIds={selectedRedactions} showSectionLabel={false} />;
            })}</div></section>)}{!reportSections.length && <div className="history-empty compact">这份报告没有对应模块内容</div>}<footer className="history-report-end"><strong>报告结尾</strong><span><MemberText value={String(detail.content.conclusion || "以上为本次群聊日报整理。")} memberNames={memberNames} /></span><small>报告由群聊拾遗生成 · {detail.display_name} · {periodLabel(detail.period_start, detail.period_end)}<br />生成时间：{detail.generated_at.slice(0, 19)}</small></footer></div>
            : <div className="history-module-list">{visibleModules.map((module) => {
              const target = module.redaction_target_id ? redactionTargetById.get(module.redaction_target_id) : undefined;
              return <ModuleCard key={`${module.module_key}-${module.ordinal}`} module={module} memberNames={memberNames} editMode={editMode} target={target} selected={Boolean(target && selectedRedactions.includes(target.id))} onToggle={toggleRedaction} targetById={redactionTargetById} selectedIds={selectedRedactions} />;
            })}{!visibleModules.length && <div className="history-empty compact">这份报告没有对应模块内容</div>}</div>}
        </>}
      </section>
    </div>
  </div>;
}
