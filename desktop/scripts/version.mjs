import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(scriptDir, "../..");
const files = {
  packageJson: path.join(repoRoot, "desktop/package.json"),
  packageLock: path.join(repoRoot, "desktop/package-lock.json"),
  tauriConfig: path.join(repoRoot, "desktop/src-tauri/tauri.conf.json"),
  cargoToml: path.join(repoRoot, "desktop/src-tauri/Cargo.toml"),
  cargoLock: path.join(repoRoot, "desktop/src-tauri/Cargo.lock"),
};

const semverPattern = /^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?$/;

function parseSemver(value) {
  const match = semverPattern.exec(value);
  if (!match) {
    throw new Error(`版本号必须是 SemVer 且不要带 v 前缀：${value}`);
  }
  return {
    raw: value,
    core: match.slice(1, 4).map(Number),
    prerelease: match[4] ? match[4].split(".") : [],
  };
}

function compareSemver(leftValue, rightValue) {
  const left = parseSemver(leftValue);
  const right = parseSemver(rightValue);
  for (let index = 0; index < 3; index += 1) {
    if (left.core[index] !== right.core[index]) return left.core[index] - right.core[index];
  }
  if (!left.prerelease.length && !right.prerelease.length) return 0;
  if (!left.prerelease.length) return 1;
  if (!right.prerelease.length) return -1;
  const length = Math.max(left.prerelease.length, right.prerelease.length);
  for (let index = 0; index < length; index += 1) {
    const leftPart = left.prerelease[index];
    const rightPart = right.prerelease[index];
    if (leftPart === undefined) return -1;
    if (rightPart === undefined) return 1;
    if (leftPart === rightPart) continue;
    const leftNumeric = /^\d+$/.test(leftPart);
    const rightNumeric = /^\d+$/.test(rightPart);
    if (leftNumeric && rightNumeric) return Number(leftPart) - Number(rightPart);
    if (leftNumeric !== rightNumeric) return leftNumeric ? -1 : 1;
    return leftPart.localeCompare(rightPart, "en");
  }
  return 0;
}

function readJson(file) {
  return JSON.parse(fs.readFileSync(file, "utf8"));
}

function writeJson(file, value) {
  fs.writeFileSync(file, `${JSON.stringify(value, null, 2)}\n`, "utf8");
}

function readVersions() {
  const packageJson = readJson(files.packageJson);
  const packageLock = readJson(files.packageLock);
  const tauriConfig = readJson(files.tauriConfig);
  const cargoToml = fs.readFileSync(files.cargoToml, "utf8");
  const cargoLock = fs.readFileSync(files.cargoLock, "utf8");
  const cargoTomlMatch = cargoToml.match(/^\[package\][\s\S]*?^version\s*=\s*"([^"]+)"/m);
  const cargoLockMatch = cargoLock.match(/\[\[package\]\]\r?\nname = "wechat-chat-summary-desktop"\r?\nversion = "([^"]+)"/);
  if (!cargoTomlMatch || !cargoLockMatch) throw new Error("无法读取 Cargo 包版本。\n");
  return {
    "desktop/package.json": packageJson.version,
    "desktop/package-lock.json": packageLock.version,
    "desktop/package-lock.json#packages-root": packageLock.packages?.[""]?.version,
    "desktop/src-tauri/tauri.conf.json": tauriConfig.version,
    "desktop/src-tauri/Cargo.toml": cargoTomlMatch[1],
    "desktop/src-tauri/Cargo.lock": cargoLockMatch[1],
  };
}

function assertConsistent(expectedVersion) {
  const versions = readVersions();
  const canonical = expectedVersion ?? versions["desktop/package.json"];
  parseSemver(canonical);
  const conflicts = Object.entries(versions).filter(([, value]) => value !== canonical);
  if (conflicts.length) {
    const detail = Object.entries(versions).map(([file, value]) => `${file}=${value}`).join("\n");
    throw new Error(`版本号不一致，已停止：\n${detail}`);
  }
  return canonical;
}

function setVersion(version) {
  parseSemver(version);
  assertConsistent();

  const packageJson = readJson(files.packageJson);
  packageJson.version = version;
  writeJson(files.packageJson, packageJson);

  const packageLock = readJson(files.packageLock);
  packageLock.version = version;
  packageLock.packages[""].version = version;
  writeJson(files.packageLock, packageLock);

  const tauriConfig = readJson(files.tauriConfig);
  tauriConfig.version = version;
  writeJson(files.tauriConfig, tauriConfig);

  const cargoToml = fs.readFileSync(files.cargoToml, "utf8").replace(
    /(^\[package\][\s\S]*?^version\s*=\s*")[^"]+(".*$)/m,
    `$1${version}$2`,
  );
  fs.writeFileSync(files.cargoToml, cargoToml, "utf8");

  const cargoLock = fs.readFileSync(files.cargoLock, "utf8").replace(
    /(\[\[package\]\]\r?\nname = "wechat-chat-summary-desktop"\r?\nversion = ")[^"]+("\r?\n)/,
    `$1${version}$2`,
  );
  fs.writeFileSync(files.cargoLock, cargoLock, "utf8");
  assertConsistent(version);
  console.log(`VERSION_SET=${version}`);
}

const [command = "--check", argument] = process.argv.slice(2);
try {
  if (command === "--check") {
    console.log(`VERSION_OK=${assertConsistent()}`);
  } else if (command === "--print") {
    console.log(assertConsistent());
  } else if (command === "--set" && argument) {
    setVersion(argument);
  } else if (command === "--assert-greater" && argument) {
    const current = assertConsistent();
    if (compareSemver(argument, current) <= 0) {
      throw new Error(`目标版本 ${argument} 必须高于当前版本 ${current}。`);
    }
    console.log(`VERSION_GREATER=${argument}>${current}`);
  } else if (command === "--assert-not-lower" && argument) {
    const current = assertConsistent();
    if (compareSemver(argument, current) < 0) {
      throw new Error(`目标版本 ${argument} 不得低于当前版本 ${current}。`);
    }
    console.log(`VERSION_NOT_LOWER=${argument}>=${current}`);
  } else {
    throw new Error("用法：version.mjs --check | --print | --set <version> | --assert-greater <version> | --assert-not-lower <version>");
  }
} catch (error) {
  console.error(error instanceof Error ? error.message : String(error));
  process.exit(1);
}
