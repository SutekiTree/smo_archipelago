"""Tests for SMOClientCommandProcessor — the `/`-command surface in
`context.py` — plus a regression test for the AP-server-issued ItemMsg
name-resolution path.

The pure parser is exercised in test_repl.py.

Gated on Archipelago availability (subclassing CommonContext requires
CommonClient on sys.path) — same pattern as test_deathlink.py.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_AP = Path(__file__).resolve().parents[3] / "vendor" / "Archipelago"
if _AP.exists() and str(_AP) not in sys.path:
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

from client.context import SMOContext, SMOClientCommandProcessor  # noqa: E402
from client.datapackage import DataPackage  # noqa: E402
from client.maps import CaptureMap, ShineMap  # noqa: E402
from client.protocol import ItemMsg  # noqa: E402
from client.state import BridgeState  # noqa: E402

_APWORLD_DATA = Path(__file__).resolve().parent.parent / "data"


class _StubSwitch:
    def __init__(self) -> None:
        self.items: list[ItemMsg] = []
        self.kills: list = []
        self.labels: list = []
        self.outstanding: list = []

    async def send_item(self, item: ItemMsg) -> None:
        self.items.append(item)

    async def send_kill(self, kill) -> None:
        self.kills.append(kill)

    async def send_moon_label(self, label) -> None:
        self.labels.append(label)

    async def send_outstanding(self, msg) -> None:
        # M6 phase D: context.py pushes the authoritative per-kingdom
        # balance to the Switch whenever a Moon item is granted (so
        # ap_moons_kingdom[bit] on the mod side stays in sync). Stub it
        # for tests that just observe send_item.
        self.outstanding.append(msg)


@pytest.mark.asyncio
async def test_cmd_inject_deathlink_routes_killmsg_to_switch():
    import asyncio
    ctx = SMOContext(
        server_address=None, password=None,
        state=BridgeState(),
        datapackage=DataPackage(),
        shine_map=ShineMap(),
        capture_map=CaptureMap(),
    )
    ctx.auth = "Mario"
    sw = _StubSwitch()
    ctx.switch = sw  # type: ignore[assignment]

    proc = SMOClientCommandProcessor(ctx)
    proc._cmd_inject_deathlink("Tester", "for science")
    await asyncio.sleep(0)

    assert len(sw.kills) == 1
    assert sw.kills[0].source == "Tester"
    assert sw.kills[0].cause == "for science"


@pytest.mark.asyncio
async def test_ap_received_item_carries_name_for_moon():
    """Regression: AP-issued moons must reach the Switch with their name.

    The bug: `ClassifiedItem.to_ref()` used to zero `name` for non-OTHER
    kinds, so MOON/CAPTURE/KINGDOM items arrived on the Switch with no
    `name` field (stripped by `_strip_none`) and rendered as `?` in-game.
    """
    import asyncio
    state = BridgeState()
    ctx = SMOContext(
        server_address=None, password=None,
        state=state,
        datapackage=DataPackage(apworld_data_dir=_APWORLD_DATA),
        shine_map=ShineMap(),
        capture_map=CaptureMap(),
    )
    ctx.auth = "Mario"
    sw = _StubSwitch()
    ctx.switch = sw  # type: ignore[assignment]

    # Pretend the AP DataPackage handshake completed.
    ctx.dp.item_id_to_name[42] = "Cascade Kingdom Power Moon"
    ctx.dp.item_name_to_id["Cascade Kingdom Power Moon"] = 42

    await ctx._handle_ap_package("ReceivedItems", {
        "items": [{"item": 42, "player": 0, "flags": 0}],
    })
    await asyncio.sleep(0)

    assert len(sw.items) == 1
    msg = sw.items[0]
    assert msg.kind == "moon"
    assert msg.kingdom == "Cascade"
    assert msg.shine_id == "Power Moon"
    assert msg.name == "Cascade Kingdom Power Moon"

    # Wire payload must include the name (not stripped as None).
    from client.protocol import encode
    wire = encode(msg).decode("utf-8")
    assert '"name":"Cascade Kingdom Power Moon"' in wire


def test_to_ref_preserves_name_for_all_kinds():
    """Pure unit-level guard against re-introducing the OTHER-only conditional."""
    from client.datapackage import ClassifiedItem
    from client.protocol import ItemKind

    for kind, kwargs in [
        (ItemKind.MOON, {"kingdom": "Cascade", "shine_id": "Power Moon"}),
        (ItemKind.CAPTURE, {"cap": "Goomba"}),
        (ItemKind.KINGDOM, {"kingdom": "Sand"}),
        (ItemKind.OTHER, {}),
    ]:
        ci = ClassifiedItem(kind=kind, name=f"test-{kind.value}", **kwargs)
        ref = ci.to_ref()
        assert ref.name == f"test-{kind.value}", (
            f"to_ref() dropped name for kind={kind.value!r}; "
            f"this is the AP-server `?`-display regression."
        )
