import type { GenerationTask, GenerationTaskStatus, Progress } from "../types/desktop";

export type NewGenerationTask = Omit<GenerationTask, "started_at" | "status" | "progress">;

export type GenerationSelection = {
  chat_name: string;
  start_date: string;
  end_date: string;
};

export function createGenerationTask(task: NewGenerationTask): GenerationTask {
  return {
    ...task,
    started_at: new Date().toISOString(),
    status: "running",
    progress: { stage: "waiting", percent: 0, message: "等待分析引擎启动…", elapsed_seconds: 0 },
  };
}

export function updateGenerationTask(
  current: GenerationTask | null,
  taskId: string,
  progress: Progress,
  status?: GenerationTaskStatus,
) {
  if (!current || current.task_id !== taskId) return current;
  return { ...current, status: status || current.status, progress };
}

export function generationTaskPresentation(
  current: GenerationTask | null,
  fallback: GenerationSelection,
): GenerationSelection {
  if (!current) return fallback;
  return {
    chat_name: current.chat_name,
    start_date: current.start_date,
    end_date: current.end_date,
  };
}
