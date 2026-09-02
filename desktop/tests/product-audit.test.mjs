import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const app = readFileSync(new URL("../src/App.tsx", import.meta.url), "utf8");
const guide = readFileSync(new URL("../src/components/GuideDialog.tsx", import.meta.url), "utf8");
const history = readFileSync(new URL("../src/pages/HistoryPage.tsx", import.meta.url), "utf8");
const generation = readFileSync(new URL("../src/hooks/useReportGeneration.ts", import.meta.url), "utf8");
const styles = readFileSync(new URL("../src/styles.css", import.meta.url), "utf8");

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
