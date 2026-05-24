// Talkatoo% picker-exhaustion fix.
//
// PROBLEM: Phase 4's TalkatooSpeechHook substitutes Talkatoo's speech bubble
// with AP-pool moon names. But the vanilla picker `rs::calcShineIndexTableNameAvailable`
// (called from Poetter::exeWait BEFORE our substitute hook) walks
// `GameDataFile::isOpenShineName(world_id, idx)` for every vanilla index in
// the kingdom and counts how many return FALSE ("name not yet revealed").
// If the count is zero, Poetter shows the vanilla "No more hints now"
// terminal and `tryFindShineMessage` is never called — our substitute hook
// never gets a chance.
//
// PRIOR STRATEGY (2026-05-22): OR our `named_moons_bits` set into
// `isOpenShineName`, so AP-spoken moons render as "named" in the pause menu.
// This accelerated picker exhaustion: every Talkatoo visit called
// `markMoonNamed` on the spoken uid, so each subsequent visit had one fewer
// index the picker considered unnamed. After enough visits the picker
// returned 0 and Talkatoo said "No more hints" → bug.
//
// CURRENT STRATEGY (2026-05-23): hook the same getter but with INVERTED
// logic. Under `talkatoo_mode`, return FALSE unconditionally — the picker
// always sees a full pool and never exhausts. Vanilla state writes
// (whatever path Talkatoo uses to mutate the underlying bit — likely the
// inlined `rs::tryUnlockShineName` per our 2026-05-23 finding that the
// `rs::` wrapper isn't exported) become inert because every reader through
// this getter ignores the bit in talkatoo_mode.
//
// We also tried hooking the `rs::tryUnlockShineName(LiveActor*, s32)` writer
// directly. Both candidate manglings (non-const `PN` and const `PKN`) hung
// the boot inside HkTrampoline::installAtSym — symptom of the symbol being
// inlined into Poetter::exeWait and not exported in SMO 1.0.0 main.nso, so
// sail's fakelib stub resolved to a bogus address. The getter-side override
// avoids the problem entirely (well-exported class method).
//
// TRADEOFFS (pre-approved):
//   - Under talkatoo_mode the pause-menu Power Moon list shows NO moons
//     as "named" — vanilla picks, AP picks, and Hint-Toad reveals all
//     render unmarked. Same regression the OR-in approach traded off
//     differently.
//   - Achievement-hint reveals (which presumably ALSO check this getter)
//     forget they revealed. Harmless — the hint just shows again next time.
//   - The collection-block path in MoonGetHook is UNAFFECTED: it consults
//     `ApState::isMoonNamed` (our own bitset), not `GameDataFile::isOpenShineName`.
//
// tryUnlockShineName trampoline is kept as a PASS-THROUGH + log so we can
// see when non-Talkatoo paths fire (achievement-reveal, Hint-Toad). The
// 2026-05-22 user log captured exactly one suppress line per session,
// confirming SOME caller exists; logging passthrough preserves that
// observability without affecting state.
//
// FILE LAYOUT NOTES:
//   - findShine + sanitization helpers are kept (no harm; unused by the
//     new false-override path). Future iterations that want to map
//     world_id+idx → shine_uid for fancier logic can re-use them.
//   - 1b observability counters (g_obs_isopen_* arrays) are kept and still
//     emit per-100-call summaries under talkatoo_mode so we can confirm
//     the hook is firing in practice.

#include "hk/hook/Trampoline.h"
#include "hk/ro/RoUtil.h"
#include "hk/types.h"

#include <cstddef>
#include <cstdint>

#include "../ap/ApState.hpp"
#include "../game/KingdomUnlock.hpp"
#include "../util/Log.hpp"
#include "HookSymbols.hpp"

namespace smoap::hooks {

namespace {

// Cheap diagnostics gate — log the first time each hook fires under
// talkatoo_mode_on. Both demote silently after the first hit.
std::atomic<bool> g_logged_first_isopen{false};
std::atomic<bool> g_logged_first_tryunlock{false};

// Observability — per-kingdom counter of force-false overrides emitted by
// the isOpenShineName trampoline. Periodic summary every 100 calls confirms
// the override is firing during playtest and gives a sense of picker load.
// Frame-thread only; atomic only for visibility consistency with the rest
// of ApState.
constexpr std::size_t kObsKingdomCount = 17;
std::atomic<std::uint32_t> g_obs_isopen_called[kObsKingdomCount] = {};
std::atomic<std::uint32_t> g_obs_isopen_total_calls{0};

HkTrampoline<bool, const void*, int, int> isOpenShineNameHook =
    hk::hook::trampoline([](const void* self, int world_id, int index) -> bool {
        const bool talkatoo_mode_on =
            smoap::ap::ApState::instance().talkatoo_mode.load(
                std::memory_order_acquire);

        // Mode OFF: pass-through unchanged. Preserves the vanilla behaviour
        // (collected / achievement / Hint-Toad reveals all still mark
        // correctly in the pause menu).
        if (!talkatoo_mode_on) {
            return isOpenShineNameHook.orig(self, world_id, index);
        }

        // Mode ON: force-false override. The picker
        // `rs::calcShineIndexTableNameAvailable` walks this getter for every
        // vanilla index and counts indices where it returns false; returning
        // false unconditionally keeps the picker pool at full capacity so
        // Talkatoo never exhausts a kingdom. Vanilla state writes (the
        // inlined rs::tryUnlockShineName path) become inert through this
        // getter. Pause-menu mark regression is the pre-approved tradeoff.
        //
        // 1b observability — bump per-kingdom + total counters and emit a
        // periodic summary so we can confirm the override is firing during
        // playtest. With the new strategy, vanilla_true and ap_named_true
        // are no longer meaningful (we never call Orig and never check
        // ApState), so the summary just shows `called` per kingdom. We
        // keep the old field names so log-parsing tooling stays compatible.
        const std::uint8_t bit_raw = smoap::game::kingdomBitForWorldId(world_id);
        const std::size_t bit_obs =
            (bit_raw < kObsKingdomCount) ? bit_raw : (kObsKingdomCount - 1);
        g_obs_isopen_called[bit_obs].fetch_add(1, std::memory_order_relaxed);
        const auto total =
            g_obs_isopen_total_calls.fetch_add(1, std::memory_order_relaxed) + 1;

        bool expected = false;
        if (g_logged_first_isopen.compare_exchange_strong(
                expected, true, std::memory_order_relaxed)) {
            SMOAP_LOG_INFO("[talkatoo-menu] first force-false override: "
                           "world_id=%d index=%d bit=%u",
                           world_id, index, static_cast<unsigned>(bit_obs));
        }

        if ((total % 100) == 0) {
            SMOAP_LOG_INFO(
                "[talkatoo-obs:1b] isOpenShineName=false summary @ %u calls — "
                "world_id=%d bit=%u: called_this_bit=%u",
                total, world_id, static_cast<unsigned>(bit_obs),
                g_obs_isopen_called[bit_obs].load(std::memory_order_relaxed));
        }

        return false;
    });

// Pass-through + log. This class-method setter is hooked PRIMARILY for
// observability — the 2026-05-22 user log showed it fires exactly once per
// session under talkatoo_mode, meaning some non-Talkatoo path (achievement-
// reveal? Hint-Toad?) routes through here. Talkatoo itself uses the inlined
// `rs::tryUnlockShineName(LiveActor*, s32)` wrapper which doesn't go through
// this method (verified by symbol-lookup hangs on the rs:: wrapper).
//
// We DON'T need to suppress this write: the new isOpenShineName override
// returns false unconditionally in talkatoo_mode, so whatever bit this
// setter flips is inert as far as the picker / pause-menu reading-side is
// concerned. Letting Orig run preserves whatever non-Talkatoo system was
// depending on this state for non-Talkatoo behaviours.
//
// Return-value contract still matters: bool ("true if newly named"), used
// downstream as a "did the pick succeed?" signal. Pass-through naturally
// preserves Orig's value.
HkTrampoline<bool, void*, int, int> tryUnlockShineNameHook =
    hk::hook::trampoline([](void* self, int world_id, int index) -> bool {
        const bool orig_result =
            tryUnlockShineNameHook.orig(self, world_id, index);

        const bool talkatoo_mode_on =
            smoap::ap::ApState::instance().talkatoo_mode.load(
                std::memory_order_acquire);

        bool expected = false;
        if (g_logged_first_tryunlock.compare_exchange_strong(
                expected, true, std::memory_order_relaxed)) {
            SMOAP_LOG_INFO("[talkatoo-menu] first GameDataFile::"
                           "tryUnlockShineName passthrough: "
                           "world_id=%d index=%d orig=%d mode=%d",
                           world_id, index,
                           static_cast<int>(orig_result),
                           static_cast<int>(talkatoo_mode_on));
        }
        return orig_result;
    });

}  // namespace

void installTalkatooMenuMarkHook() {
    // findShine resolution removed 2026-05-23: the new force-false strategy
    // doesn't need to translate (world_id, idx) → shine_uid. The 2026-05-22
    // OR-in approach used findShine + readFixedSafeStringBuffer to consult
    // ApState::named_moons_bits, but that's now a dead path.
    SMOAP_LOG_INFO("installing TalkatooMenuMarkHook isOpenShineName -> %s",
                   smoap::sym::kGameDataFileIsOpenShineName);
    isOpenShineNameHook.installAtSym<
        "_ZNK12GameDataFile15isOpenShineNameEii">();

    SMOAP_LOG_INFO("installing TalkatooMenuMarkHook tryUnlockShineName -> %s",
                   smoap::sym::kGameDataFileTryUnlockShineName);
    tryUnlockShineNameHook.installAtSym<
        "_ZN12GameDataFile18tryUnlockShineNameEii">();
}

}  // namespace smoap::hooks
