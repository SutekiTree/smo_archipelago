"""Detect the tools the setup wizard needs.

The wizard runs these detectors on the Prereq-check page. Each detector
returns a `PrereqResult` with a `ok` flag, a human-readable status detail
(e.g. "cmake 3.30.5" on success, or "not found on PATH" on failure), and
an `install_url` the wizard surfaces as a clickable link when `ok=False`.

Detectors are intentionally pure-Python and stdlib-only so they import on
any Python 3.10+ — no Kivy, no third-party deps. The wizard module is the
only thing that pulls in Kivy.

For unit-testability every shell-out goes through `_run`, which is a thin
wrapper around `subprocess.run`. Tests monkeypatch `_run` to return scripted
results without touching the user's machine. Filesystem checks use
`pathlib.Path` directly because mocking `Path.exists` per-test is cleaner
than abstracting a filesystem facade.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

# Hard min for cmake — lunakit's toolchain file uses target_link_options
# (3.13+) and project(... LANGUAGES CXX) policies (3.24 enables CMP0135),
# and our switch-mod uses target features that landed in 3.24.
MIN_CMAKE = (3, 24)

# Install pages we link to from the wizard. Kept in this module so the
# wizard layer is pure layout; copy-paste from
# https://devkitpro.org/wiki/Getting_Started → the Windows-installer page
# is the canonical entry.
INSTALL_URLS = {
    "python312": "https://www.python.org/downloads/release/python-3120/",
    "devkitpro": "https://devkitpro.org/wiki/Getting_Started",
    "cmake": "https://cmake.org/download/",
    "ninja": "https://github.com/ninja-build/ninja/releases",
    "hactool": "https://github.com/SciresM/hactool/releases",
    "prodkeys": "https://github.com/Lockpick-Switch/Lockpick_RCM",
}


@dataclass
class PrereqResult:
    """Outcome of a single detector.

    `key` is the stable identifier the wizard uses to map back into
    `INSTALL_URLS` and to render the right label. `detail` is the
    human-readable extra (version string, error message). `install_url`
    is non-empty when `ok=False` so the wizard can surface a clickable
    link.
    """
    key: str
    name: str
    ok: bool
    detail: str
    install_url: str = ""


def _run(cmd: list[str], *, timeout: float = 10.0) -> tuple[int, str, str]:
    """Subprocess wrapper that returns (returncode, stdout, stderr).

    Centralized so tests can monkeypatch one function instead of mocking
    `subprocess.run` per-detector. Non-zero exit codes are NOT exceptions
    — they're the normal "tool not found" signal.

    Raises `FileNotFoundError` only when the executable name itself can't
    be resolved (i.e. not on PATH); detectors catch this and treat it as
    "not installed".
    """
    res = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return res.returncode, res.stdout or "", res.stderr or ""


def _safe_run(cmd: list[str]) -> tuple[int, str, str] | None:
    """`_run` that returns None instead of raising on FileNotFoundError /
    OSError. Use when a detector wants to treat 'executable missing' the
    same as 'executable exists but exited non-zero'."""
    try:
        return _run(cmd)
    except (FileNotFoundError, OSError):
        return None
    except subprocess.TimeoutExpired:
        return (1, "", "timeout")


def check_python312() -> PrereqResult:
    """Python 3.12 launcher availability.

    The shine-map extractor scripts (`extract_shine_map.py`) self-bootstrap
    a Python 3.12 venv because `oead` (the BYML/MSBT parser) has no wheel
    for Python 3.13+. The wizard inherits this requirement.

    On Windows we look for the `py -3.12` launcher first (standard on a
    full Python install), and fall back to plain `python3.12` for users
    whose installer didn't register the launcher.
    """
    for cmd in (["py", "-3.12", "--version"], ["python3.12", "--version"]):
        r = _safe_run(cmd)
        if r is None:
            continue
        rc, out, err = r
        if rc == 0:
            ver = (out + err).strip()
            return PrereqResult("python312", "Python 3.12", True, ver)
    return PrereqResult(
        "python312", "Python 3.12", False,
        "not found (the moon/capture extractor needs Python 3.12 because "
        "`oead` has no 3.13 wheel)",
        INSTALL_URLS["python312"],
    )


def check_devkitpro() -> PrereqResult:
    """devkitPro installation (devkitA64 cross-compiler).

    Detection is layered: the env var `DEVKITPRO` is the canonical signal
    set by the Windows installer; we also verify the cross-compiler binary
    actually exists at the expected sub-path so a stale env var pointing
    at a deleted install reports cleanly.
    """
    root = os.environ.get("DEVKITPRO")
    if not root:
        return PrereqResult(
            "devkitpro", "devkitPro / devkitA64", False,
            "DEVKITPRO env var not set (re-run devkitPro installer or open "
            "a new shell after install)",
            INSTALL_URLS["devkitpro"],
        )
    gxx = Path(root) / "devkitA64" / "bin" / "aarch64-none-elf-g++.exe"
    if not gxx.exists():
        # Try POSIX layout (no .exe extension) for Linux users who set
        # DEVKITPRO manually.
        gxx_nox = Path(root) / "devkitA64" / "bin" / "aarch64-none-elf-g++"
        if not gxx_nox.exists():
            return PrereqResult(
                "devkitpro", "devkitPro / devkitA64", False,
                f"DEVKITPRO={root} but aarch64-none-elf-g++ not found "
                f"(install incomplete?)",
                INSTALL_URLS["devkitpro"],
            )
        gxx = gxx_nox
    r = _safe_run([str(gxx), "--version"])
    if r and r[0] == 0:
        first_line = (r[1] or r[2]).splitlines()[0] if (r[1] or r[2]) else "ok"
        return PrereqResult(
            "devkitpro", "devkitPro / devkitA64", True,
            f"{root} ({first_line})",
        )
    return PrereqResult(
        "devkitpro", "devkitPro / devkitA64", False,
        f"DEVKITPRO={root}; binary exists but failed to run --version",
        INSTALL_URLS["devkitpro"],
    )


def _parse_cmake_version(text: str) -> tuple[int, int, int] | None:
    """`cmake --version` prints `cmake version 3.30.5\\nCMake suite ...`."""
    m = re.search(r"cmake version (\d+)\.(\d+)(?:\.(\d+))?", text)
    if not m:
        return None
    major, minor, patch = m.group(1), m.group(2), m.group(3) or "0"
    return (int(major), int(minor), int(patch))


def check_cmake() -> PrereqResult:
    r = _safe_run(["cmake", "--version"])
    if r is None or r[0] != 0:
        return PrereqResult(
            "cmake", f"CMake {MIN_CMAKE[0]}.{MIN_CMAKE[1]}+", False,
            "not found on PATH",
            INSTALL_URLS["cmake"],
        )
    ver = _parse_cmake_version(r[1] or r[2])
    if ver is None:
        return PrereqResult(
            "cmake", f"CMake {MIN_CMAKE[0]}.{MIN_CMAKE[1]}+", False,
            "found, but couldn't parse `cmake --version` output",
            INSTALL_URLS["cmake"],
        )
    if (ver[0], ver[1]) < MIN_CMAKE:
        return PrereqResult(
            "cmake", f"CMake {MIN_CMAKE[0]}.{MIN_CMAKE[1]}+", False,
            f"{ver[0]}.{ver[1]}.{ver[2]} too old (need "
            f"{MIN_CMAKE[0]}.{MIN_CMAKE[1]}+)",
            INSTALL_URLS["cmake"],
        )
    return PrereqResult(
        "cmake", f"CMake {MIN_CMAKE[0]}.{MIN_CMAKE[1]}+", True,
        f"{ver[0]}.{ver[1]}.{ver[2]}",
    )


def check_ninja() -> PrereqResult:
    r = _safe_run(["ninja", "--version"])
    if r is None or r[0] != 0:
        return PrereqResult(
            "ninja", "Ninja", False,
            "not found on PATH",
            INSTALL_URLS["ninja"],
        )
    ver = (r[1] or r[2]).strip()
    return PrereqResult("ninja", "Ninja", True, ver)


def check_hactool() -> PrereqResult:
    """`hactool` for unpacking the user's SMO NSP during map extraction.

    The extractor script (`scripts/extract_shine_map.py`) calls hactool
    to extract program NCA → RomFS. It is NOT bundled (Switch-tooling
    license + the extractor already accepts an explicit `--hactool` path
    override), so the wizard just confirms it's on PATH.
    """
    exe = shutil.which("hactool") or shutil.which("hactool.exe")
    if not exe:
        return PrereqResult(
            "hactool", "hactool", False,
            "not found on PATH (needed to extract RomFS from your SMO NSP)",
            INSTALL_URLS["hactool"],
        )
    return PrereqResult("hactool", "hactool", True, exe)


def check_prod_keys() -> PrereqResult:
    """Switch console keys at the standard hactool default location.

    The extractor needs `prod.keys` to decrypt the NSP. Users typically dump
    these via Lockpick_RCM into `~/.switch/prod.keys` (hactool's default
    location); we look there only. If a user has them elsewhere they can
    point the extractor at them via the `--keys` arg (the wizard will
    surface that override option in a future revision).
    """
    p = Path.home() / ".switch" / "prod.keys"
    if not p.exists():
        return PrereqResult(
            "prodkeys", "prod.keys", False,
            f"not found at {p} (dump with Lockpick_RCM)",
            INSTALL_URLS["prodkeys"],
        )
    return PrereqResult("prodkeys", "prod.keys", True, str(p))


# Order matters for UI: heaviest / most-likely-missing first so the user
# isn't surprised at the end of the list.
_ALL_CHECKS = (
    check_devkitpro,
    check_cmake,
    check_ninja,
    check_python312,
    check_hactool,
    check_prod_keys,
)


def check_all() -> list[PrereqResult]:
    """Run every detector. Order is wizard-display order."""
    return [check() for check in _ALL_CHECKS]


def all_ok(results: list[PrereqResult]) -> bool:
    return all(r.ok for r in results)
