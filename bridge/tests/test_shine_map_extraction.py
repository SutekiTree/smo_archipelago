"""Validate a locally-extracted shine_map.json (gitignored, so often absent).

These tests are skipped when shine_map.json hasn't been generated yet (fresh
clone, CI without a SMO dump). After running `python scripts/extract_shine_map.py`
they confirm the file's schema, count, and the M5.7 anchor entry.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from smo_ap_bridge.maps import MoonResolution, ShineMap

SHINE_MAP_PATH = Path(__file__).resolve().parent.parent / "smo_ap_bridge" / "data" / "shine_map.json"


def _entries() -> list[dict]:
    if not SHINE_MAP_PATH.exists():
        pytest.skip(f"{SHINE_MAP_PATH} not generated; run scripts/extract_shine_map.py")
    return json.loads(SHINE_MAP_PATH.read_text(encoding="utf-8"))


REQUIRED_KEYS = {"stage_name", "object_id", "kingdom", "shine_id", "shine_uid"}


def test_extracted_count_is_complete() -> None:
    entries = _entries()
    # SMO 1.0.0 has 775 raw shines across 17 HomeStage BYMLs. Allow some
    # latitude in case Nintendo data layout shifts slightly between regions.
    assert len(entries) >= 500, f"too few entries: {len(entries)}"


def test_extracted_schema() -> None:
    for i, e in enumerate(_entries()):
        missing = REQUIRED_KEYS - set(e)
        assert not missing, f"entry {i} missing keys {missing}: {e}"
        assert isinstance(e["stage_name"], str) and e["stage_name"]
        assert isinstance(e["object_id"], str) and e["object_id"]
        assert isinstance(e["kingdom"], str) and e["kingdom"]
        assert isinstance(e["shine_id"], str) and e["shine_id"]
        assert isinstance(e["shine_uid"], int)


def test_extracted_no_duplicate_pair_keys() -> None:
    pairs = [(e["stage_name"], e["object_id"]) for e in _entries()]
    dups = {p for p in pairs if pairs.count(p) > 1}
    assert not dups, f"duplicate (stage_name, object_id) keys: {sorted(dups)[:5]}"


def test_extracted_anchor_resolves() -> None:
    """The M5.7 ground-truth entry must resolve identically.

    Confirmed live: Mario collects 'Our First Power Moon' in Ryujinx ->
    MoonGetHook fires with stage=WaterfallWorldHomeStage, obj=obj214.
    """
    m = ShineMap(SHINE_MAP_PATH)
    res = m.resolve("WaterfallWorldHomeStage", "obj214")
    assert res == MoonResolution(kingdom="Cascade", shine_id="Our First Power Moon")


def test_extracted_kingdom_set_known() -> None:
    """All extracted kingdom labels must be ones the apworld knows about."""
    known = {
        "Cap", "Cascade", "Sand", "Lake", "Wooded", "Cloud", "Lost",
        "Metro", "Snow", "Seaside", "Luncheon", "Ruined", "Bowser's",
        "Moon", "Mushroom", "Dark Side", "Darker Side",
    }
    actual = {e["kingdom"] for e in _entries()}
    extra = actual - known
    assert not extra, f"unexpected kingdoms in extraction: {extra}"
