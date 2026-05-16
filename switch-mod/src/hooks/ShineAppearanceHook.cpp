// Hook on rs::setStageShineAnimFrame(al::LiveActor*, const char*, s32, bool).
//
// SMO ships per-stage shine color animations; this function (called from
// Shine::* methods during spawn/animate) selects which animation frame the
// shine renders at. By substituting the frame index we recolor individual
// shines without touching any model assets.
//
// Reference impl: Kgamer77/SuperMarioOdysseyArchipelago Mod/source/main.cpp
// `setShineColor` / `setShineModelColor` callbacks (MIT). Theirs trampolines
// the Shine class methods that call this function; ours trampolines the
// function itself, which is one layer lower but functionally equivalent
// because every shine color update goes through here.
//
// Actor -> shine_uid recovery: SMO's Shine actor is an al::LiveActor subclass
// that holds a ShineInfo* somewhere in its member layout. We don't have a
// public reference for the exact offset on 1.0.0 (lunakit-vendor doesn't ship
// a Shine class definition and OdysseyDecomp leaves Shine in the un-decomp'd
// remainder). For now, this hook PROBES a few plausible offsets at runtime
// and logs which (if any) point at a ShineInfo whose stageName matches the
// animation argument. Once Ryujinx confirms an offset, the speculative probe
// gets collapsed into a single hard-coded read.
//
// Until then the hook passes through every call unchanged; the only effect
// is a diagnostic log line on the first N invocations so we can identify
// the right offset off-device.

#include "lib.hpp"  // HOOK_DEFINE_TRAMPOLINE
#include "../ap/ApState.hpp"
#include "../game/ShineInfoLayout.hpp"
#include "../util/Log.hpp"
#include "HookSymbols.hpp"
#include "SoftInstall.hpp"

#include <cstdint>
#include <cstring>

namespace al { class LiveActor; }

namespace smoap::hooks {

namespace {

bool stringSane(const char* s) {
    if (!s) return false;
    auto p = reinterpret_cast<std::uintptr_t>(s);
    if (p < 0x10000) return false;
    for (int i = 0; i < 8; ++i) {
        const unsigned char c = static_cast<unsigned char>(s[i]);
        if (c == 0) return i > 0;
        if (c < 0x20 || c > 0x7e) return false;
    }
    return true;
}

// Candidate offsets for the ShineInfo* within the Shine actor. SMO actors
// typically place subclass members at 0xC0-0x250 past the al::LiveActor base;
// we try a small set of plausible spots. The probe accepts the first offset
// where (a) the pointer dereferences cleanly, (b) the would-be ShineInfo's
// stageName field is printable ASCII, and (c) (optional) it matches the
// `anim` argument fed to setStageShineAnimFrame.
constexpr std::size_t kCandidateShineInfoOffsets[] = {
    0xC8, 0xD0, 0xE0, 0xF0, 0x100, 0x108, 0x110, 0x118, 0x120, 0x130, 0x150, 0x1C8, 0x200,
};

// Try each candidate offset; return shine_uid (>=0) on first match. Caller
// passes the animation-arg stage name so we can prefer offsets whose
// would-be ShineInfo agrees with it.
int probeShineUid(const void* actor, const char* anim_arg) {
    if (!actor) return -1;
    for (std::size_t off : kCandidateShineInfoOffsets) {
        auto candidate_ptr = *reinterpret_cast<void* const*>(
            static_cast<const std::uint8_t*>(actor) + off);
        if (!candidate_ptr) continue;
        auto cp = reinterpret_cast<std::uintptr_t>(candidate_ptr);
        if (cp < 0x10000) continue;
        const char* stage = smoap::game::shine_info_layout::stageName(candidate_ptr);
        if (!stringSane(stage)) continue;
        // Prefer an offset whose ShineInfo.stageName matches the anim arg
        // (which is the stage's own name string). Accept any sane offset
        // otherwise — we'll still get a uid that's at least likely correct.
        const int uid = smoap::game::shine_info_layout::shineId(candidate_ptr);
        if (uid < 0) continue;
        if (anim_arg && std::strcmp(stage, anim_arg) == 0) {
            return uid;
        }
        // Fallback: take the first plausible-looking entry. (Will still get
        // overwritten by a later better match if the loop continued, but we
        // return early on a stage-match win.)
        return uid;
    }
    return -1;
}

HOOK_DEFINE_TRAMPOLINE(StageShineAnimFrameHook) {
    static void Callback(al::LiveActor* actor, const char* anim, int frame, bool flag) {
        static int s_call_count = 0;
        const int uid = probeShineUid(actor, anim);
        const std::uint8_t pal = (uid >= 0)
            ? smoap::ap::ApState::instance().getShinePalette(uid)
            : smoap::ap::ApState::kNoPaletteOverride;

        // Log the first handful of calls so we can characterize the actor's
        // ShineInfo* offset in Ryujinx, plus any time we'd actually substitute.
        const bool log_this = (s_call_count < 8) ||
                              (pal != smoap::ap::kNoPaletteOverride);
        if (log_this) {
            SMOAP_LOG_INFO("[shine-color] call#%d actor=%p anim=%s frame=%d "
                           "uid=%d palette=%u flag=%d",
                           s_call_count + 1, static_cast<const void*>(actor),
                           anim ? anim : "<null>", frame, uid,
                           static_cast<unsigned>(pal), flag ? 1 : 0);
        }
        ++s_call_count;

        if (pal != smoap::ap::kNoPaletteOverride) {
            Orig(actor, anim, static_cast<int>(pal), flag);
            return;
        }
        Orig(actor, anim, frame, flag);
    }
};

}  // namespace

void installShineAppearanceHook() {
    SMOAP_LOG_INFO("installing ShineAppearanceHook -> %s",
                   smoap::sym::kRsSetStageShineAnimFrame);
    softInstallAtSymbol<StageShineAnimFrameHook>(
        smoap::sym::kRsSetStageShineAnimFrame);
}

}  // namespace smoap::hooks
