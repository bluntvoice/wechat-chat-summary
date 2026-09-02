import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const app = readFileSync(new URL("../src/App.tsx", import.meta.url), "utf8");
const guide = readFileSync(new URL("../src/components/GuideDialog.tsx", import.meta.url), "utf8");
const history = readFileSync(new URL("../src/pages/HistoryPage.tsx", import.meta.url), "utf8");
const generation = readFileSync(new URL("../src/hooks/useReportGeneration.ts", import.meta.url), "utf8");
const styles = readFileSync(new URL("../src/styles.css", import.meta.url), "utf8");
const html = readFileSync(new URL("../index.html", import.meta.url), "utf8");
const tauriConfig = JSON.parse(readFileSync(new URL("../src-tauri/tauri.conf.json", import.meta.url), "utf8"));
const installer = readFileSync(new URL("../installer/test-installer.nsi", import.meta.url), "utf8");
const buildScript = readFileSync(new URL("../scripts/build-windows-test-package.ps1", import.meta.url), "utf8");

test("primary navigation uses a unified icon library and resets page scroll", () => {
  assert.match(app, /from "lucide-react"/);
  assert.doesNotMatch(app, /<span>[生历热设关]<\/span>/);
  assert.match(app, /window\.scrollTo\(\{ top: 0, left: 0/);
});

test("quick guide is dismissible and contains seven concise steps", () => {
  assert.match(app, /quick-guide-dismissed/);
  assert.match(app, /GuideDialog/);
  assert.equal((guide.match(/^  \["/gm) ?? []).length, 7);
  assert.match(guide, /关闭使用指南/);
});

test("elapsed time uses the local clock while percent remains backend-owned", () => {
  assert.match(generation, /Date\.now\(\) - startedAt/);
  assert.match(generation, /\.\.\.snapshot/);
  assert.doesNotMatch(generation, /percent\s*\+\s*1/);
});

test("history resolves member placeholders and avoids internal schema noise", () => {
  assert.match(history, /resolveMemberTokens/);
  assert.match(history, /member_aliases/);
  assert.doesNotMatch(history, /Schema \{detail\.schema_version\}/);
  assert.match(styles, /\.redaction-groups[^\n]+align-items: start/);
});

test("history preview supports validated inline redaction with an auxiliary target list", () => {
  assert.match(history, /get_redaction_targets/);
  assert.match(history, /module\.redaction_target_id/);
  assert.match(history, /role=\{selectable \? "checkbox"/);
  assert.match(history, /RedactionTargetGroups/);
  assert.match(history, /"redact_report"/);
  assert.match(history, /updated\.report_id/);
  assert.match(styles, /\.history-module\.redaction-selectable/);
});

test("history activity statistics use a bounded compact renderer", () => {
  assert.match(history, /function ActivityStatsView/);
  assert.match(history, /\.slice\(0, 5\)/);
  assert.match(history, /\.slice\(0, 12\)/);
  assert.match(history, /isActivityStatsModule\(module\)/);
  assert.match(styles, /\.history-activity-metrics[^\n]+repeat\(3/);
  assert.match(styles, /\.history-segment-list[^\n]+repeat\(2/);
});

test("all user-visible desktop product names use 群聊拾遗", () => {
  assert.equal(tauriConfig.productName, "群聊拾遗");
  assert.equal(tauriConfig.app.windows[0].title, "群聊拾遗");
  assert.match(html, /<title>群聊拾遗<\/title>/);
  assert.match(installer, /InstallDir "\$LOCALAPPDATA\\Programs\\群聊拾遗"/);
  assert.match(installer, /File "\/oname=群聊拾遗\.exe"/);
  assert.match(installer, /CreateShortcut "\$DESKTOP\\群聊拾遗\.lnk"/);
  assert.match(installer, /WriteUninstaller "\$INSTDIR\\卸载群聊拾遗\.exe"/);
  assert.doesNotMatch(buildScript, /微信群聊总结/);
  assert.doesNotMatch(buildScript, /WeChat Chat Summary/);
});
