import type { Chat, ScheduleTask } from "../types/desktop";

export type ScheduledQueueItem = {
  key: string;
  scheduleTaskId: string;
  chatId: string;
  chatName: string;
  reportDate: string;
};

export function createScheduleTask(
  chat: Chat,
  time = "22:30",
  dateMode: ScheduleTask["date_mode"] = "today",
  taskId = crypto.randomUUID(),
): ScheduleTask {
  return {
    task_id: taskId,
    chat_id: chat.id,
    chat_name: chat.name,
    time,
    date_mode: dateMode,
    enabled: true,
    created_at: new Date().toISOString(),
    last_attempt_date: "",
    last_run_at: "",
    last_report_date: "",
    last_run_status: "",
  };
}

export function upsertScheduleTask(tasks: ScheduleTask[], task: ScheduleTask) {
  const duplicate = tasks.find((item) => item.chat_id === task.chat_id && item.task_id !== task.task_id);
  if (duplicate) throw new Error("该群聊已设置定时总结，可直接修改现有任务。");
  const found = tasks.some((item) => item.task_id === task.task_id);
  return found ? tasks.map((item) => item.task_id === task.task_id ? task : item) : [...tasks, task];
}

export function refreshScheduleTaskNames(tasks: ScheduleTask[], chats: Chat[]) {
  const names = new Map(chats.map((chat) => [chat.id, chat.name]));
  return tasks.map((task) => {
    const currentName = names.get(task.chat_id);
    return currentName && currentName !== task.chat_name ? { ...task, chat_name: currentName } : task;
  });
}

export function dueScheduleTasks(tasks: ScheduleTask[], today: string, clock: string) {
  return tasks
    .filter((task) => task.enabled && task.time <= clock && task.last_attempt_date !== today)
    .sort((left, right) => left.time.localeCompare(right.time) || left.created_at.localeCompare(right.created_at) || left.task_id.localeCompare(right.task_id));
}

export class SerialGenerationQueue {
  private pending: ScheduledQueueItem[] = [];
  private keys = new Set<string>();
  private draining = false;

  enqueue(item: ScheduledQueueItem) {
    if (this.keys.has(item.key)) return false;
    this.keys.add(item.key);
    this.pending.push(item);
    return true;
  }

  snapshot() {
    return { pending: this.pending.length, running: this.draining };
  }

  clearPending() {
    if (this.draining) return;
    for (const item of this.pending) this.keys.delete(item.key);
    this.pending = [];
  }

  async drain(
    execute: (item: ScheduledQueueItem) => Promise<void>,
    onChange: (pending: number, current: ScheduledQueueItem | null) => void = () => undefined,
  ) {
    if (this.draining) return;
    this.draining = true;
    try {
      while (this.pending.length) {
        const item = this.pending.shift()!;
        onChange(this.pending.length, item);
        try {
          await execute(item);
        } catch {
          // 单项失败由调用方记录；队列必须继续处理后续任务。
        } finally {
          this.keys.delete(item.key);
        }
      }
    } finally {
      this.draining = false;
      onChange(0, null);
    }
  }
}
