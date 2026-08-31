[CmdletBinding()]
param(
    [ValidateSet("Test", "Stable", "Prerelease")]
    [string]$PackageKind = "Test",
    [string]$OutputDirectory = "",
    [string]$MakensisPath = "",
    [string]$PythonPath = "",
    [switch]$SkipDependencyInstall
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$OutputEncoding = [Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)

if ($PSVersionTable.PSVersion.Major -lt 7) {
    throw "打包脚本要求 PowerShell 7 或更新版本。"
}

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$desktopRoot = Join-Path $repoRoot "desktop"
$cacheRoot = Join-Path $repoRoot ".dev-cache"
$engineDistRoot = Join-Path $cacheRoot "pyinstaller\dist"
$engineDir = Join-Path $engineDistRoot "group-insight-sidecar"
$sidecarExe = Join-Path $engineDir "group-insight-sidecar.exe"
$cargoTarget = if ($env:CARGO_TARGET_DIR) { $env:CARGO_TARGET_DIR } else { Join-Path $cacheRoot "cargo-target" }
$appExe = Join-Path $cargoTarget "release\wechat-chat-summary-desktop.exe"
$installerScript = Join-Path $desktopRoot "installer\test-installer.nsi"
$versionScript = Join-Path $desktopRoot "scripts\version.mjs"

function Resolve-PythonExecutable {
    if ($PythonPath) {
        if (-not (Test-Path -LiteralPath $PythonPath -PathType Leaf)) {
            throw "指定的 Python 不存在：$PythonPath"
        }
        return (Resolve-Path -LiteralPath $PythonPath).Path
    }

    $venvPython = Join-Path $repoRoot ".venv\Scripts\python.exe"
    if (Test-Path -LiteralPath $venvPython -PathType Leaf) {
        return $venvPython
    }

    $command = Get-Command python -ErrorAction SilentlyContinue
    if ($command -and $command.Source -and $command.Source -notlike "*\WindowsApps\*") {
        return $command.Source
    }

    throw "未找到可用的 Python。请通过 -PythonPath 指定，或创建项目 .venv。"
}

function Resolve-MakensisExecutable {
    $candidates = @()
    if ($MakensisPath) { $candidates += $MakensisPath }
    if ($env:MAKENSIS_PATH) { $candidates += $env:MAKENSIS_PATH }

    $command = Get-Command makensis.exe -ErrorAction SilentlyContinue
    if ($command -and $command.Source) { $candidates += $command.Source }

    if (${env:ProgramFiles(x86)}) {
        $candidates += Join-Path ${env:ProgramFiles(x86)} "NSIS\makensis.exe"
    }
    if ($env:ProgramFiles) {
        $candidates += Join-Path $env:ProgramFiles "NSIS\makensis.exe"
    }
    if ($env:LOCALAPPDATA) {
        $candidates += Join-Path $env:LOCALAPPDATA "tauri\NSIS\makensis.exe"
    }

    foreach ($candidate in $candidates | Select-Object -Unique) {
        if ($candidate -and (Test-Path -LiteralPath $candidate -PathType Leaf)) {
            return (Resolve-Path -LiteralPath $candidate).Path
        }
    }

    throw "未找到 NSIS makensis.exe。请安装 NSIS，设置 MAKENSIS_PATH，或通过 -MakensisPath 指定。"
}

function Assert-NoPrivateRuntimeFiles {
    param([Parameter(Mandatory)][string]$Root)

    $forbiddenNames = @(
        ".env",
        "secrets.env",
        "config.json",
        "history.sqlite3"
    )
    $forbiddenExtensions = @(".sqlite", ".sqlite3", ".db")
    $matches = Get-ChildItem -LiteralPath $Root -Recurse -Force -File | Where-Object {
        $_.Name -in $forbiddenNames -or $_.Extension.ToLowerInvariant() -in $forbiddenExtensions
    }
    if ($matches) {
        $paths = ($matches.FullName -join [Environment]::NewLine)
        throw "sidecar 产物包含禁止打包的本地配置或数据库：`n$paths"
    }
}

$python = Resolve-PythonExecutable
$makensis = Resolve-MakensisExecutable

if (-not $OutputDirectory) {
    $OutputDirectory = Join-Path $repoRoot "artifacts\windows"
}
$OutputDirectory = [IO.Path]::GetFullPath($OutputDirectory)

& node $versionScript --check
if ($LASTEXITCODE -ne 0) { throw "版本一致性检查失败。" }
$version = (& node $versionScript --print).Trim()
if ($LASTEXITCODE -ne 0 -or -not $version) { throw "读取版本号失败。" }

$coreVersion = ($version -split "-")[0]
$fileVersion = "$coreVersion.0"
switch ($PackageKind) {
    "Test" {
        $installerName = "WeChat-Chat-Summary_${version}-test_x64-setup.exe"
        $productName = "微信群聊总结（测试版）"
        $fileDescription = "微信群聊总结 Windows 测试安装包"
    }
    "Prerelease" {
        $installerName = "WeChat-Chat-Summary_${version}_x64-setup.exe"
        $productName = "微信群聊总结（预发布版）"
        $fileDescription = "微信群聊总结 Windows 预发布安装包"
    }
    default {
        $installerName = "WeChat-Chat-Summary_${version}_x64-setup.exe"
        $productName = "微信群聊总结"
        $fileDescription = "微信群聊总结 Windows 安装包"
    }
}
$outputFile = Join-Path $OutputDirectory $installerName
$checksumFile = "$outputFile.sha256"

New-Item -ItemType Directory -Force -Path $cacheRoot, $OutputDirectory | Out-Null
if (-not $env:npm_config_cache) { $env:npm_config_cache = Join-Path $cacheRoot "npm" }
if (-not $env:PIP_CACHE_DIR) { $env:PIP_CACHE_DIR = Join-Path $cacheRoot "pip" }
if (-not $env:PYINSTALLER_CONFIG_DIR) { $env:PYINSTALLER_CONFIG_DIR = Join-Path $cacheRoot "pyinstaller-config" }
if (-not $env:CARGO_HOME) { $env:CARGO_HOME = Join-Path $cacheRoot "cargo-home" }
$env:CARGO_TARGET_DIR = $cargoTarget
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"

if (-not $SkipDependencyInstall) {
    Write-Host "[1/5] 安装/校验 Python 与前端依赖"
    & $python -m pip install -r (Join-Path $repoRoot "requirements.txt") -r (Join-Path $desktopRoot "requirements-build.txt")
    if ($LASTEXITCODE -ne 0) { throw "安装 Python 打包依赖失败。" }
    Push-Location $desktopRoot
    try {
        & npm.cmd ci
        if ($LASTEXITCODE -ne 0) { throw "安装前端依赖失败。" }
    }
    finally {
        Pop-Location
    }
}
else {
    Write-Host "[1/5] 使用已安装依赖"
}

Write-Host "[2/5] 生成独立 Python 分析引擎"
& $python -m PyInstaller `
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

Write-Host "[3/5] 检查 sidecar 产物不包含私密运行时数据"
Assert-NoPrivateRuntimeFiles -Root $engineDir

Write-Host "[4/5] 构建 Tauri Release 主程序"
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

Write-Host "[5/5] 生成 NSIS 安装包和 SHA-256 校验文件"
& $makensis `
    "/INPUTCHARSET" `
    "UTF8" `
    "/DAPP_EXE=$appExe" `
    "/DENGINE_DIR=$engineDir" `
    "/DOUTPUT_FILE=$outputFile" `
    "/DVERSION=$version" `
    "/DFILE_VERSION=$fileVersion" `
    "/DPRODUCT_NAME=$productName" `
    "/DFILE_DESCRIPTION=$fileDescription" `
    $installerScript
if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $outputFile -PathType Leaf)) {
    throw "NSIS 安装包生成失败。"
}

$artifact = Get-Item -LiteralPath $outputFile
$hash = Get-FileHash -LiteralPath $outputFile -Algorithm SHA256
[IO.File]::WriteAllText($checksumFile, "$($hash.Hash)  $($artifact.Name)", [Text.UTF8Encoding]::new($false))

if ($env:GITHUB_OUTPUT) {
    Add-Content -LiteralPath $env:GITHUB_OUTPUT -Encoding utf8 -Value "version=$version"
    Add-Content -LiteralPath $env:GITHUB_OUTPUT -Encoding utf8 -Value "installer=$($artifact.FullName)"
    Add-Content -LiteralPath $env:GITHUB_OUTPUT -Encoding utf8 -Value "checksum=$checksumFile"
}

Write-Host "DONE version=$version package=$($artifact.FullName) bytes=$($artifact.Length) sha256=$($hash.Hash) checksum=$checksumFile"
