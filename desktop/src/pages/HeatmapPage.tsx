import { useEffect, useMemo, useRef, useState } from "react";

import { filterAndSortChats, type ChatListFilter } from "../services/chatList";
import { bridge } from "../services/desktopBridge";
import {
  buildCalendarCells,
  dayTooltip,
  heatmapRange,
  HEATMAP_METRICS,
  historyTargetForDay,
  metricValue,
} from "../services/heatmap";
import type {
  Chat,
  HeatmapData,
  HeatmapDay,
  HeatmapMetric,
  HistoryNavigationTarget,
} from "../types/desktop";

type HeatmapPageProps = {
  active: boolean;
  onOpenHistory: (target: HistoryNavigationTarget) => void;
};

const pendingEnsures = new Map<string, Promise<HeatmapData>>();

function ensureData(chatId: string, chatName: string, startDate: string, endDate: string) {
  const key = `${chatId}|${startDate}|${endDate}`;
  const existing = pendingEnsures.get(key);
  if (existing) return existing;
  const request = bridge<HeatmapData>("ensure_daily_stats", {
    chat_id: chatId,
    chat_name: chatName,
    start_date: startDate,
    end_date: endDate,
  }).finally(() => pendingEnsures.delete(key));
  pendingEnsures.set(key, request);
  return request;
}

function rangeDays(start: string, end: string) {
  if (!start || !end) return 0;
  return Math.round((new Date(`${end}T00:00:00`).getTime() - new Date(`${start}T00:00:00`).getTime()) / 86_400_000) + 1;
}

function readableDate(value: string) {
  return new Intl.DateTimeFormat("zh-CN", { year: "numeric", month: "long", day: "numeric", weekday: "short" })
    .format(new Date(`${value}T00:00:00`));
}

export default function HeatmapPage({ active, onOpenHistory }: HeatmapPageProps) {
  const rolling = heatmapRange("rolling");
  const [chats, setChats] = useState<Chat[]>([]);
  const [chatId, setChatId] = useState("");
  const [chatQuery, setChatQuery] = useState("");
  const [chatFilter, setChatFilter] = useState<ChatListFilter>("all");
  const [rangeMode, setRangeMode] = useState("rolling");
  const [customStart, setCustomStart] = useState(rolling.start);
  const [customEnd, setCustomEnd] = useState(rolling.end);
  const [metric, setMetric] = useState<HeatmapMetric>("message_count");
  const [data, setData] = useState<HeatmapData | null>(null);
  const [selectedDate, setSelectedDate] = useState("");
  const [phase, setPhase] = useState<"idle" | "loading" | "scanning" | "ready" | "error">("idle");
  const [message, setMessage] = useState("选择群聊后，将按需读取本地聊天并缓存每日聚合统计。");
  const [refreshToken, setRefreshToken] = useState(0);
  const requestIdentity = useRef(0);

  const summarizedIds = useMemo(() => chats.filter((chat) => chat.summarized).map((chat) => chat.id), [chats]);
  const visibleChats = useMemo(
    () => filterAndSortChats(chats, summarizedIds, chatQuery, chatFilter),
    [chats, summarizedIds, chatQuery, chatFilter],
  );
  const selectedChat = chats.find((chat) => chat.id === chatId);
  const range = heatmapRange(rangeMode, customStart, customEnd);
  const currentYear = new Date().getFullYear();
  const yearOptions = Array.from({ length: 8 }, (_, index) => currentYear - index);

  useEffect(() => {
    if (!active) return;
    let cancelled = false;
    setPhase("loading");
    setMessage("正在连接 WeChatDataAnalysis 并读取群聊列表…");
    bridge<{ chats: Chat[] }>("list_chats").then((response) => {
      if (cancelled) return;
      setChats(response.chats);
      setChatId((current) => response.chats.some((chat) => chat.id === current) ? current : response.chats[0]?.id || "");
      setPhase("idle");
      setMessage(response.chats.length ? "群聊已就绪，正在读取所选范围的统计缓存。" : "当前数据源没有可用群聊。");
    }).catch((error) => {
      if (cancelled) return;
      setPhase("error");
      setMessage(`WeChatDataAnalysis 未连接：${error instanceof Error ? error.message : String(error)}`);
    });
    return () => { cancelled = true; };
  }, [active, refreshToken]);

  useEffect(() => {
    if (visibleChats.some((chat) => chat.id === chatId)) return;
    setChatId(visibleChats[0]?.id || "");
  }, [visibleChats, chatId]);

  useEffect(() => {
    if (!active || !selectedChat || !range.start || !range.end) return;
    const days = rangeDays(range.start, range.end);
    if (days < 1 || days > 366) {
      setPhase("error");
      setMessage("自定义范围需为有效日期，且单次最多 366 天。");
      return;
    }
    const identity = ++requestIdentity.current;
    const timer = window.setTimeout(async () => {
      setPhase("loading");
      setMessage("正在查询本机 SQLite 日统计缓存…");
      try {
        const cached = await bridge<HeatmapData>("get_heatmap_data", {
          chat_id: selectedChat.id,
          chat_name: selectedChat.name,
          start_date: range.start,
          end_date: range.end,
        });
        if (identity !== requestIdentity.current) return;
        setData(cached);
        setSelectedDate((current) => cached.days.some((day) => day.date === current) ? current : cached.days.at(-1)?.date || "");
        if (!cached.unknown_days) {
          const total = cached.days.reduce((sum, day) => sum + (day.message_count || 0), 0);
          setPhase("ready");
          setMessage(total ? "已使用本地缓存完成热力图。" : "该范围已统计，未发现聊天消息。");
          return;
        }
        setPhase("scanning");
        setMessage(`有 ${cached.unknown_days} 天尚未统计，正在按连续区间读取本地聊天；不会调用 AI。`);
        const filled = await ensureData(selectedChat.id, selectedChat.name, range.start, range.end);
        if (identity !== requestIdentity.current) return;
        setData(filled);
        setSelectedDate((current) => filled.days.some((day) => day.date === current) ? current : filled.days.at(-1)?.date || "");
        const total = filled.days.reduce((sum, day) => sum + (day.message_count || 0), 0);
        setPhase("ready");
        setMessage(total
          ? `统计完成：新增缓存 ${filled.scan?.scanned_days || 0} 天，仅保存聚合结果。`
          : "该范围读取完成，未发现聊天消息；这些日期已记录为真实 0。");
      } catch (error) {
        if (identity !== requestIdentity.current) return;
        setPhase("error");
        setMessage(`统计读取失败：${error instanceof Error ? error.message : String(error)}；失败日期不会被写成 0。`);
      }
    }, 240);
    return () => {
      window.clearTimeout(timer);
      if (identity === requestIdentity.current) requestIdentity.current += 1;
    };
  }, [active, selectedChat?.id, range.start, range.end, refreshToken]);

  const view = useMemo(() => data ? buildCalendarCells(data, metric) : null, [data, metric]);
  const selectedDay = data?.days.find((day) => day.date === selectedDate) || null;
  const knownDays = data?.days.filter((day) => day.status === "known") || [];
  const activeDays = knownDays.filter((day) => (metricValue(day, metric) || 0) > 0).length;
  const totalValue = knownDays.reduce((sum, day) => sum + (metricValue(day, metric) || 0), 0);
  const peakDay = knownDays.reduce<HeatmapDay | null>((best, day) => {
    if (!best || (metricValue(day, metric) || 0) > (metricValue(best, metric) || 0)) return day;
    return best;
  }, null);
  const monthLabels = useMemo(() => {
    if (!view) return [];
    const labels: Array<{ label: string; week: number }> = [];
    const seen = new Set<string>();
    for (const cell of view.cells) {
      if (!cell.day) continue;
      const month = cell.day.date.slice(0, 7);
      if (seen.has(month)) continue;
      seen.add(month);
      labels.push({ label: `${Number(month.slice(5))}月`, week: cell.week });
    }
    return labels;
  }, [view]);

  function openHistory(day: HeatmapDay) {
    const target = historyTargetForDay(day, data?.chat_id || chatId, Date.now());
    if (target) onOpenHistory(target);
  }

  return <div className="workspace heatmap-workspace">
    <header className="topbar heatmap-topbar">
      <div><p className="eyebrow">LOCAL · ACTIVITY CALENDAR</p><h1>热力图分析</h1></div>
      <div className="heatmap-top-actions"><div className={`heatmap-status status-${phase}`}><i />{phase === "scanning" ? "正在补齐统计" : phase === "loading" ? "读取中" : phase === "error" ? "需要处理" : "本地聚合"}</div><button className="button secondary" disabled={phase === "scanning"} onClick={() => setRefreshToken((value) => value + 1)}>重新读取</button></div>
    </header>
    <section className="notice heatmap-notice" aria-live="polite"><strong>数据说明</strong><span>{message}</span></section>

    <section className="heatmap-controls">
      <label className="heatmap-chat-search"><span>群聊</span><input disabled={phase === "scanning"} placeholder="筛选群聊" value={chatQuery} onChange={(event) => setChatQuery(event.target.value)} /></label>
      <label><span>选择群聊</span><select disabled={phase === "scanning"} value={chatId} onChange={(event) => setChatId(event.target.value)}>{visibleChats.map((chat) => <option key={chat.id} value={chat.id}>{chat.summarized ? "● " : ""}{chat.name}</option>)}</select></label>
      <label><span>范围</span><select disabled={phase === "scanning"} value={rangeMode} onChange={(event) => setRangeMode(event.target.value)}><option value="rolling">最近一年</option>{yearOptions.map((year) => <option key={year} value={String(year)}>{year} 年</option>)}<option value="custom">自定义</option></select></label>
      <div className="heatmap-chat-filter" aria-label="群聊筛选"><button disabled={phase === "scanning"} className={chatFilter === "all" ? "selected" : ""} onClick={() => setChatFilter("all")}>全部</button><button disabled={phase === "scanning"} className={chatFilter === "summarized" ? "selected" : ""} onClick={() => setChatFilter("summarized")}>已总结</button></div>
      {rangeMode === "custom" && <div className="heatmap-custom-range"><input disabled={phase === "scanning"} aria-label="热力图开始日期" type="date" max={rolling.end} value={customStart} onChange={(event) => setCustomStart(event.target.value)} /><span>—</span><input disabled={phase === "scanning"} aria-label="热力图结束日期" type="date" max={rolling.end} value={customEnd} onChange={(event) => setCustomEnd(event.target.value)} /></div>}
    </section>

    <div className="heatmap-layout">
      <section className="heatmap-main-card">
        <div className="heatmap-card-head">
          <div><span>{selectedChat?.name || "尚未选择群聊"}</span><h2>{range.start} 至 {range.end}</h2></div>
          <div className="heatmap-metrics" aria-label="热力图指标">{HEATMAP_METRICS.map((item) => <button key={item.value} className={metric === item.value ? "selected" : ""} onClick={() => setMetric(item.value)}>{item.label}</button>)}</div>
        </div>
        <div className="heatmap-summary-row"><div><strong>{totalValue.toLocaleString()}</strong><span>范围合计</span></div><div><strong>{activeDays}</strong><span>活跃天数</span></div><div><strong>{peakDay ? metricValue(peakDay, metric) : 0}</strong><span>单日峰值</span></div><div><strong>{data ? `${data.known_days}/${data.days.length}` : "0/0"}</strong><span>已统计覆盖</span></div></div>

        {!view && <div className="heatmap-empty"><strong>等待群聊统计</strong><span>连接本地数据源后，这里会显示每日活跃程度。</span></div>}
        {view && <div className="heatmap-scroll" tabIndex={0} aria-label="群聊日历热力图">
          <div className="heatmap-calendar" style={{ minWidth: `${view.weekCount * 16 + 38}px` }}>
            <div className="heatmap-months" style={{ gridTemplateColumns: `repeat(${view.weekCount}, 13px)` }}>{monthLabels.map((item) => <span key={`${item.label}-${item.week}`} style={{ gridColumn: item.week + 1 }}>{item.label}</span>)}</div>
            <div className="heatmap-weekdays"><span>一</span><span>三</span><span>五</span><span>日</span></div>
            <div className="heatmap-grid" style={{ gridTemplateColumns: `repeat(${view.weekCount}, 13px)` }}>
              {view.cells.map((cell) => cell.day
                ? <button key={cell.key} className={`heatmap-cell level-${cell.intensity} ${selectedDate === cell.key ? "selected" : ""} ${cell.day.report ? "has-report" : ""}`} style={{ gridColumn: cell.week + 1, gridRow: cell.weekday + 1 }} aria-label={dayTooltip(cell.day, metric)} data-tooltip={dayTooltip(cell.day, metric)} onClick={() => setSelectedDate(cell.key)} />
                : <span key={cell.key} className="heatmap-cell outside" style={{ gridColumn: cell.week + 1, gridRow: cell.weekday + 1 }} />)}
            </div>
          </div>
        </div>}
        <div className="heatmap-legend"><span>未知</span><i className="level--1" /><span>真实 0</span><i className="level-0" /><span>低</span><i className="level-1" /><i className="level-2" /><i className="level-3" /><i className="level-4" /><span>高</span></div>
      </section>

      <aside className="heatmap-day-card">
        {!selectedDay && <div className="heatmap-empty compact"><strong>选择一个日期</strong><span>查看当天的聚合统计。</span></div>}
        {selectedDay && <>
          <div className="heatmap-day-head"><span>{selectedDay.status === "known" ? "已统计" : "尚未统计"}</span><h2>{readableDate(selectedDay.date)}</h2>{selectedDay.report && <em>已有总结 · v{selectedDay.report.version}</em>}</div>
          {selectedDay.status === "unknown"
            ? <div className="heatmap-unknown-copy">该日期还没有可靠统计，不能显示为 0。若补齐失败，请确认 WeChatDataAnalysis 已连接后重试。</div>
            : <dl className="heatmap-day-stats"><div><dt>消息数</dt><dd>{selectedDay.message_count}</dd></div><div><dt>有效消息</dt><dd>{selectedDay.effective_message_count}</dd></div><div><dt>参与人数</dt><dd>{selectedDay.participant_count}</dd></div><div><dt>有效字符</dt><dd>{selectedDay.effective_char_count}</dd></div><div><dt>链接</dt><dd>{selectedDay.link_count}</dd></div><div><dt>文件</dt><dd>{selectedDay.file_count}</dd></div></dl>}
          {selectedDay.report
            ? <button className="button primary heatmap-history-button" onClick={() => openHistory(selectedDay)}>查看历史总结</button>
            : <p className="heatmap-no-report">该日期没有历史报告，仅展示本地统计。</p>}
        </>}
      </aside>
    </div>
  </div>;
}
