"""Tests for `_setup.net` — LAN-IP autodetect for the Bridge-IP wizard
page, and IPv4 input-validation helper."""

from __future__ import annotations

import pytest

from _setup.net import detect_lan_ip, is_plausible_ipv4


def test_detect_lan_ip_returns_dotted_quad() -> None:
    """In any environment with at least loopback (i.e. every environment
    pytest can run in), detect_lan_ip should return a parseable IPv4."""
    ip = detect_lan_ip()
    assert is_plausible_ipv4(ip)


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
