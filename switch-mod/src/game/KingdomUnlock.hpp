// Kingdom-unlock bit assignment.
//
// 17 kingdoms (Cap..Darker Side); we use the first 17 bits of
// ApState::received_kingdom_mask.

#pragma once

#include <cstdint>

namespace smoap::game {

std::uint8_t kingdomBitFor(const char* kingdom);
const char* kingdomForBit(std::uint8_t bit);

// M6 phase D — map SMO's internal world id (returned by
// GameDataFunction::getCurrentWorldIdNoDevelop) to our kKingdoms[] bit index.
// 17 kingdoms in total, but the SMO ordering DIFFERS from our kKingdoms[] in
// two places (verified against OdysseyDecomp's getWorldIndex* functions):
//
//   - SMO id 8  = Sea (Seaside)   → our bit 9  (Seaside)
//   - SMO id 9  = Snow            → our bit 8  (Snow)
//   - SMO id 11 = Boss (Bowser's) → our bit 12 (Bowser)
//   - SMO id 12 = Sky (Ruined)    → our bit 11 (Ruined)
//
// Other 13 ids are identity-mapped. Returns 0xff for out-of-range / unknown
// (caller treats as "kingdom-less" and suppresses any debit). Don't reorder
// kKingdoms[] — it's the canonical ordering used by the apworld and
// captureBitFor / kingdomBitFor for AP names.
std::uint8_t kingdomBitForWorldId(int world_id);

// M6 phase D — resolve GameDataFunction::getCurrentWorldIdNoDevelop via
// nn::ro::LookupSymbol once and store the function pointer on ApState. Same
// pattern as M6-B's addHackDictionary symbol bind. Called from main.cpp at
// module load; the AddPayShineHook callback reads the function pointer to
// resolve "which kingdom is Mario in" inside its hot path.
void installDepositKingdomLookupSymbol();

}  // namespace smoap::game
