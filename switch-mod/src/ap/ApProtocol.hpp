// Wire format mirror for the Switch <-> Bridge channel.
// Authoritative spec lives in docs/wire-protocol.md and bridge/smo_ap_bridge/protocol.py.
//
// Single persistent TCP connection. Each message is one '\n'-terminated line
// of UTF-8 JSON. Field "t" is the message type. Max line: 8 KiB.

#pragma once

#include <cstdint>
#include <string>
#include <vector>

#include "../util/Json.hpp"

namespace smoap::ap {

inline constexpr std::size_t kMaxLineBytes = 8 * 1024;

enum class ItemKind : std::uint8_t {
    Moon = 0,
    Capture = 1,
    Kingdom = 2,
    Shop = 3,
    Other = 4,
};

const char* toWire(ItemKind k);          // "moon" / "capture" / ...
ItemKind fromWire(const char* s);        // returns Other for unknown
ItemKind fromWire(const std::string& s); // legacy overload — forwards to char*

// Switch -> Bridge ----------------------------------------------------------

struct Hello {
    std::string mod_ver;
    std::string smo_ver;
    std::string cap_table_hash;
};

// Fixed-size char buffer used for Check string fields. libstdc++'s
// std::string allocator path NULL-derefs in our subsdk9 context for any
// string that exceeds SSO (~15 bytes), same root cause as the std::set
// crash. Keeping checks allocation-free here means the frame thread can
// produce them without touching the broken allocator. 64 bytes covers every
// stage name, moon objectId, capture, and kingdom string SMO emits.
inline constexpr std::size_t kCheckFieldCap = 64;

// Inbound-side caps. DecodedMsg fields use these — see comment on the
// structs below for the empirical justification (the worker-thread
// std::string allocator NULL-derefs once heap state has drifted, observed
// 2026-05-16 in parseCheckedReplay → readIntoString on a 20-char shine_id).
inline constexpr std::size_t kMediumFieldCap = 128;  // shine_id, name, ctx
inline constexpr std::size_t kLongFieldCap   = 256;  // err msgs, kill cause
inline constexpr std::size_t kPrintFieldCap  = 512;  // bridge print.text

// Copy a C-string into a fixed buffer, null-terminating. Null src -> empty.
inline void copyCheckField(char (&dst)[kCheckFieldCap], const char* src) {
    if (!src) { dst[0] = '\0'; return; }
    std::size_t i = 0;
    while (i + 1 < kCheckFieldCap && src[i] != '\0') {
        dst[i] = src[i];
        ++i;
    }
    dst[i] = '\0';
}

// Generic fixed-buffer copy (C-string source). Same shape as copyCheckField
// but works for any compile-time buffer size — used by inbound DecodedMsg
// fields which use varying sizes (64/128/256/512).
template <std::size_t N>
inline void copyFixedField(char (&dst)[N], const char* src) {
    if (!src) { dst[0] = '\0'; return; }
    std::size_t i = 0;
    while (i + 1 < N && src[i] != '\0') {
        dst[i] = src[i];
        ++i;
    }
    dst[i] = '\0';
}

// Length-bounded variant — used when the source is a string_view from the
// inbound JSON Reader (which does NOT null-terminate). Truncates and always
// null-terminates the destination.
template <std::size_t N>
inline void copyFixedFieldN(char (&dst)[N], const char* src, std::size_t n) {
    const std::size_t take = (n < N - 1) ? n : (N - 1);
    for (std::size_t i = 0; i < take; ++i) dst[i] = src[i];
    dst[take] = '\0';
}

struct Check {
    ItemKind kind = ItemKind::Moon;
    // legacy resolved fields (still used by inbound items / shop / kingdom)
    char kingdom[kCheckFieldCap] = {};
    char shine_id[kCheckFieldCap] = {};
    char cap[kCheckFieldCap] = {};
    int slot = -1;  // -1 means absent
    // M4 raw identifiers — bridge resolves these via shine_map.json / capture_map.json
    char stage_name[kCheckFieldCap] = {};  // moons: ShineInfo::stageName
    char object_id[kCheckFieldCap] = {};   // moons: ShineInfo::objectId
    int shine_uid = -1;                    // moons: ShineInfo::shineId
    char hack_name[kCheckFieldCap] = {};   // captures: PlayerHackKeeper::getCurrentHackName
};

struct Status {
    std::string kingdom;
    int scenario = -1;
    int moons_collected = -1;
    std::string stage_name;  // M4: raw stage at the time of the scenario flip
};

struct Goal {};

struct Death {
    std::int64_t ts_ms = 0;
};

struct Ping {
    std::int64_t ts_ms = 0;
};

struct Log {
    std::string level = "info";
    std::string msg;
};

// State snapshot. Sent by the Switch on every (re)connect right after HELLO,
// and (transitively) on save load via SaveLoadHook -> requestRehello. Three
// kinds of message in sequence: one StateBegin, N StateChunk (per-stage shines
// + a trailing "_meta" chunk for cross-stage data), one StateEnd.
//
// Carries RAW SMO identifiers (stage_name, object_id, shine_uid, hack_name)
// matching M4's Check semantics; the bridge resolves via shine_map.json /
// capture_map.json. The bridge is the source of truth for what AP knows; the
// snapshot lets AP learn about anything collected while disconnected.
//
// Outbound state-snapshot structs (Switch -> Bridge). std::string fields
// here get assigned then immediately handed to encodeStateChunk for one-shot
// serialization on the worker. Disproven assumption (2026-05-16): "std::string
// is safe on the worker" — *outbound* assignment can still allocate. Most
// values here are short (stage_name max ~24 chars, object_id ~8 chars) and
// have not crashed in practice; converting them to char[] is M-future work.
// The crash-driven fix-up has only addressed inbound DecodedMsg fields.

struct StateBegin {
    std::string mod_ver;
    int save_slot = -1;  // -1 means absent; bridge does NOT fence on this
};

struct ShineEntry {
    std::string object_id;
    int shine_uid = -1;
};

struct StateChunk {
    // Per-stage chunk: stage_name = SMO stage key (e.g. "CapWorldHomeStage"),
    //   shines = list of {object_id, shine_uid}.
    // Cross-stage "_meta" chunk: stage_name = "_meta", captures = list of raw
    //   hack_names, include_goal_reached/goal_reached for the goal flag.
    std::string stage_name;
    std::vector<ShineEntry> shines;
    std::vector<std::string> captures;
    bool include_goal_reached = false;
    bool goal_reached = false;
};

struct StateEnd {};

// Bridge -> Switch ----------------------------------------------------------
//
// Fixed-size char buffers throughout. Originally these were std::string
// fields under the assumption "std::string is safe on the worker." That
// assumption broke 2026-05-16: parseCheckedReplay's first ItemRef.shine_id
// assignment (a 20-char "Our First Power Moon") NULL-deref'd inside
// libstdc++'s allocator. The encoder path was fixed by going through a
// LineBuffer; this is the matching inbound-side fix. Sizes are budgeted from
// observed traffic + 2x headroom.

struct HelloAck {
    bool ok = false;
    char seed[kCheckFieldCap] = {};
    char slot[kCheckFieldCap] = {};
    char cap_table_hash[kCheckFieldCap] = {};
    // Bridge-owned DeathLink toggle. Mod ships the inbound apply path
    // unconditionally; this flag gates whether we act on inbound kill messages
    // so the user enables DeathLink in bridge config without rebuilding.
    bool deathlink_enabled = false;
    char err[kLongFieldCap] = {};
};

struct ItemRef {
    ItemKind kind = ItemKind::Other;
    char kingdom[kCheckFieldCap] = {};
    char shine_id[kMediumFieldCap] = {};
    char cap[kCheckFieldCap] = {};
    char name[kMediumFieldCap] = {};
    int slot = -1;
};

struct CheckedReplay {
    // Fixed-size array — `std::vector::push_back` triggered the libstdc++
    // allocator NULL-deref on a re-HELLO 2026-05-16, same root cause as the
    // other inbound fields. 128 entries covers typical session replay (the
    // bridge only emits checks observed since the last connect). Overflow
    // truncates with a log line.
    static constexpr std::size_t kMaxIds = 128;
    ItemRef ids[kMaxIds]{};
    std::size_t id_count = 0;
    bool truncated = false;
};

struct Item {
    ItemKind kind = ItemKind::Other;
    char kingdom[kCheckFieldCap] = {};
    char shine_id[kMediumFieldCap] = {};
    char cap[kCheckFieldCap] = {};
    char name[kMediumFieldCap] = {};
    int slot = -1;
    char from[kCheckFieldCap] = {};
    // M6 phase B: populated by the bridge for capture items via the reverse
    // CaptureMap (cap_name -> hack_name). Mod feeds straight to
    // GameDataFunction::addHackDictionary. Empty when the bridge had no map
    // entry — mod logs and drops in that case.
    char hack_name[kCheckFieldCap] = {};
};

struct Print {
    char text[kPrintFieldCap] = {};
};

struct ApStateMsg {
    // Renamed from ApState to avoid collision with class smoap::ap::ApState
    // (the in-process singleton). Carries the bridge's view of the AP-server
    // connection state.
    char conn[kCheckFieldCap] = {};  // "disconnected" | "connecting" | "ready"
};

struct Pong {
    std::int64_t ts_ms = 0;
};

struct Err {
    char code[kCheckFieldCap] = {};
    char ctx[kMediumFieldCap] = {};
};

struct Kill {
    // DeathLink forwarded from another slot. M4 logs this; killing Mario
    // belongs to M6 where we also have the player-state-write machinery.
    char source[kCheckFieldCap] = {};
    char cause[kLongFieldCap] = {};
};

// (de)serialization --------------------------------------------------------
// Implementations in ApProtocol.cpp use util/Json.hpp (no STL exceptions).
//
// Encoders write into a caller-owned LineBuffer. The trailing '\n' is
// included. Use `line.data()` / `line.size()` to send on the socket.
// Caller-owned buffers keep the encode path off the libstdc++ allocator,
// which NULL-derefs in our subsdk9 link once heap state drifts (see project
// memory `libstdcpp_allocator_broken_in_subsdk9`).

void encodeHello(smoap::util::json::LineBuffer&, const Hello&);
void encodeCheck(smoap::util::json::LineBuffer&, const Check&);
void encodeStatus(smoap::util::json::LineBuffer&, const Status&);
void encodeGoal(smoap::util::json::LineBuffer&);
void encodeDeath(smoap::util::json::LineBuffer&, const Death&);
void encodePing(smoap::util::json::LineBuffer&, const Ping&);
void encodeLog(smoap::util::json::LineBuffer&, const Log&);
void encodeStateBegin(smoap::util::json::LineBuffer&, const StateBegin&);
void encodeStateChunk(smoap::util::json::LineBuffer&, const StateChunk&);
void encodeStateEnd(smoap::util::json::LineBuffer&);

// Returns true on parse success and fills the discriminated union outputs.
struct DecodedMsg {
    char t[kCheckFieldCap] = {};  // type discriminator: "hello_ack" etc.
    HelloAck hello_ack{};
    CheckedReplay checked_replay{};
    Item item{};
    Print print{};
    ApStateMsg ap_state{};
    Pong pong{};
    Err err{};
    Kill kill{};
};
bool decode(const char* data, std::size_t len, DecodedMsg& out);

}  // namespace smoap::ap
