[CmdletBinding()]
param(
    [string]$OutputDirectory = "D:\工具\WeChat Chat Summary\test-builds",
    [string]$MakensisPath = "C:\Users\jhj33\AppData\Local\tauri\NSIS\makensis.exe"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$OutputEncoding = [Console]::OutputEncoding = [Text.UTF8Encoding]::new()

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$desktopRoot = Join-Path $repoRoot "desktop"
$cacheRoot = Join-Path $repoRoot ".dev-cache"
$venvPython = Join-Path $repoRoot ".venv\Scripts\python.exe"
$engineDistRoot = Join-Path $cacheRoot "pyinstaller\dist"
$engineDir = Join-Path $engineDistRoot "group-insight-sidecar"
$sidecarExe = Join-Path $engineDir "group-insight-sidecar.exe"
$cargoTarget = Join-Path $cacheRoot "cargo-target"
$appExe = Join-Path $cargoTarget "release\wechat-chat-summary-desktop.exe"
$installerScript = Join-Path $desktopRoot "installer\test-installer.nsi"
$version = (Get-Content (Join-Path $desktopRoot "package.json") -Raw -Encoding utf8 | ConvertFrom-Json).version
$outputFile = Join-Path $OutputDirectory "WeChat-Chat-Summary_${version}-test_x64-setup.exe"

if (-not (Test-Path -LiteralPath $venvPython -PathType Leaf)) {
    throw "未找到项目虚拟环境 Python：$venvPython"
}
if (-not (Test-Path -LiteralPath $MakensisPath -PathType Leaf)) {
    throw "未找到 NSIS：$MakensisPath。请先确认 NSIS 的 D 盘安装目录后再继续。"
}

New-Item -ItemType Directory -Force -Path $cacheRoot, $OutputDirectory | Out-Null
$env:npm_config_cache = Join-Path $cacheRoot "npm"
$env:PIP_CACHE_DIR = Join-Path $cacheRoot "pip"
$env:PYINSTALLER_CONFIG_DIR = Join-Path $cacheRoot "pyinstaller-config"
$env:CARGO_HOME = Join-Path $cacheRoot "cargo-home"
$env:CARGO_TARGET_DIR = $cargoTarget
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"

Write-Host "[1/4] 安装/校验测试打包依赖（缓存：$env:PIP_CACHE_DIR）"
& $venvPython -m pip install -r (Join-Path $desktopRoot "requirements-build.txt")
if ($LASTEXITCODE -ne 0) { throw "安装 PyInstaller 失败。" }

Write-Host "[2/4] 生成独立 Python 分析引擎"
& $venvPython -m PyInstaller `
    --noconfirm `
    --clean `
    --onedir `
    --name "group-insight-sidecar" `
    --distpath $engineDistRoot `
    --workpath (Join-Path $cacheRoot "pyinstaller\work") `
    --specpath (Join-Path $cacheRoot "pyinstaller\spec") `
    --paths $repoRoot `
    --collect-all playwright `
    --collect-data jieba `
    --hidden-import group_insight.cli `
    (Join-Path $desktopRoot "sidecar_entry.py")
if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $sidecarExe -PathType Leaf)) {
    throw "生成 Python 分析引擎失败。"
}

Write-Host "[3/4] 构建 Tauri Release 主程序"
Push-Location $desktopRoot
try {
    & npm.cmd run tauri build -- --no-bundle
    if ($LASTEXITCODE -ne 0) { throw "Tauri Release 构建失败。" }
}
finally {
    Pop-Location
}
if (-not (Test-Path -LiteralPath $appExe -PathType Leaf)) {
    throw "未找到 Tauri Release 主程序：$appExe"
}

Write-Host "[4/4] 生成可选择安装目录的 NSIS 测试安装包"
& $MakensisPath `
    "/INPUTCHARSET" `
    "UTF8" `
    "/DAPP_EXE=$appExe" `
    "/DENGINE_DIR=$engineDir" `
    "/DOUTPUT_FILE=$outputFile" `
    "/DVERSION=$version" `
    $installerScript
if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $outputFile -PathType Leaf)) {
    throw "NSIS 测试安装包生成失败。"
}

$artifact = Get-Item -LiteralPath $outputFile
$hash = Get-FileHash -LiteralPath $outputFile -Algorithm SHA256
Write-Host "DONE package=$($artifact.FullName) bytes=$($artifact.Length) sha256=$($hash.Hash)"
