#include "KingdomUnlock.hpp"

#include <array>
#include <cstring>

#include "lib/nx/nx.h"          // Result, R_FAILED
#include "nn/ro.h"              // nn::ro::LookupSymbol
#include "../ap/ApState.hpp"
#include "../hooks/HookSymbols.hpp"
#include "../util/Log.hpp"

namespace smoap::game {

// Order matches apworld's kingdom progression. Kept as a simple flat table so
// it's trivially diffable when extending.
static constexpr std::array<const char*, 17> kKingdoms = {
    "Cap", "Cascade", "Sand", "Wooded", "Lake", "Cloud", "Lost",
    "Metro", "Snow", "Seaside", "Luncheon", "Ruined",
    "Bowser", "Moon", "Mushroom", "Dark Side", "Darker Side",
};

std::uint8_t kingdomBitFor(const char* kingdom) {
    if (!kingdom) return 0xff;
    for (std::uint8_t i = 0; i < kKingdoms.size(); ++i) {
        if (std::strcmp(kingdom, kKingdoms[i]) == 0) return i;
    }
    return 0xff;
}

const char* kingdomForBit(std::uint8_t bit) {
    if (bit >= kKingdoms.size()) return "";
    return kKingdoms[bit];
}

void installDepositKingdomLookupSymbol() {
    uintptr_t addr = 0;
    const Result rc = nn::ro::LookupSymbol(&addr,
        smoap::sym::kGameDataFunctionGetCurrentWorldIdNoDevelop);
    if (R_FAILED(rc)) {
        SMOAP_LOG_ERROR("getCurrentWorldIdNoDevelop lookup FAILED rc=0x%x — "
                        "AddPayShineHook will suppress all debits", rc);
        smoap::ap::ApState::instance().get_current_world_id_fn = nullptr;
        return;
    }
    smoap::ap::ApState::instance().get_current_world_id_fn = reinterpret_cast<void*>(addr);
    SMOAP_LOG_INFO("getCurrentWorldIdNoDevelop resolved @ 0x%lx", addr);
}

std::uint8_t kingdomBitForWorldId(int world_id) {
    // 0..16 maps mostly 1:1 to kKingdoms[], with the four swaps documented in
    // KingdomUnlock.hpp. Encoded as a constexpr table for trivial diffability.
    static constexpr std::uint8_t kWorldIdToBit[17] = {
        0,   // 0  Hat        -> Cap
        1,   // 1  Waterfall  -> Cascade
        2,   // 2  Sand       -> Sand
        3,   // 3  Forest     -> Wooded
        4,   // 4  Lake       -> Lake
        5,   // 5  Cloud      -> Cloud
        6,   // 6  Clash      -> Lost
        7,   // 7  City       -> Metro
        9,   // 8  Sea        -> Seaside (bit 9)   <-- SWAP
        8,   // 9  Snow       -> Snow    (bit 8)   <-- SWAP
        10,  // 10 Lava       -> Luncheon
        12,  // 11 Boss       -> Bowser  (bit 12)  <-- SWAP
        11,  // 12 Sky        -> Ruined  (bit 11)  <-- SWAP
        13,  // 13 Moon       -> Moon
        14,  // 14 Peach      -> Mushroom
        15,  // 15 Special1   -> Dark Side
        16,  // 16 Special2   -> Darker Side
    };
    if (world_id < 0 || world_id >= 17) return 0xff;
    return kWorldIdToBit[world_id];
}

}  // namespace smoap::game
