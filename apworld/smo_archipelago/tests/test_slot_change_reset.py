"""Tests for slot-change handling on AP reconnect.

Regression: prior to this fix, `BridgeState.received_items` was
initialized once in `__init__` and never cleared across Connects. On a
same-process reconnect to a DIFFERENT slot, AP replays the new slot's
full history with index=0 — and the position-based dedup in
`SMOContext._process_received_items` (`pos < initial_mirror_len`)
silently swallowed every item at positions 0..prev_slot_count-1.
Observed live: after swapping slots, captures_unlocked stayed frozen
at whatever the previous slot had received (Shiverian Racer + Zipper
from the original Talkatoo seed), and relaunching SMOClient was the
only way to recover because a fresh-process `received_items=[]` lets
the dedup correctly admit everything.

Fix: detect slot change in the Connected handler (prev `state.slot`
vs new `self.auth`) and clear per-slot bridge state via the new
`BridgeState.clear_received` helper. Same-slot reconnect must NOT
clear — that path relies on the mirror to suppress duplicate
side effects (double-Cappy, double moon credit) on AP's full-history
replay.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest


def _find_archipelago() -> Path | None:
    for parent in Path(__file__).resolve().parents:
        cand = parent / "vendor" / "Archipelago"
        if (cand / "CommonClient.py").exists():
            return cand
        worktrees = parent.parent
        if worktrees.name == "worktrees":
            main_cand = worktrees.parent.parent / "vendor" / "Archipelago"
            if (main_cand / "CommonClient.py").exists():
                return main_cand
    return None


_AP = _find_archipelago()
if _AP is not None and str(_AP) not in sys.path:
    sys.path.insert(0, str(_AP))

try:  # pragma: no cover
    import ModuleUpdate  # type: ignore[import-not-found]
    ModuleUpdate.update_ran = True
except ImportError:
    pass

pytest.importorskip(
    "CommonClient",
    reason="Archipelago checkout not present; init the vendor/Archipelago submodule.",
)

from client.context import SMOContext  # noqa: E402
from client.datapackage import DataPackage  # noqa: E402
from client.maps import CaptureMap, ShineMap  # noqa: E402
from client.protocol import ItemRef  # noqa: E402
from client.state import BridgeState, CheckEvent, ItemEvent  # noqa: E402


# ---- BridgeState.clear_received unit tests --------------------------------


def _seed_state_with_one_of_everything(s: BridgeState) -> None:
    """Populate every field clear_received() is responsible for, so the
    "after clear" assertions catch any field we forget to reset."""
    s.add_received_item(ItemEvent(
        item=ItemRef(kind="capture", cap="Killer"), sender="self",
    ))
    s.add_received_item(ItemEvent(
        item=ItemRef(kind="moon", kingdom="Cascade", shine_id="Power Moon"),
        sender="self",
    ))
    s.add_received_item(ItemEvent(
        item=ItemRef(kind="moon", kingdom="Cap", shine_id="Multi Moon",
                     shine_uid=999),
        sender="self",
    ))
    s.add_checked_location(CheckEvent(item=ItemRef(
        kind="moon", kingdom="Cap", shine_id="Our First Power Moon",
    )))
    s.set_shine_palette({100: 2, 101: 1})
    s.apply_pay_snapshot({"Cascade": 5})


def test_clear_received_zeros_every_per_slot_field():
    s = BridgeState()
    _seed_state_with_one_of_everything(s)

    # Sanity: state was actually seeded.
    assert s.received_items
    assert s.captures_unlocked
    assert s.moons_received_by_kingdom
    assert s.moons_checked_by_kingdom
    assert s.checked_locations
    assert s.shine_palette
    assert s.pay_shine_num_by_kingdom is not None

    s.clear_received()

    assert s.received_items == []
    assert s.captures_unlocked == set()
    assert s.moons_received_by_kingdom == {}
    assert s.moons_checked_by_kingdom == {}
    assert s.checked_locations == []
    assert s.shine_palette == {}
    assert s.pay_shine_num_by_kingdom is None


def test_clear_received_lets_dedup_admit_a_repeat_check():
    """After clear, the per-ItemRef dedup keyset is empty too — a
    subsequent add_checked_location with the same identity must be
    accepted as new (not silently dropped as 'already in
    _checked_keys')."""
    s = BridgeState()
    evt = CheckEvent(item=ItemRef(
        kind="moon", kingdom="Cap", shine_id="Our First Power Moon",
    ))
    assert s.add_checked_location(evt) is True
    assert s.add_checked_location(evt) is False  # dedup

    s.clear_received()

    # Same identity now admitted — keyset was cleared.
    evt2 = CheckEvent(item=ItemRef(
        kind="moon", kingdom="Cap", shine_id="Our First Power Moon",
    ))
    assert s.add_checked_location(evt2) is True


def test_clear_received_does_not_touch_non_slot_state():
    """Switch-registry, snapshot accumulator, last_messages, death_count
    are bridge-/Switch-side state with no AP-slot affinity. clear_received
    must leave them alone — otherwise a slot swap would drop the user's
    chat log + paired Switch device just because they typed a new slot
    name."""
    s = BridgeState()
    s.add_log("hello")
    s.bump_death_count()
    s.bump_death_count()
    s.register_switch("dev123", "192.168.1.50", mod_ver="0.1.0", smo_ver="1.0.0")
    s.set_active_switch("dev123")
    s.begin_snapshot(save_slot=0)
    s.add_snapshot_chunk_shines("CapWorldHomeStage", [
        {"object_id": "MoonA", "shine_uid": 1},
    ])

    s.clear_received()

    assert s.last_messages == ["hello"]
    assert s.death_count == 2
    assert s.get_active_switch() == "dev123"
    assert len(s.get_switches()) == 1
    # Snapshot accumulator survives a clear (it's per-Switch-connection,
    # not per-AP-slot — finishing the snapshot mid-clear would drop
    # legitimate Switch-side reconciliation entries).
    entries, _ = s.end_snapshot()
    assert len(entries) == 1


# ---- SMOContext slot-change wiring tests ----------------------------------


class _StubSwitch:
    """Minimal switch surface for Connected handler — None-able in tests."""

    def __init__(self) -> None:
        self.ap_states: list[str] = []
        self.capturesanity: list[bool] = []
        self.deathlink: list[bool] = []
        self.helloack_pushes = 0
        self.talkatoo_pushes: list[tuple[bool, dict]] = []
        self.drains = 0

    def set_capturesanity_enabled(self, enabled: bool) -> None:
        self.capturesanity.append(enabled)

    async def push_capturesanity_replay(self) -> None:
        pass

    def set_deathlink_enabled(self, enabled: bool) -> None:
        self.deathlink.append(enabled)

    async def push_deathlink_helloack(self) -> None:
        self.helloack_pushes += 1

    def set_talkatoo_pool(self, mode: bool, pool: dict) -> None:
        self.talkatoo_pushes.append((mode, pool))

    async def push_talkatoo_pool(self) -> None:
        pass

    async def send_ap_state(self, conn: str) -> None:
        self.ap_states.append(conn)

    async def drain_pending_snapshot(self) -> None:
        self.drains += 1


def _make_ctx(*, switch_connected: bool = False) -> tuple[SMOContext, BridgeState, _StubSwitch | None]:
    state = BridgeState()
    ctx = SMOContext(
        server_address=None,
        password=None,
        state=state,
        datapackage=DataPackage(),
        shine_map=ShineMap(),
        capture_map=CaptureMap(),
        display_enabled=False,  # skip scout warmup (would need a server)
    )
    # Disable colors too so the LocationScouts kick is skipped end-to-end.
    ctx.colors.enabled = False
    sw: _StubSwitch | None = None
    if switch_connected:
        sw = _StubSwitch()
        ctx.switch = sw  # type: ignore[assignment]
    return ctx, state, sw


@pytest.mark.asyncio
async def test_slot_change_clears_received_state():
    """User reconnects to a DIFFERENT slot in the same SMOClient process.
    The prior slot's received_items + derived counters must be wiped so
    the new slot's index-0 ReceivedItems replay isn't swallowed by the
    position-based dedup."""
    ctx, state, _sw = _make_ctx()

    # Seed prior slot's state directly (skips the full ReceivedItems path,
    # which would require a wired AP server — same effect).
    state.add_received_item(ItemEvent(
        item=ItemRef(kind="capture", cap="Shiverian Racer"), sender="self",
    ))
    state.add_received_item(ItemEvent(
        item=ItemRef(kind="capture", cap="Zipper"), sender="self",
    ))
    state.add_received_item(ItemEvent(
        item=ItemRef(kind="moon", kingdom="Cascade", shine_id="Power Moon"),
        sender="self",
    ))
    state.slot = "PlayerA"
    ctx._switch_reported_loc_ids.add(12345)
    ctx._goal_reported = True

    # Now reconnect to a new slot.
    ctx.auth = "PlayerB"
    await ctx._handle_ap_package("Connected", {"slot_data": {}})

    assert state.slot == "PlayerB"
    assert state.received_items == []
    assert state.captures_unlocked == set()
    assert state.moons_received_by_kingdom == {}
    assert ctx._switch_reported_loc_ids == set()
    assert ctx._goal_reported is False


@pytest.mark.asyncio
async def test_same_slot_reconnect_preserves_received_state():
    """AP often replays the full history on a reconnect blip (same slot).
    The dedup in _process_received_items needs `received_items` intact to
    suppress double-Cappy / double moon credit on those replays.
    clear_received must NOT fire on a same-slot reconnect."""
    ctx, state, _sw = _make_ctx()
    state.add_received_item(ItemEvent(
        item=ItemRef(kind="capture", cap="Killer"), sender="self",
    ))
    state.add_received_item(ItemEvent(
        item=ItemRef(kind="moon", kingdom="Cascade", shine_id="Power Moon"),
        sender="self",
    ))
    state.slot = "PlayerA"
    ctx._switch_reported_loc_ids.add(7777)
    ctx._goal_reported = True

    ctx.auth = "PlayerA"  # SAME slot
    await ctx._handle_ap_package("Connected", {"slot_data": {}})

    # State preserved.
    assert state.slot == "PlayerA"
    assert len(state.received_items) == 2
    assert state.captures_unlocked == {"Killer"}
    assert state.moons_received_by_kingdom == {"Cascade": 1}
    assert ctx._switch_reported_loc_ids == {7777}
    assert ctx._goal_reported is True


@pytest.mark.asyncio
async def test_first_connect_with_empty_prior_slot_does_not_clear():
    """Fresh launch: state.slot defaults to ''. First Connected must NOT
    treat this as a slot change (no prior state to wipe; clearing is a
    no-op semantically, but should be skipped to keep the log line off
    every first connect)."""
    ctx, state, _sw = _make_ctx()
    state.slot = ""  # default
    # Pre-seed something the clear would wipe IF wrongly invoked.
    state.add_received_item(ItemEvent(
        item=ItemRef(kind="capture", cap="Killer"), sender="self",
    ))

    ctx.auth = "PlayerA"
    await ctx._handle_ap_package("Connected", {"slot_data": {}})

    # State preserved (no slot-change clear fired) — first-connect path.
    assert state.slot == "PlayerA"
    assert len(state.received_items) == 1
    assert state.captures_unlocked == {"Killer"}


@pytest.mark.asyncio
async def test_slot_change_then_process_received_items_admits_new_history():
    """End-to-end behavior the regression is named after: after a slot
    change, the new slot's ReceivedItems batch starting at index=0 must
    actually be mirrored + side-effected (not silently dedup'd out)."""
    ctx, state, _sw = _make_ctx()

    # Prior slot received 3 items.
    state.add_received_item(ItemEvent(
        item=ItemRef(kind="capture", cap="Shiverian Racer"), sender="self",
    ))
    state.add_received_item(ItemEvent(
        item=ItemRef(kind="capture", cap="Zipper"), sender="self",
    ))
    state.add_received_item(ItemEvent(
        item=ItemRef(kind="moon", kingdom="Cascade", shine_id="Power Moon"),
        sender="self",
    ))
    state.slot = "PlayerA"

    # Slot change.
    ctx.auth = "PlayerB"
    await ctx._handle_ap_package("Connected", {"slot_data": {}})

    # Now simulate AP replaying the new slot's history. Set up the
    # datapackage so _parse_received_item can resolve item names.
    ctx.dp.item_id_to_name = {1: "Frog", 2: "Cap Power Moon"}
    ctx.dp.item_name_to_id = {v: k for k, v in ctx.dp.item_id_to_name.items()}

    # New slot's ReceivedItems batch, index=0 (would be swallowed
    # pre-fix because positions 0,1 < prev_mirror_len 3).
    await ctx._process_received_items({
        "index": 0,
        "items": [
            {"item": 1, "player": 0, "location": -1, "flags": 0},  # Frog capture
            {"item": 2, "player": 0, "location": -1, "flags": 0},  # Cap moon
        ],
    })

    # Pre-fix this would have stayed empty / partial. Post-fix the new
    # slot's items land.
    assert len(state.received_items) == 2
    received_names = sorted(e.item.name for e in state.received_items)
    assert received_names == ["Cap Power Moon", "Frog"]


@pytest.mark.asyncio
async def test_same_slot_reconnect_dedups_history_replay():
    """Pair to the slot-change test: confirm the dedup still works for
    same-slot reconnects so we don't regress the original Connect blip
    handling while fixing the slot-swap bug."""
    ctx, state, _sw = _make_ctx()
    ctx.dp.item_id_to_name = {1: "Frog"}
    ctx.dp.item_name_to_id = {v: k for k, v in ctx.dp.item_id_to_name.items()}

    # Original Connect on PlayerA — one item received at index=0.
    ctx.auth = "PlayerA"
    await ctx._handle_ap_package("Connected", {"slot_data": {}})
    await ctx._process_received_items({
        "index": 0,
        "items": [{"item": 1, "player": 0, "location": -1, "flags": 0}],
    })
    assert len(state.received_items) == 1

    # Reconnect blip — same slot, AP replays the full history.
    await ctx._handle_ap_package("Connected", {"slot_data": {}})
    await ctx._process_received_items({
        "index": 0,
        "items": [{"item": 1, "player": 0, "location": -1, "flags": 0}],
    })

    # Mirror did NOT grow — position-based dedup did its job.
    assert len(state.received_items) == 1
