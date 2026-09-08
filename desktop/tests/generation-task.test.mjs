import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  createGenerationTask,
  generationTaskPresentation,
  updateGenerationTask,
} from "../src/services/generationTasks.ts";

const hook = readFileSync(new URL("../src/hooks/useReportGeneration.ts", import.meta.url), "utf8");
const generatePage = readFileSync(new URL("../src/pages/GeneratePage.tsx", import.meta.url), "utf8");
const historyPage = readFileSync(new URL("../src/pages/HistoryPage.tsx", import.meta.url), "utf8");

function task(source = "scheduled") {
  return createGenerationTask({
    task_id: "task-a",
    source,
    chat_id: "chat-a",
    chat_name: "A群",
    start_date: "2026-09-07",
    end_date: "2026-09-07",
  });
}

test("scheduled progress remains bound to A when the form changes to B or C", () => {
  const running = task("scheduled");
  assert.deepEqual(generationTaskPresentation(running, {
    chat_name: "B群", start_date: "2026-09-08", end_date: "2026-09-08",
  }), { chat_name: "A群", start_date: "2026-09-07", end_date: "2026-09-07" });
  assert.deepEqual(generationTaskPresentation(running, {
    chat_name: "C群", start_date: "2026-09-09", end_date: "2026-09-10",
  }), { chat_name: "A群", start_date: "2026-09-07", end_date: "2026-09-07" });
});

test("manual and regenerate tasks keep their original identity after selection changes", () => {
  for (const source of ["manual", "regenerate"]) {
    const running = task(source);
    const completed = updateGenerationTask(running, "task-a", {
      stage: "completed", percent: 100, message: "完成", elapsed_seconds: 12,
    }, "success");
    assert.equal(completed.source, source);
    assert.equal(completed.chat_id, "chat-a");
    assert.equal(completed.start_date, "2026-09-07");
    assert.equal(generationTaskPresentation(completed, {
      chat_name: "B群", start_date: "2026-09-08", end_date: "2026-09-08",
    }).chat_name, "A群");
  }
});

test("stale progress cannot overwrite a newer task", () => {
  const running = task();
  assert.equal(updateGenerationTask(running, "other-task", {
    stage: "failed", percent: 99, message: "旧任务", elapsed_seconds: 1,
  }), running);
});

test("all three generation sources use the shared generation hook", () => {
  assert.match(hook, /import type \{[^}]*GenerationSource/);
  assert.match(hook, /generation_source: source/);
  assert.match(generatePage, /source: "scheduled"/);
  assert.match(generatePage, /runGenerationRef\.current/);
  assert.match(historyPage, /source: "regenerate"/);
  assert.match(generatePage, /generationTaskPresentation\(currentTask/);
});
