import { X } from "lucide-react";

type GuideDialogProps = {
  onClose: () => void;
  onOpenSettings: () => void;
};

const STEPS = [
  ["启动数据源", "先运行 WeChatDataAnalysis，保持本机接口可用。"],
  ["连接微信数据", "在生成页测试连接并读取群聊列表。"],
  ["配置 AI API", "在设置中保存服务地址、模型和本机私有 Key。"],
  ["选择范围", "选择群聊与单日或自定义日期区间。"],
  ["生成总结", "观察真实处理阶段、百分比与耗时。"],
  ["查看报告", "打开 PNG、HTML，或进入报告所在目录。"],
  ["回顾记录", "在历史中心检索报告，在热力图查看每日活跃。"],
] as const;

export default function GuideDialog({ onClose, onOpenSettings }: GuideDialogProps) {
  return <div className="guide-backdrop" role="presentation" onMouseDown={(event) => {
    if (event.target === event.currentTarget) onClose();
  }}>
    <section className="guide-dialog" role="dialog" aria-modal="true" aria-labelledby="guide-title">
      <header className="guide-heading">
        <div><h2 id="guide-title">快速开始</h2><p>按顺序完成以下步骤即可生成第一份群聊总结。</p></div>
        <button className="icon-button" onClick={onClose} aria-label="关闭使用指南" title="关闭"><X size={18} aria-hidden="true" /></button>
      </header>
      <ol className="guide-steps">{STEPS.map(([title, detail], index) => <li key={title}><span>{index + 1}</span><div><strong>{title}</strong><p>{detail}</p></div></li>)}</ol>
      <footer className="guide-actions"><button className="button secondary" onClick={onClose}>稍后再看</button><button className="button primary small" onClick={onOpenSettings}>打开设置</button></footer>
    </section>
  </div>;
}
