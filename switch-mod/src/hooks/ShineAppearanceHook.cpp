// Per-shine palette override via inline patches at 4 BL call sites inside
// Shine::init. Matches Kgamer77/SuperMarioOdysseyArchipelago's technique
// (MIT, codehook.slpatch) on SMO 1.0.0 — they redirect each BL to a wrapper;
// we use exlaunch's HOOK_DEFINE_INLINE to intercept before the BL fires and
// modify the color arg register in place.
//
// Why inline patches, not a symbol hook on rs::setStageShineAnimFrame?
// That function is called from MULTIPLE actor types (Shine AND
// ShineTowerRocket, observed live). Reading Shine-class fields off a
// non-Shine actor crashed in StageScene init. Patching inside Shine::init's
// body guarantees the actor IS a Shine, so we can safely read mShineIdx
// at the offset Kgamer77's Mod/include/game/Actors/Shine.h documents.
//
// 1.0.0 offsets (verified against main.nso by Kgamer77):
//   0x1cdce4 -> BL rs::setStageShineAnimFrame   (setShineColor pair 1)
//   0x1cdd3c -> BL rs::setStageShineAnimFrame   (setShineModelColor pair 1)
//   0x1cddcc -> BL rs::setStageShineAnimFrame   (setShineColor pair 2)
//   0x1cde24 -> BL rs::setStageShineAnimFrame   (setShineModelColor pair 2)
//
// At each site, the AArch64 ABI has:
//   X0 = Shine* self
//   X1 = const char* stageName
//   W2 = int color           <-- substitute this
//   W3 = bool flag

#include "lib.hpp"  // HOOK_DEFINE_INLINE, exl::hook::InlineCtx
#include "../ap/ApState.hpp"
#include "../util/Log.hpp"
#include "SoftInstall.hpp"

#include <cstdint>

namespace smoap::hooks {

namespace {

// Shine::mShineIdx offset per Kgamer77/SuperMarioOdysseyArchipelago
// Mod/include/game/Actors/Shine.h (MIT). Same value the bridge keys the
// palette table by — MoonGetHook reports it as ShineInfo::shineId for
// outbound checks, and Shine caches it locally on the actor.
inline constexpr std::size_t kShineMShineIdxOffset = 0x290;

// 1.0.0 BL call sites Kgamer77 patches in Shine::init. Same 4 offsets
// applied to our exlaunch InlineHook give us the same effect: substitute
// the color arg right before the BL fires.
inline constexpr ptrdiff_t kShineColorPatchOffsets[] = {
    0x1cdce4, 0x1cdd3c, 0x1cddcc, 0x1cde24,
};

HOOK_DEFINE_INLINE(ShineInitColorPatch) {
    static void Callback(exl::hook::InlineCtx* ctx) {
        // X0 is `this` (the Shine* about to be passed to setStageShineAnim
        // Frame). Sites are inside Shine::init so this cast is sound.
        const auto* self = reinterpret_cast<const std::uint8_t*>(ctx->X[0]);
        if (!self) return;
        const int uid = *reinterpret_cast<const int*>(
            self + kShineMShineIdxOffset);
        if (uid < 0 ||
            static_cast<std::size_t>(uid) >= smoap::ap::ApState::kMaxShineUid) {
            return;
        }
        const std::uint8_t pal = smoap::ap::ApState::instance().getShinePalette(uid);
        if (pal == smoap::ap::ApState::kNoPaletteOverride) return;

        // Log first few real substitutions so we can confirm in Ryujinx.
        // Per-shine, each Shine::init fires 2 of the 4 patches, so 2 fires
        // per moon is the natural rate — 16 substitutions covers ~8 shines.
        static int s_subst_count = 0;
        if (s_subst_count < 16) {
            SMOAP_LOG_INFO("[shine-color] subst#%d shine=%p uid=%d palette=%u",
                           s_subst_count + 1, ctx->X[0], uid,
                           static_cast<unsigned>(pal));
        }
        ++s_subst_count;
        ctx->W[2] = pal;  // substitute the color arg (zero-extends X2)
    }
};

}  // namespace

void installShineAppearanceHook() {
    for (ptrdiff_t off : kShineColorPatchOffsets) {
        SMOAP_LOG_INFO("installing ShineInitColorPatch @ +0x%lx",
                       static_cast<unsigned long>(off));
        ShineInitColorPatch::InstallAtOffset(off);
    }
}

}  // namespace smoap::hooks
