"""Tests for bridge-side goal detection.

The "Defeat Bowser and Escape the Moon" location (locations.json `victory:
true`) is the canonical end-of-game signal. When the Switch reports its
collection via a moon-check, the bridge fires `report_goal()` exactly once.

This replaces the old Switch-side `EndingHook` on
`DemoPeachWedding::makeActorAlive` — that actor turned out to be a generic
"Peach in wedding dress on screen" actor (per OdysseyDecomp) used in the
Bowser's Kingdom kidnapping cutscene as well as the real Moon ending, so
the hook fired in the wrong place. Detecting at the apworld-location level
is robust against any cutscene/actor reuse.
"""

from __future__ import annotations

import json
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

from client.context import (  # noqa: E402
    MOON_NAME_ALIASES,
    SMOContext,
    VICTORY_LOCATION_NAME,
)
from client.datapackage import DataPackage  # noqa: E402
from client.maps import CaptureMap, ShineMap  # noqa: E402
from client.state import BridgeState  # noqa: E402


VICTORY_LOC_ID = 70001
NON_VICTORY_LOC_ID = 70002

# Switch-side raw IDs for the canonical victory Multi Moon. Nintendo's MSBT
# names it "Long Journey's End"; the apworld renames it for goal clarity,
# and the alias dict in context.py papers over the difference at lookup.
VICTORY_STAGE = "MoonWorldHomeStage"
VICTORY_OBJECT_ID = "MoonRockMoonWorld"  # stand-in; only the resolution matters
VICTORY_SHINE_UID = 42

# A non-goal moon used to assert we don't fire on every moon.
NON_VICTORY_STAGE = "CapWorldHomeStage"
NON_VICTORY_OBJECT_ID = "MoonOurFirst"


def _write_shine_map(tmp_path: Path) -> Path:
    """A two-entry shine_map: the victory moon (with Nintendo's MSBT name)
    and one ordinary moon (Our First Power Moon — the well-known fixture
    used elsewhere in the bridge tests)."""
    p = tmp_path / "shine_map.json"
    p.write_text(
        json.dumps([
            # Victory Multi Moon: shine_id is Nintendo's MSBT text. The
            # MOON_NAME_ALIASES table maps `"Moon: Long Journey's End"` ->
            # `"Defeat Bowser and Escape the Moon"` at lookup time.
            {
                "stage_name": VICTORY_STAGE,
                "object_id": VICTORY_OBJECT_ID,
                "shine_uid": VICTORY_SHINE_UID,
                "kingdom": "Moon",
                "shine_id": "Long Journey's End",
            },
            {
                "stage_name": NON_VICTORY_STAGE,
                "object_id": NON_VICTORY_OBJECT_ID,
                "kingdom": "Cap",
                "shine_id": "Our First Power Moon",
            },
        ]),
        encoding="utf-8",
    )
    return p


def _make_ctx(tmp_path: Path) -> SMOContext:
    state = BridgeState()
    shine_map = ShineMap(_write_shine_map(tmp_path))
    dp = DataPackage()
    # Hand-populate the apworld-location lookup. `report_check` only reads
    # `dp.location_name_to_id`; we don't need the categories tables here.
    dp.location_name_to_id[VICTORY_LOCATION_NAME] = VICTORY_LOC_ID
    dp.location_id_to_name[VICTORY_LOC_ID] = VICTORY_LOCATION_NAME
    dp.location_name_to_id["Cap: Our First Power Moon"] = NON_VICTORY_LOC_ID
    dp.location_id_to_name[NON_VICTORY_LOC_ID] = "Cap: Our First Power Moon"

    ctx = SMOContext(
        server_address=None,
        password=None,
        state=state,
        datapackage=dp,
        shine_map=shine_map,
        capture_map=CaptureMap(),
        # Suppress the scout-cache warmup in the Connected handler — it
        # would otherwise emit a LocationScouts in our test and complicate
        # the assertions.
        display_enabled=False,
    )
    ctx.colors.enabled = False
    return ctx


def _install_send_capture(ctx: SMOContext) -> list[dict]:
    """Replace ctx.send_msgs with a capturer that records each outbound
    AP command. Returns the list (mutated in place)."""
    captured: list[dict] = []

    async def fake_send_msgs(msgs: list[dict]) -> None:
        captured.extend(msgs)

    ctx.send_msgs = fake_send_msgs  # type: ignore[method-assign]
    return captured


# ---- sanity: the alias table is wired ---------------------------------


def test_moon_name_aliases_maps_nintendo_text_to_apworld_name():
    """The alias must point at the same canonical name `report_check`
    compares against — otherwise the goal trigger silently misfires."""
    assert MOON_NAME_ALIASES["Moon: Long Journey's End"] == VICTORY_LOCATION_NAME


# ---- core trigger behavior --------------------------------------------


@pytest.mark.asyncio
async def test_report_goal_fires_on_victory_moon_check(tmp_path: Path):
    ctx = _make_ctx(tmp_path)
    sent = _install_send_capture(ctx)

    loc_id = await ctx.report_check(
        kind="moon",
        stage_name=VICTORY_STAGE,
        object_id=VICTORY_OBJECT_ID,
        shine_uid=VICTORY_SHINE_UID,
    )

    assert loc_id == VICTORY_LOC_ID
    # We should see exactly two AP commands: the LocationChecks for the
    # moon, then the StatusUpdate{ClientGoal} fired by report_goal.
    cmds = [m["cmd"] for m in sent]
    assert cmds == ["LocationChecks", "StatusUpdate"]
    assert sent[0]["locations"] == [VICTORY_LOC_ID]
    assert sent[1]["status"] == 30  # ClientStatus.CLIENT_GOAL
    assert ctx._goal_reported is True


@pytest.mark.asyncio
async def test_report_goal_does_not_fire_on_other_moons(tmp_path: Path):
    ctx = _make_ctx(tmp_path)
    sent = _install_send_capture(ctx)

    loc_id = await ctx.report_check(
        kind="moon",
        stage_name=NON_VICTORY_STAGE,
        object_id=NON_VICTORY_OBJECT_ID,
    )

    assert loc_id == NON_VICTORY_LOC_ID
    cmds = [m["cmd"] for m in sent]
    assert cmds == ["LocationChecks"]  # no StatusUpdate
    assert ctx._goal_reported is False


@pytest.mark.asyncio
async def test_report_goal_is_idempotent_on_replay(tmp_path: Path):
    """A snapshot replay of the victory location must not re-fire goal
    even though the location reaches the bridge twice."""
    ctx = _make_ctx(tmp_path)
    sent = _install_send_capture(ctx)

    await ctx.report_check(
        kind="moon",
        stage_name=VICTORY_STAGE,
        object_id=VICTORY_OBJECT_ID,
        shine_uid=VICTORY_SHINE_UID,
    )
    await ctx.report_check(
        kind="moon",
        stage_name=VICTORY_STAGE,
        object_id=VICTORY_OBJECT_ID,
        shine_uid=VICTORY_SHINE_UID,
    )

    cmds = [m["cmd"] for m in sent]
    # First call: LocationChecks + StatusUpdate. Second call: dedup early-
    # return (loc already in locations_checked) and goal already latched.
    assert cmds == ["LocationChecks", "StatusUpdate"]


@pytest.mark.asyncio
async def test_connected_pre_arms_goal_when_already_checked(tmp_path: Path):
    """If the AP server reports the victory loc_id as already-checked at
    Connected time, the next victory replay must not re-fire goal.

    NOTE: in a real bridge process, `_handle_ap_package('Connected', ...)`
    first calls `_populate_datapackage_from_self()` which mirrors the AP
    server's id-allocation into `ctx.dp.location_name_to_id` — when the
    apworld is importable (test env included), this replaces any hand-
    populated test id with the real one (e.g. 14481151936 for the victory
    location). We work with the real id by reading it back after the
    populate runs, then re-driving the handler.
    """
    ctx = _make_ctx(tmp_path)
    sent = _install_send_capture(ctx)

    # First, let the handler run its `_populate_datapackage_from_self()`
    # so the dp reflects whatever id the AP-side id-allocation produced.
    # checked_locations is empty so the pre-arm is a no-op on this pass.
    await ctx._handle_ap_package("Connected", {"slot_data": {}})
    assert ctx._goal_reported is False  # no pre-arm yet
    sent.clear()

    # Now mark the (real) victory loc_id as already-checked and run the
    # handler again — this is the post-reconnect / replay shape.
    real_victory_id = ctx.dp.location_name_to_id[VICTORY_LOCATION_NAME]
    ctx.checked_locations.add(real_victory_id)
    await ctx._handle_ap_package("Connected", {"slot_data": {}})

    assert ctx._goal_reported is True, (
        f"pre-arm did not fire; victory_id={real_victory_id}, "
        f"in checked={real_victory_id in ctx.checked_locations}"
    )

    # A subsequent victory moon-check should still send a LocationChecks
    # (the bridge's local dedup set started empty), but NOT a StatusUpdate.
    sent.clear()
    await ctx.report_check(
        kind="moon",
        stage_name=VICTORY_STAGE,
        object_id=VICTORY_OBJECT_ID,
        shine_uid=VICTORY_SHINE_UID,
    )
    cmds = [m["cmd"] for m in sent]
    assert cmds == ["LocationChecks"]  # no StatusUpdate re-fire
