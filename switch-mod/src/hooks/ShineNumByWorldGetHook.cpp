// Hook on GameDataFunction::getGotShineNum(GameDataHolderAccessor, s32 worldId).
//
// Called by SMO for per-kingdom moon counts (kingdom menu, shine list, possibly
// some progression gates). We trampoline through orig() and DELIBERATELY DROP
// orig — only the AP-credit count for the matching kingdom is returned. See
// ShineNumGetHook.cpp for the design rationale (AP-only counting).
//
// M6 phase D audit (2026-05-17): per OdysseyDecomp src/System/GameDataFunction.h,
// the int parameter is `file_id` (save-slot index, default -1), NOT a world
// id. The function returns global lifetime collected from that save slot.
// Our existing `world_id` naming is misleading — what we receive is actually
// a save-slot id (typically -1 or 0). That's consistent with the M6 phase A
// finding that this hook never fires in normal Cascade play: SMO's per-world
// HUD reads `GameDataFile::getShineNum(world_id)` directly (inlined field
// access) and only calls this wrapper when something genuinely wants a save
// slot's global total.
//
// Kept hooked as defense — returning AP credit instead of vanilla's count is
// still the correct behavior if any code path does query us. Freeze on
// bridge-offline mirrors ShineNumGetHook for the same reason.

#include "lib.hpp"
#include "../ap/ApState.hpp"
#include "../game/KingdomUnlock.hpp"
#include "../util/Log.hpp"
#include "HookSymbols.hpp"
#include "SoftInstall.hpp"

struct GameDataHolderAccessor {
    void* mData;
};

namespace smoap::hooks {

namespace {

// M6 phase D: the int param is `file_id` (save slot) per OdysseyDecomp, not
// a world id. But since the function returns a GLOBAL count, and our only
// defensive purpose for hooking it is "return AP credit instead of vanilla
// count if anything ever calls us", we just sum all kingdoms' AP credit.
// The argument is ignored for the AP-credit calculation; we still call Orig
// with it so the trampoline's diagnostic logging stays meaningful.
int sumAllKingdomCredits() {
    int total = 0;
    auto& s = smoap::ap::ApState::instance();
    for (auto& a : s.ap_moons_kingdom) {
        total += a.load(std::memory_order_relaxed);
    }
    return total;
}

HOOK_DEFINE_TRAMPOLINE(ShineNumByWorldGetHook) {
    static int Callback(GameDataHolderAccessor accessor, int world_id) {
        const int orig = Orig(accessor, world_id);  // diagnostic + side effects
        auto& s = smoap::ap::ApState::instance();
        // M6 phase D — freeze on bridge-offline.
        if (!s.bridge_connected.load(std::memory_order_relaxed)) {
            return 0;
        }
        const int credit = sumAllKingdomCredits();
        const int bit = (world_id >= 0 && world_id < 17) ? world_id : -1;

        // Throttle: first 6 calls (we expect ~17 distinct world_ids being
        // queried at menu open, want at least a few) plus any change on
        // either side (so we catch local moon collects via orig AND AP
        // credit applications via credit).
        static int s_call_count = 0;
        static int s_last_returned[17] = {};
        static int s_last_orig[17] = {};
        static bool s_inited = false;
        if (!s_inited) {
            for (int i = 0; i < 17; ++i) { s_last_returned[i] = -1; s_last_orig[i] = -1; }
            s_inited = true;
        }
        const bool first_calls = (s_call_count < 6);
        const bool valid_bit = (bit >= 0 && bit < 17);
        const bool ret_changed = valid_bit && (credit != s_last_returned[bit]);
        const bool orig_changed = valid_bit && (orig != s_last_orig[bit]);
        if (first_calls || ret_changed || orig_changed) {
            const char* kname = (bit >= 0 && bit < 17)
                ? smoap::game::kingdomForBit(static_cast<std::uint8_t>(bit))
                : "<oob>";
            SMOAP_LOG_INFO("[m6-hook] getGotShineNum: worldId=%d (our "
                           "bit=%d, name=%s) smo_natural=%d credit=%d "
                           "returned (call#%d%s%s)",
                           world_id, bit, kname, orig, credit,
                           s_call_count + 1,
                           ret_changed && !first_calls ? " ap-changed" : "",
                           orig_changed && !first_calls ? " natural-changed" : "");
        }
        ++s_call_count;
        if (valid_bit) { s_last_returned[bit] = credit; s_last_orig[bit] = orig; }
        return credit;
    }
};

}  // namespace

void installShineNumByWorldGetHook() {
    SMOAP_LOG_INFO("installing ShineNumByWorldGetHook -> %s",
                   smoap::sym::kGameDataFunctionGetGotShineNum);
    softInstallAtSymbol<ShineNumByWorldGetHook>(
        smoap::sym::kGameDataFunctionGetGotShineNum);
}

}  // namespace smoap::hooks
