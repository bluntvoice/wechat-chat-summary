import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const aboutPage = readFileSync(new URL("../src/pages/AboutPage.tsx", import.meta.url), "utf8");
const installer = readFileSync(new URL("../installer/test-installer.nsi", import.meta.url), "utf8");
const packageInfo = JSON.parse(readFileSync(new URL("../package.json", import.meta.url), "utf8"));
const packageLock = JSON.parse(readFileSync(new URL("../package-lock.json", import.meta.url), "utf8"));
const tauriConfig = JSON.parse(readFileSync(new URL("../src-tauri/tauri.conf.json", import.meta.url), "utf8"));
const cargoToml = readFileSync(new URL("../src-tauri/Cargo.toml", import.meta.url), "utf8");
const cargoLock = readFileSync(new URL("../src-tauri/Cargo.lock", import.meta.url), "utf8");
const updater = readFileSync(new URL("../src-tauri/src/updater.rs", import.meta.url), "utf8");

test("About reads the runtime version and renders it only once", () => {
  assert.match(aboutPage, /getVersion\(\)/);
  assert.equal((aboutPage.match(/v\{version\}/g) ?? []).length, 1);
  assert.match(aboutPage, /当前版本/);
});

test("update checks are manual and expose all user-facing states", () => {
  const mountEffects = aboutPage.slice(0, aboutPage.indexOf("async function copyProjectUrl"));
  assert.doesNotMatch(mountEffects, /check_update/);
  assert.match(aboutPage, /onClick=\{checkForUpdates\}/);
  assert.match(aboutPage, /正在检查…/);
  assert.match(aboutPage, /已是最新版本/);
  assert.match(aboutPage, /发现新版本 v/);
  assert.match(aboutPage, /检查更新失败，请稍后重试/);
});

test("About uses matching lightweight actions and states the network boundary", () => {
  assert.match(aboutPage, /import \{ Copy, RefreshCw \} from "lucide-react"/);
  assert.match(aboutPage, /<Copy size=\{15\}/);
  assert.match(aboutPage, /<RefreshCw size=\{15\}/);
  assert.match(aboutPage, /className="spinning"/);
  assert.match(aboutPage, /secondary about-action[^>]+onClick=\{copyProjectUrl\}/);
  assert.match(aboutPage, /secondary about-action[^>]+onClick=\{checkForUpdates\}/);
  assert.match(aboutPage, /仅在点击检查更新后访问 GitHub/);
  assert.match(aboutPage, /不上传聊天、API Key、历史数据库、报告或群聊名称/);
  assert.match(aboutPage, /尚未进行代码签名/);
});

test("all desktop version files remain synchronized", () => {
  const cargoTomlVersion = cargoToml.match(/^version\s*=\s*"([^"]+)"/m)?.[1];
  const cargoLockVersion = cargoLock.match(/\[\[package\]\]\r?\nname = "wechat-chat-summary-desktop"\r?\nversion = "([^"]+)"/)?.[1];
  const versions = [
    packageInfo.version,
    packageLock.version,
    packageLock.packages[""].version,
    tauriConfig.version,
    cargoTomlVersion,
    cargoLockVersion,
  ];
  assert.deepEqual(new Set(versions), new Set([packageInfo.version]));
});

test("installer replaces only program and preserves user-owned locations", () => {
  const destructiveLines = installer
    .split(/\r?\n/)
    .filter((line) => /^\s*(?:Delete|RMDir)\b/i.test(line))
    .join("\n");
  assert.match(installer, /RMDir \/r "\$INSTDIR\\program"/);
  assert.match(installer, /\$INSTDIR\\program\\engine/);
  assert.doesNotMatch(destructiveLines, /RMDir \/r "\$INSTDIR"/);
  assert.doesNotMatch(destructiveLines, /RMDir \/r "\$INSTDIR\\engine"/);
  assert.doesNotMatch(destructiveLines, /APPDATA|(?:data|reports?)\b/i);
});

test("updater does not recursively remove its predictable temporary directory", () => {
  assert.doesNotMatch(updater, /remove_dir_all/);
  assert.match(updater, /symlink_metadata/);
  assert.match(updater, /canonical_target\.parent\(\)/);
});
