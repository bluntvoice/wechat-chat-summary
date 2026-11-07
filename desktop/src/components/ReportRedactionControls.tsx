import { TextRedactionEditor } from "./TextRedactionEditor";
import type { RedactionTarget, TextRedaction } from "../types/desktop";

export function ReportRedactionControls({ targets, selectedIds, textRedactions, busy, onToggle, onTextChange, onToggleKeywords }: {
  targets: RedactionTarget[]; selectedIds: string[]; textRedactions: TextRedaction[]; busy: boolean;
  onToggle: (target: RedactionTarget) => void;
  onTextChange: (targetId: string, edits: TextRedaction[]) => void;
  onToggleKeywords: () => void;
}) {
  const keywords = targets.filter((target) => target.id.startsWith("word_cloud:"));
  const editable = keywords.filter((target) => !target.redacted);
  const allSelected = editable.length > 0 && editable.every((target) => selectedIds.includes(target.id));
  return <>
    {targets.filter((target) => target.text !== undefined).map((target) => <TextRedactionEditor key={target.id} target={target} wholeSelected={selectedIds.includes(target.id)} edits={textRedactions.filter((edit) => edit.target_id === target.id)} busy={busy} onToggle={onToggle} onChange={onTextChange} />)}
    {keywords.length > 0 && <section className="text-redaction-editor"><div className="text-redaction-heading"><h4>群关键词</h4><button className="button secondary small" disabled={busy || !editable.length} onClick={onToggleKeywords}>{allSelected ? "取消全选关键词" : "全选关键词"}</button></div><p className="text-redaction-help">可逐个勾选，也可全选后取消不需要屏蔽的词；生成后所选关键词将不再显示。</p><div className="history-keyword-list">{keywords.map((target) => <label key={target.id}><input type="checkbox" checked={selectedIds.includes(target.id)} disabled={busy || target.redacted} onChange={() => onToggle(target)} />{target.redacted ? "已屏蔽关键词" : target.preview}</label>)}</div></section>}
  </>;
}
