"""Unit tests for the SMOClient command parser.

Covers the pure `parse_command` function — no asyncio, no GUI. Item
injection commands (`/grant`, `/capture`, `/kingdom`) were removed
once the AP-received path was fixed to carry `name` over the wire;
use `/send <slot> <item>` on the AP server console instead. The
surviving commands here are debug utilities.
"""

from __future__ import annotations

import pytest

from client.commands import parse_command
from client.state import BridgeState


@pytest.fixture
def state() -> BridgeState:
    return BridgeState()


def test_empty_line_is_noop(state):
    r = parse_command("", state)
    assert r.error is None and r.info is None and not r.quit


def test_whitespace_only_is_noop(state):
    r = parse_command("   \t  ", state)
    assert r.error is None and r.info is None


def test_help_command(state):
    r = parse_command("help", state)
    assert r.info is not None
    assert "smo_status" in r.info
    assert "inject_deathlink" in r.info
    assert "/send" in r.info  # points users at the AP-server console


def test_help_alias_h(state):
    r = parse_command("h", state)
    assert r.info is not None and "smo_status" in r.info


def test_quit(state):
    assert parse_command("quit", state).quit
    assert parse_command("exit", state).quit
    assert parse_command("q", state).quit
    assert parse_command("QUIT", state).quit  # case-insensitive command


def test_unknown_command(state):
    r = parse_command("foobar arg", state)
    assert r.error is not None and "foobar" in r.error


def test_removed_grant_command_is_unknown(state):
    """`/grant` is gone — use `/send <slot> <item>` on the AP server console."""
    r = parse_command("grant Cascade Kingdom Power Moon", state)
    assert r.error is not None and "grant" in r.error


def test_removed_capture_command_is_unknown(state):
    r = parse_command("capture Goomba", state)
    assert r.error is not None and "capture" in r.error


def test_removed_kingdom_command_is_unknown(state):
    r = parse_command("kingdom Sand", state)
    assert r.error is not None and "kingdom" in r.error


def test_status_empty_state(state):
    r = parse_command("status", state)
    assert r.info is not None
    assert "received_items=0" in r.info
    assert "checked_locations=0" in r.info


def test_status_after_received_item(state):
    # Inject a moon item directly into state to simulate prior activity.
    from client.protocol import ItemRef
    from client.state import ItemEvent

    state.add_received_item(ItemEvent(
        item=ItemRef(kind="moon", kingdom="Cap", shine_id="Power Moon"),
        sender="P2",
    ))
    r = parse_command("status", state)
    assert "received_items=1" in r.info
    assert "Cap=1" in r.info
    assert "Power Moon" in r.info
