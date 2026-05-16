"""Tests for the bridge's raw-ID resolution tables."""

from __future__ import annotations

import json
from pathlib import Path

from smo_ap_bridge.maps import CaptureMap, MoonResolution, ShineMap


def _write(tmp_path: Path, name: str, entries: list) -> Path:
    p = tmp_path / name
    p.write_text(json.dumps(entries), encoding="utf-8")
    return p


def test_shine_map_resolves_by_pair(tmp_path: Path) -> None:
    p = _write(tmp_path, "shine.json", [
        {"stage_name": "CapWorldHomeStage", "object_id": "MoonOurFirst",
         "kingdom": "Cap", "shine_id": "Our First Power Moon"},
    ])
    m = ShineMap(p)
    res = m.resolve("CapWorldHomeStage", "MoonOurFirst")
    assert res == MoonResolution(kingdom="Cap", shine_id="Our First Power Moon")


def test_shine_map_returns_none_for_unknown(tmp_path: Path) -> None:
    p = _write(tmp_path, "shine.json", [])
    m = ShineMap(p)
    assert m.resolve("BogusStage", "MoonBogus") is None


def test_shine_map_falls_back_to_uid(tmp_path: Path) -> None:
    p = _write(tmp_path, "shine.json", [
        {"stage_name": "X", "object_id": "Y", "shine_uid": 999,
         "kingdom": "Cap", "shine_id": "Test Moon"},
    ])
    m = ShineMap(p)
    # Pair lookup fails (wrong names), so we fall back to uid.
    assert m.resolve("other", "other", 999) is not None


def test_shine_map_handles_missing_file() -> None:
    m = ShineMap(Path("/nonexistent/path/shine_map.json"))
    assert m.resolve("any", "any") is None


def test_capture_map_passthrough_when_unmapped(tmp_path: Path) -> None:
    p = _write(tmp_path, "cap.json", [])
    m = CaptureMap(p)
    assert m.resolve("Goomba") == "Goomba"  # pass-through


def test_capture_map_translates(tmp_path: Path) -> None:
    p = _write(tmp_path, "cap.json", [
        {"hack_name": "Kuribo", "cap": "Goomba"},
    ])
    m = CaptureMap(p)
    assert m.resolve("Kuribo") == "Goomba"
    # Unmapped names still pass through.
    assert m.resolve("Frog") == "Frog"


def test_capture_map_none_input() -> None:
    m = CaptureMap()
    assert m.resolve(None) is None
    assert m.resolve("") is None


# M6 phase B — reverse lookup (cap_name -> hack_name) used by item application.


def test_capture_map_reverse_resolves(tmp_path: Path) -> None:
    p = _write(tmp_path, "cap.json", [
        {"hack_name": "Kuribo", "cap": "Goomba"},
        {"hack_name": "Pukupuku", "cap": "Cheep Cheep"},
    ])
    m = CaptureMap(p)
    assert m.cap_to_hack("Goomba") == "Kuribo"
    assert m.cap_to_hack("Cheep Cheep") == "Pukupuku"


def test_capture_map_reverse_passthrough_when_unmapped(tmp_path: Path) -> None:
    """Caps not in the map identity-passthrough — covers the 1:1 names."""
    p = _write(tmp_path, "cap.json", [
        {"hack_name": "Kuribo", "cap": "Goomba"},
    ])
    m = CaptureMap(p)
    assert m.cap_to_hack("Frog") == "Frog"


def test_capture_map_reverse_handles_missing_file() -> None:
    m = CaptureMap(Path("/nonexistent/path/capture_map.json"))
    assert m.cap_to_hack("Goomba") == "Goomba"  # full identity-passthrough


def test_capture_map_reverse_none_input() -> None:
    m = CaptureMap()
    assert m.cap_to_hack(None) is None
    assert m.cap_to_hack("") is None
