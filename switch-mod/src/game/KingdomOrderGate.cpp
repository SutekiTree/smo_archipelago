#include "KingdomOrderGate.hpp"

#include <cstring>

#include "../ap/ApState.hpp"
#include "KingdomUnlock.hpp"

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

}  // namespace

OrderGateDecision evaluateOrderGateForKingdom(const char* kingdom_short) {
    OrderGateDecision d{};
    if (!kingdom_short || !*kingdom_short) return d;

    for (const auto& r : kRules) {
        if (std::strcmp(kingdom_short, r.picked) != 0) continue;

        const std::uint8_t prereq_bit = kingdomBitFor(r.prereq);
        if (prereq_bit == 0xff) {
            // Misconfigured rule (prereq kingdom not in KingdomUnlock's table)
            // — fail open. Caller logs.
            return d;
        }
        const int have = smoap::ap::ApState::instance()
                             .ap_moons_kingdom[prereq_bit]
                             .load(std::memory_order_relaxed);
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
