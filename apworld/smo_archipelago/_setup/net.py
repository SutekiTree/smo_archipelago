"""LAN-IP autodetect for the Bridge-PC-IP wizard page.

The setup wizard pre-fills the Bridge IP field with whatever
`detect_lan_ip()` returns, so the user just confirms in the common case
(single ethernet/wifi adapter on a typical home LAN). They can still
override — the wizard's text field is editable.

The "right" IP here is the one the Switch will be able to reach. On a
typical home LAN that's the same as the IP a UDP socket bound for an
arbitrary external host would use — that's what we probe for. We do NOT
actually send anything; the connect() on a UDP socket only sets the kernel
routing table entry and lets us read back the local end.
"""

from __future__ import annotations

import socket


# Use a likely-routable but not-must-respond destination. We don't send
# packets; `connect()` on UDP only triggers kernel route resolution.
# 8.8.8.8 is Google DNS — a stable, well-known public IP. Port number
# doesn't matter (no packets go out).
_PROBE_HOST = "8.8.8.8"
_PROBE_PORT = 80

# Fallback when route resolution fails (no network, all interfaces down).
_LOOPBACK = "127.0.0.1"


def detect_lan_ip() -> str:
    """Best-effort LAN IP for prefilling the wizard's Bridge-IP field.

    Returns "127.0.0.1" when no usable interface is available — useful as
    a default for Ryujinx-on-same-host development without forcing the
    user to look up their adapter IP. The user can always override.
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # connect() on UDP just primes the kernel routing table; no packet
        # leaves the wire. The local end is then resolved against whatever
        # interface the kernel would route the packet through.
        s.connect((_PROBE_HOST, _PROBE_PORT))
        ip, _port = s.getsockname()
        if ip and not ip.startswith("0."):
            return ip
        return _LOOPBACK
    except OSError:
        return _LOOPBACK
    finally:
        s.close()


def is_plausible_ipv4(s: str) -> bool:
    """Very loose IPv4 validation for the wizard's text-field gate.

    Accepts `"a.b.c.d"` where each octet is 0-255. Doesn't try to validate
    reachability or topology — the user knows their own LAN better than we
    do.
    """
    if not s:
        return False
    parts = s.split(".")
    if len(parts) != 4:
        return False
    for p in parts:
        if not p or not p.isdigit():
            return False
        n = int(p)
        if n < 0 or n > 255:
            return False
    return True
