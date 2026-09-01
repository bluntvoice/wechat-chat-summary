import assert from "node:assert/strict";
import test from "node:test";

import { buildCalendarCells, historyTargetForDay, intensityFor } from "../src/services/heatmap.ts";

const knownDay = (date, count, report = null) => ({
  date,
  status: "known",
  message_count: count,
  effective_message_count: Math.max(0, count - 1),
  participant_count: count ? 2 : 0,
  effective_char_count: 20,
  link_count: 0,
  file_count: 0,
  calculated_at: "2026-09-01 10:00:00",
  report,
});

test("unknown and zero use different heatmap levels", () => {
  const unknown = { ...knownDay("2026-08-01", 0), status: "unknown", message_count: null };
  assert.equal(intensityFor(unknown, "message_count", [1, 2, 3, 4]), -1);
  assert.equal(intensityFor(knownDay("2026-08-02", 0), "message_count", [1, 2, 3, 4]), 0);
});

test("calendar conversion aligns dates into Monday-first weeks", () => {
  const data = {
    version: 1,
    chat_id: "room",
    chat_name: "群",
    start_date: "2026-08-03",
    end_date: "2026-08-09",
    days: [knownDay("2026-08-03", 1), knownDay("2026-08-09", 8)],
    missing_ranges: [],
    known_days: 2,
    unknown_days: 0,
  };
  const view = buildCalendarCells(data, "message_count");
  assert.equal(view.weekCount, 1);
  assert.equal(view.cells[0].day.date, "2026-08-03");
  assert.equal(view.cells[6].day.date, "2026-08-09");
});

test("history navigation is only created for a report date", () => {
  const report = { report_id: "report-1", report_date: "2026-08-03", version: 1, headline: "标题", one_line_summary: "摘要" };
  assert.equal(historyTargetForDay(knownDay("2026-08-02", 2), "room", 1), null);
  assert.deepEqual(
    historyTargetForDay(knownDay("2026-08-03", 2, report), "room", 7),
    { chatId: "room", date: "2026-08-03", reportId: "report-1", requestId: 7 },
  );
});
