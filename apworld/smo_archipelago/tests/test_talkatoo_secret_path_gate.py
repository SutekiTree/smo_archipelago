"""Regression test for the Talkatoo% cross-kingdom Secret Path gate.

Two "Secret Path" warp-painting moons are NAMED after their destination
kingdom (their ``<Kingdom>:`` prefix, which the bridge buckets the Talkatoo
window by) but are PHYSICALLY collected in an earlier kingdom's painting
room:

    "Metro: Secret Path to New Donk City!"    -> collected in Sand,   named by Metro
    "Luncheon: Secret Path to Mount Volbono!" -> collected in Wooded, named by Luncheon

In Talkatoo% mode a moon is only collectable once its naming kingdom's
Talkatoo names it, so these two must NOT be in logic until the naming
kingdom is reachable -- a constraint their earlier collection region does
not impose. ``hooks/Rules.py::TalkatooReach`` adds it, gated on
``talkatoo_mode``. This test pins that behavior: off Talkatoo% the moon is
reachable as soon as its (earlier) source kingdom + capture are, on
Talkatoo% it is blocked until the naming kingdom is reachable.

The check builds a real SMO world and evaluates the actual location access
rules under crafted CollectionStates. Like the other live-AP tests it needs
``vendor/Archipelago`` checked out + AP pip deps installed, so it is skipped
unless ``SMOAP_LIVE_AP=1``. It runs the world build in a SUBPROCESS so the
pytest process never imports Archipelago (see conftest.py for why that
matters).
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
AP_ROOT = REPO / "vendor" / "Archipelago"
INSTALL_SCRIPT = REPO / "scripts" / "install_apworld.py"

pytestmark = pytest.mark.skipif(
    os.environ.get("SMOAP_LIVE_AP") != "1",
    reason="set SMOAP_LIVE_AP=1 to run the Talkatoo Secret Path gate test "
           "(requires vendor/Archipelago checkout + AP pip deps installed)",
)


# Child program: builds the SMO world twice (Talkatoo off / on), evaluates
# the two moons' real access rules under crafted item states, and exits
# non-zero with a message on the first mismatch. Runs in a clean subprocess
# with vendor/Archipelago on sys.path.
_CHILD = r'''
import os, sys, warnings
warnings.filterwarnings("ignore")
AP = sys.argv[1]
sys.path.insert(0, AP)
os.chdir(AP)

from BaseClasses import CollectionState
from worlds.AutoWorld import AutoWorldRegister
from test.general import setup_multiworld

WT = AutoWorldRegister.world_types["Spicy Meatball Overdrive"]
METRO = "Metro: Secret Path to New Donk City!"
LUNCHEON = "Luncheon: Secret Path to Mount Volbono!"

def fail(msg):
    print("FAIL: " + msg)
    raise SystemExit(1)

def build(talkatoo):
    return setup_multiworld(
        WT,
        options={"talkatoo_mode": 1 if talkatoo else 0, "capturesanity": 1},
        seed=20260516,
    )

def state(mw, counts):
    st = CollectionState(mw)
    for name, n in counts.items():
        for _ in range(n):
            st.collect(mw.worlds[1].create_item(name), prevent_sweep=True)
    st.update_reachable_regions(1)
    return st

def region_reachable(mw, st, name):
    return mw.get_region(name, 1).can_reach(st)

def loc_reachable(mw, st, name):
    return mw.get_location(name, 1).can_reach(st)

# --- Metro: reach Sand (>=5 Cascade moons) + Bullet Bill, but NOT Metro ---
METRO_EARLY = {"Cascade Kingdom Power Moon": 6, "Bullet Bill": 1}
for talk in (False, True):
    mw = build(talk)
    st = state(mw, METRO_EARLY)
    # Preconditions: source kingdom reachable, naming kingdom not. If the
    # region graph shifts under us, fail loudly instead of passing silently.
    if not region_reachable(mw, st, "Sand Kingdom"):
        fail("precondition: Sand Kingdom should be reachable with 6 Cascade moons")
    if region_reachable(mw, st, "Metro Kingdom"):
        fail("precondition: Metro Kingdom should NOT be reachable in METRO_EARLY")
    got = loc_reachable(mw, st, METRO)
    want = (not talk)  # off -> reachable (early painting); on -> blocked
    if got != want:
        fail(f"{METRO} talkatoo={talk}: reachable={got}, expected {want}")

# --- Luncheon: reach Wooded (Cascade5/Sand16/Lake8) + Uproot, but NOT Luncheon ---
LUNCHEON_EARLY = {"Cascade Kingdom Power Moon": 6, "Sand Kingdom Power Moon": 16,
                  "Lake Kingdom Power Moon": 8, "Uproot": 1, "Sherm": 1}
for talk in (False, True):
    mw = build(talk)
    st = state(mw, LUNCHEON_EARLY)
    if not region_reachable(mw, st, "Wooded Kingdom"):
        fail("precondition: Wooded Kingdom should be reachable in LUNCHEON_EARLY")
    if region_reachable(mw, st, "Luncheon Kingdom"):
        fail("precondition: Luncheon Kingdom should NOT be reachable in LUNCHEON_EARLY")
    got = loc_reachable(mw, st, LUNCHEON)
    want = (not talk)
    if got != want:
        fail(f"{LUNCHEON} talkatoo={talk}: reachable={got}, expected {want}")

# --- On Talkatoo%, both unblock once every item (so the naming kingdom) is owned ---
mw = build(True)
st_all = CollectionState(mw)
for it in mw.get_items():
    if it.player == 1:
        st_all.collect(it, prevent_sweep=True)
st_all.update_reachable_regions(1)
for m in (METRO, LUNCHEON):
    if not loc_reachable(mw, st_all, m):
        fail(f"{m} talkatoo=on: should be reachable once all items (naming kingdom) are owned")

print("OK")
'''


def _install_apworld():
    result = subprocess.run(
        [sys.executable, str(INSTALL_SCRIPT)],
        capture_output=True, text=True, check=False,
    )
    if result.returncode != 0:
        pytest.fail(f"install_apworld.py failed:\n{result.stdout}\n{result.stderr}")


def test_talkatoo_secret_path_gate():
    """Metro/Luncheon Secret Path moons flip from reachable (Talkatoo off)
    to blocked-until-naming-kingdom (Talkatoo on), and unblock once that
    kingdom is reached."""
    if not (AP_ROOT / "BaseClasses.py").exists():
        # Populated only in a full checkout (e.g. the main clone / CI); a
        # git worktree typically has the submodule dir but not its contents.
        pytest.skip(f"vendor/Archipelago not populated at {AP_ROOT}")
    _install_apworld()
    result = subprocess.run(
        [sys.executable, "-c", _CHILD, str(AP_ROOT)],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0 and "OK" in result.stdout, (
        f"world-build check failed:\n{result.stdout}\n{result.stderr}"
    )
