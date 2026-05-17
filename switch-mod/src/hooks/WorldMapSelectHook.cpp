// M7 Path A — world-map kingdom-order gate (three-layer architecture).
//
// Forces a linear progression order at SMO's two world-map bifurcations: the
// post-Sand fork (Lake before Wooded) and the post-Metro fork (Snow before
// Seaside). Substitutes Wooded->Lake and Seaside->Snow at every layer the
// world-map UI / fork cinematic can ask "what kingdom is at this slot?" or
// "what's the destination of this transition?". From SMO's perspective the
// gated kingdom is never offered as an option; from the player's perspective
// the menu shows the prerequisite kingdom in both slots of the fork (one
// natural, one substituted) and picking either flies cleanly to the prereq.
//
// Layered defense — outer layers run first; each is a different fn the
// world-map / fork code can call to ask about kingdoms:
//
//   Layer 1: getUnlockWorldIdForWorldMap (4 overloads by ptr-type)
//     The regular world-map UI uses this AFTER the fork has been resolved
//     (Odyssey → world map post-cutscene). Verified firing in playtest as
//     LiveActor + Scene overloads on slot 3.
//
//   Layer 2: calcNextLockedWorldIdForWorldMap (LayoutActor + Scene overloads)
//     The post-Multi-Moon FORK cinematic uses this to populate the "new
//     kingdoms unlocked" presentation. Verified firing in the 2026-05-17
//     fresh-save fork playtest as Scene overload on slot 0 — this is what
//     actually catches the one-time fork moment.
//
//   Layer 3: tryChangeNextStageWithDemoWorldWarp + WorldWarpHole (BACKSTOP)
//     The actual stage-commit chokepoint. If a future SMO update routes the
//     fork through a path neither Layer 1 nor Layer 2 catches, this catches
//     it. WARN-level log fires when the backstop substitutes — that's a
//     signal a new code path needs to be added to the upstream layers.
//     Substitution at this layer can produce broken cutscene visuals
//     (per the failed iteration #3 documented in CLAUDE.md M7 section);
//     better than going to the wrong kingdom, but not the desired path.
//
// Iteration history that informed this design — see CLAUDE.md M7 section's
// "prior-iteration failure log" for the failed attempts (skip Orig at
// ChangeStage / DemoWorldWarp produces UI soft-lock; substitute at
// DemoWorldWarp produces broken cutscene visuals; isUnlockedWorld doesn't
// gate the cursor; refusing tryChange soft-locks the menu).

#include "lib.hpp"  // HOOK_DEFINE_TRAMPOLINE

#include "lib/nx/nx.h"  // Result, R_FAILED — via extern "C" wrapper
#include "nn/ro.h"

#include <cstdint>
#include <cstring>

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

// Shared substitution helper for per-slot world-id callbacks (both menu-Id
// and calcNextLocked layers). Given the worldId Orig returned, decide
// whether to substitute. `origin` is a log prefix that identifies which
// hook fired.
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
    // capture state transitions (e.g., prereq becomes met → substitution
    // stops firing → next call re-logs once when the rule changes).
    static const char* s_last_origin   = nullptr;
    static int         s_last_index    = -1;
    static int         s_last_orig_id  = -1;
    const bool changed =
        s_last_origin  != origin  ||
        s_last_index   != index   ||
        s_last_orig_id != orig_world_id;
    if (changed) {
        SMOAP_LOG_INFO("[wmap.%s] SUB slot=%d origId=%d (%s) -> prereqId=%d (%s) "
                       "have=%d need=%d",
                       origin, index, orig_world_id, kingdom,
                       prereq_id, decision.required_kingdom_short,
                       decision.prereq_moons_now, decision.prereq_required);
        s_last_origin  = origin;
        s_last_index   = index;
        s_last_orig_id = orig_world_id;
    }
    return prereq_id;
}

// ----------------------------------------------------------------------------
// Layer 1: getUnlockWorldIdForWorldMap — the regular world-map UI's per-slot
// "what worldId lives here?" query. Four overloads by first-arg ptr-type
// (GameDataHolder*, al::LayoutActor*, al::Scene*, al::LiveActor*); different
// world-map call sites use different convenience overloads, so we hook all
// four.
//
// In AArch64 calling convention all pointer types go in X0, so void* in our
// trampoline signature is interchangeable with any pointer type — we pass
// through to Orig without dereferencing.
// ----------------------------------------------------------------------------

HOOK_DEFINE_TRAMPOLINE(GetUnlockWorldIdHolderHook) {
    static int Callback(const void* p, int index) {
        return substituteSlotWorldId("menu.Id.Holder", index, Orig(p, index));
    }
};
HOOK_DEFINE_TRAMPOLINE(GetUnlockWorldIdLayoutActorHook) {
    static int Callback(const void* p, int index) {
        return substituteSlotWorldId("menu.Id.Layout", index, Orig(p, index));
    }
};
HOOK_DEFINE_TRAMPOLINE(GetUnlockWorldIdSceneHook) {
    static int Callback(const void* p, int index) {
        return substituteSlotWorldId("menu.Id.Scene", index, Orig(p, index));
    }
};
HOOK_DEFINE_TRAMPOLINE(GetUnlockWorldIdLiveActorHook) {
    static int Callback(const void* p, int index) {
        return substituteSlotWorldId("menu.Id.LiveActor", index, Orig(p, index));
    }
};

// ----------------------------------------------------------------------------
// Layer 2: calcNextLockedWorldIdForWorldMap — the post-Multi-Moon FORK
// cinematic uses this to populate the "newly unlocked" destinations. Two
// overloads (LayoutActor*, Scene*). Verified firing in 2026-05-17 fresh-save
// playtest as Scene overload on slot 0. Same substitution rule as Layer 1.
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
// Layer 3: tryChangeNextStageWith{DemoWorldWarp,WorldWarpHole} — BACKSTOP.
//
// If neither Layer 1 nor Layer 2 catches a code path that commits a gated
// destination, this layer rewrites the stage arg. The WARN-level log makes
// such an event loud — it's a signal that a new upstream catch is needed.
// Substitution at this layer may produce broken cutscene visuals (per
// failed-iteration #3 in CLAUDE.md M7 section's prior-iteration failure log)
// because the world-map state machine may have already pre-loaded the gated
// kingdom's cutscene assets by the time tryChange runs. Refusing (returning
// false) was tried and soft-locks the menu, so substitution is the safer
// choice despite the visual cost.
// ----------------------------------------------------------------------------

HOOK_DEFINE_TRAMPOLINE(TryChangeDemoWorldWarpHook) {
    static bool Callback(GameDataHolderWriter writer, const char* stage) {
        const char* kingdom = stage ? smoap::game::kingdomShortFromHomeStage(stage)
                                     : nullptr;
        if (kGateEnabled && kingdom) {
            const auto decision = smoap::game::evaluateOrderGateForKingdom(kingdom);
            if (decision.blocked && decision.required_stage) {
                SMOAP_LOG_WARN("[wmap.tryChange.Demo] BACKSTOP substituting "
                               "stage='%s' -> '%s' (upstream menu catch missed) "
                               "have=%d need=%d",
                               stage, decision.required_stage,
                               decision.prereq_moons_now, decision.prereq_required);
                return Orig(writer, decision.required_stage);
            }
        }
        return Orig(writer, stage);
    }
};

HOOK_DEFINE_TRAMPOLINE(TryChangeWorldWarpHoleHook) {
    static bool Callback(GameDataHolderWriter writer, const char* stage) {
        const char* kingdom = stage ? smoap::game::kingdomShortFromHomeStage(stage)
                                     : nullptr;
        if (kGateEnabled && kingdom) {
            const auto decision = smoap::game::evaluateOrderGateForKingdom(kingdom);
            if (decision.blocked && decision.required_stage) {
                SMOAP_LOG_WARN("[wmap.tryChange.Hole] BACKSTOP substituting "
                               "stage='%s' -> '%s' have=%d need=%d",
                               stage, decision.required_stage,
                               decision.prereq_moons_now, decision.prereq_required);
                return Orig(writer, decision.required_stage);
            }
        }
        return Orig(writer, stage);
    }
};

}  // namespace

void installWorldMapSelectHook() {
    SMOAP_LOG_INFO("installing M7 Path A Layer 1 (menu-Id, 4 overloads)");
    softInstallAtSymbol<GetUnlockWorldIdHolderHook>(
        smoap::sym::kGameDataFunctionGetUnlockWorldIdForWorldMap_Holder);
    softInstallAtSymbol<GetUnlockWorldIdLayoutActorHook>(
        smoap::sym::kGameDataFunctionGetUnlockWorldIdForWorldMap_LayoutActor);
    softInstallAtSymbol<GetUnlockWorldIdSceneHook>(
        smoap::sym::kGameDataFunctionGetUnlockWorldIdForWorldMap_Scene);
    softInstallAtSymbol<GetUnlockWorldIdLiveActorHook>(
        smoap::sym::kGameDataFunctionGetUnlockWorldIdForWorldMap_LiveActor);

    SMOAP_LOG_INFO("installing M7 Path A Layer 2 (calcNextLocked, 2 overloads)");
    softInstallAtSymbol<CalcNextLockedWorldIdLayoutActorHook>(
        smoap::sym::kGameDataFunctionCalcNextLockedWorldIdForWorldMap_LayoutActor);
    softInstallAtSymbol<CalcNextLockedWorldIdSceneHook>(
        smoap::sym::kGameDataFunctionCalcNextLockedWorldIdForWorldMap_Scene);

    SMOAP_LOG_INFO("installing M7 Path A Layer 3 (tryChange backstops, 2)");
    softInstallAtSymbol<TryChangeDemoWorldWarpHook>(
        smoap::sym::kGameDataFunctionTryChangeNextStageWithDemoWorldWarp);
    softInstallAtSymbol<TryChangeWorldWarpHoleHook>(
        smoap::sym::kGameDataFunctionTryChangeNextStageWithWorldWarpHole);
}

}  // namespace smoap::hooks
