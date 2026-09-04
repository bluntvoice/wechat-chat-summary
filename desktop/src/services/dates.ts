export function localDate(offsetDays = 0) {
  const value = new Date();
  value.setDate(value.getDate() + offsetDays);
  return formatLocalDate(value);
}

function formatLocalDate(value: Date) {
  return `${value.getFullYear()}-${String(value.getMonth() + 1).padStart(2, "0")}-${String(value.getDate()).padStart(2, "0")}`;
}

export function scheduledReportDate(triggerDate: string, mode: "today" | "yesterday") {
  const matched = /^(\d{4})-(\d{2})-(\d{2})$/.exec(triggerDate);
  if (!matched) throw new Error("定时任务触发日期格式无效。");
  const value = new Date(Number(matched[1]), Number(matched[2]) - 1, Number(matched[3]), 12);
  if (formatLocalDate(value) !== triggerDate) throw new Error("定时任务触发日期无效。");
  if (mode === "today") return triggerDate;
  if (mode !== "yesterday") throw new Error("定时报告日期仅支持当日或昨日。");
  value.setDate(value.getDate() - 1);
  return formatLocalDate(value);
}

function parseIsoDate(value: string, label: string) {
  const matched = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);
  if (!matched) throw new Error(`${label}格式无效。`);
  const timestamp = Date.UTC(Number(matched[1]), Number(matched[2]) - 1, Number(matched[3]));
  const parsed = new Date(timestamp);
  const normalized = `${parsed.getUTCFullYear()}-${String(parsed.getUTCMonth() + 1).padStart(2, "0")}-${String(parsed.getUTCDate()).padStart(2, "0")}`;
  if (normalized !== value) throw new Error(`${label}无效。`);
  return parsed;
}

export function inclusiveDateRange(start: string, end: string, maxDays = 7) {
  const startDate = parseIsoDate(start, "开始日期");
  const endDate = parseIsoDate(end, "结束日期");
  if (endDate < startDate) throw new Error("结束日期不能早于开始日期。");
  const dayCount = Math.floor((endDate.getTime() - startDate.getTime()) / 86_400_000) + 1;
  if (dayCount > maxDays) throw new Error(`逐日生成一次最多选择 ${maxDays} 天。`);
  return Array.from({ length: dayCount }, (_, index) => {
    const value = new Date(startDate.getTime() + index * 86_400_000);
    return `${value.getUTCFullYear()}-${String(value.getUTCMonth() + 1).padStart(2, "0")}-${String(value.getUTCDate()).padStart(2, "0")}`;
  });
}
