import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { scheduledReportDate } from "../src/services/dates.ts";
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
