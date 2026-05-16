"""Tests for ColorsConfig (AP-classification -> palette mapping) and the
BridgeState shine-palette accessors used by the scout-replay path."""

from __future__ import annotations

from smo_ap_bridge.config import ColorsConfig
from smo_ap_bridge.state import BridgeState


def test_colors_config_defaults_are_distinct():
    """Defaults must give each non-filler classification a unique palette
    index so they're visually distinguishable out of the box."""
    c = ColorsConfig()
    indices = {c.progression, c.useful, c.trap}
    assert len(indices) == 3
    # Filler (0) is the "no override" sentinel; it's fine for it to share a
    # value with the trap default conceptually, but defaults shouldn't.
    assert c.filler == 0


def test_for_classification_known_values():
    c = ColorsConfig(progression=1, useful=2, trap=3, filler=0)
    assert c.for_classification("progression") == 1
    assert c.for_classification("useful") == 2
    assert c.for_classification("trap") == 3
    assert c.for_classification("filler") == 0


def test_for_classification_unknown_falls_through_to_filler():
    c = ColorsConfig(progression=1, useful=2, trap=3, filler=7)
    assert c.for_classification("") == 7
    assert c.for_classification("bogus") == 7


def test_state_shine_palette_round_trip():
    s = BridgeState()
    assert s.all_shine_palette() == {}
    s.set_shine_palette({12: 1, 47: 3})
    assert s.all_shine_palette() == {12: 1, 47: 3}


def test_state_shine_palette_replace_not_merge():
    """set_shine_palette replaces the table — each LocationInfo reply is
    the authoritative full picture for the seed."""
    s = BridgeState()
    s.set_shine_palette({12: 1, 47: 3})
    s.set_shine_palette({100: 2})
    assert s.all_shine_palette() == {100: 2}


def test_state_shine_palette_returns_copy():
    """Mutating the returned dict must not affect bridge state."""
    s = BridgeState()
    s.set_shine_palette({1: 1})
    out = s.all_shine_palette()
    out[999] = 999
    assert 999 not in s.all_shine_palette()
