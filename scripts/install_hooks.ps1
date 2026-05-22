# One-time setup: point this clone's core.hooksPath at the in-repo
# .githooks/ directory so the tracked pre-push hook fires on tag pushes.
# Idempotent -- re-running just confirms the config is correct.
#
# After running, `git push origin v0.X.Y-alpha` will invoke
# scripts/local_release_audit.ps1 before the push lands. See
# docs/release-process.md for the full pre-tag flow.

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path "$PSScriptRoot\..").Path
Set-Location $repoRoot

$current = git config --local --get core.hooksPath
if ($current -eq ".githooks") {
  Write-Host "core.hooksPath already points at .githooks/ -- no change needed."
} else {
  git config --local core.hooksPath .githooks
  if ($LASTEXITCODE -ne 0) { throw "git config failed (rc=$LASTEXITCODE)" }
  $prev = if ($current) { $current } else { '<unset>' }
  Write-Host "Set core.hooksPath = .githooks (was: $prev)"
}

# Sanity-check: confirm the hook exists and is reachable. A missing hook
# isn't fatal -- git will just no-op the pre-push step -- but it almost
# certainly means a botched clone (forgot to fetch the .githooks/ path
# because of a sparse-checkout or partial submodule init).
$hook = Join-Path $repoRoot ".githooks\pre-push"
if (-not (Test-Path $hook)) {
  Write-Warning "expected hook not found at $hook -- check that your clone is complete."
} else {
  Write-Host "Pre-push hook present at $hook"
}
