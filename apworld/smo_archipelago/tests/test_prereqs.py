"""Tests for `_setup.prereqs` — the detectors that drive the wizard's
Prereq-check page.

All shell-outs go through `_setup.prereqs._run`; we monkeypatch it per-test
to script success / failure without touching the user's actual machine.
Filesystem-touching detectors are tested by manipulating `Path.home`
(prod.keys check) or `os.environ` (devkitPro check) via monkeypatch.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

import pytest

from _setup import prereqs
from _setup.prereqs import (
    PrereqResult,
    all_ok,
    check_all,
    check_cmake,
    check_devkitpro,
    check_hactool,
    check_ninja,
    check_prod_keys,
    check_python312,
)


@pytest.fixture
def fake_run(monkeypatch):
    """Replace `prereqs._run` with a scripted responder.

    Usage:
        fake_run({"cmake --version": (0, "cmake version 3.30.5\\n", "")})
    """
    def install(cmd_to_result: dict[str, tuple[int, str, str]]):
        def _impl(cmd, *, timeout=10.0):
            key = " ".join(cmd)
            if key in cmd_to_result:
                return cmd_to_result[key]
            # Default: pretend the binary doesn't exist.
            raise FileNotFoundError(cmd[0])
        monkeypatch.setattr(prereqs, "_run", _impl)
    return install


# ---------- check_python312 ----------

def test_python312_found_via_py_launcher(fake_run) -> None:
    fake_run({"py -3.12 --version": (0, "Python 3.12.7\n", "")})
    r = check_python312()
    assert r.ok
    assert "3.12.7" in r.detail


def test_python312_falls_back_to_python312_command(fake_run) -> None:
    fake_run({"python3.12 --version": (0, "Python 3.12.3\n", "")})
    r = check_python312()
    assert r.ok
    assert "3.12.3" in r.detail


def test_python312_missing(fake_run) -> None:
    fake_run({})
    r = check_python312()
    assert not r.ok
    assert r.install_url.startswith("https://")


# ---------- check_devkitpro ----------

def test_devkitpro_env_missing(monkeypatch) -> None:
    monkeypatch.delenv("DEVKITPRO", raising=False)
    r = check_devkitpro()
    assert not r.ok
    assert "DEVKITPRO" in r.detail


def test_devkitpro_env_set_binary_present(monkeypatch, tmp_path, fake_run) -> None:
    # Build a fake devkitPro tree with the cross-compiler.
    bindir = tmp_path / "devkitA64" / "bin"
    bindir.mkdir(parents=True)
    gxx = bindir / "aarch64-none-elf-g++.exe"
    gxx.write_text("")
    monkeypatch.setenv("DEVKITPRO", str(tmp_path))
    fake_run({f"{gxx} --version": (0, "g++ (devkitA64) 15.1.0\n", "")})
    r = check_devkitpro()
    assert r.ok
    assert "g++" in r.detail


def test_devkitpro_env_set_binary_missing(monkeypatch, tmp_path) -> None:
    # Env points at empty dir — installer aborted or got cleaned up.
    monkeypatch.setenv("DEVKITPRO", str(tmp_path))
    r = check_devkitpro()
    assert not r.ok
    assert "not found" in r.detail or "incomplete" in r.detail


# ---------- check_cmake ----------

def test_cmake_modern_version(fake_run) -> None:
    fake_run({"cmake --version": (
        0, "cmake version 3.30.5\nCMake suite maintained by Kitware\n", "")})
    r = check_cmake()
    assert r.ok
    assert "3.30.5" in r.detail


def test_cmake_too_old(fake_run) -> None:
    fake_run({"cmake --version": (0, "cmake version 3.20.1\n", "")})
    r = check_cmake()
    assert not r.ok
    assert "too old" in r.detail
    assert "3.24" in r.name


def test_cmake_unparseable_output(fake_run) -> None:
    fake_run({"cmake --version": (0, "garbage from a wrapper\n", "")})
    r = check_cmake()
    assert not r.ok
    assert "couldn't parse" in r.detail


def test_cmake_missing(fake_run) -> None:
    fake_run({})
    r = check_cmake()
    assert not r.ok
    assert r.install_url


def test_cmake_3_24_0_exact_boundary(fake_run) -> None:
    """3.24.0 should be accepted (>= 3.24)."""
    fake_run({"cmake --version": (0, "cmake version 3.24.0\n", "")})
    r = check_cmake()
    assert r.ok


# ---------- check_ninja ----------

def test_ninja_present(fake_run) -> None:
    fake_run({"ninja --version": (0, "1.12.1\n", "")})
    r = check_ninja()
    assert r.ok
    assert "1.12.1" in r.detail


def test_ninja_missing(fake_run) -> None:
    fake_run({})
    r = check_ninja()
    assert not r.ok


# ---------- check_hactool ----------

def test_hactool_present(monkeypatch, tmp_path) -> None:
    hac = tmp_path / "hactool.exe"
    hac.write_text("")
    monkeypatch.setattr("shutil.which", lambda name: str(hac) if name in (
        "hactool", "hactool.exe") else None)
    r = check_hactool()
    assert r.ok
    assert str(hac) in r.detail


def test_hactool_missing(monkeypatch) -> None:
    monkeypatch.setattr("shutil.which", lambda name: None)
    r = check_hactool()
    assert not r.ok


# ---------- check_prod_keys ----------

def test_prod_keys_present(monkeypatch, tmp_path) -> None:
    home = tmp_path / "userhome"
    (home / ".switch").mkdir(parents=True)
    (home / ".switch" / "prod.keys").write_text("# keys\n")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    r = check_prod_keys()
    assert r.ok


def test_prod_keys_missing(monkeypatch, tmp_path) -> None:
    home = tmp_path / "userhome"
    home.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    r = check_prod_keys()
    assert not r.ok
    assert "Lockpick" in r.install_url


# ---------- check_all / all_ok ----------

def test_check_all_runs_every_detector() -> None:
    results = check_all()
    keys = {r.key for r in results}
    assert {"devkitpro", "cmake", "ninja", "python312",
            "hactool", "prodkeys"} <= keys


def test_all_ok_aggregate() -> None:
    assert all_ok([
        PrereqResult("a", "A", True, ""),
        PrereqResult("b", "B", True, ""),
    ])
    assert not all_ok([
        PrereqResult("a", "A", True, ""),
        PrereqResult("b", "B", False, "missing"),
    ])
    assert all_ok([])  # vacuously true; check_all() should never return empty
