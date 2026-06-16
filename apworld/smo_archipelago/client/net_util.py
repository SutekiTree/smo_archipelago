"""Network helpers shared by the runtime client and the setup wizard.

`detect_lan_ip()` returns the local IP the kernel would use to reach an
arbitrary external host — i.e. the address a peer on the LAN can route
to. The DiscoveryResponder advertises this in its UDP replies so the
Switch always TCP-connects via a routable interface (even when the
probe arrived on loopback or broadcast).

Why loopback is poison in the discovery reply: when `detect_lan_ip()`
falls back to "127.0.0.1" (no routable LAN address found), the Switch
mod dials loopback. A real Switch can never reach the PC's loopback;
worse, Ryujinx's host-networking ManagedSocket binds its outgoing
socket to the configured network interface (a LAN IP), and a
LAN-bound socket cannot route to 127.0.0.1 — Windows rejects the
connect with WSAEADDRNOTAVAIL (10049), which surfaces on the Switch
side as a cryptic "address not valid in its context". So we work hard
to return a routable RFC-1918 address and treat loopback as a genuine
last resort.

`is_plausible_ipv4()` is a loose dotted-quad validator used by the
wizard's optional "manual override" field.
"""

from __future__ import annotations

import socket

_PROBE_HOST = "8.8.8.8"
_PROBE_PORT = 80

_LOOPBACK = "127.0.0.1"


def _is_private_ipv4(ip: str) -> bool:
    """True for an RFC-1918 private IPv4 (the only addresses a LAN peer
    like the Switch can route to). Excludes loopback, link-local, and
    public addresses."""
    parts = ip.split(".")
    if len(parts) != 4:
        return False
    try:
        a, b = int(parts[0]), int(parts[1])
    except ValueError:
        return False
    if a == 10:
        return True
    if a == 172 and 16 <= b <= 31:
        return True
    if a == 192 and b == 168:
        return True
    return False


def _private_ipv4_rank(ip: str) -> int:
    """Preference order when several private IPs exist and the route
    probe gave us nothing to disambiguate. 192.168/16 is the canonical
    home-LAN range; 172.16/12 next; 10/8 last because virtual adapters
    (VPN, WSL, Docker, Hyper-V) overwhelmingly squat there."""
    a = ip.split(".", 1)[0]
    if a == "192":
        return 0
    if a == "172":
        return 1
    return 2  # 10.x


def _enumerate_private_ipv4s() -> list[str]:
    """Every RFC-1918 IPv4 bound to this host, best-guess first.

    Fallback for when the route-probe trick can't run (no default route —
    e.g. an internet-less LAN). `getaddrinfo` over the hostname is
    dependency-free and covers the common multi-homed case."""
    found: set[str] = set()
    try:
        for info in socket.getaddrinfo(
            socket.gethostname(), None, socket.AF_INET
        ):
            ip = info[4][0]
            if _is_private_ipv4(ip):
                found.add(ip)
    except OSError:
        pass
    return sorted(found, key=lambda ip: (_private_ipv4_rank(ip), ip))


def detect_lan_ip() -> str:
    """Best-effort LAN IP — the address a LAN peer (the Switch) can route
    to. Strategy, in order:

      1. Route-resolution trick: UDP-`connect()` to a public host (no
         packet is sent; this only triggers kernel route resolution) and
         read back the local endpoint the kernel chose. Picks the
         interface with the default route — correct on any machine with
         internet.
      2. Fallback when (1) yields nothing usable (no default route): pick
         a private (RFC-1918) address bound to this host. Still routable
         for the Switch; loopback is NOT (see module docstring).
      3. "127.0.0.1" as a true last resort — only reachable by
         Ryujinx-on-same-host dev, never by a real Switch.
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect((_PROBE_HOST, _PROBE_PORT))
        ip, _port = s.getsockname()
        if ip and not ip.startswith("0.") and ip != _LOOPBACK:
            return ip
    except OSError:
        pass
    finally:
        s.close()

    private = _enumerate_private_ipv4s()
    if private:
        return private[0]

    return _LOOPBACK


def is_plausible_ipv4(s: str) -> bool:
    """Loose IPv4 validator — accepts `"a.b.c.d"` with each octet 0-255.

    Does not validate reachability; the wizard's manual-override field
    only needs to refuse obvious typos.
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
