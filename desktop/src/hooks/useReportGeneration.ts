import { useEffect, useRef, useState, type Dispatch, type SetStateAction } from "react";

import { bridge } from "../services/desktopBridge";
import type { GenerationResult, Progress, Settings } from "../types/desktop";

type GenerationOptions = {
  settings: Settings;
  setSettings: Dispatch<SetStateAction<Settings>>;
  setMessage: Dispatch<SetStateAction<string>>;
  saveSettings: (showNotice?: boolean) => Promise<void>;
  beforeGeneration: () => void;
};

export function useReportGeneration({
  settings,
  setSettings,
  setMessage,
  saveSettings,
  beforeGeneration,
}: GenerationOptions) {
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState<Progress | null>(null);
  const [result, setResult] = useState<GenerationResult | null>(null);
  const progressTimer = useRef<number | null>(null);

  useEffect(
    () => () => {
      if (progressTimer.current) window.clearInterval(progressTimer.current);
    },
    [],
  );

  async function runGeneration(
    targetChatId: string,
    targetChatName: string,
    start: string,
    end: string,
    rangeMode: "single" | "custom",
    scheduled = false,
  ) {
    const jobId = crypto.randomUUID();
    const startedAt = Date.now();
    setBusy(true);
    setResult(null);
    beforeGeneration();
    setProgress({ stage: "waiting", percent: 0, message: "等待分析引擎启动…", elapsed_seconds: 0 });
    setMessage(scheduled ? `正在执行 ${targetChatName || "已设群聊"} 的定时日报…` : "正在生成总结，进度会按真实处理阶段更新。");
    try {
      if (!scheduled) await saveSettings(false);
      progressTimer.current = window.setInterval(() => {
        bridge<Progress>("get_progress", { job_id: jobId }).then(setProgress).catch(() => undefined);
      }, 900);
      const generated = await bridge<GenerationResult>("generate", {
        job_id: jobId,
        chat: targetChatId,
        chat_name: targetChatName,
        range_mode: rangeMode,
        start: `${start} 00:00:00`,
        end: `${end} 23:59:59`,
        export_root: settings.export_root,
      });
      setResult(generated);
      setProgress({
        stage: "completed",
        percent: 100,
        message: "报告生成完成",
        elapsed_seconds: Math.round((Date.now() - startedAt) / 1000),
      });
      setSettings((current) => ({
        ...current,
        last_chat_id: targetChatId,
        last_chat_name: targetChatName,
      }));
      setMessage(scheduled ? "定时日报已生成，图片与完整 HTML 分别可打开。" : "报告已生成，图片与完整 HTML 分别可打开。");
      return generated;
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error));
      throw error;
    } finally {
      if (progressTimer.current) window.clearInterval(progressTimer.current);
      progressTimer.current = null;
      setBusy(false);
    }
  }

  return { busy, setBusy, progress, result, setResult, runGeneration };
}
