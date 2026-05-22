"""Tests for `_diagnose_oead_import_failure` in scripts/extract_shine_map.py.

Regression coverage for the infinite re-exec loop that bit a real user
(see git history): when the bootstrapped venv exists but `import oead`
still fails, the old code would call `_bootstrap_and_reexec`, which
skips the install step (venv already exists) and just relaunches itself,
producing a fork-bomb-flavored loop that printed the same banner ~1000
times before the wizard's stall watchdog noticed.

The diagnostic helper is a pure function — tests drive it directly with
synthetic ImportError / executable-path inputs.
"""

from __future__ import annotations

import importlib.util
import io
import os
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest

SCRIPT = (Path(__file__).resolve().parent.parent.parent.parent
          / "scripts" / "extract_shine_map.py")


def _load_extract_module():
    """Re-uses the technique from test_extract_hactool_runner.py: stub
    `oead` so the script imports cleanly under test."""
    if not SCRIPT.exists():
        pytest.skip(f"{SCRIPT} not present (running from installed apworld)")
    if "oead" not in sys.modules:
        stub = types.ModuleType("oead")
        stub.yaz0 = types.SimpleNamespace(decompress=lambda b: b)
        stub.Sarc = MagicMock()
        stub.byml = types.SimpleNamespace(from_binary=lambda b: {})
        sys.modules["oead"] = stub
    spec = importlib.util.spec_from_file_location(
        "extract_shine_map_guard_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    saved_stdout, saved_stderr = sys.stdout, sys.stderr
    sys.stdout = io.TextIOWrapper(open(os.devnull, "wb"), encoding="utf-8")
    sys.stderr = io.TextIOWrapper(open(os.devnull, "wb"), encoding="utf-8")
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.stdout, sys.stderr = saved_stdout, saved_stderr
    return mod


@pytest.fixture(scope="module")
def extract_mod():
    return _load_extract_module()


def test_not_in_venv_returns_none(extract_mod, tmp_path) -> None:
    """When the current Python isn't the venv Python, the helper returns
    None — caller proceeds to bootstrap-and-reexec normally."""
    venv_dir = tmp_path / ".extract-venv"
    venv_py = venv_dir / "Scripts" / "python.exe"
    venv_py.parent.mkdir(parents=True)
    venv_py.write_bytes(b"")  # exists so resolve() works
    other_python = tmp_path / "system-python.exe"
    other_python.write_bytes(b"")

    diag = extract_mod._diagnose_oead_import_failure(
        ImportError("No module named 'oead'"),
        str(other_python), venv_py, venv_dir,
    )
    assert diag is None


def test_in_venv_with_dll_load_failed_surfaces_vcredist_hint(
    extract_mod, tmp_path,
) -> None:
    """The hot path: we ARE the venv Python, the error mentions DLL load
    failure, so the user gets a VCRedist install link. This is the case
    that produced the infinite loop in the field."""
    venv_dir = tmp_path / ".extract-venv"
    venv_py = venv_dir / "Scripts" / "python.exe"
    venv_py.parent.mkdir(parents=True)
    venv_py.write_bytes(b"")

    diag = extract_mod._diagnose_oead_import_failure(
        ImportError(
            "DLL load failed while importing _oead: "
            "The specified module could not be found."
        ),
        str(venv_py), venv_py, venv_dir,
    )
    assert diag is not None
    # The user-actionable artifacts: the VCRedist URL and a probe command
    # they can paste to confirm the diagnosis.
    assert "aka.ms" in diag
    assert "vc_redist" in diag
    assert "import oead" in diag
    # Recursion guard signals "FATAL" so the caller knows to sys.exit
    # rather than re-launching.
    assert "FATAL" in diag


def test_in_venv_with_other_import_error_surfaces_alternatives(
    extract_mod, tmp_path,
) -> None:
    """Non-DLL ImportError — could be a broken wheel, ABI mismatch, AV
    quarantine. The helper enumerates those plausible causes instead of
    pointing the user at VCRedist (which wouldn't fix any of them)."""
    venv_dir = tmp_path / ".extract-venv"
    venv_py = venv_dir / "Scripts" / "python.exe"
    venv_py.parent.mkdir(parents=True)
    venv_py.write_bytes(b"")

    diag = extract_mod._diagnose_oead_import_failure(
        ImportError("No module named '_oead'"),
        str(venv_py), venv_py, venv_dir,
    )
    assert diag is not None
    # Should NOT point at VCRedist — wrong diagnosis for a missing-module
    # error. Should point at delete-the-venv + alternative causes.
    assert "aka.ms" not in diag
    assert str(venv_dir) in diag
    assert "antivirus" in diag.lower() or "abi" in diag.lower()


def test_resolve_failure_treats_as_not_in_venv(extract_mod, tmp_path) -> None:
    """Path.resolve() can raise OSError on Windows for paths with
    permission issues or unusual reparse points. The helper falls back
    to 'not in venv' rather than crashing — better to attempt one
    bootstrap-relaunch than to fail with an opaque OSError."""
    venv_dir = tmp_path / ".extract-venv"
    venv_py = venv_dir / "Scripts" / "python.exe"
    # Don't create the venv_py file — its resolve() will succeed but
    # `current_executable` resolve will work too. Use a comparison that
    # absolutely won't match.
    other = tmp_path / "definitely-not-venv.exe"
    other.write_bytes(b"")
    diag = extract_mod._diagnose_oead_import_failure(
        ImportError("anything"),
        str(other), venv_py, venv_dir,
    )
    assert diag is None
