# Install repo git hooks (pre-commit runs quality gate + pyright).
$ErrorActionPreference = "Stop"

$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$HookSrc = Join-Path $RepoRoot "scripts\hooks\pre-commit"
$HookDst = Join-Path $RepoRoot ".git\hooks\pre-commit"

if (-not (Test-Path (Join-Path $RepoRoot ".git"))) {
  Write-Error "install-git-hooks: not a git repository: $RepoRoot"
}

Copy-Item -Force $HookSrc $HookDst
Write-Host "Installed $HookDst"
