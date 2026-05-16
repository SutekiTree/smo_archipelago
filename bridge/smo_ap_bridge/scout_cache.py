"""Pre-computed map of `location_id -> (item_id, recipient_slot_idx)`.

Channel A (M6 phase A.5) needs to know, the moment Mario collects a moon,
what item that location *is going to* produce and which slot will receive
it — so the in-game cutscene label can read e.g. "Sent Cap Power Moon ->
Player3" without waiting for the AP server round-trip.

Archipelago's `LocationScouts` request returns exactly that info in
`LocationInfo` packets (`NetworkItem(item, location, player, flags)`,
where for scout responses `player` is the *receiving* player). The bridge
issues one bulk `LocationScouts` for all SMO locations on `Connected`,
then absorbs each `LocationInfo` packet into the cache.

The Switch never sees this cache; only the bridge consults it when
synthesizing `MoonLabelMsg` text.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Iterable

log = logging.getLogger(__name__)

# Defensive chunk size for LocationScouts. AP servers accept arbitrarily
# many locations in one request, but bucketing keeps individual ws frames
# below the deflate sweet spot and limits damage from a malformed reply.
SCOUT_CHUNK_SIZE = 200


@dataclass(frozen=True)
class ScoutInfo:
    item_id: int
    recipient: int  # slot index (NetworkItem.player for LocationInfo replies)
    flags: int = 0


class ScoutCache:
    """In-memory `location_id -> ScoutInfo` cache.

    Populated incrementally as `LocationInfo` packets arrive (one per
    location). `lookup` returns None before the entry is known, so
    early collects (within the few hundred ms before the cache warms)
    degrade gracefully to vanilla cutscene labels.

    Re-warming on reconnect is the caller's job: bridge calls
    `request_scout(...)` from its `Connected` handler.
    """

    def __init__(self) -> None:
        self._by_loc: dict[int, ScoutInfo] = {}

    def absorb(self, location: int, item: int, recipient: int, flags: int = 0) -> None:
        """Record a scouted location. Idempotent — later writes win."""
        self._by_loc[int(location)] = ScoutInfo(int(item), int(recipient), int(flags))

    def absorb_network_item(self, ni: Any) -> None:
        """Convenience: accept anything with `.item/.location/.player[/.flags]`
        attributes (NetworkItem NamedTuple) or a dict with the same keys."""
        if hasattr(ni, "location"):
            self.absorb(ni.location, ni.item, ni.player, getattr(ni, "flags", 0))
        elif isinstance(ni, dict):
            self.absorb(ni["location"], ni["item"], ni["player"], ni.get("flags", 0))
        else:
            raise TypeError(f"unsupported network item: {type(ni).__name__}")

    def absorb_location_info(self, args: dict) -> int:
        """Drain a `LocationInfo` AP packet's `locations` array. Returns count."""
        n = 0
        for ni in args.get("locations") or ():
            try:
                self.absorb_network_item(ni)
                n += 1
            except (KeyError, TypeError, AttributeError) as e:
                log.warning("malformed scout entry: %r (%s)", ni, e)
        return n

    def lookup(self, location_id: int) -> ScoutInfo | None:
        return self._by_loc.get(int(location_id))

    def __contains__(self, location_id: int) -> bool:
        return int(location_id) in self._by_loc

    def __len__(self) -> int:
        return len(self._by_loc)

    def clear(self) -> None:
        self._by_loc.clear()


async def request_scout(
    ctx: Any,
    location_ids: Iterable[int],
    cache: ScoutCache | None = None,
) -> int:
    """Issue a LocationScouts request for the given location ids.

    If `cache` is provided, locations already present are skipped (so
    reconnect re-warm only fetches the new ones — though typically the
    cache is cleared first on disconnect, so this is just defense).
    Returns the number of locations actually requested.
    """
    ids = [int(i) for i in location_ids if i and int(i) > 0]
    if cache is not None:
        ids = [i for i in ids if i not in cache]
    if not ids:
        return 0
    sent = 0
    for i in range(0, len(ids), SCOUT_CHUNK_SIZE):
        chunk = ids[i : i + SCOUT_CHUNK_SIZE]
        await ctx.send_msgs([{"cmd": "LocationScouts", "locations": chunk}])
        sent += len(chunk)
    log.info("scout: requested %d locations in %d chunk(s)",
             sent, (sent + SCOUT_CHUNK_SIZE - 1) // SCOUT_CHUNK_SIZE)
    return sent
