import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { spawnSync } from "node:child_process";
import test from "node:test";
import { fileURLToPath } from "node:url";

const desktopRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const scriptPath = path.join(desktopRoot, "scripts/prepare-release-notes.ps1");

function findPowerShell() {
  const candidates = [
    process.env.LOCALAPPDATA && path.join(process.env.LOCALAPPDATA, "Programs/PowerShell/7/pwsh.exe"),
    process.env.ProgramW6432 && path.join(process.env.ProgramW6432, "PowerShell/7/pwsh.exe"),
    process.env.ProgramFiles && path.join(process.env.ProgramFiles, "PowerShell/7/pwsh.exe"),
  ].filter(Boolean);
  const executable = candidates.find((candidate) => fs.existsSync(candidate));
  if (!executable) {
    throw new Error(`未找到 PowerShell 7：${candidates.join(", ")}`);
  }
  return executable;
}

function runFixture(lineEnding, version) {
  const temporaryRoot = fs.mkdtempSync(path.join(os.tmpdir(), "wechat-release-notes-"));
  const notesPath = path.join(temporaryRoot, "notes.md");
  const changelogPath = path.join(temporaryRoot, "CHANGELOG.md");
  try {
    fs.writeFileSync(notesPath, `## 版本亮点${lineEnding}${lineEnding}- 换行兼容测试`, "utf8");
    fs.writeFileSync(
      changelogPath,
      `# 更新日志${lineEnding}${lineEnding}<!-- 新版本由 release.yml 插入到此行之后 -->${lineEnding}`,
      "utf8",
    );
    const result = spawnSync(
      findPowerShell(),
      [
        "-NoLogo",
        "-NoProfile",
        "-File",
        scriptPath,
        "-Version",
        version,
        "-NotesPath",
        notesPath,
        "-ChangelogPath",
        changelogPath,
      ],
      { encoding: "utf8" },
    );
    assert.equal(result.status, 0, `${result.stdout}\n${result.stderr}`);
    const changelog = fs.readFileSync(changelogPath, "utf8");
    assert.match(changelog, new RegExp(`^## \\[${version.replaceAll(".", "\\.")}\\]`, "m"));
    assert.match(changelog, /^### 版本亮点/m);
  } finally {
    const safePrefix = `${path.resolve(os.tmpdir())}${path.sep}`;
    assert.ok(path.resolve(temporaryRoot).startsWith(safePrefix));
    fs.rmSync(temporaryRoot, { recursive: true, force: true });
  }
}

test("release notes script accepts CRLF heading", () => {
  runFixture("\r\n", "9.9.1");
});

test("release notes script accepts LF heading", () => {
  runFixture("\n", "9.9.2");
});
