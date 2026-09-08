import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { parseReleaseNotes } from "../src/services/releaseNotes.ts";

const aboutPage = readFileSync(new URL("../src/pages/AboutPage.tsx", import.meta.url), "utf8");
const styles = readFileSync(new URL("../src/styles.css", import.meta.url), "utf8");
const updater = readFileSync(new URL("../src-tauri/src/updater.rs", import.meta.url), "utf8");

for (const newline of ["\n", "\r\n"]) {
  test(`Release Notes preserve paragraphs, lists and bold with ${JSON.stringify(newline)} line endings`, () => {
    const source = [
      "## 版本亮点",
      "",
      "新增以下功能：",
      "",
      "- 功能 **A**",
      "- 功能 B",
      "",
      "修复：",
      "",
      "1. 问题 C",
      "2. 问题 D",
    ].join(newline);
    const blocks = parseReleaseNotes(source);
    assert.deepEqual(blocks.map((block) => block.kind), [
      "heading", "paragraph", "unordered-list", "paragraph", "ordered-list",
    ]);
    assert.equal(blocks[2].items[0].map((part) => part.text).join(""), "功能 A");
    assert.equal(blocks[2].items[0][1].kind, "strong");
  });
}

test("update dialog is scroll-bounded and exposes every recoverable phase", () => {
  for (const status of [
    "idle", "checking", "update_available", "downloading", "verifying", "ready_to_install",
    "installing", "check_failed", "download_failed", "verify_failed", "install_failed",
  ]) assert.match(aboutPage, new RegExp(`\\"${status}\\"`));
  assert.match(styles, /\.update-release-notes[^}]*max-height:\s*300px[^}]*overflow-y:\s*auto/s);
  assert.match(styles, /\.update-release-notes p[^}]*white-space:\s*pre-wrap/s);
  assert.match(aboutPage, /重新下载/);
  assert.match(aboutPage, /重新安装/);
  assert.match(aboutPage, /重新检查/);
});

test("retry resets progress and errors while action guards block duplicate work", () => {
  assert.match(aboutPage, /if \(actionGuard\.current \|\| !update\) return/);
  assert.match(aboutPage, /setProgress\(\{ phase: "downloading", downloaded_bytes: 0, total_bytes: null, percent: null \}\)/);
  assert.match(aboutPage, /setErrorDetail\(""\)/);
  assert.match(aboutPage, /setVerified\(null\)/);
  assert.match(updater, /downloading\.swap\(true, Ordering::SeqCst\)/);
  assert.match(updater, /installing\.swap\(true, Ordering::SeqCst\)/);
});

test("progress uses emitted byte counts and explicitly enters verification", () => {
  assert.match(updater, /downloaded_bytes: downloaded/);
  assert.match(updater, /total_bytes: expected_total/);
  assert.match(updater, /phase: "verifying"\.to_string\(\)/);
  assert.match(aboutPage, /progress\.downloaded_bytes/);
  assert.match(aboutPage, /progress\.total_bytes/);
  assert.doesNotMatch(aboutPage, /percent\s*\+\s*1/);
});
