// M7 Path A — fork-cinematic kingdom-order gate.
//
// See production switch-mod's WorldMapSelectHook.cpp for the full design
// narrative. This port keeps logic identical and swaps HOOK_DEFINE_TRAMPOLINE
// → HkTrampoline + installAtSym.

#include "hk/hook/Trampoline.h"
#include "hk/types.h"

#include <cstdint>

#include "../ap/ApState.hpp"
#include "../game/KingdomOrderGate.hpp"
#include "../game/KingdomUnlock.hpp"
#include "../util/Log.hpp"

namespace smoap::hooks {

namespace {

struct GameDataHolderWriter { void* mData; };

constexpr bool kGateEnabled = true;

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
                       decision.required_kingdom_short ?
                           decision.required_kingdom_short : "(null)",
                       orig_world_id);
        return orig_world_id;
    }
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
        s_last_origin = origin;
        s_last_index = index;
        s_last_orig_id = orig_world_id;
    }
    return prereq_id;
}

void markVisitedFromStage(const char* origin, const char* stage) {
    if (!stage) return;
    const char* kingdom = smoap::game::kingdomShortFromHomeStage(stage);
    if (!kingdom) return;
    const std::uint8_t bit = smoap::game::kingdomBitFor(kingdom);
    if (bit >= 17) return;
    auto& st = smoap::ap::ApState::instance();
    const bool was_visited = st.isKingdomBitVisited(static_cast<int>(bit));
    if (!was_visited) {
        SMOAP_LOG_INFO("[wmap.%s] visited[%s] = true (stage='%s')",
                       origin, kingdom, stage);
    }
    st.markKingdomBitVisited(static_cast<int>(bit));
}

HkTrampoline<int, const void*, int> calcNextLockedLayoutHook =
    hk::hook::trampoline([](const void* p, int index) -> int {
        return substituteSlotWorldId("menu.NextLocked.Layout", index,
                                     calcNextLockedLayoutHook.orig(p, index));
    });

HkTrampoline<int, const void*, int> calcNextLockedSceneHook =
    hk::hook::trampoline([](const void* p, int index) -> int {
        return substituteSlotWorldId("menu.NextLocked.Scene", index,
                                     calcNextLockedSceneHook.orig(p, index));
    });

HkTrampoline<bool, GameDataHolderWriter, const char*> tryChangeDemoWarpHook =
    hk::hook::trampoline([](GameDataHolderWriter writer, const char* stage) -> bool {
        const char* final_stage = stage;
        const char* kingdom = stage ? smoap::game::kingdomShortFromHomeStage(stage)
                                     : nullptr;
        if (kGateEnabled && kingdom) {
            const auto decision = smoap::game::evaluateOrderGateForKingdom(kingdom);
            if (decision.blocked && decision.required_stage) {
                SMOAP_LOG_WARN("[wmap.tryChange.Demo] BACKSTOP substituting "
                               "stage='%s' -> '%s'",
                               stage, decision.required_stage);
                final_stage = decision.required_stage;
            }
        }
        markVisitedFromStage("tryChange.Demo", final_stage);
        return tryChangeDemoWarpHook.orig(writer, final_stage);
    });

HkTrampoline<bool, GameDataHolderWriter, const char*> tryChangeWarpHoleHook =
    hk::hook::trampoline([](GameDataHolderWriter writer, const char* stage) -> bool {
        markVisitedFromStage("tryChange.Hole", stage);
        return tryChangeWarpHoleHook.orig(writer, stage);
    });

}  // namespace

// Drain a pending PC /warp request (ApState::inbound_warp_pending) and teleport
// Mario to the requested hub home stage. Called every frame from drawMain.
//
// Uses tryChangeWarpHoleHook.orig() — the painting/portal warp — NOT
// DemoWorldWarp. DemoWorldWarp (the world-map selection cinematic) leaves
// GameDataHolder::mIsStageChanging == false, so when called from in-stage the
// sequence never picks the change up and nothing happens (observed in the
// 2026-06-19 Ryujinx log: both warp log lines fired but Mario didn't move).
// WorldWarpHole instead sets mIsStageChanging = true and returns success, which
// is what actually drives the transition from anywhere. Calling .orig() bypasses
// our own gate hook; the WorldWarpHole hook is visited-only (no redirect), so
// there's nothing to bypass beyond the visited-bit bookkeeping.
//
// This is still a pure stage change: it does NOT touch mUnlockWorldNum, so it
// never opens forward access (e.g. it can't unlock Moon to escape Bowser's).
// The player lands at a hub kingdom where the Odyssey works normally and can
// fly back to any *already-unlocked* kingdom to collect what they're missing,
// then return and clear the gate the intended way (beat the boss).
//
// The destination string was validated to a Switch-side allowlist when the
// "warp" message was decoded (ApClient), so warp_dest_stage is always a safe
// hub home stage here.
void tickPendingWarp() {
    auto& st = smoap::ap::ApState::instance();
    if (!st.inbound_warp_pending.load(std::memory_order_acquire)) return;
    void* gdh = st.game_data_holder_cache.load(std::memory_order_relaxed);
    if (!gdh) return;  // scene not ready yet — leave the flag set, retry next frame
    st.inbound_warp_pending.store(false, std::memory_order_release);

    // Snapshot the stage name onto the stack (socket worker wrote it before
    // setting the flag we just observed, so it's stable).
    char stage[sizeof(st.warp_dest_stage)];
    std::size_t i = 0;
    for (; i + 1 < sizeof(stage) && st.warp_dest_stage[i] != '\0'; ++i) {
        stage[i] = st.warp_dest_stage[i];
    }
    stage[i] = '\0';
    if (stage[0] == '\0') return;

    GameDataHolderWriter writer{gdh};
    const bool ok = tryChangeWarpHoleHook.orig(writer, stage);
    SMOAP_LOG_INFO("[warp] teleporting to '%s' (PC /warp) -> %s", stage,
                   ok ? "accepted" : "REJECTED (stage change already in flight)");
}

void installWorldMapSelectHook() {
    SMOAP_LOG_INFO("installing M7 Path A Layer 1 (calcNextLocked, 2 overloads)");
    calcNextLockedLayoutHook.installAtSym<
        "_ZN16GameDataFunction32calcNextLockedWorldIdForWorldMapEPKN2al11LayoutActorEi">();
    calcNextLockedSceneHook.installAtSym<
        "_ZN16GameDataFunction32calcNextLockedWorldIdForWorldMapEPKN2al5SceneEi">();

    SMOAP_LOG_INFO("installing M7 Path A Layer 2 (DemoWorldWarp backstop + visited)");
    tryChangeDemoWarpHook.installAtSym<
        "_ZN16GameDataFunction35tryChangeNextStageWithDemoWorldWarpE20GameDataHolderWriterPKc">();

    SMOAP_LOG_INFO("installing M7 Path A WorldWarpHole (visited-only, no gate)");
    tryChangeWarpHoleHook.installAtSym<
        "_ZN16GameDataFunction35tryChangeNextStageWithWorldWarpHoleE20GameDataHolderWriterPKc">();
}

}  // namespace smoap::hooks
