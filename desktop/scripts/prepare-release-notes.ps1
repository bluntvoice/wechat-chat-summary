[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [ValidatePattern('^\d+\.\d+\.\d+(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$')]
    [string]$Version,
    [Parameter(Mandatory)]
    [string]$NotesPath,
    [string]$ChangelogPath = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$OutputEncoding = [Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
if (-not $ChangelogPath) {
    $ChangelogPath = Join-Path $repoRoot "CHANGELOG.md"
}

if (-not (Test-Path -LiteralPath $NotesPath -PathType Leaf)) {
    throw "发布说明文件不存在：$NotesPath"
}
if (-not (Test-Path -LiteralPath $ChangelogPath -PathType Leaf)) {
    throw "CHANGELOG 不存在：$ChangelogPath"
}

$notes = [IO.File]::ReadAllText((Resolve-Path -LiteralPath $NotesPath), [Text.UTF8Encoding]::new($false)).Trim()
if ([string]::IsNullOrWhiteSpace($notes)) {
    throw "发布说明不能为空。"
}
$releaseNotesHeadingPattern = '(?m)^## 版本亮点[ \t]*(?=\r?$)'
if ($notes -notmatch $releaseNotesHeadingPattern) {
    throw "发布说明必须包含二级标题：## 版本亮点"
}

$changelogFullPath = (Resolve-Path -LiteralPath $ChangelogPath).Path
$changelog = [IO.File]::ReadAllText($changelogFullPath, [Text.UTF8Encoding]::new($false))
if ($changelog -match "(?m)^## \[$([regex]::Escape($Version))\](?:\s|$)") {
    throw "CHANGELOG 已存在版本 $Version，拒绝重复发布。"
}

$notesForChangelog = [regex]::Replace($notes, $releaseNotesHeadingPattern, '### 版本亮点', 1)
$entry = "## [$Version] - $((Get-Date).ToString('yyyy-MM-dd'))`r`n`r`n$notesForChangelog`r`n`r`n"
$anchor = "<!-- 新版本由 release.yml 插入到此行之后 -->"
if (-not $changelog.Contains($anchor)) {
    throw "CHANGELOG 缺少自动插入锚点：$anchor"
}

$updated = $changelog.Replace($anchor, "$anchor`r`n`r`n$entry")
$temporaryPath = "$changelogFullPath.tmp"
try {
    [IO.File]::WriteAllText($temporaryPath, $updated, [Text.UTF8Encoding]::new($false))
    Move-Item -LiteralPath $temporaryPath -Destination $changelogFullPath -Force
}
finally {
    if (Test-Path -LiteralPath $temporaryPath) {
        Remove-Item -LiteralPath $temporaryPath -Force
    }
}

Write-Host "CHANGELOG_OK version=$Version path=$changelogFullPath"
