// M6 phase C: snapshot enumeration. Walks GameDataFile::mShineHintList and
// emits (stage_name, object_id, unique_id) for each owned shine into the
// caller-supplied callback. Worker-thread safe — no allocations, only raw
// pointer reads against in-game memory + one bound symbol call per slot.

#include "MoonApply.hpp"

#include <cstddef>
#include <cstdint>

#include "lib/nx/nx.h"           // Result, R_FAILED
#include "nn/ro.h"               // nn::ro::LookupSymbol
#include "../ap/ApState.hpp"
#include "../hooks/HookSymbols.hpp"
#include "../util/Log.hpp"

namespace smoap::game {

namespace {

// Layout offsets (verified against lunakit-vendor headers; comments cite the
// source line so future spot-checks land in seconds):

// GameDataHolder.h:94 — first non-vtable field is GameDataFile* mGameDataFile.
constexpr std::size_t kGameDataHolder_mGameDataFileOffset = 0x20;

// GameDataFile.h:463 — `HintInfo *mShineHintList; // 0x9A0`. Pointer to a
// dynamically-allocated array of HintInfo, one per known shine.
constexpr std::size_t kGameDataFile_mShineHintListOffset = 0x9A0;

// GameDataFile.h:86 — `static_assert(sizeof(HintInfo) == 0x238)`.
constexpr std::size_t kHintInfo_Size = 0x238;

// HintInfo fields (offsets from GameDataFile.h:57-83):
constexpr std::size_t kHintInfo_StageName  = 0x000;  // FixedSafeString<0x80>
constexpr std::size_t kHintInfo_ObjId      = 0x098;  // FixedSafeString<0x80>
constexpr std::size_t kHintInfo_UniqueID   = 0x1F0;  // int

// sead::FixedSafeString layout: vtable at +0x0, then `char* mBuffer` at +0x8
// pointing at the inline `mInlineBuffer` at +0x18. Reading mBuffer gives a
// const char* equivalent to FixedSafeString::cstr() — no symbol bind needed
// and no allocation.
constexpr std::size_t kSeadFixedSafeString_mBufferOffset = 0x08;

// lunakit's custom findShine(int shineUid) scans 0x400 entries unconditionally
// (see GameDataFile.h:362-369), so mShineHintList is sized for ≥ 0x400.
constexpr int kShineHintListScanCount = 0x400;

using IsGotShineByUidFn = bool (*)(const void* /* GameDataFile* this */, int);
IsGotShineByUidFn s_isGotShine = nullptr;

inline const char* readFixedSafeStringBuffer(const std::uint8_t* fss_addr) {
    return *reinterpret_cast<const char* const*>(
        fss_addr + kSeadFixedSafeString_mBufferOffset);
}

}  // namespace

void grantShine(const std::string& kingdom, const std::string& shine_id) {
    SMOAP_LOG_INFO("grantShine (stub): %s / %s", kingdom.c_str(), shine_id.c_str());
    // M6:
    //   GameDataHolder* gdh = al::tryGetGameDataHolder();
    //   if (!gdh) return;
    //   ShineId sid = mapShineId(kingdom, shine_id);
    //   if (gdh->isGetShine(sid)) return;
    //   gdh->setShineGet(sid);  // also bumps moon counter / opens gates
}

bool extractShineCoords(std::string& out_kingdom, std::string& out_shine_id) {
    out_kingdom.clear();
    out_shine_id.clear();
    return false;
}

void enumerateOwnedShines(ShineEnumerationCallback cb, void* ctx) {
    void* gdh = smoap::ap::ApState::instance().game_data_holder_cache.load(
        std::memory_order_relaxed);
    if (!gdh || !s_isGotShine) {
        SMOAP_LOG_WARN("[snapshot] enumerateOwnedShines skipped: gdh=%p sym=%p",
                       gdh, reinterpret_cast<void*>(s_isGotShine));
        return;
    }
    const auto* gdh_bytes = reinterpret_cast<const std::uint8_t*>(gdh);
    void* gdf = *reinterpret_cast<void* const*>(
        gdh_bytes + kGameDataHolder_mGameDataFileOffset);
    if (!gdf) {
        SMOAP_LOG_WARN("[snapshot] enumerateOwnedShines: GameDataFile* is null");
        return;
    }
    const auto* gdf_bytes = reinterpret_cast<const std::uint8_t*>(gdf);
    const auto* hint_base = *reinterpret_cast<const std::uint8_t* const*>(
        gdf_bytes + kGameDataFile_mShineHintListOffset);
    if (!hint_base) {
        SMOAP_LOG_WARN("[snapshot] enumerateOwnedShines: mShineHintList is null");
        return;
    }

    int scanned = 0;
    int emitted = 0;
    for (int i = 0; i < kShineHintListScanCount; ++i) {
        const std::uint8_t* h = hint_base + (i * kHintInfo_Size);
        const int uid = *reinterpret_cast<const int*>(h + kHintInfo_UniqueID);
        if (uid == 0) continue;  // unused slot
        ++scanned;
        if (!s_isGotShine(gdf, uid)) continue;
        const char* stage = readFixedSafeStringBuffer(h + kHintInfo_StageName);
        const char* obj   = readFixedSafeStringBuffer(h + kHintInfo_ObjId);
        if (!stage || !obj || !stage[0] || !obj[0]) continue;
        cb(ctx, stage, obj, uid);
        ++emitted;
    }
    SMOAP_LOG_INFO("[snapshot] enumerateOwnedShines scanned=%d emitted=%d",
                   scanned, emitted);
}

void installSnapshotSymbols() {
    uintptr_t addr = 0;
    Result rc = nn::ro::LookupSymbol(&addr, smoap::sym::kGameDataFileIsGotShineByUid);
    if (R_FAILED(rc)) {
        SMOAP_LOG_ERROR("isGotShine(int) lookup FAILED rc=0x%x", rc);
        return;
    }
    s_isGotShine = reinterpret_cast<IsGotShineByUidFn>(addr);
    SMOAP_LOG_INFO("isGotShine(int) resolved @ 0x%lx", addr);
}

}  // namespace smoap::game
