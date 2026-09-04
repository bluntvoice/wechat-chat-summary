import { useEffect, useRef, useState, type Dispatch, type SetStateAction } from "react";

import { bridge } from "../services/desktopBridge";
import type { BatchGenerationItem, GenerationResult, Progress, Settings } from "../types/desktop";

type GenerationOptions = {
  settings: Settings;
  setSettings: Dispatch<SetStateAction<Settings>>;
  setMessage: Dispatch<SetStateAction<string>>;
  saveSettings: (showNotice?: boolean) => Promise<void>;
  beforeGeneration: () => void;
};

type ProgressScale = { index: number; total: number; label: string; batchStartedAt: number };

function noMessagesError(error: unknown) {
  return String(error instanceof Error ? error.message : error).includes("指定时间范围内没有消息");
}

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
  const [batchResults, setBatchResults] = useState<BatchGenerationItem[]>([]);
  const progressTimer = useRef<number | null>(null);
  const elapsedTimer = useRef<number | null>(null);

  function stopProgressTimers() {
    if (progressTimer.current) window.clearInterval(progressTimer.current);
    progressTimer.current = null;
    if (elapsedTimer.current) window.clearInterval(elapsedTimer.current);
    elapsedTimer.current = null;
  }

  useEffect(() => stopProgressTimers, []);

  function applyProgress(snapshot: Progress, startedAt: number, scale?: ProgressScale) {
    const elapsedBase = scale?.batchStartedAt ?? startedAt;
    const percent = scale
      ? Math.round(((scale.index + Math.max(0, Math.min(100, snapshot.percent)) / 100) / scale.total) * 100)
      : snapshot.percent;
    setProgress({
      ...snapshot,
      percent,
      message: scale ? `${scale.label} · ${snapshot.message}` : snapshot.message,
      elapsed_seconds: Math.floor((Date.now() - elapsedBase) / 1000),
    });
  }

  async function generateOne(
    targetChatId: string,
    targetChatName: string,
    start: string,
    end: string,
    rangeMode: "single" | "custom",
    scale?: ProgressScale,
  ) {
    const jobId = crypto.randomUUID();
    const startedAt = Date.now();
    applyProgress({ stage: "waiting", percent: 0, message: "等待分析引擎启动…", elapsed_seconds: 0 }, startedAt, scale);
    elapsedTimer.current = window.setInterval(() => {
      setProgress((current) => current ? {
        ...current,
        elapsed_seconds: Math.floor((Date.now() - (scale?.batchStartedAt ?? startedAt)) / 1000),
      } : current);
    }, 500);
    progressTimer.current = window.setInterval(() => {
      bridge<Progress>("get_progress", { job_id: jobId })
        .then((snapshot) => applyProgress(snapshot, startedAt, scale))
        .catch(() => undefined);
    }, 900);
    try {
      return await bridge<GenerationResult>("generate", {
        job_id: jobId,
        chat: targetChatId,
        chat_name: targetChatName,
        range_mode: rangeMode,
        start: `${start} 00:00:00`,
        end: `${end} 23:59:59`,
        export_root: settings.export_root,
      });
    } finally {
      stopProgressTimers();
    }
  }

  async function refreshedChatIds(targetChatId: string, fallback: string[] = []) {
    let summarizedChatIds = fallback;
    try {
      const refreshed = await bridge<{ summarized_chat_ids?: string[] }>("refresh_history_state", {
        import_reports: false,
      });
      summarizedChatIds = refreshed.summarized_chat_ids || summarizedChatIds;
    } catch {
      // 生成结果已写入 SQLite；状态刷新失败时仅即时补上当前群。
    }
    return summarizedChatIds.includes(targetChatId)
      ? summarizedChatIds
      : [...summarizedChatIds, targetChatId];
  }

  async function runGeneration(
    targetChatId: string,
    targetChatName: string,
    start: string,
    end: string,
    rangeMode: "single" | "custom",
    scheduled = false,
  ) {
    const startedAt = Date.now();
    setBusy(true);
    setResult(null);
    setBatchResults([]);
    beforeGeneration();
    setMessage(scheduled ? `正在执行 ${targetChatName || "已设群聊"} 的定时日报…` : "正在生成总结，进度会按真实处理阶段更新。");
    try {
      if (!scheduled) await saveSettings(false);
      const generated = await generateOne(targetChatId, targetChatName, start, end, rangeMode);
      const summarizedChatIds = await refreshedChatIds(targetChatId, generated.summarized_chat_ids || []);
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
        summarized_chat_ids: summarizedChatIds,
      }));
      setMessage(scheduled ? "定时日报已生成，PNG 与 HTML 均可直接打开。" : "报告已生成，PNG 与 HTML 均可直接打开。");
      return generated;
    } catch (error) {
      setProgress((current) => ({
        stage: "failed",
        percent: current?.percent || 0,
        message: "生成失败",
        elapsed_seconds: Math.floor((Date.now() - startedAt) / 1000),
      }));
      setMessage(error instanceof Error ? error.message : String(error));
      throw error;
    } finally {
      stopProgressTimers();
      setBusy(false);
    }
  }

  async function runBatchGeneration(
    targetChatId: string,
    targetChatName: string,
    dates: string[],
    preserveExisting = false,
  ) {
    const batchStartedAt = Date.now();
    setBusy(true);
    setResult(null);
    beforeGeneration();
    if (preserveExisting) {
      setBatchResults((current) => current.filter((item) => !dates.includes(item.date)));
    } else {
      setBatchResults([]);
    }
    try {
      await saveSettings(false);
      const completed: BatchGenerationItem[] = [];
      for (let index = 0; index < dates.length; index += 1) {
        const date = dates[index];
        const label = `第 ${index + 1}/${dates.length} 日 · ${date}`;
        setMessage(`${label} · 正在生成单日报告…`);
        let item: BatchGenerationItem;
        try {
          const generated = await generateOne(targetChatId, targetChatName, date, date, "single", {
            index,
            total: dates.length,
            label,
            batchStartedAt,
          });
          item = { date, status: "success", result: generated, message: "报告已生成" };
        } catch (error) {
          const detail = error instanceof Error ? error.message : String(error);
          item = noMessagesError(error)
            ? { date, status: "skipped", message: "无消息，已跳过" }
            : { date, status: "failed", message: detail || "生成失败" };
        }
        completed.push(item);
        setBatchResults((current) => [...current.filter((existing) => existing.date !== date), item].sort((a, b) => a.date.localeCompare(b.date)));
      }

      const successes = completed.filter((item) => item.status === "success");
      const skipped = completed.filter((item) => item.status === "skipped");
      const failed = completed.filter((item) => item.status === "failed");
      if (successes.length) {
        const lastResult = successes.at(-1)?.result || null;
        const summarizedChatIds = await refreshedChatIds(targetChatId, lastResult?.summarized_chat_ids || []);
        setResult(lastResult);
        setSettings((current) => ({
          ...current,
          last_chat_id: targetChatId,
          last_chat_name: targetChatName,
          summarized_chat_ids: summarizedChatIds,
        }));
      }
      setProgress({
        stage: failed.length ? "completed_with_errors" : "completed",
        percent: 100,
        message: failed.length ? "批量任务已完成，部分日期失败" : "批量任务已完成",
        elapsed_seconds: Math.round((Date.now() - batchStartedAt) / 1000),
      });
      setMessage(`逐日生成完成：成功 ${successes.length} 天，跳过 ${skipped.length} 天，失败 ${failed.length} 天。`);
      return completed;
    } finally {
      stopProgressTimers();
      setBusy(false);
    }
  }

  return {
    busy,
    setBusy,
    progress,
    result,
    setResult,
    batchResults,
    runGeneration,
    runBatchGeneration,
  };
}
