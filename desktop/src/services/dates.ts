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
