"""Tests for the LocationScouts cache used by Channel A label synthesis."""

from __future__ import annotations

import asyncio
from collections import namedtuple

import pytest

from smo_ap_bridge.scout_cache import ScoutCache, ScoutInfo, request_scout


# Minimal stand-in for AP's NetworkItem; the cache treats it duck-typed.
FakeNetItem = namedtuple("FakeNetItem", "item location player flags")


def test_absorb_and_lookup_returns_recipient_and_item():
    cache = ScoutCache()
    cache.absorb(location=14481151511, item=4242, recipient=3, flags=1)
    info = cache.lookup(14481151511)
    assert info == ScoutInfo(item_id=4242, recipient=3, flags=1)


def test_lookup_unknown_returns_none():
    cache = ScoutCache()
    assert cache.lookup(999) is None


def test_absorb_idempotent_last_writer_wins():
    cache = ScoutCache()
    cache.absorb(1, 10, 0)
    cache.absorb(1, 20, 5)
    info = cache.lookup(1)
    assert info is not None and info.item_id == 20 and info.recipient == 5


def test_absorb_network_item_namedtuple():
    cache = ScoutCache()
    cache.absorb_network_item(FakeNetItem(item=7, location=200, player=2, flags=0))
    assert cache.lookup(200) == ScoutInfo(7, 2, 0)


def test_absorb_network_item_dict():
    cache = ScoutCache()
    cache.absorb_network_item({"item": 7, "location": 200, "player": 2})
    assert cache.lookup(200) == ScoutInfo(7, 2, 0)


def test_absorb_location_info_packet_counts_and_skips_malformed():
    cache = ScoutCache()
    args = {"locations": [
        FakeNetItem(item=1, location=100, player=0, flags=0),
        FakeNetItem(item=2, location=101, player=1, flags=0),
        {"not_a_valid_entry": True},  # absorbed without `location` key → skipped
    ]}
    n = cache.absorb_location_info(args)
    assert n == 2
    assert 100 in cache and 101 in cache
    assert len(cache) == 2


def test_absorb_location_info_empty_packet():
    cache = ScoutCache()
    assert cache.absorb_location_info({}) == 0
    assert cache.absorb_location_info({"locations": []}) == 0


def test_clear_drops_all_entries():
    cache = ScoutCache()
    cache.absorb(1, 10, 0)
    cache.absorb(2, 20, 0)
    assert len(cache) == 2
    cache.clear()
    assert len(cache) == 0
    assert cache.lookup(1) is None


def test_request_scout_filters_already_cached():
    cache = ScoutCache()
    cache.absorb(1, 10, 0)
    cache.absorb(2, 20, 0)

    sent: list[list[dict]] = []

    class FakeCtx:
        async def send_msgs(self, msgs):
            sent.append(msgs)

    n = asyncio.run(request_scout(FakeCtx(), [1, 2, 3, 4], cache))
    assert n == 2  # 3 and 4 only
    assert len(sent) == 1
    assert sent[0][0]["cmd"] == "LocationScouts"
    assert sorted(sent[0][0]["locations"]) == [3, 4]


def test_request_scout_skips_zero_and_negative_ids():
    sent: list[list[dict]] = []

    class FakeCtx:
        async def send_msgs(self, msgs):
            sent.append(msgs)

    n = asyncio.run(request_scout(FakeCtx(), [0, -1, 5]))
    assert n == 1
    assert sent[0][0]["locations"] == [5]


def test_request_scout_no_ops_when_nothing_to_send():
    sent: list[list[dict]] = []

    class FakeCtx:
        async def send_msgs(self, msgs):
            sent.append(msgs)

    n = asyncio.run(request_scout(FakeCtx(), []))
    assert n == 0
    assert sent == []


def test_request_scout_chunks_large_request():
    from smo_ap_bridge import scout_cache as sc

    sent: list[list[dict]] = []

    class FakeCtx:
        async def send_msgs(self, msgs):
            sent.append(msgs)

    big = list(range(1, sc.SCOUT_CHUNK_SIZE * 2 + 5))
    n = asyncio.run(request_scout(FakeCtx(), big))
    assert n == len(big)
    assert len(sent) == 3
    assert sum(len(s[0]["locations"]) for s in sent) == len(big)
