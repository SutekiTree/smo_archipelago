// M7 Path A — kingdom-order gate policy.
//
// Decides whether a world the player just picked on the world map should be
// allowed (player has enough prerequisite AP-credited moons) or REDIRECTED
// (substitute the prerequisite kingdom so the cutscene plays cleanly there).
//
// Two bifurcation gates today:
//   - Post-Sand: Wooded gated by Lake (>= kLakeRequired AP moons)
//   - Post-Metro: Seaside gated by Snow (>= kSnowRequired AP moons)
//
// The gate is read-only on ApState (consumes ap_moons_kingdom counts populated
// by M6 phase A's ItemMsg handling) and contains no Switch-specific state — so
// it is also unit-testable on a host build, though no host test is shipped yet.
//
// Order policy comes from apworld/.../data/regions.json's linear-chain edits;
// the moon thresholds match the {LakePeace}/{SnowPeace} helpers there.

#pragma once

#include <cstdint>

namespace smoap::game {

// Moon thresholds. Keep in sync with apworld hooks/Rules.py LakePeace /
// SnowPeace helpers. The plan's authoritative wording is "Lake>=8 or Snow>=10".
inline constexpr int kLakeRequiredForWooded   = 8;
inline constexpr int kSnowRequiredForSeaside  = 10;

struct OrderGateDecision {
    // True if the player's choice should NOT proceed as-is. When true,
    // required_kingdom_short and required_stage point to the prerequisite
    // kingdom they have to complete first (used by the hook to substitute the
    // destination via tryChangeNextStageWithDemoWorldWarp). When false the
    // remaining fields are unset (nullptr / empty).
    bool blocked = false;

    // Apworld kingdom short name ("Lake", "Snow"). nullptr when !blocked.
    const char* required_kingdom_short = nullptr;

    // SMO HomeStage name ("LakeWorldHomeStage", "SnowWorldHomeStage"). nullptr
    // when !blocked. Suitable for passing to GameDataFunction::
    // tryChangeNextStageWithDemoWorldWarp.
    const char* required_stage = nullptr;

    // Diagnostic: count of AP-credit moons currently held for the
    // prerequisite kingdom (populated even when !blocked, for log clarity;
    // 0 when no kingdom maps).
    int prereq_moons_now = 0;

    // Diagnostic: threshold the prereq kingdom needs to clear. 0 when
    // !blocked.
    int prereq_required = 0;
};

// Evaluate the gate for a kingdom the player just picked, identified by
// apworld short name ("Wooded", "Seaside", etc.). Returns blocked=false for
// any non-gated kingdom (e.g., Cap, Cascade, Lake, Snow, Luncheon, ...).
//
// Reads ApState::ap_moons_kingdom[] via the existing KingdomUnlock
// kingdomBitFor() index, so the kingdom short name must match the kKingdoms
// table in KingdomUnlock.cpp. Unknown kingdoms also return blocked=false
// (fail open — better to let an unrecognized kingdom through than to soft-lock
// the player out of progression).
OrderGateDecision evaluateOrderGateForKingdom(const char* kingdom_short);

}  // namespace smoap::game
