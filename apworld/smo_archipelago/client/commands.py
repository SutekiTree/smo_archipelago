"""Pure command parsing for SMOClient's `/`-commands.

`parse_command()` is the load-bearing function — pure input string ->
ParseResult dataclass. The Kivy GUI's ClientCommandProcessor (in
context.py) calls each `_cmd_*` method, which delegates to this parser.

Item injection used to live here (`/grant`, `/capture`, `/kingdom`),
but those duplicated what the AP server's `/send` console already
does for every apworld. After they were removed, the AP-received
path in `context.py::_handle_ap_package` is the sole producer of
ItemMsgs. Use `/send <slot> <item name>` on the AP server console
to inject items during dev.

Surviving commands (`/smo_status`, `/inject_deathlink`) are debug
utilities, not item sends. Both are pure ClientCommandProcessor
methods in `context.py`; this module owns the shared `status`
parser they delegate to.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from .state import BridgeState

log = logging.getLogger(__name__)


HELP_TEXT = """\
SMO Client commands (type with leading /):
  /smo_status                       show client-side tracker state
  /warp [cascade|cap]               teleport Mario to a hub kingdom so he can
                                    escape a one-way kingdom (e.g. stuck in
                                    Bowser's without Pokio). Default: cascade.
                                    Pure teleport — never unlocks anything.
  /inject_deathlink [src] [cause]
                                    synthesize an inbound KillMsg straight
                                    to the Switch, bypassing AP (debug)

To inject items, use the AP server console:
  /send <slot> <item name>          e.g. /send Mario Cascade Kingdom Power Moon
"""


@dataclass
class ParseResult:
    """Outcome of parsing a single command line.

    Exactly one (or none) of `info`, `error`, `quit` is set.
    """
    info: str | None = None
    error: str | None = None
    quit: bool = False


def parse_command(line: str, state: BridgeState | None = None) -> ParseResult:
    """Pure parser — line -> action. Unit-testable without I/O."""
    s = line.strip()
    if not s:
        return ParseResult()  # silent no-op
    cmd = s.split(None, 1)[0].lower()

    if cmd in ("quit", "exit", "q"):
        return ParseResult(quit=True)
    if cmd in ("help", "?", "h"):
        return ParseResult(info=HELP_TEXT)
    if cmd == "status":
        if state is None:
            return ParseResult(info="status unavailable (no client state attached)")
        n_items = len(state.received_items)
        n_checks = len(state.checked_locations)
        n_caps = len(state.captures_unlocked)
        moons_by_k = ", ".join(
            f"{k}={v}" for k, v in sorted(state.moons_received_by_kingdom.items())
        ) or "(none)"
        last = ""
        if n_items > 0:
            evt = state.received_items[-1]
            last = (f"  last item: kind={evt.item.kind} kingdom={evt.item.kingdom!r}"
                    f" shine_id={evt.item.shine_id!r} cap={evt.item.cap!r}"
                    f" from={evt.sender!r}\n")
        return ParseResult(info=(
            f"received_items={n_items} (by kingdom: {moons_by_k})\n"
            f"checked_locations={n_checks}\n"
            f"captures_unlocked={n_caps}\n"
            + last
        ))

    return ParseResult(error=f"unknown command: {cmd!r}; type `help`")
