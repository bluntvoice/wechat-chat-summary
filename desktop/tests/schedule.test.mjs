import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { inclusiveDateRange, scheduledReportDate } from "../src/services/dates.ts";
import {
  createScheduleTask,
  dueScheduleTasks,
  refreshScheduleTaskNames,
  SerialGenerationQueue,
  upsertScheduleTask,
} from "../src/services/scheduleTasks.ts";
import { INITIAL_SETTINGS } from "../src/types/desktop.ts";

const generatePage = readFileSync(new URL("../src/pages/GeneratePage.tsx", import.meta.url), "utf8");

test("scheduled reports preserve today as the backward-compatible default", () => {
  assert.equal(INITIAL_SETTINGS.schedule_date_mode, "today");
  assert.equal(scheduledReportDate("2026-09-02", "today"), "2026-09-02");
});

test("yesterday mode crosses month, year and leap-day boundaries", () => {
  assert.equal(scheduledReportDate("2026-03-01", "yesterday"), "2026-02-28");
  assert.equal(scheduledReportDate("2024-03-01", "yesterday"), "2024-02-29");
  assert.equal(scheduledReportDate("2026-01-01", "yesterday"), "2025-12-31");
});

test("invalid scheduled dates and modes fail fast", () => {
  assert.throws(() => scheduledReportDate("2026-02-30", "today"));
  assert.throws(() => scheduledReportDate("2026/09/02", "today"));
  assert.throws(() => scheduledReportDate("2026-09-02", "other"));
});

test("generate page offers multi-chat schedule management and exact delete confirmation", () => {
  assert.match(generatePage, /aria-label="定时报告日期"/);
  assert.match(generatePage, /定时总结管理/);
  assert.match(generatePage, /添加定时总结/);
  assert.match(generatePage, /删除定时总结？/);
  assert.match(generatePage, /删除后将不再自动生成该群聊的定时报告/);
  assert.match(generatePage, /last_attempt_date: triggerDate/);
  assert.match(generatePage, /last_report_date: reportDate/);
});

test("multiple schedule tasks coexist, update independently and reject duplicate chats", () => {
  const chatA = { id: "a@chatroom", name: "A群" };
  const chatB = { id: "b@chatroom", name: "B群" };
  const taskA = createScheduleTask(chatA, "22:30", "today", "task-a");
  const taskB = createScheduleTask(chatB, "23:00", "yesterday", "task-b");
  let tasks = upsertScheduleTask([], taskA);
  tasks = upsertScheduleTask(tasks, taskB);
  assert.deepEqual(tasks.map((item) => item.chat_id), [chatA.id, chatB.id]);
  tasks = upsertScheduleTask(tasks, { ...taskA, enabled: false, time: "21:00" });
  assert.equal(tasks.find((item) => item.task_id === "task-a").enabled, false);
  assert.equal(tasks.find((item) => item.task_id === "task-a").time, "21:00");
  assert.equal(tasks.find((item) => item.task_id === "task-b").time, "23:00");
  assert.throws(() => upsertScheduleTask(tasks, { ...taskB, task_id: "duplicate" }), /可直接修改现有任务/);
  assert.deepEqual(tasks.filter((item) => item.task_id !== "task-a").map((item) => item.task_id), ["task-b"]);
});

test("stable chat ids survive rename and missing ids are never matched by name", () => {
  const task = createScheduleTask({ id: "stable-id", name: "旧群名" }, "22:30", "today", "task-a");
  assert.equal(refreshScheduleTaskNames([task], [{ id: "stable-id", name: "新群名" }])[0].chat_name, "新群名");
  assert.equal(refreshScheduleTaskNames([task], [{ id: "different-id", name: "旧群名" }])[0].chat_name, "旧群名");
});

test("due selection uses per-task time and last attempt date", () => {
  const first = createScheduleTask({ id: "a", name: "A" }, "21:00", "today", "a");
  const second = createScheduleTask({ id: "b", name: "B" }, "22:00", "today", "b");
  const disabled = { ...createScheduleTask({ id: "c", name: "C" }, "20:00", "today", "c"), enabled: false };
  const attempted = { ...createScheduleTask({ id: "d", name: "D" }, "20:00", "today", "d"), last_attempt_date: "2026-09-08" };
  assert.deepEqual(dueScheduleTasks([second, disabled, attempted, first], "2026-09-08", "21:30").map((item) => item.task_id), ["a"]);
});

test("serial queue keeps B pending, deduplicates chat/date and isolates A failure", async () => {
  const queue = new SerialGenerationQueue();
  const itemA = { key: "a:2026-09-08", scheduleTaskId: "a", chatId: "a", chatName: "A", reportDate: "2026-09-08" };
  const itemB = { key: "b:2026-09-08", scheduleTaskId: "b", chatId: "b", chatName: "B", reportDate: "2026-09-08" };
  assert.equal(queue.enqueue(itemA), true);
  assert.equal(queue.enqueue(itemA), false);
  assert.equal(queue.enqueue(itemB), true);
  const events = [];
  await queue.drain(async (item) => {
    events.push(`start:${item.chatId}`);
    if (item.chatId === "a") throw new Error("A failed");
    events.push(`success:${item.chatId}`);
  }, (pending, current) => events.push(`queue:${pending}:${current?.chatId || "none"}`));
  assert.deepEqual(events, ["queue:1:a", "start:a", "queue:0:b", "start:b", "success:b", "queue:0:none"]);
  assert.deepEqual(queue.snapshot(), { pending: 0, running: false });
});

test("a queue can release pending dedupe keys after persistence fails", () => {
  const queue = new SerialGenerationQueue();
  const item = { key: "chat-a:2026-09-08", scheduleTaskId: "a", chatId: "chat-a", chatName: "A", reportDate: "2026-09-08" };
  assert.equal(queue.enqueue(item), true);
  assert.equal(queue.enqueue(item), false);
  queue.clearPending();
  assert.deepEqual(queue.snapshot(), { pending: 0, running: false });
  assert.equal(queue.enqueue(item), true);
});

test("daily range generation is inclusive and limited to seven dates", () => {
  assert.deepEqual(inclusiveDateRange("2024-02-28", "2024-03-01"), [
    "2024-02-28", "2024-02-29", "2024-03-01",
  ]);
  assert.equal(inclusiveDateRange("2026-09-01", "2026-09-07").length, 7);
  assert.throws(() => inclusiveDateRange("2026-09-01", "2026-09-08"), /最多选择 7 天/);
  assert.throws(() => inclusiveDateRange("2026-09-03", "2026-09-02"), /不能早于/);
  assert.throws(() => inclusiveDateRange("2026-02-30", "2026-03-01"), /无效/);
});

test("custom ranges default to separate daily reports and retain a combined option", () => {
  assert.equal(INITIAL_SETTINGS.range_output_mode, "daily");
  assert.match(generatePage, /每日分别生成/);
  assert.match(generatePage, /合并成一份/);
  assert.match(generatePage, /runBatchGeneration/);
  assert.match(generatePage, /`生成 \$\{selectedDayCount\} 份单日报告`/);
  assert.match(generatePage, /retryBatchDate/);
});
