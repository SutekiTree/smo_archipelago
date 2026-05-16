#include "KingdomUnlock.hpp"

#include <array>
#include <cstring>

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

}  // namespace smoap::game
