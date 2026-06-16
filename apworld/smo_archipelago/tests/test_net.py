"""Tests for `_setup.net` — LAN-IP autodetect for the Bridge-IP wizard
page, and IPv4 input-validation helper."""

from __future__ import annotations

import pytest

from _setup.net import detect_lan_ip, is_plausible_ipv4
from client import net_util


def test_detect_lan_ip_returns_dotted_quad() -> None:
    """In any environment with at least loopback (i.e. every environment
    pytest can run in), detect_lan_ip should return a parseable IPv4."""
    ip = detect_lan_ip()
    assert is_plausible_ipv4(ip)


@pytest.mark.parametrize("ip", [
    "10.0.0.1", "10.5.0.2", "172.16.0.5", "172.31.255.254", "192.168.1.153",
])
def test_is_private_ipv4_accepts_rfc1918(ip: str) -> None:
    assert net_util._is_private_ipv4(ip)


@pytest.mark.parametrize("ip", [
    "127.0.0.1",      # loopback
    "169.254.1.1",    # link-local
    "8.8.8.8",        # public
    "172.15.0.1",     # just below the 172.16/12 block
    "172.32.0.1",     # just above
    "192.169.1.1",    # not 192.168/16
    "0.0.0.0",
    "garbage",
    "1.2.3",
])
def test_is_private_ipv4_rejects_non_rfc1918(ip: str) -> None:
    assert not net_util._is_private_ipv4(ip)


def test_private_ipv4_rank_prefers_192_over_172_over_10() -> None:
    ranked = sorted(
        ["10.5.0.2", "192.168.1.153", "172.16.0.5"],
        key=net_util._private_ipv4_rank,
    )
    assert ranked == ["192.168.1.153", "172.16.0.5", "10.5.0.2"]


def test_detect_lan_ip_uses_route_probe_when_available(monkeypatch) -> None:
    """Happy path: the UDP route probe yields a routable address — return
    it verbatim and never touch the enumeration fallback."""
    class _FakeSock:
        def connect(self, addr): pass
        def getsockname(self): return ("192.168.1.153", 12345)
        def close(self): pass

    monkeypatch.setattr(net_util.socket, "socket", lambda *a, **k: _FakeSock())
    monkeypatch.setattr(
        net_util, "_enumerate_private_ipv4s",
        lambda: pytest.fail("enumeration should not run when probe succeeds"),
    )
    assert net_util.detect_lan_ip() == "192.168.1.153"


def test_detect_lan_ip_falls_back_to_private_enum_on_no_route(monkeypatch) -> None:
    """No default route (probe raises OSError) — pick a private address
    from the interface enumeration rather than poisoning the discovery
    reply with loopback."""
    class _DeadSock:
        def connect(self, addr): raise OSError("network unreachable")
        def getsockname(self): raise AssertionError("unreachable")
        def close(self): pass

    monkeypatch.setattr(net_util.socket, "socket", lambda *a, **k: _DeadSock())
    monkeypatch.setattr(
        net_util, "_enumerate_private_ipv4s", lambda: ["192.168.1.153", "10.5.0.2"],
    )
    assert net_util.detect_lan_ip() == "192.168.1.153"


def test_detect_lan_ip_loopback_is_true_last_resort(monkeypatch) -> None:
    """Both the probe AND the enumeration come up empty — only then do we
    return loopback (and the DiscoveryResponder WARNs about it)."""
    class _DeadSock:
        def connect(self, addr): raise OSError("network unreachable")
        def getsockname(self): raise AssertionError("unreachable")
        def close(self): pass

    monkeypatch.setattr(net_util.socket, "socket", lambda *a, **k: _DeadSock())
    monkeypatch.setattr(net_util, "_enumerate_private_ipv4s", lambda: [])
    assert net_util.detect_lan_ip() == "127.0.0.1"


def test_detect_lan_ip_skips_loopback_from_probe(monkeypatch) -> None:
    """If the route probe somehow reads back loopback, treat it as a
    miss and fall through to the enumeration rather than advertising
    127.0.0.1."""
    class _LoopbackSock:
        def connect(self, addr): pass
        def getsockname(self): return ("127.0.0.1", 12345)
        def close(self): pass

    monkeypatch.setattr(net_util.socket, "socket", lambda *a, **k: _LoopbackSock())
    monkeypatch.setattr(
        net_util, "_enumerate_private_ipv4s", lambda: ["10.5.0.2"],
    )
    assert net_util.detect_lan_ip() == "10.5.0.2"


def test_is_plausible_ipv4_accepts_typical_lan() -> None:
    for ok in ("192.168.1.1", "10.0.0.1", "172.16.0.5",
               "127.0.0.1", "0.0.0.0", "255.255.255.255"):
        assert is_plausible_ipv4(ok), f"should accept {ok}"


@pytest.mark.parametrize("bad", [
    "",
    "1.2.3",         # too few octets
    "1.2.3.4.5",     # too many
    "1.2.3.256",     # out of range
    "1.2.3.-1",      # negative
    "a.b.c.d",       # non-numeric
    "1..2.3",        # empty octet
    "192.168.1.1 ",  # whitespace (don't auto-trim — wizard does that)
    "::1",           # IPv6
])
def test_is_plausible_ipv4_rejects_bad(bad: str) -> None:
    assert not is_plausible_ipv4(bad), f"should reject {bad!r}"
