// Hook on GameDataFile::initializeData(). Clears session dedupe state and
// requests a fresh HELLO replay from the bridge. Debounces a burst of
// initializeData calls that SMO emits for a single save-load event.

#include "hk/hook/Trampoline.h"
#include "hk/ro/RoUtil.h"
#include "hk/types.h"

#include <atomic>
#include <cstdint>

#include "../ap/ApClient.hpp"
#include "../ap/ApState.hpp"
#include "../ui/CappyMessenger.hpp"
#include "../util/Log.hpp"

class GameDataFile;

namespace smoap::hooks {

namespace {

std::atomic<std::uint64_t> g_fire_counter{0};
std::atomic<std::int64_t>  g_last_fire_ms{0};
std::atomic<std::int64_t>  g_last_side_effect_ms{0};
constexpr std::int64_t kSaveLoadDebounceMs = 500;

// BISECT phase 9: gutted lambda body. Only calls .orig(self). If this still
// crashes -> trampoline mechanism specifically for initializeData is the
// issue (the function's prologue or body interacts badly with the JIT).
// If survives -> our lambda body's code is the issue and we narrow further.
HkTrampoline<void, GameDataFile*> saveLoadHook =
    hk::hook::trampoline([](GameDataFile* self) -> void {
        saveLoadHook.orig(self);
    });

}  // namespace

void installSaveLoadHook() {
    SMOAP_LOG_INFO("installing SaveLoadHook -> GameDataFile::initializeData");
    saveLoadHook.installAtSym<"_ZN12GameDataFile14initializeDataEv">();
}

}  // namespace smoap::hooks
