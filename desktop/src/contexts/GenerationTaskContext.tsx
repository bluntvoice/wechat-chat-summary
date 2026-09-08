import { createContext, useContext, useMemo, useRef, useState, type ReactNode } from "react";

import type { GenerationTask, GenerationTaskStatus, Progress } from "../types/desktop";
import { createGenerationTask, updateGenerationTask, type NewGenerationTask } from "../services/generationTasks";

type GenerationTaskState = {
  currentTask: GenerationTask | null;
  startTask: (task: NewGenerationTask) => GenerationTask;
  updateProgress: (taskId: string, progress: Progress) => void;
  finishTask: (taskId: string, status: Extract<GenerationTaskStatus, "success" | "failed" | "cancelled">, progress: Progress) => void;
};

const GenerationTaskContext = createContext<GenerationTaskState | null>(null);

export function GenerationTaskProvider({ children }: { children: ReactNode }) {
  const [currentTask, setCurrentTask] = useState<GenerationTask | null>(null);
  const currentRef = useRef<GenerationTask | null>(null);

  const value = useMemo<GenerationTaskState>(() => ({
    currentTask,
    startTask(task) {
      if (currentRef.current && ["queued", "running"].includes(currentRef.current.status)) {
        throw new Error("已有生成任务正在执行。");
      }
      const started = createGenerationTask(task);
      currentRef.current = started;
      setCurrentTask(started);
      return started;
    },
    updateProgress(taskId, progress) {
      if (currentRef.current?.task_id !== taskId) return;
      const updated = updateGenerationTask(currentRef.current, taskId, progress);
      if (!updated) return;
      currentRef.current = updated;
      setCurrentTask(updated);
    },
    finishTask(taskId, status, progress) {
      if (currentRef.current?.task_id !== taskId) return;
      const updated = updateGenerationTask(currentRef.current, taskId, progress, status);
      if (!updated) return;
      currentRef.current = updated;
      setCurrentTask(updated);
    },
  }), [currentTask]);

  return <GenerationTaskContext.Provider value={value}>{children}</GenerationTaskContext.Provider>;
}

export function useGenerationTaskContext() {
  const value = useContext(GenerationTaskContext);
  if (!value) throw new Error("GenerationTaskProvider is missing.");
  return value;
}

export function generationSourceLabel(source: GenerationTask["source"]) {
  if (source === "scheduled") return "定时总结";
  if (source === "regenerate") return "重新生成";
  return "手动生成";
}
