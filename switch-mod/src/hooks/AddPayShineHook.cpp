// Hook on GameDataFunction::addPayShine(GameDataHolderWriter, s32).
//
// This is THE chokepoint for moon "spend" in SMO. When Mario hand-tosses a
// moon at an Odyssey, vanilla does NOT decrement mShineNum directly — it calls
// GameDataFile::addPayShine which monotonically grows a separate PayShineNum
// counter. getCurrentShineNum returns ShineNum - PayShineNum clamped to 0.
//
// We hook the public GameDataFunction wrapper (not the GameDataFile member,
// which is inlined into all callers in 1.0.0 main.nso). The wrapper is the
// canonical entry-point game code uses for per-toss payments.
//
// On each fire:
//   - read bridge_connected; if offline, SUPPRESS Orig (defensive — keeps
//     vanilla PayShine from drifting from our AP credit, although in
//     practice ShineNumGetHook returns 0 when offline so the Odyssey UI
//     refuses fuel and addPayShine never reaches us)
//   - resolve current kingdom via getCurrentWorldIdNoDevelop function
//     pointer
//   - call Orig so vanilla state stays consistent
//   - debit ap_moons_kingdom[currentKingdom_bit] by min(count, current
//     balance) — clamp at 0, preserves the per-kingdom-isolation invariant
//   - stamp a monotonic seq onto a Deposit message and push into the
//     pending-deposit ring; the worker thread picks it up in pumpOnce.

#include "lib.hpp"

#include "AddPayShineHook.hpp"

#include "../ap/ApClient.hpp"
#include "../ap/ApState.hpp"
#include "../game/KingdomUnlock.hpp"
#include "../util/Log.hpp"
#include "HookSymbols.hpp"
#include "SoftInstall.hpp"

#include <cstring>

// Minimal layout mirror. GameDataHolderWriter is a 1-pointer trivially-
// copyable wrapper (Itanium ABI passes in x0). Same shape as the one used
// by CaptureGate / addHackDictionary call sites.
struct GameDataHolderWriter   { void* mData; };
struct GameDataHolderAccessor { void* mData; };

namespace smoap::hooks {

namespace {

using GetCurrentWorldIdNoDevelopFn = int (*)(GameDataHolderAccessor);

// Resolve the current kingdom from cached game data holder. Returns -1 on
// any failure (no cached holder / unresolved fn / out-of-range world id).
// Caller treats -1 as "kingdom unknown → suppress debit".
int resolveCurrentKingdomBit() {
    auto& s = smoap::ap::ApState::instance();
    void* holder = s.game_data_holder_cache.load(std::memory_order_relaxed);
    if (!holder || !s.get_current_world_id_fn) return 0xff;
    auto fn = reinterpret_cast<GetCurrentWorldIdNoDevelopFn>(s.get_current_world_id_fn);
    GameDataHolderAccessor acc{holder};
    const int world_id = fn(acc);
    return smoap::game::kingdomBitForWorldId(world_id);
}

void copyKingdomField(char (&dst)[32], const char* src) {
    if (!src) { dst[0] = '\0'; return; }
    std::size_t i = 0;
    while (i + 1 < sizeof(dst) && src[i] != '\0') {
        dst[i] = src[i];
        ++i;
    }
    dst[i] = '\0';
}

HOOK_DEFINE_TRAMPOLINE(AddPayShineHook) {
    static void Callback(GameDataHolderWriter writer, int count) {
        auto& s = smoap::ap::ApState::instance();

        // Freeze: defensive — when bridge is offline, ShineNumGetHook returns
        // 0 so the Odyssey UI should refuse fuel before this hook is ever
        // reached. If somehow we fire anyway (scripted scenario, future code
        // path), SKIP Orig too so vanilla PayShine doesn't move out of sync
        // with our (zeroed) HUD.
        if (!s.bridge_connected.load(std::memory_order_relaxed)) {
            SMOAP_LOG_WARN("[m6-deposit] addPayShine count=%d BLOCKED (bridge offline)",
                           count);
            return;
        }

        // Resolve kingdom BEFORE Orig so a downstream hook that mutates
        // game data can't change the answer between resolution and debit.
        const std::uint8_t bit = static_cast<std::uint8_t>(resolveCurrentKingdomBit());

        Orig(writer, count);  // vanilla bumps PayShineNum

        if (bit >= 17) {
            SMOAP_LOG_WARN("[m6-deposit] suppressed: world_id unmapped (count=%d) "
                           "— cached holder=%p, fn=%p",
                           count,
                           smoap::ap::ApState::instance().game_data_holder_cache.load(std::memory_order_relaxed),
                           smoap::ap::ApState::instance().get_current_world_id_fn);
            return;
        }

        const int cur = s.ap_moons_kingdom[bit].load(std::memory_order_relaxed);
        const int debit = (count < cur) ? count : cur;  // clamp at 0
        if (debit > 0) {
            s.ap_moons_kingdom[bit].fetch_sub(debit, std::memory_order_relaxed);
        }

        const std::uint64_t seq = s.next_deposit_seq.fetch_add(1, std::memory_order_relaxed);
        smoap::ap::ApState::PendingDeposit pd{};
        pd.seq = seq;
        copyKingdomField(pd.kingdom, smoap::game::kingdomForBit(bit));
        pd.amount = debit;
        if (!s.pending_deposits.push(pd)) {
            // Ring full — the worker hasn't drained as fast as deposits are
            // arriving. Vanilla applied the debit already; we lose the
            // bridge-side notification for this one. Log loudly so we catch
            // a sustained backpressure pattern that suggests bumping the
            // ring size.
            SMOAP_LOG_WARN("[m6-deposit] DROPPED seq=%llu kingdom=%s count=%d "
                           "debit=%d (pending_deposits ring full)",
                           seq, smoap::game::kingdomForBit(bit), count, debit);
            return;
        }

        SMOAP_LOG_INFO("[m6-deposit] seq=%llu kingdom=%s(bit=%u) count=%d "
                       "debit=%d credit %d->%d",
                       seq, smoap::game::kingdomForBit(bit), bit,
                       count, debit, cur, cur - debit);
    }
};

// addPayShineCurrentAll — "pay everything in current kingdom" (probably used
// by kingdom-complete celebrations). The function takes no count, so we must
// compute the debit from our AP credit balance (debit-all-we-have semantics).
HOOK_DEFINE_TRAMPOLINE(AddPayShineAllHook) {
    static void Callback(GameDataHolderWriter writer) {
        auto& s = smoap::ap::ApState::instance();

        if (!s.bridge_connected.load(std::memory_order_relaxed)) {
            SMOAP_LOG_WARN("[m6-deposit] addPayShineCurrentAll BLOCKED (bridge offline)");
            return;
        }

        const std::uint8_t bit = static_cast<std::uint8_t>(resolveCurrentKingdomBit());

        Orig(writer);

        if (bit >= 17) {
            SMOAP_LOG_WARN("[m6-deposit-all] suppressed: world_id unmapped");
            return;
        }

        const int cur = s.ap_moons_kingdom[bit].load(std::memory_order_relaxed);
        if (cur <= 0) {
            // Nothing to debit — vanilla had natural moons but no AP credit.
            SMOAP_LOG_INFO("[m6-deposit-all] kingdom=%s no AP credit to debit",
                           smoap::game::kingdomForBit(bit));
            return;
        }
        s.ap_moons_kingdom[bit].fetch_sub(cur, std::memory_order_relaxed);

        const std::uint64_t seq = s.next_deposit_seq.fetch_add(1, std::memory_order_relaxed);
        smoap::ap::ApState::PendingDeposit pd{};
        pd.seq = seq;
        copyKingdomField(pd.kingdom, smoap::game::kingdomForBit(bit));
        pd.amount = cur;
        if (!s.pending_deposits.push(pd)) {
            SMOAP_LOG_WARN("[m6-deposit-all] DROPPED seq=%llu kingdom=%s amount=%d "
                           "(pending_deposits ring full)",
                           seq, smoap::game::kingdomForBit(bit), cur);
            return;
        }

        SMOAP_LOG_INFO("[m6-deposit-all] seq=%llu kingdom=%s(bit=%u) "
                       "debit=%d credit %d->0",
                       seq, smoap::game::kingdomForBit(bit), bit, cur, cur);
    }
};

}  // namespace

void installAddPayShineHook() {
    SMOAP_LOG_INFO("installing AddPayShineHook -> %s",
                   smoap::sym::kGameDataFunctionAddPayShine);
    softInstallAtSymbol<AddPayShineHook>(smoap::sym::kGameDataFunctionAddPayShine);
}

void installAddPayShineAllHook() {
    SMOAP_LOG_INFO("installing AddPayShineAllHook -> %s",
                   smoap::sym::kGameDataFunctionAddPayShineCurrentAll);
    softInstallAtSymbol<AddPayShineAllHook>(smoap::sym::kGameDataFunctionAddPayShineCurrentAll);
}

}  // namespace smoap::hooks
