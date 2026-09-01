import type {
  HeatmapData,
  HeatmapDay,
  HeatmapMetric,
  HistoryNavigationTarget,
} from "../types/desktop";

export const HEATMAP_METRICS: Array<{ value: HeatmapMetric; label: string; unit: string }> = [
  { value: "message_count", label: "消息数量", unit: "条" },
  { value: "participant_count", label: "参与人数", unit: "人" },
  { value: "effective_message_count", label: "有效消息数量", unit: "条" },
];

export type CalendarCell = {
  key: string;
  day: HeatmapDay | null;
  week: number;
  weekday: number;
  intensity: -1 | 0 | 1 | 2 | 3 | 4;
};

function parseDate(value: string) {
  return new Date(`${value}T00:00:00`);
}

function isoDate(value: Date) {
  return `${value.getFullYear()}-${String(value.getMonth() + 1).padStart(2, "0")}-${String(value.getDate()).padStart(2, "0")}`;
}

function addDays(value: Date, amount: number) {
  const result = new Date(value);
  result.setDate(result.getDate() + amount);
  return result;
}

export function heatmapRange(mode: string, customStart = "", customEnd = "") {
  const today = new Date();
  const todayText = isoDate(today);
  if (mode === "custom") return { start: customStart, end: customEnd };
  if (mode === "rolling") return { start: isoDate(addDays(today, -364)), end: todayText };
  const year = Number(mode);
  return {
    start: `${year}-01-01`,
    end: year === today.getFullYear() ? todayText : `${year}-12-31`,
  };
}

export function metricValue(day: HeatmapDay, metric: HeatmapMetric) {
  return day.status === "known" ? day[metric] ?? 0 : null;
}

export function intensityThresholds(days: HeatmapDay[], metric: HeatmapMetric) {
  const values = days
    .map((day) => metricValue(day, metric))
    .filter((value): value is number => value != null && value > 0)
    .sort((left, right) => left - right);
  if (!values.length) return [0, 0, 0, 0] as const;
  const at = (ratio: number) => values[Math.min(values.length - 1, Math.floor((values.length - 1) * ratio))];
  return [at(0.2), at(0.45), at(0.7), values[values.length - 1]] as const;
}

export function intensityFor(day: HeatmapDay, metric: HeatmapMetric, thresholds: readonly number[]) {
  const value = metricValue(day, metric);
  if (value == null) return -1 as const;
  if (value === 0) return 0 as const;
  if (value <= thresholds[0]) return 1 as const;
  if (value <= thresholds[1]) return 2 as const;
  if (value <= thresholds[2]) return 3 as const;
  return 4 as const;
}

export function buildCalendarCells(data: HeatmapData, metric: HeatmapMetric) {
  const dayMap = new Map(data.days.map((day) => [day.date, day]));
  const thresholds = intensityThresholds(data.days, metric);
  const start = parseDate(data.start_date);
  const end = parseDate(data.end_date);
  const mondayOffset = (start.getDay() + 6) % 7;
  const gridStart = addDays(start, -mondayOffset);
  const endOffset = 6 - ((end.getDay() + 6) % 7);
  const gridEnd = addDays(end, endOffset);
  const cells: CalendarCell[] = [];
  let cursor = gridStart;
  let index = 0;
  while (cursor <= gridEnd) {
    const key = isoDate(cursor);
    const day = dayMap.get(key) || null;
    cells.push({
      key,
      day,
      week: Math.floor(index / 7),
      weekday: index % 7,
      intensity: day ? intensityFor(day, metric, thresholds) : -1,
    });
    cursor = addDays(cursor, 1);
    index += 1;
  }
  return { cells, thresholds, weekCount: Math.ceil(cells.length / 7) };
}

export function historyTargetForDay(day: HeatmapDay, chatId: string, requestId: number): HistoryNavigationTarget | null {
  if (!day.report) return null;
  return { chatId, date: day.date, reportId: day.report.report_id, requestId };
}

export function dayTooltip(day: HeatmapDay, metric: HeatmapMetric) {
  if (day.status === "unknown") return `${day.date} · 尚未统计`;
  const metricInfo = HEATMAP_METRICS.find((item) => item.value === metric)!;
  return `${day.date} · ${metricInfo.label} ${metricValue(day, metric)} ${metricInfo.unit}`;
}
