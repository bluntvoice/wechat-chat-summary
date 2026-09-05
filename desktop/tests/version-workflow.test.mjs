import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { spawnSync } from "node:child_process";
import test from "node:test";
import { fileURLToPath } from "node:url";

const packageInfo = JSON.parse(readFileSync(new URL("../package.json", import.meta.url), "utf8"));
const versionScript = fileURLToPath(new URL("../scripts/version.mjs", import.meta.url));
const releaseWorkflow = readFileSync(new URL("../../.github/workflows/release.yml", import.meta.url), "utf8");

test("release version guard accepts a source version already staged for the target patch", () => {
  const result = spawnSync(process.execPath, [versionScript, "--assert-not-lower", packageInfo.version], {
    encoding: "utf8",
  });
  assert.equal(result.status, 0, result.stderr);
  assert.match(result.stdout, /VERSION_NOT_LOWER=/);
});

test("release version guard still rejects an older target", () => {
  const result = spawnSync(process.execPath, [versionScript, "--assert-not-lower", "0.0.1"], {
    encoding: "utf8",
  });
  assert.notEqual(result.status, 0);
  assert.match(result.stderr, /不得低于当前版本/);
});

test("release workflow only requires version-file diffs when the target was not pre-staged", () => {
  assert.match(releaseWorkflow, /version_changed=/);
  assert.match(releaseWorkflow, /VERSION_CHANGED/);
  assert.match(releaseWorkflow, /if \(\$env:VERSION_CHANGED -eq "true"\)/);
});
