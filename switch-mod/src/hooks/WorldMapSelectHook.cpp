// M7 Path A — fork-cinematic kingdom-order gate (two-layer architecture).
//
// Forces linear progression at SMO's two world-map bifurcations only at the
// FORK CINEMATIC moment: the post-Sand fork substitutes Wooded->Lake; the
// post-Metro fork substitutes Seaside->Snow. The regular (post-fork) world
// map is intentionally NOT hooked here — once the cinematic has flown Mario
// to the prereq kingdom, both kingdoms are unlocked on the regular map
// (vanilla SMO behavior) and the player can travel freely between any
// unlocked kingdom. That free-travel property is what prevents the
// "stuck in Seaside without enough Seaside moons to advance to Luncheon"
// soft-lock — Mario can always teleport back via the regular map.
//
// Layered defense — outer layer runs first; each is a different fn the
// FORK cinematic can call to ask about kingdoms:
//
//   Layer 1: calcNextLockedWorldIdForWorldMap (LayoutActor + Scene overloads)
//     The post-Multi-Moon fork cinematic uses this to populate the "newly
//     unlocked" presentation. Verified firing in the 2026-05-17 fresh-save
//     fork playtest as Scene overload on slot 0 — this is what actually
//     catches the one-time fork moment.
//
//   Layer 2: tryChangeNextStageWithDemoWorldWarp (BACKSTOP)
//     The cinematic's stage-commit chokepoint. If a future SMO update
//     routes the cinematic through a path Layer 1 doesn't catch, this
//     catches it. WARN-level log fires when the backstop substitutes —
//     that's a signal the upstream catch needs adding back. Substitution
//     at this layer can produce broken cutscene visuals (per failed
//     iteration #3 in CLAUDE.md M7 section's prior-iteration failure log);
//     better than going to the wrong kingdom, but not the desired path.
//
// History — the prior three-layer design also hooked getUnlockWorldId
// (regular world map, 4 overloads) and tryChangeNextStageWithWorldWarpHole
// (regular-map portal-hole commit). That made the post-fork regular map
// behave the same as the cinematic — Seaside was substituted to Snow on
// every map open even after Mario had already been to Snow. Combined with
// the threshold gate it produced a soft-lock when a player had >=10
// lifetime Snow AP-receipts (e.g., from other players' completions of
// own-slot moons) but had never visited Snow: the cinematic released
// Seaside, the player picked it, and couldn't farm enough Seaside moons
// to advance. Narrowing substitution to the cinematic + dropping the
// threshold removes the trap entirely.
//
// See CLAUDE.md M7 section's "prior-iteration failure log" for the earlier
// failed attempts (skip Orig at ChangeStage / DemoWorldWarp produces UI
// soft-lock; substitute at DemoWorldWarp produces broken cutscene visuals;
// isUnlockedWorld doesn't gate the cursor; refusing tryChange soft-locks
// the menu).

#include "lib.hpp"  // HOOK_DEFINE_TRAMPOLINE

#include "lib/nx/nx.h"  // Result, R_FAILED — via extern "C" wrapper
#include "nn/ro.h"

#include <cstdint>
#include <cstring>

#include "../ap/ApState.hpp"
#include "../game/KingdomOrderGate.hpp"
#include "../game/KingdomUnlock.hpp"
#include "../util/Log.hpp"
#include "HookSymbols.hpp"
#include "SoftInstall.hpp"

namespace smoap::hooks {

namespace {

// 1-pointer Itanium-ABI wrappers, matching game/CaptureGate.cpp.
struct GameDataHolderWriter   { void* mData; };
struct GameDataHolderAccessor { void* mData; };

// Compile-time kill switch. When false, the hooks log substitutions they
// WOULD have applied but pass Orig's value through unchanged. Useful for
// disabling the gate without rebuilding observation-only.
constexpr bool kGateEnabled = true;

// Shared substitution helper for the cinematic UI's per-slot world-id
// callback. Given the worldId Orig returned, decide whether to substitute.
// `origin` is a log prefix that identifies which hook fired.
int substituteSlotWorldId(const char* origin, int index, int orig_world_id) {
    if (!kGateEnabled) return orig_world_id;

    const char* kingdom = smoap::game::kingdomShortFromWorldId(orig_world_id);
    if (!kingdom) return orig_world_id;

    auto decision = smoap::game::evaluateOrderGateForKingdom(kingdom);
    if (!decision.blocked) return orig_world_id;

    const int prereq_id = smoap::game::worldIdFromKingdomShort(
        decision.required_kingdom_short);
    if (prereq_id < 0) {
        SMOAP_LOG_WARN("[wmap.%s] gate misconfigured: prereq='%s' not in "
                       "kKingdoms; passing original worldId=%d through",
                       origin,
                       decision.required_kingdom_short
                           ? decision.required_kingdom_short
                           : "(null)",
                       orig_world_id);
        return orig_world_id;
    }

    // Throttle the log so per-frame re-queries don't flood. Key the throttle
    // on (origin, index, orig_id) — re-log when any of these changes so we
    // capture state transitions.
    static const char* s_last_origin   = nullptr;
    static int         s_last_index    = -1;
    static int         s_last_orig_id  = -1;
    const bool changed =
        s_last_origin  != origin  ||
        s_last_index   != index   ||
        s_last_orig_id != orig_world_id;
    if (changed) {
        SMOAP_LOG_INFO("[wmap.%s] SUB slot=%d origId=%d (%s) -> prereqId=%d (%s)",
                       origin, index, orig_world_id, kingdom,
                       prereq_id, decision.required_kingdom_short);
        s_last_origin  = origin;
        s_last_index   = index;
        s_last_orig_id = orig_world_id;
    }
    return prereq_id;
}

// ----------------------------------------------------------------------------
// Layer 1: calcNextLockedWorldIdForWorldMap — the post-Multi-Moon FORK
// cinematic uses this to populate the "newly unlocked" destinations. Two
// overloads (LayoutActor*, Scene*). Verified firing in 2026-05-17 fresh-save
// playtest as Scene overload on slot 0.
// ----------------------------------------------------------------------------

HOOK_DEFINE_TRAMPOLINE(CalcNextLockedWorldIdLayoutActorHook) {
    static int Callback(const void* p, int index) {
        return substituteSlotWorldId("menu.NextLocked.Layout", index, Orig(p, index));
    }
};
HOOK_DEFINE_TRAMPOLINE(CalcNextLockedWorldIdSceneHook) {
    static int Callback(const void* p, int index) {
        return substituteSlotWorldId("menu.NextLocked.Scene", index, Orig(p, index));
    }
};

// ----------------------------------------------------------------------------
// Layer 2: tryChangeNextStageWithDemoWorldWarp — BACKSTOP for the cinematic
// stage commit ("Demo" = cutscene in SMO parlance; this is the cinematic
// flight path). If Layer 1 misses, this rewrites the stage arg. WARN-level
// log makes any backstop fire loud — it's a signal that a new upstream catch
// is needed. Substitution at this layer may produce broken cutscene visuals
// (per failed-iteration #3 in CLAUDE.md M7 section) because the world-map
// state machine may have already pre-loaded the gated kingdom's cutscene
// assets by the time tryChange runs. Refusing (returning false) was tried
// and soft-locks the menu, so substitution is the safer choice despite the
// visual cost.
//
// The regular-map portal-hole equivalent (tryChangeNextStageWithWorldWarpHole)
// is intentionally NOT hooked — the regular map should permit free travel
// between any unlocked kingdom.
// ----------------------------------------------------------------------------

// Mark Mario as having "visited" the destination kingdom. Called from both
// tryChange* hooks below — these are the actual stage-commit chokepoints
// (cinematic Odyssey-flight + regular-map portal-hole), so they're the right
// time to flip the sticky bit. Save-data load doesn't go through either, so
// reloading into Lake won't pollute visited[Lake].
void markVisitedFromStage(const char* origin, const char* stage) {
    if (!stage) return;
    const char* kingdom = smoap::game::kingdomShortFromHomeStage(stage);
    if (!kingdom) return;
    const std::uint8_t bit = smoap::game::kingdomBitFor(kingdom);
    if (bit >= 17) return;
    auto& st = smoap::ap::ApState::instance();
    if (!st.isKingdomBitVisited(static_cast<int>(bit))) {
        SMOAP_LOG_INFO("[wmap.%s] visited[%s] = true (stage='%s')",
                       origin, kingdom, stage);
    }
    st.markKingdomBitVisited(static_cast<int>(bit));
}

HOOK_DEFINE_TRAMPOLINE(TryChangeDemoWorldWarpHook) {
    static bool Callback(GameDataHolderWriter writer, const char* stage) {
        const char* final_stage = stage;
        const char* kingdom = stage ? smoap::game::kingdomShortFromHomeStage(stage)
                                     : nullptr;
        if (kGateEnabled && kingdom) {
            const auto decision = smoap::game::evaluateOrderGateForKingdom(kingdom);
            if (decision.blocked && decision.required_stage) {
                SMOAP_LOG_WARN("[wmap.tryChange.Demo] BACKSTOP substituting "
                               "stage='%s' -> '%s' (upstream cinematic catch missed)",
                               stage, decision.required_stage);
                final_stage = decision.required_stage;
            }
        }
        // Visited tracking: record the kingdom Mario actually flies to
        // (post-substitution). The cinematic-fork case substitutes
        // Wooded->Lake here; we want visited[Lake] to set so the next gate
        // consult releases. The flag is sticky; no harm in setting it on
        // every cinematic flight.
        markVisitedFromStage("tryChange.Demo", final_stage);
        return Orig(writer, final_stage);
    }
};

// Regular-map portal-hole commit. NOT used for substitution (the regular
// map should allow free travel between unlocked kingdoms — see the header
// comment). Re-installed solely to mark visited on the destination so the
// gate's sticky bit reflects "Mario actually flew here at some point this
// session," not "Mario is sitting here right now" (the latter is the gate's
// own current-kingdom OR-check, see KingdomOrderGate.cpp).
HOOK_DEFINE_TRAMPOLINE(TryChangeWorldWarpHoleHook) {
    static bool Callback(GameDataHolderWriter writer, const char* stage) {
        markVisitedFromStage("tryChange.Hole", stage);
        return Orig(writer, stage);
    }
};

}  // namespace

void installWorldMapSelectHook() {
    SMOAP_LOG_INFO("installing M7 Path A Layer 1 (calcNextLocked, 2 overloads)");
    softInstallAtSymbol<CalcNextLockedWorldIdLayoutActorHook>(
        smoap::sym::kGameDataFunctionCalcNextLockedWorldIdForWorldMap_LayoutActor);
    softInstallAtSymbol<CalcNextLockedWorldIdSceneHook>(
        smoap::sym::kGameDataFunctionCalcNextLockedWorldIdForWorldMap_Scene);

    SMOAP_LOG_INFO("installing M7 Path A Layer 2 (DemoWorldWarp backstop + visited)");
    softInstallAtSymbol<TryChangeDemoWorldWarpHook>(
        smoap::sym::kGameDataFunctionTryChangeNextStageWithDemoWorldWarp);

    SMOAP_LOG_INFO("installing M7 Path A WorldWarpHole (visited-only, no gate)");
    softInstallAtSymbol<TryChangeWorldWarpHoleHook>(
        smoap::sym::kGameDataFunctionTryChangeNextStageWithWorldWarpHole);
}

}  // namespace smoap::hooks
