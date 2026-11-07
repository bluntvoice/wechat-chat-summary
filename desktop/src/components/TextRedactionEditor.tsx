import { useRef, useState } from "react";

import { previewTextRedactions, REDACTION_NOTICE, textRedactionSelection } from "../services/textRedaction";
import type { RedactionTarget, TextRedaction } from "../types/desktop";

type Props = {
  target: RedactionTarget;
  wholeSelected: boolean;
  edits: TextRedaction[];
  busy: boolean;
  onToggle: (target: RedactionTarget) => void;
  onChange: (targetId: string, edits: TextRedaction[]) => void;
};

export function TextRedactionEditor({ target, wholeSelected, edits, busy, onToggle, onChange }: Props) {
  const input = useRef<HTMLTextAreaElement>(null);
  const [selection, setSelection] = useState<TextRedaction | null>(null);
  const text = target.text || "";
  const disabled = busy || target.redacted || wholeSelected;
  function selectText() {
    const element = input.current;
    if (element) setSelection(textRedactionSelection(target.id, text, element.selectionStart, element.selectionEnd, target.atomic_ranges));
  }
  function addSelection() {
    if (!selection || disabled) return;
    if (!edits.some((edit) => edit.start === selection.start && edit.end === selection.end)) {
      onChange(target.id, [...edits, selection]);
    }
    setSelection(null);
  }
  return <section className="text-redaction-editor">
    <div className="text-redaction-heading"><h4>{target.module_label}</h4><label><input type="checkbox" checked={wholeSelected} disabled={busy || target.redacted} onChange={() => onToggle(target)} />{target.redacted ? "已全部屏蔽" : "整段屏蔽"}</label></div>
    {!target.redacted && <>
      <p className="text-redaction-help">在下方选中文字后，点击“屏蔽选中文字”，可连续标记多处。选中昵称的一部分时会屏蔽整个昵称。</p>
      <textarea ref={input} aria-label={`${target.module_label}原文`} value={text} readOnly disabled={disabled} rows={4} onSelect={selectText} />
      <button className="button secondary small" disabled={disabled || !selection} onClick={addSelection}>屏蔽选中文字</button>
      {edits.length > 0 && <ul className="text-redaction-selections">{edits.map((edit, index) => <li key={`${edit.start}-${edit.end}`}><span>待屏蔽：{edit.text}</span><button className="button secondary small" disabled={busy} onClick={() => onChange(target.id, edits.filter((_, itemIndex) => itemIndex !== index))}>撤销此处</button></li>)}</ul>}
      {(wholeSelected || edits.length > 0) && <div className="text-redaction-preview"><strong>屏蔽后预览</strong><p>{wholeSelected ? REDACTION_NOTICE : previewTextRedactions(text, edits)}</p></div>}
    </>}
  </section>;
}
