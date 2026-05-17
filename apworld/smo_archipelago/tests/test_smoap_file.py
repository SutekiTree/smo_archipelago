"""Tests for `_setup.smoap_file` — the .smoap-file format that triggers
the first-run wizard or pre-fills SMOClient on subsequent runs."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from _setup.smoap_file import (
    GAME_NAME,
    SMOAP_SCHEMA_VERSION,
    SmoapFile,
    parse_smoap,
    smoap_to_launch_args,
)


def test_round_trip_minimal(tmp_path: Path) -> None:
    """A fresh-AP-gen .smoap with only the slot name round-trips losslessly."""
    s = SmoapFile(slot_name="Mario")
    p = tmp_path / "Mario_P1.smoap"
    s.write(p)

    parsed = parse_smoap(p)
    assert parsed.slot_name == "Mario"
    assert parsed.game == GAME_NAME
    assert parsed.version == SMOAP_SCHEMA_VERSION
    assert parsed.server_address == ""
    assert parsed.password == ""


def test_round_trip_all_fields(tmp_path: Path) -> None:
    s = SmoapFile(
        slot_name="Luigi",
        seed_name="ABCD1234EFGH5678",
        server_address="archipelago.gg:38281",
        password="hunter2",
    )
    p = tmp_path / "Luigi_P2.smoap"
    s.write(p)

    parsed = parse_smoap(p)
    assert parsed.slot_name == "Luigi"
    assert parsed.seed_name == "ABCD1234EFGH5678"
    assert parsed.server_address == "archipelago.gg:38281"
    assert parsed.password == "hunter2"


def test_human_readable_field_order(tmp_path: Path) -> None:
    """A human inspecting the .smoap should see `game` and `version` first
    so they can tell what kind of file it is."""
    s = SmoapFile(slot_name="Mario")
    p = tmp_path / "x.smoap"
    s.write(p)

    text = p.read_text(encoding="utf-8")
    game_pos = text.index("game")
    version_pos = text.index("version")
    slot_pos = text.index("slot_name")
    assert game_pos < slot_pos
    assert version_pos < slot_pos


def test_rejects_wrong_game() -> None:
    bad = json.dumps({
        "game": "A Link to the Past",
        "version": 1,
        "slot_name": "Link",
    })
    with pytest.raises(ValueError, match="not for"):
        parse_smoap(bad)


def test_rejects_missing_slot() -> None:
    bad = json.dumps({
        "game": GAME_NAME,
        "version": 1,
        "slot_name": "",
    })
    with pytest.raises(ValueError, match="slot_name"):
        parse_smoap(bad)


def test_rejects_missing_version() -> None:
    bad = json.dumps({
        "game": GAME_NAME,
        "slot_name": "Mario",
    })
    with pytest.raises(ValueError, match="version"):
        parse_smoap(bad)


def test_rejects_future_version() -> None:
    """A .smoap from a future client should refuse to load, not silently
    drop fields the older client doesn't know how to interpret."""
    bad = json.dumps({
        "game": GAME_NAME,
        "version": SMOAP_SCHEMA_VERSION + 5,
        "slot_name": "Mario",
    })
    with pytest.raises(ValueError, match="newer"):
        parse_smoap(bad)


def test_rejects_non_json() -> None:
    with pytest.raises(ValueError, match="invalid JSON"):
        parse_smoap('{this is not json')


def test_ignores_unknown_fields() -> None:
    """Forward-compat: a future .smoap with extra fields should still load
    on an older client as long as game+version are within range."""
    forward = json.dumps({
        "game": GAME_NAME,
        "version": 1,
        "slot_name": "Mario",
        "future_field": {"nested": [1, 2, 3]},
    })
    parsed = parse_smoap(forward)
    assert parsed.slot_name == "Mario"


def test_launch_args_minimal() -> None:
    """`--name` is always present; `--connect` and `--password` are
    skipped when their .smoap field is empty."""
    s = SmoapFile(slot_name="Mario")
    assert smoap_to_launch_args(s) == ["--name", "Mario"]


def test_launch_args_with_server_and_password() -> None:
    s = SmoapFile(
        slot_name="Luigi",
        server_address="localhost:38281",
        password="p4ss",
    )
    args = smoap_to_launch_args(s)
    assert args == [
        "--name", "Luigi",
        "--connect", "localhost:38281",
        "--password", "p4ss",
    ]


def test_parse_raw_json_string() -> None:
    """`parse_smoap` should accept JSON text directly (not just a path) so
    tests + the wizard can construct + parse without bouncing off the fs."""
    s = SmoapFile(slot_name="Mario")
    parsed = parse_smoap(s.to_json())
    assert parsed.slot_name == "Mario"
