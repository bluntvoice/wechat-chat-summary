import assert from "node:assert/strict";
import test from "node:test";

import { previewTextRedactions, REDACTION_NOTICE, textRedactionSelection, toggleKeywordSelection } from "../src/services/textRedaction.ts";

test("text selections after emoji use Unicode character offsets", () => {
  assert.deepEqual(textRedactionSelection("conclusion", "😀公开私密结尾", 4, 6), {
    target_id: "conclusion", start: 3, end: 5, text: "私密",
  });
});

test("empty or invalid selections cannot be submitted", () => {
  for (const [start, end] of [[0, 0], [-1, 2], [1, 99], [0, 1]]) {
    assert.equal(textRedactionSelection("conclusion", " 结尾", start, end), null);
  }
});

test("partial nickname selections expand to the entire displayed member token", () => {
  assert.deepEqual(textRedactionSelection("one_line_summary", "😀小明同学讨论", 3, 4, [{ start: 1, end: 5 }]), {
    target_id: "one_line_summary", start: 1, end: 5, text: "小明同学",
  });
});

test("multiple overlapping ranges produce one marker per continuous selection", () => {
  const text = "公开甲私密甲，保留😀私密乙结尾";
  const first = textRedactionSelection("conclusion", text, 3, 6);
  const second = textRedactionSelection("conclusion", text, 11, 14);
  assert.equal(previewTextRedactions(text, [second, first, first]), `公开甲${REDACTION_NOTICE}，保留😀${REDACTION_NOTICE}结尾`);
  assert.equal(previewTextRedactions(text, []), text);
});

test("keyword select all covers hidden words, preserves unrelated and locked selections, and can be reversed", () => {
  const targets = Array.from({ length: 30 }, (_, index) => ({ id: `word_cloud:${index}`, redacted: index === 0 }));
  const initial = ["topics:0", "word_cloud:0", "word_cloud:2"];
  const selected = toggleKeywordSelection(initial, targets);
  assert.equal(selected.length, 31);
  assert.ok(selected.includes("word_cloud:29"));
  assert.deepEqual(toggleKeywordSelection(selected, targets), ["topics:0", "word_cloud:0"]);
  const exceptOne = selected.filter((id) => id !== "word_cloud:15");
  assert.ok(toggleKeywordSelection(exceptOne, targets).includes("word_cloud:15"));
});
