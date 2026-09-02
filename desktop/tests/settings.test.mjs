import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { INITIAL_SETTINGS } from "../src/types/desktop.ts";

const settingsPage = readFileSync(new URL("../src/pages/SettingsPage.tsx", import.meta.url), "utf8");
const rustBridge = readFileSync(new URL("../src-tauri/src/lib.rs", import.meta.url), "utf8");

test("MCP is off by default and uses a loopback Streamable HTTP endpoint", () => {
  assert.equal(INITIAL_SETTINGS.mcp_enabled, false);
  assert.equal(INITIAL_SETTINGS.mcp_port, 8765);
  assert.match(settingsPage, /Streamable HTTP/);
  assert.match(settingsPage, /http:\/\/127\.0\.0\.1:/);
  assert.match(rustBridge, /http:\/\/127\.0\.0\.1:\{port\}\/mcp/);
});

test("settings explains the MCP Server role without presenting it as an MCP Client", () => {
  assert.match(
    settingsPage,
    /群聊拾遗作为 MCP Server 提供数据与报告能力，实际 AI 分析由连接的软件 \/ AI 客户端完成。/,
  );
  assert.match(settingsPage, />启动</);
  assert.match(settingsPage, />停止</);
  assert.doesNotMatch(settingsPage, /正在通过 MCP 调用 AI/);
});

test("generic provider settings do not render DeepSeek-only controls", () => {
  assert.match(settingsPage, /settings\.provider === "deepseek"/);
  assert.match(settingsPage, /Base URL \/ Chat Completions URL/);
  assert.match(settingsPage, /Reasoning Effort/);
});
