import fs from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const defaultReadmePath = path.resolve(scriptDir, "../../README.md");
const stableSemverPattern = /^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$/;
const prereleaseSemverPattern = /^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*$/;

const markerNames = [
  "badges",
  "current-version",
  "release-status",
  "download",
  "prestable-history-note",
  "development-status",
];
const historyAnchor = "<!-- release-readme:history -->";

function normalizeLineEndings(value, eol) {
  return value.replace(/\r\n|\r|\n/g, eol);
}

function countOccurrences(value, needle) {
  return value.split(needle).length - 1;
}

function replaceMarkedBlock(readme, markerName, replacement, eol) {
  const start = `<!-- release-readme:${markerName}:start -->`;
  const end = `<!-- release-readme:${markerName}:end -->`;
  if (countOccurrences(readme, start) !== 1 || countOccurrences(readme, end) !== 1) {
    throw new Error(`README 标记缺失或重复：${markerName}`);
  }

  const startIndex = readme.indexOf(start);
  const endIndex = readme.indexOf(end, startIndex + start.length);
  if (endIndex < startIndex) {
    throw new Error(`README 标记顺序错误：${markerName}`);
  }

  const normalized = normalizeLineEndings(replacement.trim(), eol);
  const body = normalized ? `${eol}${normalized}${eol}` : eol;
  return `${readme.slice(0, startIndex)}${start}${body}${readme.slice(endIndex)}`;
}

function escapeRegExp(value) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function upsertHistoryEntry(readme, version, summary, eol) {
  if (countOccurrences(readme, historyAnchor) !== 1) {
    throw new Error(`README 缺少或重复版本日志锚点：${historyAnchor}`);
  }

  const heading = `### v${version}`;
  const entry = `${heading}${eol}${eol}${normalizeLineEndings(summary.trim(), eol)}`;
  const headingPattern = new RegExp(`^${escapeRegExp(heading)}[ \\t]*$`, "m");
  const match = headingPattern.exec(readme);
  if (match) {
    const nextHeadingPattern = /^#{2,3}\s+/gm;
    nextHeadingPattern.lastIndex = match.index + match[0].length;
    const nextHeading = nextHeadingPattern.exec(readme);
    const endIndex = nextHeading?.index ?? readme.length;
    return `${readme.slice(0, match.index)}${entry}${eol}${eol}${readme.slice(endIndex)}`;
  }

  return readme.replace(historyAnchor, `${historyAnchor}${eol}${eol}${entry}`);
}

export function updateReleaseReadme({ readme, version, channel, summary = "" }) {
  if (channel !== "stable" && channel !== "prerelease") {
    throw new Error(`未知发布通道：${channel}`);
  }
  const versionPattern = channel === "stable" ? stableSemverPattern : prereleaseSemverPattern;
  if (!versionPattern.test(version)) {
    throw new Error(`${channel} 版本号格式不正确：${version}`);
  }
  if (channel === "prerelease") {
    return { changed: false, content: readme };
  }
  if (!summary.trim()) {
    throw new Error("Stable Release 的 README 简版摘要不能为空。");
  }
  if (/^#{1,6}\s+/m.test(summary)) {
    throw new Error("README 简版摘要不应包含 Markdown 标题，版本标题由脚本生成。");
  }

  const eol = readme.includes("\r\n") ? "\r\n" : "\n";
  let updated = readme;
  for (const markerName of markerNames) {
    const start = `<!-- release-readme:${markerName}:start -->`;
    const end = `<!-- release-readme:${markerName}:end -->`;
    if (countOccurrences(updated, start) !== 1 || countOccurrences(updated, end) !== 1) {
      throw new Error(`README 标记缺失或重复：${markerName}`);
    }
  }

  updated = replaceMarkedBlock(
    updated,
    "badges",
    "![GitHub Downloads](https://img.shields.io/github/downloads/bluntvoice/wechat-chat-summary/total?style=flat&label=Downloads)\n\n![GitHub Release](https://img.shields.io/github/v/release/bluntvoice/wechat-chat-summary?style=flat&label=Release)",
    eol,
  );
  updated = replaceMarkedBlock(updated, "current-version", `> 当前版本：**v${version}**`, eol);
  updated = replaceMarkedBlock(
    updated,
    "release-status",
    "> 当前主要面向 Windows 桌面环境。\n>\n> 项目仍在持续开发。\n>\n> 当前提供 Windows x64 正式安装版本。",
    eol,
  );
  updated = replaceMarkedBlock(
    updated,
    "download",
    `当前正式版本通过本仓库的 [GitHub Releases](https://github.com/bluntvoice/wechat-chat-summary/releases) 提供。\n\n### Windows\n\n当前正式版本主要面向 Windows x64。用户可从 [最新版下载页](https://github.com/bluntvoice/wechat-chat-summary/releases/latest) 下载：\n\n\`\`\`text\nWeChat-Chat-Summary_${version}_x64-setup.exe\nWeChat-Chat-Summary_${version}_x64-setup.exe.sha256\n\`\`\`\n\n安装步骤：\n\n1. 下载最新版安装程序及同名 \`.sha256\` 完整性校验文件；\n2. 运行安装程序；\n3. 首次启动后，根据软件内引导单独安装并运行 WeChatDataAnalysis；\n4. 配置 AI API；\n5. 选择独立的报告目录；\n6. 开始生成群聊总结。`,
    eol,
  );
  updated = replaceMarkedBlock(updated, "prestable-history-note", "", eol);
  updated = replaceMarkedBlock(
    updated,
    "development-status",
    "- Windows x64 正式安装包通过 GitHub Releases 提供；\n- Stable / Prerelease 发布流程已经建立；\n- 测试安装包继续用于正式发布前验收；\n- 用户可在关于页手动检查更新、下载正式安装包并进行 SHA-256 完整性校验；\n- 软件启动时不会自动检查更新，也不会后台周期检查；\n- Windows 安装包当前仍未进行代码签名。",
    eol,
  );
  updated = upsertHistoryEntry(updated, version, summary, eol);

  return { changed: updated !== readme, content: updated };
}

function parseArguments(argv) {
  const values = new Map();
  for (let index = 0; index < argv.length; index += 2) {
    const name = argv[index];
    const value = argv[index + 1];
    if (!name?.startsWith("--") || value === undefined) {
      throw new Error("用法：update-release-readme.mjs --version <x.y.z> --channel <stable|prerelease> [--summary-file <path>] [--readme <path>]");
    }
    values.set(name, value);
  }
  return values;
}

export function runCli(argv = process.argv.slice(2)) {
  const args = parseArguments(argv);
  const version = args.get("--version");
  const channel = args.get("--channel");
  const readmePath = path.resolve(args.get("--readme") ?? defaultReadmePath);
  if (!version || !channel) {
    throw new Error("必须提供 --version 和 --channel。");
  }

  const readme = fs.readFileSync(readmePath, "utf8");
  let summary = "";
  if (channel === "stable") {
    const summaryPath = args.get("--summary-file");
    if (!summaryPath) {
      throw new Error("Stable Release 必须提供 --summary-file。");
    }
    summary = fs.readFileSync(path.resolve(summaryPath), "utf8");
  }

  const result = updateReleaseReadme({ readme, version, channel, summary });
  if (result.changed) {
    fs.writeFileSync(readmePath, result.content, "utf8");
  }
  console.log(`README_RELEASE_UPDATE channel=${channel} version=${version} changed=${result.changed}`);
}

const invokedPath = process.argv[1] ? pathToFileURL(path.resolve(process.argv[1])).href : "";
if (import.meta.url === invokedPath) {
  try {
    runCli();
  } catch (error) {
    console.error(error instanceof Error ? error.message : String(error));
    process.exit(1);
  }
}
