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

test("model identifiers stay editable and the options can always be opened", () => {
  assert.match(settingsPage, /function ModelCombobox/);
  assert.match(settingsPage, /aria-autocomplete="list"/);
  assert.match(settingsPage, /aria-label=\{open \? "收起模型选项" : "展开模型选项"\}/);
  assert.match(settingsPage, /可直接输入任意非空模型标识/);
  assert.doesNotMatch(settingsPage, /<datalist/);
  assert.doesNotMatch(settingsPage, /settings\.provider === "deepseek" \? <select value=\{settings\.model\}/);
});

test("successful API tests refresh persisted provider-specific model options", () => {
  assert.match(settingsPage, /remembered_models: Settings\["remembered_models"\]/);
  assert.match(settingsPage, /rememberedModels=\{settings\.remembered_models\[settings\.provider\]/);
  assert.match(settingsPage, /测试成功的模型会保存在本机供后续选择/);
});

test("AI provider and model controls share one aligned grid row", () => {
  assert.match(settingsPage, /field-grid ai-provider-grid/);
  assert.match(settingsPage, /className="ai-provider-field"/);
  assert.match(settingsPage, /className="ai-model-field"/);
});
