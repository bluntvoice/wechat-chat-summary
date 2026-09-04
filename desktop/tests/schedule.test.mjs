import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { inclusiveDateRange, scheduledReportDate } from "../src/services/dates.ts";
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

test("generate page offers explicit today and yesterday schedule choices", () => {
  assert.match(generatePage, /aria-label="定时报告日期"/);
  assert.match(generatePage, /schedule_date_mode: "today"/);
  assert.match(generatePage, /schedule_date_mode: "yesterday"/);
  assert.match(generatePage, /schedule_last_attempt_date: triggerDate/);
  assert.match(generatePage, /schedule_last_run_date: reportDate/);
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
