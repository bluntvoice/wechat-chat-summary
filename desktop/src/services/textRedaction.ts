import type { RedactionTarget, TextRedaction } from "../types/desktop";

export const REDACTION_NOTICE = "已屏蔽，建议在群内查看";
export const REDACTION_MASK = "■";

export function toggleKeywordSelection(current: string[], targets: RedactionTarget[]): string[] {
  const ids = targets.filter((target) => target.id.startsWith("word_cloud:") && !target.redacted).map((target) => target.id);
  return ids.every((id) => current.includes(id))
    ? current.filter((id) => !ids.includes(id))
    : [...new Set([...current, ...ids])];
}

// textarea 的下标是 UTF-16；桥接使用 Unicode 字符下标，避免 emoji 后方选区错位。
export function textRedactionSelection(targetId: string, text: string, start: number, end: number,
  atomicRanges: Array<{ start: number; end: number }> = []): TextRedaction | null {
  if (start < 0 || end <= start || end > text.length || !text.slice(start, end).trim()) return null;
  let first = Array.from(text.slice(0, start)).length;
  let last = Array.from(text.slice(0, end)).length;
  atomicRanges.forEach((range) => {
    if (first < range.end && last > range.start) {
      first = Math.min(first, range.start);
      last = Math.max(last, range.end);
    }
  });
  return {
    target_id: targetId,
    start: first,
    end: last,
    text: Array.from(text).slice(first, last).join(""),
  };
}

export function previewTextRedactions(text: string, edits: TextRedaction[]): string {
  const chars = Array.from(text);
  const hidden = new Set<number>();
  edits.forEach(({ start, end }) => { for (let index = start; index < end; index += 1) hidden.add(index); });
  return chars.map((char, index) => hidden.has(index) ? REDACTION_MASK : char).join("");
}
