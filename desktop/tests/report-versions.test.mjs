import assert from "node:assert/strict";
import test from "node:test";
import { reportVersionLabel } from "../src/services/reportVersions.ts";

test("history uses stable masked labels instead of its internal file revision", () => {
  assert.equal(reportVersionLabel({ version: 2, report_variant: "normal", version_label: "屏蔽版 v1.1" }), "屏蔽版 v1.1");
  assert.equal(reportVersionLabel({ version: 3, report_variant: "normal", version_label: "屏蔽版 v1.2" }), "屏蔽版 v1.2");
});

test("original and anonymous reports retain a readable fallback", () => {
  assert.equal(reportVersionLabel({ version: 1 }), "正常版 v1");
  assert.equal(reportVersionLabel({ version: 4, report_variant: "anonymous" }), "匿名版 · 来源 v4");
  assert.equal(reportVersionLabel({ version: 2, report_variant: "anonymous", version_label: "匿名版 · 来源屏蔽版 v1.1" }), "匿名版 · 来源屏蔽版 v1.1");
});
