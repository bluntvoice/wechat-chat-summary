import { X } from "lucide-react";
import { useMemo } from "react";

import type { RedactionTarget } from "../types/desktop";

type Props = {
  targets: RedactionTarget[];
  selectedIds: string[];
  busy: boolean;
  onClose: () => void;
  onToggle: (target: RedactionTarget) => void;
  onApply: () => void;
};

type TargetGroupsProps = Pick<Props, "targets" | "selectedIds" | "busy" | "onToggle">;

export function RedactionTargetGroups({ targets, selectedIds, busy, onToggle }: TargetGroupsProps) {
  const groups = useMemo(() => {
    const values = new Map<string, RedactionTarget[]>();
    targets.forEach((target) => {
      values.set(target.module_label, [...(values.get(target.module_label) || []), target]);
    });
    return [...values.entries()];
  }, [targets]);

  return <div className="redaction-groups">{groups.map(([label, groupTargets]) => <div className="redaction-group" key={label}><h3>{label}<span>{groupTargets.length}</span></h3>{groupTargets.map((target) => <label className={`redaction-row ${target.redacted ? "already" : ""}`} key={target.id}><input type="checkbox" checked={selectedIds.includes(target.id)} disabled={target.redacted || busy} onChange={() => onToggle(target)} /><span><strong>{target.redacted ? "已屏蔽" : target.preview}</strong><small>{target.time_label}{target.redacted ? " · 已屏蔽，建议在群内查看" : ""}</small></span></label>)}</div>)}</div>;
}

export default function RedactionEditor({
  targets,
  selectedIds,
  busy,
  onClose,
  onToggle,
  onApply,
}: Props) {
  const existingCount = targets.filter((target) => target.redacted).length;

  return <section className="redaction-panel">
    <div className="redaction-heading"><div><h2>人工屏蔽报告内容</h2><p>勾选后将生成本地新版本；不再次调用 AI。已屏蔽条目不能在当前版本取消，可回到原版本重新编辑。</p></div><button className="icon-button" onClick={onClose} aria-label="收起屏蔽编辑器" title="收起"><X size={18} aria-hidden="true" /></button></div>
    <RedactionTargetGroups targets={targets} selectedIds={selectedIds} busy={busy} onToggle={onToggle} />
    <div className="redaction-footer"><span>已选择 {selectedIds.length} 项（含既有屏蔽）</span><button className="button primary" disabled={busy || selectedIds.length <= existingCount} onClick={onApply}>{busy ? "正在生成…" : "生成屏蔽版新报告"}</button></div>
  </section>;
}
