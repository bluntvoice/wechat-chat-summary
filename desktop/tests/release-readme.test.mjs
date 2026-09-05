import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import { updateReleaseReadme } from "../scripts/update-release-readme.mjs";

const marker = (name, body) => `<!-- release-readme:${name}:start -->\n${body}\n<!-- release-readme:${name}:end -->`;

function fixture() {
  return [
    "# 群聊拾遗",
    "",
    marker("badges", "<!-- 首次 Stable Release 后启用 -->"),
    "",
    marker("current-version", "> 当前版本：**v0.2.4**"),
    marker("release-status", "> GitHub 暂未发布正式 Stable Release。"),
    "",
    "正文中的数字 0.2.4 和 10392 不应被修改。",
    "",
    marker("download", "> 待补充"),
    "",
    "## 版本更新日志",
    "",
    "<!-- release-readme:history -->",
    "",
    "### v0.2.4",
    "",
    "- 旧版本内容。",
    "",
    marker("prestable-history-note", "尚未发布。"),
    "",
    "> 更完整的版本变化请查看 [CHANGELOG.md](./CHANGELOG.md)。",
    "",
    "## 当前开发状态",
    "",
    marker("development-status", "- 尚无正式 Release；"),
    "",
  ].join("\n");
}

const summary = "首个正式稳定版本。\n\n- 完成正式发布闭环；\n- 提供历史报告中心。";
const repositoryReadme = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../README.md");

test("Stable Release 更新正式状态并插入简版版本日志", () => {
  const result = updateReleaseReadme({ readme: fixture(), version: "1.0.0", channel: "stable", summary });
  assert.equal(result.changed, true);
  assert.match(result.content, /> 当前版本：\*\*v1\.0\.0\*\*/);
  assert.match(result.content, /github\/downloads\/bluntvoice\/wechat-chat-summary\/total/);
  assert.match(result.content, /当前提供 Windows x64 正式安装版本/);
  assert.match(result.content, /WeChat-Chat-Summary_1\.0\.0_x64-setup\.exe\.sha256/);
  assert.match(result.content, /### v1\.0\.0\n\n首个正式稳定版本/);
  assert.ok(result.content.indexOf("### v1.0.0") < result.content.indexOf("### v0.2.4"));
  assert.match(result.content, /正文中的数字 0\.2\.4 和 10392 不应被修改/);
  assert.doesNotMatch(result.content, /尚未发布。/);
});

test("Prerelease 不覆盖 README 的 Stable 状态", () => {
  const readme = fixture();
  const result = updateReleaseReadme({ readme, version: "1.1.0-beta.1", channel: "prerelease" });
  assert.equal(result.changed, false);
  assert.equal(result.content, readme);
});

test("同一 Stable 版本重复执行时不会重复插入", () => {
  const first = updateReleaseReadme({ readme: fixture(), version: "1.0.0", channel: "stable", summary });
  const second = updateReleaseReadme({ readme: first.content, version: "1.0.0", channel: "stable", summary });
  assert.equal(second.changed, false);
  assert.equal((second.content.match(/^### v1\.0\.0$/gm) ?? []).length, 1);
});

test("Stable 更新在 README 缺少预期标记时明确失败", () => {
  const readme = fixture().replace("<!-- release-readme:history -->", "");
  assert.throws(
    () => updateReleaseReadme({ readme, version: "1.0.0", channel: "stable", summary }),
    /README 缺少或重复版本日志锚点/,
  );
});

test("Stable 更新只替换受控区域中的版本号", () => {
  const result = updateReleaseReadme({ readme: fixture(), version: "2.0.0", channel: "stable", summary });
  assert.match(result.content, /> 当前版本：\*\*v2\.0\.0\*\*/);
  assert.match(result.content, /正文中的数字 0\.2\.4 和 10392 不应被修改/);
  assert.match(result.content, /^### v0\.2\.4$/m);
});

test("仓库 README 可由任意后续 Stable 版本更新", () => {
  const readme = fs.readFileSync(repositoryReadme, "utf8");
  assert.match(readme, /> 当前版本：\*\*v\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?\*\*/);
  const result = updateReleaseReadme({ readme, version: "99.0.0", channel: "stable", summary });
  assert.match(result.content, /> 当前版本：\*\*v99\.0\.0\*\*/);
  assert.equal((result.content.match(/^### v99\.0\.0$/gm) ?? []).length, 1);
});
