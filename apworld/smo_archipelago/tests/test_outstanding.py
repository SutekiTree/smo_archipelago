"""Unit tests for the M6 phase D per-kingdom AP-credit balance tracking.

Covers `BridgeState.apply_grant` / `apply_deposit` / replace / dedup. The
end-to-end AP-data-store hydration path is tested via `test_switch_server`'s
new outstanding-handshake test; here we focus on the math + dedup
invariants only.
"""

from __future__ import annotations

from client.state import BridgeState


# ---------- apply_grant ----------

def test_apply_grant_starts_at_zero():
    s = BridgeState()
    assert s.apply_grant("Cap", 1) == 1
    assert s.apply_grant("Cap", 1) == 2
    assert s.apply_grant("Cap", 3) == 5  # Multi-Moon
    assert s.get_outstanding() == {"Cap": 5}


def test_apply_grant_keeps_kingdoms_independent():
    s = BridgeState()
    s.apply_grant("Cap", 2)
    s.apply_grant("Wooded", 3)
    s.apply_grant("Snow", 1)
    out = s.get_outstanding()
    assert out == {"Cap": 2, "Wooded": 3, "Snow": 1}


# ---------- apply_deposit ----------

def test_apply_deposit_clamps_at_zero():
    s = BridgeState()
    s.apply_grant("Cap", 2)
    assert s.apply_deposit("Cap", 1) == 1
    assert s.apply_deposit("Cap", 5) == 0  # over-spend clamps
    assert s.apply_deposit("Cap", 1) == 0  # still 0


def test_apply_deposit_does_not_leak_across_kingdoms():
    """The defining invariant: Wooded balance is unaffected when Mario
    deposits at Cap, even when Cap balance is exhausted."""
    s = BridgeState()
    s.apply_grant("Cap", 0)        # implicit: nothing in Cap
    s.apply_grant("Wooded", 3)
    s.apply_deposit("Cap", 5)
    out = s.get_outstanding()
    assert out["Wooded"] == 3
    assert out.get("Cap", 0) == 0


def test_apply_deposit_on_unseen_kingdom_is_noop():
    s = BridgeState()
    s.apply_deposit("Sand", 5)
    assert s.get_outstanding() == {"Sand": 0}


# ---------- replace_outstanding (AP-store hydration path) ----------

def test_replace_outstanding_wholesale_replaces():
    s = BridgeState()
    s.apply_grant("Cap", 5)
    s.apply_grant("Wooded", 2)
    s.replace_outstanding({"Cap": 1, "Snow": 4})
    out = s.get_outstanding()
    assert out == {"Cap": 1, "Snow": 4}
    assert "Wooded" not in out


def test_replace_outstanding_empty_resets():
    s = BridgeState()
    s.apply_grant("Cap", 5)
    s.replace_outstanding({})
    assert s.get_outstanding() == {}


# ---------- should_skip_deposit (idempotency) ----------

def test_should_skip_deposit_advances_high_water_mark():
    s = BridgeState()
    assert not s.should_skip_deposit(1)
    assert not s.should_skip_deposit(2)
    assert not s.should_skip_deposit(3)


def test_should_skip_deposit_repeated_seq_skipped():
    s = BridgeState()
    assert not s.should_skip_deposit(5)
    assert s.should_skip_deposit(5)
    # And anything <= the high-water mark:
    assert s.should_skip_deposit(4)
    assert s.should_skip_deposit(1)


def test_should_skip_deposit_higher_seq_still_works_after_skip():
    s = BridgeState()
    assert not s.should_skip_deposit(5)
    assert s.should_skip_deposit(5)
    assert not s.should_skip_deposit(6)  # fresh seq advances
    assert s.should_skip_deposit(6)


def test_should_skip_deposit_zero_or_negative_treated_as_skip():
    """seq=0 is the "absent" sentinel — never apply, but don't poison the
    high-water mark either."""
    s = BridgeState()
    assert s.should_skip_deposit(0)
    assert s.should_skip_deposit(-1)
    # Mark unchanged:
    assert not s.should_skip_deposit(1)


def test_reset_deposit_session_lets_fresh_seqs_apply_again():
    """SaveLoadHook / new HELLO drops the high-water mark so a brand-new
    Switch session starting at seq=1 isn't filtered against an old
    session's marks."""
    s = BridgeState()
    s.should_skip_deposit(10)
    assert s.should_skip_deposit(5)  # below high-water mark
    s.reset_deposit_session()
    assert not s.should_skip_deposit(1)
    assert not s.should_skip_deposit(2)


# ---------- received_items_index (cross-restart dedup) ----------

def test_received_items_index_defaults_to_zero():
    s = BridgeState()
    assert s.get_received_items_index() == 0


def test_set_received_items_index_clamps_negative_to_zero():
    """Defensive: a corrupt AP data store value or arithmetic mistake
    should not poison the high-water mark into a negative state."""
    s = BridgeState()
    s.set_received_items_index(5)
    assert s.get_received_items_index() == 5
    s.set_received_items_index(-3)
    assert s.get_received_items_index() == 0


def test_set_received_items_index_accepts_increases_and_decreases():
    """The setter doesn't enforce monotonicity — the *caller* (context.py)
    uses max(old, new) when advancing. The setter just stores what it's
    given so hydration from AP store can also pull down a value if some
    out-of-band reset happened."""
    s = BridgeState()
    s.set_received_items_index(10)
    s.set_received_items_index(3)
    assert s.get_received_items_index() == 3


# ---------- get_kingdom_lifetime_received (M7 Path A gate source) ----------
#
# The 2026-05-18 regression: post-Sand fork showed two Lake kingdoms after
# Mario deposited at Lake's Odyssey. Cause: KingdomOrderGate read the
# undeposited balance (ap_moons_kingdom[Lake]), which the deposit had just
# debited below the 8-moon threshold. The fix moved the gate onto a
# lifetime counter that never decrements.

def test_lifetime_received_starts_at_zero_for_unseen_kingdom():
    s = BridgeState()
    assert s.get_kingdom_lifetime_received("Lake") == 0
    assert s.get_kingdom_lifetime_received("Snow") == 0


def test_lifetime_received_counts_power_moons_as_one_each():
    from client.protocol import ItemRef
    from client.state import ItemEvent
    s = BridgeState()
    for _ in range(3):
        s.add_received_item(ItemEvent(
            item=ItemRef(kind="moon", kingdom="Lake", shine_id="Power Moon"),
        ))
    assert s.get_kingdom_lifetime_received("Lake") == 3


def test_lifetime_received_weighs_multi_moon_as_three():
    """Matches `KingdomMoons` in hooks/Rules.py and the Switch's
    moonGrantAmount helper, so the gate threshold (e.g. 8 effective moons
    for Wooded) is apples-to-apples."""
    from client.protocol import ItemRef
    from client.state import ItemEvent
    s = BridgeState()
    s.add_received_item(ItemEvent(
        item=ItemRef(kind="moon", kingdom="Snow", shine_id="Multi-Moon"),
    ))
    assert s.get_kingdom_lifetime_received("Snow") == 3
    s.add_received_item(ItemEvent(
        item=ItemRef(kind="moon", kingdom="Snow", shine_id="Power Moon"),
    ))
    assert s.get_kingdom_lifetime_received("Snow") == 4


def test_lifetime_received_does_not_decay_on_deposit():
    """The regression-defining invariant: depositing at a kingdom's
    Odyssey decrements the *balance* but must NOT touch the lifetime
    counter the kingdom-order gate consumes."""
    from client.protocol import ItemRef
    from client.state import ItemEvent
    s = BridgeState()
    for _ in range(8):
        s.add_received_item(ItemEvent(
            item=ItemRef(kind="moon", kingdom="Lake", shine_id="Power Moon"),
        ))
        s.apply_grant("Lake", 1)
    # Mario fuels Lake's Odyssey to leave (debits the balance to 0).
    s.apply_deposit("Lake", 8)
    assert s.get_outstanding().get("Lake", 0) == 0   # balance drained
    assert s.get_kingdom_lifetime_received("Lake") == 8  # lifetime intact


def test_lifetime_received_ignores_non_moon_items():
    """Capture and other items must not show up in the lifetime moon count
    (they don't satisfy KingdomMoons in hooks/Rules.py either)."""
    from client.protocol import ItemRef
    from client.state import ItemEvent
    s = BridgeState()
    s.add_received_item(ItemEvent(
        item=ItemRef(kind="capture", kingdom="Lake", cap="Cheep Cheep"),
    ))
    s.add_received_item(ItemEvent(
        item=ItemRef(kind="other", kingdom="Lake"),
    ))
    assert s.get_kingdom_lifetime_received("Lake") == 0
