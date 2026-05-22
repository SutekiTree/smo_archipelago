#!/usr/bin/env python3
"""Build sail (LibHakkun's symbol-DB host binary) on Windows.

Sail is a C++23 program that runs on the *host* (not the Switch). LibHakkun's
upstream `tools/setup_sail.py` at main HEAD (9892726+) uses `cmake --build`
which IS Windows-compatible — so on paper we could delegate to it. But we
don't, for two reasons: (1) the upstream script doesn't `check=True` on its
subprocess calls, so a silent cmake/ninja failure leaves an empty build
dir and the caller has to detect that downstream; (2) the imgui dev branch
briefly reverted to `make` and we were burned once already. Building sail
ourselves here keeps both failure modes out of the build-wrapper.

On Windows the host build needs:

  - Windows-native CMake (not msys2 cmake which uses POSIX path resolution).
  - mingw64 g++ as host compiler (the LLVM clang we use for the Switch target
    is configured for aarch64-none-elf and can't link a Windows host binary
    without a full MSVC SDK).
  - Patched sail sources to handle Windows `std::filesystem::path` returning
    wchar_t* on Windows, and to quote the clangBinary path in popen.
    (Patches applied by scripts/patch_hakkun.py — run that first.)
"""

import os
import shutil
import subprocess
import sys

# Each binary dir is overridable via the matching SMOAP_* env var so the
# wizard can point MINGW_BIN at the WinLibs portable install. Defaults match
# a winget + msys2 hand-install so repo devs keep working unchanged.
CMAKE_BIN = os.environ.get("SMOAP_CMAKE_BIN", r"C:\Program Files\CMake\bin")
NINJA_BIN = os.environ.get(
    "SMOAP_NINJA_BIN",
    r"C:\Users\maxwe\AppData\Local\Microsoft\WinGet\Packages\Ninja-build.Ninja_Microsoft.Winget.Source_8wekyb3d8bbwe",
)
MINGW_BIN = os.environ.get("SMOAP_MINGW_BIN", r"C:\msys64\mingw64\bin")

# Script runs from switch-mod/ (cwd contains `sys/` submodule). At
# LibHakkun main HEAD (9892726+) sail lives at sys/sail/. The 2026-05-22
# imgui-dev-branch pin moved it to sys/hakkun/sail/ briefly; that bump
# was reverted because the imgui branch lacked main's devkitPro-free
# tooling. If you re-pin to a branch that relocates sail again, audit
# this path together with scripts/build_switchmod.py's ensure_sail_built.
SWITCH_MOD = os.getcwd()
SAIL_SRC = os.path.join(SWITCH_MOD, "sys", "sail")
SAIL_BUILD = os.path.join(SAIL_SRC, "build")

if not os.path.exists(os.path.join(SAIL_SRC, "CMakeLists.txt")):
    sys.exit(
        f"[setup_sail] {SAIL_SRC}/CMakeLists.txt not found. Is the sys "
        f"submodule checked out? `git submodule update --init switch-mod/sys`"
    )

env = os.environ.copy()
env["PATH"] = os.pathsep.join([MINGW_BIN, CMAKE_BIN, NINJA_BIN, env.get("PATH", "")])
env["CC"] = "gcc"
env["CXX"] = "g++"

cmake = os.path.join(CMAKE_BIN, "cmake.exe")
if not os.path.exists(cmake):
    cmake = "cmake"  # fall back to PATH lookup

# Clean slate on every invocation — the upstream setup_sail.py also does this
# (rmtree before build) and the script is only called when the binary is
# missing, so the rebuild cost is one-time per machine.
if os.path.exists(SAIL_BUILD):
    shutil.rmtree(SAIL_BUILD)
os.makedirs(SAIL_BUILD)

cfg = subprocess.run(
    [cmake, "-S", SAIL_SRC, "-B", SAIL_BUILD, "-G", "Ninja",
     "-DCMAKE_BUILD_TYPE=Release"],
    env=env,
)
if cfg.returncode != 0:
    sys.exit(f"[setup_sail] cmake configure failed (exit {cfg.returncode})")

bld = subprocess.run(
    [cmake, "--build", SAIL_BUILD, "-j", "8"],
    env=env,
)
sys.exit(bld.returncode)
