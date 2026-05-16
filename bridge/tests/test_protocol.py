"""Wire-protocol unit tests."""

from __future__ import annotations

import json

import pytest

from smo_ap_bridge import protocol
from smo_ap_bridge.protocol import (
    CheckMsg,
    HelloAckMsg,
    HelloMsg,
    ItemMsg,
    ItemRef,
    ItemKind,
    MoonLabelMsg,
    PingMsg,
    PongMsg,
    iter_lines,
)


def test_hello_round_trip():
    msg = HelloMsg(mod_ver="0.1.0+abc", smo_ver="1.0.0", cap_table_hash="sha1:deadbeef")
    raw = protocol.encode(msg)
    assert raw.endswith(b"\n")
    parsed = protocol.decode(raw.rstrip(b"\n"))
    assert parsed["t"] == "hello"
    assert parsed["mod_ver"] == "0.1.0+abc"
    assert parsed["smo_ver"] == "1.0.0"


def test_check_strips_none_fields():
    msg = CheckMsg(kind=ItemKind.MOON.value, kingdom="Cascade", shine_id="DinoNest")
    raw = protocol.encode(msg)
    parsed = protocol.decode(raw)
    assert "cap" not in parsed
    assert "slot" not in parsed
    assert parsed == {"t": "check", "kind": "moon", "kingdom": "Cascade", "shine_id": "DinoNest"}


def test_item_msg_renames_from():
    msg = ItemMsg(kind="capture", cap="Frog", from_="Bob")
    raw = protocol.encode(msg)
    parsed = protocol.decode(raw)
    assert parsed["from"] == "Bob"
    assert "from_" not in parsed


def test_item_msg_hack_name_round_trip():
    """M6 phase B: ItemMsg carries hack_name for capture items so the mod
    can pass it straight into addHackDictionary."""
    msg = ItemMsg(kind="capture", cap="Goomba", hack_name="Kuribo", from_="Mario")
    raw = protocol.encode(msg)
    parsed = protocol.decode(raw)
    assert parsed["kind"] == "capture"
    assert parsed["cap"] == "Goomba"
    assert parsed["hack_name"] == "Kuribo"


def test_item_msg_hack_name_omitted_when_none():
    """None values are stripped from the wire payload."""
    msg = ItemMsg(kind="moon", kingdom="Cap", shine_id="Power Moon")
    raw = protocol.encode(msg)
    parsed = protocol.decode(raw)
    assert "hack_name" not in parsed


def test_hello_ack_optional_fields():
    msg = HelloAckMsg(ok=True, seed="X4F2", slot="Mario")
    raw = protocol.encode(msg)
    parsed = protocol.decode(raw)
    assert parsed["ok"] is True
    assert parsed["seed"] == "X4F2"
    assert "err" not in parsed  # None should be stripped


def test_iter_lines_basic():
    buf = bytearray(b'{"t":"ping","ts_ms":1}\n{"t":"pong","ts_ms":2}\n{"t":"ping"')
    lines = list(iter_lines(buf))
    assert len(lines) == 2
    assert json.loads(lines[0])["t"] == "ping"
    assert json.loads(lines[1])["t"] == "pong"
    # Incomplete line remains in buffer.
    assert buf == bytearray(b'{"t":"ping"')


def test_iter_lines_drops_oversized_resync():
    huge = b"x" * (protocol.MAX_LINE_BYTES + 100)
    buf = bytearray(huge + b"\n" + b'{"t":"ping"}\n')
    lines = list(iter_lines(buf))
    assert len(lines) == 1
    assert json.loads(lines[0])["t"] == "ping"


def test_iter_lines_clears_corrupt_no_newline():
    """If we have > MAX_LINE_BYTES with no newline at all, resync by clearing."""
    buf = bytearray(b"x" * (protocol.MAX_LINE_BYTES + 100))
    list(iter_lines(buf))  # exhaust
    assert len(buf) == 0


def test_encode_max_line_enforced():
    msg = HelloMsg(mod_ver="x" * (protocol.MAX_LINE_BYTES + 1))
    with pytest.raises(ValueError):
        protocol.encode(msg)


def test_pong_round_trip():
    msg = PongMsg(ts_ms=12345)
    raw = protocol.encode(msg)
    parsed = protocol.decode(raw)
    assert parsed == {"t": "pong", "ts_ms": 12345}


def test_ping_default_ts_zero():
    msg = PingMsg()
    parsed = protocol.decode(protocol.encode(msg))
    assert parsed["ts_ms"] == 0


# --- M6 phase A.5: CheckMsg.seq + MoonLabelMsg -------------------------


def test_check_msg_seq_omitted_when_unset():
    # Backwards-compat: legacy switch builds omit seq entirely; bridge
    # uses presence-of-non-zero-seq as the "label me" signal. Default
    # None gets stripped from the wire so old bridges parse cleanly.
    msg = CheckMsg(kind="moon", stage_name="WaterfallWorldHomeStage",
                   object_id="obj214", shine_uid=12345)
    parsed = protocol.decode(protocol.encode(msg))
    assert "seq" not in parsed


def test_check_msg_seq_non_zero_round_trip():
    msg = CheckMsg(kind="moon", stage_name="X", object_id="obj1", seq=42)
    parsed = protocol.decode(protocol.encode(msg))
    assert parsed["seq"] == 42


def test_moon_label_msg_round_trip():
    msg = MoonLabelMsg(text="Sent Cap Power Moon -> P3", seq=7,
                      valid_for_ms=4000)
    raw = protocol.encode(msg)
    parsed = protocol.decode(raw)
    assert parsed == {
        "t": "moon_label",
        "text": "Sent Cap Power Moon -> P3",
        "seq": 7,
        "valid_for_ms": 4000,
    }


def test_moon_label_msg_defaults_round_trip():
    # Empty MoonLabelMsg should still round-trip (the Switch tolerates
    # text="" as a no-op clear).
    msg = MoonLabelMsg()
    parsed = protocol.decode(protocol.encode(msg))
    assert parsed["t"] == "moon_label"
    assert parsed["text"] == ""
    assert parsed["seq"] == 0
    assert parsed["valid_for_ms"] == 4000


def test_moon_label_msg_unicode_text_preserved():
    msg = MoonLabelMsg(text="Got Café Power Moon!", seq=1)
    raw = protocol.encode(msg)
    parsed = protocol.decode(raw)
    assert parsed["text"] == "Got Café Power Moon!"
