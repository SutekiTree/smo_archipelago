# Local replacement for the (disabled) `clean-windows-audit` CI job.
# Runs `release_audit.py --all` with $env:SMOAP_APPDATA_ROOT pointed at a
# fresh tempdir so the audit's sandbox roots, stub-map writes, and walk
# all happen INSIDE the tempdir -- the user's real
# %APPDATA%\SMOArchipelago\ is never read or written.
#
# PATH is narrowed to the vendored toolchain (LLVM + WinLibs/mingw + the
# active Python + cmake + ninja + system32 + windir) so bare `python` /
# `python3` shell-outs from cmake's child processes can't escape the
# sandbox and silently pull in deps the wizard would surface to a
# real user.
#
# Invoked automatically by .githooks/pre-push on any `git push origin v*`
# (after the user runs scripts/install_hooks.ps1). Run standalone any
# time for a sanity check; ~5-10 min on a warm-build machine.
#
# ASCII-only: PowerShell 5.1 reads .ps1 files as the active ANSI codepage
# when there is no BOM. Em-dashes / curly quotes break the parser. Stick
# to plain ASCII characters in this file.

$ErrorActionPreference = "Stop"

$repoRoot   = (Resolve-Path "$PSScriptRoot\..").Path
$llvmRoot    = Join-Path $env:LOCALAPPDATA "SMOArchipelago\llvm"
$winlibsRoot = Join-Path $env:LOCALAPPDATA "SMOArchipelago\winlibs"

function Write-Step($msg) { Write-Host "[local-audit] $msg" -ForegroundColor Cyan }
function Write-Ok($msg)   { Write-Host "[local-audit] $msg" -ForegroundColor Green }
function Write-Fail($msg) { Write-Host "[local-audit] $msg" -ForegroundColor Red }

# --- Step 1: locate toolchain --------------------------------------------
# Mirrors scripts/build_switchmod.py's resolution order: respect SMOAP_*
# env vars first, then probe the wizard's portable installs under
# %LOCALAPPDATA%\SMOArchipelago\, then fall back to the same hand-install
# defaults build_switchmod.py uses (C:\Program Files\LLVM, C:\msys64).
Write-Step "resolving toolchain..."

function Resolve-Bin($envVar, $candidates, $marker, $label) {
  $envVal = [Environment]::GetEnvironmentVariable($envVar)
  if ($envVal -and (Test-Path (Join-Path $envVal $marker))) {
    return $envVal
  }
  foreach ($c in $candidates) {
    if (Test-Path (Join-Path $c $marker)) { return $c }
  }
  throw "$label not found. Tried: `$env:$envVar, $($candidates -join ', '). Install via the wizard's 'Install prereqs' button, or set `$env:$envVar."
}

$llvmBin    = Resolve-Bin "SMOAP_LLVM_BIN" @(
  (Join-Path $llvmRoot "bin"),
  "C:\Program Files\LLVM\bin"
) "clang.exe" "LLVM clang"

$winlibsBin = Resolve-Bin "SMOAP_MINGW_BIN" @(
  (Join-Path $winlibsRoot "mingw64\bin"),
  "C:\msys64\mingw64\bin"
) "g++.exe" "WinLibs / mingw64 g++"

$cmakeBin = Resolve-Bin "SMOAP_CMAKE_BIN" @(
  "C:\Program Files\CMake\bin"
) "cmake.exe" "Windows-native CMake"
# Important: explicitly prefer C:\Program Files\CMake\bin over an msys2
# cmake (some users have both, e.g. via devkitPro). build_switchmod.py's
# header note: "msys2 cmake on PATH first breaks the build" -- so we
# resolve the Windows-native install and put IT first on PATH below.

$ninjaCmd = Get-Command ninja -ErrorAction SilentlyContinue
if (-not $ninjaCmd) { throw "ninja not found on PATH -- install via winget (Ninja-build.Ninja)." }
$ninjaBin = Split-Path -Parent $ninjaCmd.Source

$pythonCmd = Get-Command python -ErrorAction SilentlyContinue
if (-not $pythonCmd) { throw "python not found on PATH -- install Python 3.12 (the wizard's prereq install handles this)." }
$pythonBin = Split-Path -Parent $pythonCmd.Source
$pythonExe = $pythonCmd.Source

# Git is needed for the audit's submodule-tracked check
# (release_audit.py::_list_git_tracked shells out to `git ls-files`).
# Without it the audit can't tell submodule files apart from build leaks
# and falsely fails on every OdysseyHeaders / Hakkun source file.
$gitCmd = Get-Command git -ErrorAction SilentlyContinue
if (-not $gitCmd) { throw "git not found on PATH -- install Git for Windows." }
$gitBin = Split-Path -Parent $gitCmd.Source

Write-Host "  LLVM:    $llvmBin"
Write-Host "  WinLibs: $winlibsBin"
Write-Host "  CMake:   $cmakeBin"
Write-Host "  Ninja:   $ninjaBin"
Write-Host "  Python:  $pythonBin"
Write-Host "  Git:     $gitBin"

# Ensure the host-Python deps build_switchmod needs are present in this
# interpreter. The wizard's installers.py pip-installs lz4 + pyelftools +
# mmh3 into the wizard's vendored Python; for a dev-checkout run we use
# whatever Python is first on PATH, so install into THAT one if missing.
Write-Step "checking host-Python deps (lz4 + pyelftools + mmh3)..."
$missingDeps = @()
foreach ($pkg in @("lz4", "pyelftools", "mmh3")) {
  & $pythonExe -m pip show $pkg *>$null
  if ($LASTEXITCODE -ne 0) { $missingDeps += $pkg }
}
if ($missingDeps.Count -gt 0) {
  Write-Step "installing missing deps: $($missingDeps -join ', ')"
  & $pythonExe -m pip install --quiet $missingDeps
  if ($LASTEXITCODE -ne 0) { throw "pip install failed for: $($missingDeps -join ', ')" }
}

# --- Step 2: build a fresh sandbox dir for the audit's APPDATA root -----
# Tempdir lives under %TEMP%; cleanup is in the finally block. Using a
# fixed prefix instead of [IO.Path]::GetRandomFileName so a previous
# aborted run's leftover dir is obvious in %TEMP% (the user can rm it).
$sandbox = Join-Path $env:TEMP ("smoap-audit-sandbox-" + [Guid]::NewGuid().ToString("N").Substring(0, 8))
New-Item -ItemType Directory -Path $sandbox -Force | Out-Null
Write-Step "audit sandbox: $sandbox"

$auditRc = 1
try {
  # --- Step 3: narrow PATH + set SMOAP_* env vars ------------------------
  Write-Step "narrowing PATH + setting SMOAP_* env vars..."
  $env:SMOAP_APPDATA_ROOT = $sandbox
  $env:SMOAP_LLVM_BIN     = $llvmBin
  $env:SMOAP_MINGW_BIN    = $winlibsBin
  $env:SMOAP_PYTHON_BIN   = $pythonBin
  $env:SMOAP_CMAKE_BIN    = $cmakeBin
  $env:SMOAP_NINJA_BIN    = $ninjaBin

  $narrowPath = @(
    $llvmBin,
    $winlibsBin,
    $pythonBin,
    $cmakeBin,
    $ninjaBin,
    $gitBin,
    (Join-Path $env:windir "System32"),
    $env:windir
  ) -join ";"
  $savedPath = $env:PATH
  $env:PATH = $narrowPath
  Write-Host ("  PATH narrowed to {0} entries" -f ($narrowPath -split ';').Count)

  # --- Step 4: run the audit stages individually --------------------------
  # release_audit.py's `--build` stage calls _setup/build.py's
  # `run_sync_capture_table` / `run_build_switchmod`, which look up
  # `bundled_script("sync_capture_table.py")` etc. -- a path that only
  # exists inside an actual apworld zip. In a dev checkout the scripts
  # live at <repo>/scripts/, so we run them directly here (mirroring the
  # CI's "Sync capture table" step) and let release_audit.py handle just
  # the stub-map write at the start and the file-tree walk at the end.
  Write-Step "step 1/4: writing stub maps (release_audit.py --skip-extract)..."
  & $pythonExe (Join-Path $repoRoot "scripts\release_audit.py") --skip-extract
  if ($LASTEXITCODE -ne 0) {
    Write-Fail "stub-map write failed (rc=$LASTEXITCODE)."
    $auditRc = $LASTEXITCODE
    $env:PATH = $savedPath
    return
  }

  Write-Step "step 2/4: scripts/sync_capture_table.py ..."
  & $pythonExe (Join-Path $repoRoot "scripts\sync_capture_table.py")
  if ($LASTEXITCODE -ne 0) {
    Write-Fail "sync_capture_table failed (rc=$LASTEXITCODE)."
    $auditRc = $LASTEXITCODE
    $env:PATH = $savedPath
    return
  }

  Write-Step "step 3/4: scripts/build_switchmod.py (cold-build switch-mod) ..."
  # BRIDGE_HOST is required by switch-mod's CMakeLists.txt; the audit
  # doesn't validate the value (subsdk9 is never deployed from this run),
  # 127.0.0.1 just has to be a syntactically valid host. Same default
  # release_audit.py exposes as --bridge-host.
  & $pythonExe (Join-Path $repoRoot "scripts\build_switchmod.py") "-DBRIDGE_HOST=127.0.0.1"
  if ($LASTEXITCODE -ne 0) {
    Write-Fail "build_switchmod failed (rc=$LASTEXITCODE)."
    $auditRc = $LASTEXITCODE
    $env:PATH = $savedPath
    return
  }

  Write-Step "step 4/4: release_audit.py --audit (walk + verify) ..."
  & $pythonExe (Join-Path $repoRoot "scripts\release_audit.py") --audit
  $auditRc = $LASTEXITCODE

  $env:PATH = $savedPath
} finally {
  # --- Step 5: clean up tempdir ----------------------------------------
  Write-Step "cleaning up audit sandbox..."
  Remove-Item -Path $sandbox -Recurse -Force -ErrorAction SilentlyContinue
  # Also clear the env var so subsequent commands in the same shell
  # don't accidentally inherit our sandbox path.
  Remove-Item Env:\SMOAP_APPDATA_ROOT -ErrorAction SilentlyContinue
}

# --- Step 6: propagate exit code -----------------------------------------
if ($auditRc -eq 0) {
  Write-Ok "audit PASSED."
  exit 0
} else {
  Write-Fail "audit FAILED (rc=$auditRc)."
  exit $auditRc
}
