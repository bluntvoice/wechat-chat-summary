type ReportVersion = { version: number; report_variant?: string; version_label?: string };

export function reportVersionLabel(report: ReportVersion): string {
  return report.version_label || (report.report_variant === "anonymous"
    ? `匿名版 · 来源 v${report.version}` : `正常版 v${report.version}`);
}
