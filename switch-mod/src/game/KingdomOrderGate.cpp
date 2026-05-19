#include "KingdomOrderGate.hpp"

#include <cstring>

#include "../ap/ApState.hpp"

namespace smoap::game {

namespace {

struct Rule {
    const char* picked;          // kingdom short name the player picked
    const char* prereq;          // kingdom short name they must clear first
    const char* prereq_stage;    // SMO HomeStage to redirect them into
    int threshold;
};

// Gates only the two post-bifurcation siblings. Lake and Snow themselves are
// not gated — they're always available immediately post-Sand / post-Metro.
//
// The HomeStage names below are the canonical SMO 1.0.0 strings, matching the
// KINGDOM_FOR_HOMESTAGE table in scripts/extract_shine_map.py.
constexpr Rule kRules[] = {
    {"Wooded",  "Lake", "LakeWorldHomeStage", kLakeRequiredForWooded},
    {"Seaside", "Snow", "SnowWorldHomeStage", kSnowRequiredForSeaside},
};

// Map prereq short name -> the matching lifetime counter on ApState.
// Two scalars rather than an indexed array because only Lake and Snow are
// gate prereqs today (matches regions.json's KingdomMoons(Lake,8) and
// KingdomMoons(Snow,10)). Returns -1 if the prereq isn't one of those two,
// which the caller treats as fail-open (same as an unknown kingdomBitFor).
int readPrereqLifetime(const char* prereq) {
    auto& st = smoap::ap::ApState::instance();
    if (std::strcmp(prereq, "Lake") == 0) {
        return st.lake_received_total.load(std::memory_order_relaxed);
    }
    if (std::strcmp(prereq, "Snow") == 0) {
        return st.snow_received_total.load(std::memory_order_relaxed);
    }
    return -1;
}

}  // namespace

OrderGateDecision evaluateOrderGateForKingdom(const char* kingdom_short) {
    OrderGateDecision d{};
    if (!kingdom_short || !*kingdom_short) return d;

    for (const auto& r : kRules) {
        if (std::strcmp(kingdom_short, r.picked) != 0) continue;

        // Read the *lifetime* count of moons received for the prereq
        // kingdom, NOT ap_moons_kingdom[prereq] (which is the undeposited
        // balance and would re-close the gate after Mario deposits at the
        // prereq's Odyssey — see the 2026-05-18 regression where this
        // showed two Lake kingdoms at the post-Sand fork after a Lake
        // deposit). The bridge ships these in OutstandingMsg.
        const int have = readPrereqLifetime(r.prereq);
        if (have < 0) {
            // Misconfigured rule (prereq kingdom not Lake or Snow) — fail
            // open. If a new gate prereq lands in regions.json, add the
            // scalar to ApState + the wire format + readPrereqLifetime.
            return d;
        }
        d.prereq_moons_now = have;
        d.prereq_required  = r.threshold;
        if (have >= r.threshold) {
            // Gate satisfied — let it through.
            return d;
        }
        d.blocked                = true;
        d.required_kingdom_short = r.prereq;
        d.required_stage         = r.prereq_stage;
        return d;
    }
    return d;  // not a gated kingdom
}

}  // namespace smoap::game
