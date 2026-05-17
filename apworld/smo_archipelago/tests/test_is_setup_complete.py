"""Tests for `is_setup_complete()` and the APPDATA map search path in
`client/main.py`. These gate the wizard-vs-launch decision the
`launch_smo_client` Component callback makes when the user opens a
`.smoap` file."""

from __future__ import annotations

from pathlib import Path

import pytest

from client.setup_state import (
    _resolve_map_path,
    _user_data_dir,
    is_setup_complete,
)


@pytest.fixture
def isolated_appdata(monkeypatch, tmp_path: Path) -> Path:
    """Point APPDATA at a tmp dir so tests don't see / touch the real
    %APPDATA%/SMOArchipelago/ (and so this still works in CI where
    APPDATA may be unset)."""
    monkeypatch.setenv("APPDATA", str(tmp_path))
    return tmp_path / "SMOArchipelago"


def test_setup_complete_false_on_empty_appdata(isolated_appdata: Path) -> None:
    assert not is_setup_complete()


def test_setup_complete_requires_all_four_files(isolated_appdata: Path) -> None:
    data = isolated_appdata / "data"
    build = isolated_appdata / "build" / "cmake"
    data.mkdir(parents=True)
    build.mkdir(parents=True)

    # Drop only some of the required files — should still be incomplete.
    (data / "shine_map.json").write_text("[]")
    assert not is_setup_complete(), "missing capture_map + binaries"

    (data / "capture_map.json").write_text("[]")
    assert not is_setup_complete(), "missing subsdk9 + main.npdm"

    (build / "subsdk9").write_bytes(b"\x7fELF")
    assert not is_setup_complete(), "missing main.npdm"

    (build / "main.npdm").write_bytes(b"META")
    assert is_setup_complete(), "all four present"


def test_resolve_map_path_prefers_appdata(
    isolated_appdata: Path, monkeypatch
) -> None:
    """When the wizard has written maps to %APPDATA%, that's the path
    `_resolve_map_path` returns — NOT the bundled client/data/ location."""
    data = isolated_appdata / "data"
    data.mkdir(parents=True)
    appdata_shine = data / "shine_map.json"
    appdata_shine.write_text("[]")
    result = _resolve_map_path("", "shine_map.json")
    assert result == appdata_shine


def test_resolve_map_path_explicit_wins(
    isolated_appdata: Path, tmp_path: Path
) -> None:
    """An explicit host.yaml / CLI override beats any auto-discovery —
    matches the existing precedence in `client/main.py:100-135`."""
    data = isolated_appdata / "data"
    data.mkdir(parents=True)
    (data / "shine_map.json").write_text("[]")

    explicit = tmp_path / "custom_shine.json"
    explicit.write_text('[{"stage_name": "X"}]')
    result = _resolve_map_path(str(explicit), "shine_map.json")
    assert result == explicit


def test_resolve_map_path_returns_none_when_none_exist(
    isolated_appdata: Path, monkeypatch
) -> None:
    """No APPDATA, no bundled, no override → returns None so the caller
    falls through to the importlib.resources package-load path (which on
    a release zip also misses and produces empty maps)."""
    # Point setup_state's __file__ at an isolated dir so the legacy
    # client/data/ fallback (relative to that module) doesn't find the
    # real maps in the dev tree.
    import client.setup_state as ss
    fake_module_file = isolated_appdata / "fake_setup_state.py"
    fake_module_file.parent.mkdir(parents=True, exist_ok=True)
    fake_module_file.write_text("")
    monkeypatch.setattr(ss, "__file__", str(fake_module_file))
    result = _resolve_map_path("", "shine_map.json")
    assert result is None


def test_user_data_dir_honors_appdata_env(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("APPDATA", str(tmp_path))
    assert _user_data_dir() == tmp_path / "SMOArchipelago" / "data"


def test_user_data_dir_falls_back_on_non_windows(monkeypatch) -> None:
    """When APPDATA is unset (Linux/Mac, or stripped Windows env), fall
    back to ~/.local/share/SMOArchipelago/data/."""
    monkeypatch.delenv("APPDATA", raising=False)
    result = _user_data_dir()
    assert result.name == "data"
    assert result.parent.name == "SMOArchipelago"
