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
  assert.match(aboutPage, /已是最新正式版本/);
  for (const status of ["update_available", "downloading", "verifying", "ready_to_install", "installing", "check_failed", "download_failed", "verify_failed", "install_failed"]) {
    assert.match(aboutPage, new RegExp(`"${status}"`));
  }
  assert.match(aboutPage, /检查更新失败，可直接重新检查/);
});

test("About uses matching lightweight actions and states the network boundary", () => {
  assert.match(aboutPage, /import \{[^}]*Copy[^}]*RefreshCw[^}]*\} from "lucide-react"/);
  assert.match(aboutPage, /<Copy size=\{15\}/);
  assert.match(aboutPage, /<RefreshCw size=\{15\}/);
  assert.match(aboutPage, /className="spinning"/);
  assert.match(aboutPage, /secondary about-action[^>]+onClick=\{copyProjectUrl\}/);
  assert.match(aboutPage, /secondary about-action[^>]+onClick=\{checkForUpdates\}/);
  assert.match(aboutPage, /仅在点击检查更新后访问本项目官方 GitHub Stable Release/);
  assert.match(aboutPage, /不上传聊天、API Key、历史数据库、报告或群聊名称/);
  assert.match(aboutPage, /尚未进行代码签名/);
});

test("updater keeps release context and offers stage-specific retries", () => {
  assert.match(aboutPage, /setProgress\(\{ phase: "downloading", downloaded_bytes: 0, total_bytes: null, percent: null \}\)/);
  assert.match(aboutPage, /setErrorDetail\(""\)/);
  assert.match(aboutPage, /更新下载失败，已清理不完整文件，可直接重新下载/);
  assert.match(aboutPage, /安装包校验失败，损坏文件已废弃，请重新下载/);
  assert.match(aboutPage, /已校验安装包仍保留，可直接重新安装/);
  assert.match(aboutPage, />重新下载</);
  assert.match(aboutPage, />重新安装</);
  assert.match(aboutPage, /actionGuard\.current/);
  assert.match(updater, /installing\.swap\(true, Ordering::SeqCst\)/);
  assert.match(updater, /phase: "verifying"\.to_string\(\)/);
});

test("build channel is explicit and same-version Stable can replace Test", () => {
  assert.match(updater, /WECHAT_CHAT_SUMMARY_BUILD_CHANNEL/);
  assert.match(updater, /BuildChannel::Test/);
  assert.match(updater, /BuildChannel::Prerelease/);
  assert.match(updater, /should_offer_stable_update/);
  assert.match(updater, /current_channel/);
  assert.match(updater, /latest_channel/);
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
