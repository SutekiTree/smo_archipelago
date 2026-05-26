"""Generator-level tests for scripts/sync_capture_table.py.

Guards the many-hack-to-one-cap collapse for Puzzle Part / Picture Match
Part: capture_map.json carries two hack_names per apworld cap (Lake +
Metro for Puzzle Part; Mario + Goomba for Picture Match Part), but the
parallel kCaptureHackNames table can only hold one. The extras must
appear in kCaptureHackAliases so captureBitFor() resolves both directions
— otherwise the gate fail-opens on the un-tabled variant (Lake puzzle
piece captureable without owning "Puzzle Part" — bug reported 2026-05-26).
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parents[3]
_SCRIPT = _REPO_ROOT / "scripts" / "sync_capture_table.py"


def _load_sync_module():
    spec = importlib.util.spec_from_file_location("sync_capture_table", _SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["sync_capture_table"] = mod
    spec.loader.exec_module(mod)
    return mod


def _run(tmp_path: Path, items: list[dict], capture_map: list[dict] | None) -> str:
    items_path = tmp_path / "items.json"
    out_path = tmp_path / "capture_table.h"
    items_path.write_text(json.dumps(items), encoding="utf-8")
    args = ["--items", str(items_path), "--out", str(out_path)]
    if capture_map is None:
        args += ["--capture-map", str(tmp_path / "definitely_missing.json")]
    else:
        cap_path = tmp_path / "capture_map.json"
        cap_path.write_text(json.dumps(capture_map), encoding="utf-8")
        args += ["--capture-map", str(cap_path)]
    mod = _load_sync_module()
    rc = mod.main(args)
    assert rc == 0, f"sync_capture_table.main returned {rc}"
    return out_path.read_text(encoding="utf-8")


def _cap_item(name: str) -> dict:
    return {"name": name, "category": ["Capture"], "count": 1, "progression": True}


def test_emits_alias_for_second_hack_name(tmp_path: Path) -> None:
    """Two hack_names → one cap: primary in kCaptureHackNames, second in
    kCaptureHackAliases at the same bit index."""
    out = _run(
        tmp_path,
        items=[_cap_item("Goomba"), _cap_item("Puzzle Part")],
        capture_map=[
            {"hack_name": "Kuribo", "cap": "Goomba"},
            {"hack_name": "GotogotonLake", "cap": "Puzzle Part"},
            {"hack_name": "GotogotonCity", "cap": "Puzzle Part"},
        ],
    )
    # First hack_name wins the primary slot (matches Python CaptureMap
    # cap_to_hack first-write-wins, so bridge ↔ Switch agree on the wire).
    assert '"Kuribo",' in out
    assert '"GotogotonLake",' in out
    # Second variant lives in the alias array, pointing at the same bit
    # ("Puzzle Part" is index 1 in this synthetic items list).
    assert '{"GotogotonCity", 1},' in out
    # Alias array has exactly one entry.
    assert "kCaptureHackAliases = {{\n    " in out
    assert "std::array<CaptureHackAlias, 1>" in out


def test_no_aliases_when_one_to_one(tmp_path: Path) -> None:
    """No multi-hack collapses → empty alias array."""
    out = _run(
        tmp_path,
        items=[_cap_item("Goomba"), _cap_item("Frog")],
        capture_map=[
            {"hack_name": "Kuribo", "cap": "Goomba"},
            {"hack_name": "Frog", "cap": "Frog"},
        ],
    )
    assert "std::array<CaptureHackAlias, 0>" in out
    assert "kCaptureHackAliases = {};" in out


def test_missing_capture_map_emits_empty_aliases(tmp_path: Path) -> None:
    """No capture_map.json → identity hack_names + zero aliases (matches
    pre-extraction bundled build behavior)."""
    out = _run(
        tmp_path,
        items=[_cap_item("Goomba")],
        capture_map=None,
    )
    assert "std::array<CaptureHackAlias, 0>" in out


def test_real_data_lake_and_metro_both_resolvable(tmp_path: Path) -> None:
    """Drift guard against the actual user-extracted capture_map.json (if
    present): both Puzzle Part hack_names must land somewhere — primary
    OR alias. Same for Picture Match Part. This test skips when the
    extraction artifact isn't available (CI / fresh clone)."""
    cap_map = _REPO_ROOT / "apworld" / "smo_archipelago" / "client" / "data" / "capture_map.json"
    if not cap_map.exists():
        import pytest
        pytest.skip("capture_map.json not extracted; run scripts/extract_shine_map.py")
    items_path = _REPO_ROOT / "apworld" / "smo_archipelago" / "data" / "items.json"
    out_path = tmp_path / "capture_table.h"
    mod = _load_sync_module()
    rc = mod.main([
        "--items", str(items_path),
        "--out", str(out_path),
        "--capture-map", str(cap_map),
    ])
    assert rc == 0
    out = out_path.read_text(encoding="utf-8")
    # Both Lake and Metro puzzle hack_names must appear in the file
    # (one as primary, one as alias). Exact slot doesn't matter — what
    # matters is that captureBitFor finds both.
    for hack in ("GotogotonLake", "GotogotonCity",
                 "FukuwaraiFacePartsKuribo", "FukuwaraiFacePartsMario"):
        assert hack in out, f"{hack} missing from generated capture_table.h"
