import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const app = readFileSync(new URL("../src/App.tsx", import.meta.url), "utf8");
const guide = readFileSync(new URL("../src/components/GuideDialog.tsx", import.meta.url), "utf8");
const generatePage = readFileSync(new URL("../src/pages/GeneratePage.tsx", import.meta.url), "utf8");
const settings = readFileSync(new URL("../src/pages/SettingsPage.tsx", import.meta.url), "utf8");
const about = readFileSync(new URL("../src/pages/AboutPage.tsx", import.meta.url), "utf8");
const dataSource = readFileSync(new URL("../src/services/wechatDataSource.ts", import.meta.url), "utf8");
const tauriLib = readFileSync(new URL("../src-tauri/src/lib.rs", import.meta.url), "utf8");
const history = readFileSync(new URL("../src/pages/HistoryPage.tsx", import.meta.url), "utf8");
const generation = readFileSync(new URL("../src/hooks/useReportGeneration.ts", import.meta.url), "utf8");
const styles = readFileSync(new URL("../src/styles.css", import.meta.url), "utf8");
const html = readFileSync(new URL("../index.html", import.meta.url), "utf8");
const tauriConfig = JSON.parse(readFileSync(new URL("../src-tauri/tauri.conf.json", import.meta.url), "utf8"));
const installer = readFileSync(new URL("../installer/test-installer.nsi", import.meta.url), "utf8");
const buildScript = readFileSync(new URL("../scripts/build-windows-test-package.ps1", import.meta.url), "utf8");
const workflows = ["build-test.yml", "ci.yml", "release.yml"]
  .map((name) => readFileSync(new URL(`../../.github/workflows/${name}`, import.meta.url), "utf8"))
  .join("\n");

test("primary navigation uses a unified icon library and resets page scroll", () => {
  assert.match(app, /from "lucide-react"/);
  assert.doesNotMatch(app, /<span>[生历热设关]<\/span>/);
  assert.match(app, /window\.scrollTo\(\{ top: 0, left: 0/);
});

test("quick guide is dismissible and explains the three-step data source setup", () => {
  assert.match(app, /quick-guide-dismissed/);
  assert.match(app, /GuideDialog/);
  assert.equal((guide.match(/<li>/g) ?? []).length, 3);
  assert.match(guide, /关闭使用指南/);
  assert.match(guide, /安装 WeChatDataAnalysis/);
  assert.match(guide, /启动并准备微信数据/);
  assert.match(guide, /重新检测数据源/);
  assert.match(guide, /已连接 WeChatDataAnalysis/);
  assert.match(guide, /暂未检测到服务/);
});

test("data source guidance stays concise on generate and remains actionable in settings", () => {
  assert.match(generatePage, /数据源未就绪/);
  assert.match(generatePage, /重新检测/);
  assert.match(generatePage, /如何配置？/);
  assert.match(settings, /未检测到服务/);
  assert.match(settings, /下载 WeChatDataAnalysis/);
  assert.match(settings, /配置指南/);
  assert.match(settings, /重新检测/);
  assert.match(about, /数据来源/);
  assert.match(about, /独立的开源项目，需要单独下载安装并运行/);
});

test("WeChatDataAnalysis links are centralized and opened through a desktop allowlist", () => {
  assert.match(dataSource, /https:\/\/github\.com\/LifeArchiveProject\/WeChatDataAnalysis/);
  assert.match(dataSource, /WECHAT_DATA_ANALYSIS_RELEASES/);
  assert.doesNotMatch(generatePage + settings + guide + about, /https:\/\/github\.com\/LifeArchiveProject\/WeChatDataAnalysis/);
  assert.match(tauriLib, /fn open_external_url/);
  assert.match(tauriLib, /ALLOWED_URLS/);
  assert.match(tauriLib, /不允许打开未登记的外部链接/);
});

test("elapsed time uses the local clock while percent remains backend-owned", () => {
  assert.match(generation, /Date\.now\(\) - startedAt/);
  assert.match(generation, /\.\.\.snapshot/);
  assert.doesNotMatch(generation, /percent\s*\+\s*1/);
});

test("history resolves member placeholders and avoids internal schema noise", () => {
  assert.match(history, /resolveMemberTokens/);
  assert.match(history, /resolveMemberTokens\(module\.title, memberNames\)/);
  assert.match(history, /member_aliases/);
  assert.doesNotMatch(history, /value: "action_items"/);
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

test("history default view follows report sections without duplicate activity totals", () => {
  assert.match(history, /REPORT_SECTION_KEYS = \["themes", "topics", "ai_observations", "member_activity"\]/);
  assert.match(history, /history-report-sections/);
  assert.match(history, /报告结尾/);
  assert.doesNotMatch(history, /\["消息数", stats\.message_count\]/);
  assert.match(history, /function ActivityStatsView/);
  assert.match(history, /\.slice\(0, 5\)/);
  assert.match(history, /\.slice\(0, 12\)/);
  assert.match(history, /isActivityStatsModule\(module\)/);
  assert.match(styles, /\.history-report-section/);
  assert.match(styles, /\.history-segment-list[^\n]+repeat\(2/);
});

test("member observation hides only a name duplicated by its card title", () => {
  assert.match(history, /function MemberObservationView/);
  assert.match(history, /memberName && memberName === resolvedTitle/);
  assert.match(history, /filter\(\(\[key\]\) => key !== "name"\)/);
  assert.match(history, /module\.module_key === "member_activity"[\s\S]*?<MemberObservationView/);
});

test("history resources hide internal fields and use a concise preview", () => {
  assert.match(history, /function ResourcePreview/);
  assert.match(history, /related_resources/);
  assert.match(history, /module\.module_key === "resources"/);
  assert.match(history, /"message_id", "file_size", "source"/);
  assert.match(history, /topic !== "其他 \/ 未归类"/);
  assert.match(styles, /\.history-resource-preview/);
  assert.match(styles, /\.history-resource-domain[^\n]+text-overflow: ellipsis/);
  assert.match(history, /小红书/);
  assert.match(history, /淘宝 \/ 天猫/);
  assert.match(history, /公众号/);
  assert.match(history, /知乎/);
});

test("desktop typography uses readable tokens across history and helper text", () => {
  assert.match(styles, /--font-body:\s*14px/);
  assert.match(styles, /--font-meta:\s*12px/);
  assert.match(styles, /--font-caption:\s*11px/);
  assert.match(styles, /\.history-module-heading h3\s*\{[^}]*font-size:\s*var\(--font-card-title\)/s);
  assert.match(styles, /\.privacy-copy[^}]*font-size:\s*12px/s);
});

test("installer requests a graceful close before blocking install or uninstall", () => {
  assert.match(installer, /OpenMutexW/);
  assert.match(installer, /APP_RUNNING_MUTEX/);
  assert.match(installer, /FindWindow \$1 "" "\$\{PRODUCT_NAME\}"/);
  assert.match(installer, /SendMessage \$1 \$\{WM_CLOSE\}/);
  assert.match(installer, /Function RequestAppClose/);
  assert.match(installer, /Function un\.RequestAppClose/);
  assert.match(installer, /MB_RETRYCANCEL/);
  assert.match(installer, /Function EnsureAppClosed/);
  assert.match(installer, /Function un\.EnsureAppClosed/);
  assert.doesNotMatch(installer, /taskkill/i);
});

test("GitHub workflows use Node 24 based official action majors", () => {
  assert.match(workflows, /actions\/checkout@v7/);
  assert.match(workflows, /actions\/setup-node@v7/);
  assert.match(workflows, /actions\/setup-python@v7/);
  assert.match(workflows, /actions\/upload-artifact@v7/);
  assert.doesNotMatch(workflows, /actions\/(?:checkout|setup-node|setup-python|upload-artifact)@v[1-6]\b/);
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
