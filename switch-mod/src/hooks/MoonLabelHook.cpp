// M6 phase A.5 — Channel A: moon-get cutscene label substitution.
//
// Three trampolines, one per moon-cutscene state-machine entry point:
//   - StageSceneStateGetShine::exeDemoGet            (regular moons; layout @ self+0x20)
//   - StageSceneStateGetShineMain::exeDemoGetStart   (story moons;   layout @ self+0x40)
//   - StageSceneStateGetShineGrand::exeDemoGetStart  (grand shines;  layout @ self+0x40)
//
// Each Callback runs Orig (which lets SMO set up the vanilla "TxtScenario"
// pane on the cutscene's first nerve step), then if there's a fresh
// non-expired pending label from the bridge, overwrites the pane via
// al::setPaneStringFormat. Because we run AFTER Orig, our write wins.
//
// (StageSceneStateGetShineGrand::exeDemoGetFirst exists but is the
// multi-grand interstitial — it doesn't touch the title pane, so we
// don't hook it.)
//
// Provenance: layout offsets + pane name extracted by disassembling each
// call site against the real SMO 1.0.0 main.nso. See plan
// `~/.claude/plans/i-wrote-a-plan-fluffy-otter.md` "Phase 0 findings"
// for the objdump traces.

#include "lib.hpp"  // HOOK_DEFINE_TRAMPOLINE

#include "lib/nx/nx.h"  // Result, R_FAILED — via extern "C" wrapper
#include "nn/ro.h"

#include <cstdint>

#include "../ap/ApState.hpp"
#include "../util/Log.hpp"
#include "HookSymbols.hpp"
#include "SoftInstall.hpp"

namespace smoap::hooks {

namespace {

// Resolved at install time. Cached as a function pointer so the per-frame
// fast path doesn't pay another LookupSymbol cost. nullptr means the symbol
// didn't resolve — Channel A becomes a no-op (vanilla cutscene shows).
using SetPaneStringFormatFn = void (*)(void* /*iuse_layout*/,
                                       const char* /*pane*/,
                                       const char* /*fmt*/, ...);
SetPaneStringFormatFn g_set_pane_string_format = nullptr;

// SMO's own pane string for the moon-get cutscene title. Identical across
// Regular / Main / Grand demos (verified via disassembly: all three sites
// load 0x1820149 → "TxtScenario").
constexpr const char* kPaneName = "TxtScenario";

// Common helper called by each trampoline post-Orig. `layout_offset` is the
// offset within the cutscene-state object where the LayoutActor* sits.
// Per Phase 0 disassembly:
//   StageSceneStateGetShine::exeDemoGet  -> 0x20
//   StageSceneStateGetShineMain::start   -> 0x40
//   StageSceneStateGetShineGrand::start  -> 0x40
//
// LayoutActor inherits IUseLayout, with the IUseLayout subobject at offset
// 0x8 (per SMO's "add x9, x8, #0x8" pattern next to every setPaneString call).
void applyPendingLabel(void* self, std::size_t layout_offset) {
    if (g_set_pane_string_format == nullptr) return;  // helper not resolved
    if (self == nullptr) return;

    char buf[smoap::ap::kPendingMoonLabelCap];
    if (!smoap::ap::ApState::instance().tryTakePendingMoonLabel(buf)) {
        return;  // no fresh label, or already applied this cutscene
    }
    if (buf[0] == '\0') return;  // empty label = explicit clear, no-op

    auto* layout_actor = *reinterpret_cast<void* const*>(
        reinterpret_cast<const std::uint8_t*>(self) + layout_offset);
    if (layout_actor == nullptr) {
        SMOAP_LOG_WARN("[moon_label] no LayoutActor at self+0x%zx; dropping",
                       layout_offset);
        return;
    }
    // LayoutActor* -> IUseLayout*: +8 byte downcast per SMO's own code.
    void* iuse_layout = reinterpret_cast<void*>(
        reinterpret_cast<std::uint8_t*>(layout_actor) + 8);

    SMOAP_LOG_INFO("[moon_label] applying text='%s' on pane '%s' (layout=%p)",
                   buf, kPaneName, iuse_layout);
    // %s indirection: the bridge has already sanitized text but we still
    // route through a format-string `%s` arg so any literal % in the buffer
    // doesn't get treated as a format directive.
    g_set_pane_string_format(iuse_layout, kPaneName, "%s", buf);
}

HOOK_DEFINE_TRAMPOLINE(MoonGetLabelRegularHook) {
    static void Callback(void* self) {
        Orig(self);
        applyPendingLabel(self, 0x20);
    }
};

HOOK_DEFINE_TRAMPOLINE(MoonGetLabelMainHook) {
    static void Callback(void* self) {
        Orig(self);
        applyPendingLabel(self, 0x40);
    }
};

HOOK_DEFINE_TRAMPOLINE(MoonGetLabelGrandHook) {
    static void Callback(void* self) {
        Orig(self);
        applyPendingLabel(self, 0x40);
    }
};

}  // namespace

void installMoonLabelHook() {
    SMOAP_LOG_INFO("resolving M6-phase-A.5 cutscene label helper");
    std::uintptr_t addr = 0;
    const Result rc = nn::ro::LookupSymbol(&addr, smoap::sym::kAlSetPaneStringFormat);
    if (R_FAILED(rc) || addr == 0) {
        SMOAP_LOG_ERROR("[moon_label] LookupSymbol FAILED rc=0x%x sym=%s — "
                        "Channel A disabled (cutscenes will show vanilla)",
                        rc, smoap::sym::kAlSetPaneStringFormat);
    } else {
        SMOAP_LOG_INFO("[moon_label] setPaneStringFormat @ 0x%lx", addr);
        g_set_pane_string_format = reinterpret_cast<SetPaneStringFormatFn>(addr);
    }

    SMOAP_LOG_INFO("installing 3 M6-phase-A.5 MoonLabelHook trampolines");
    softInstallAtSymbol<MoonGetLabelRegularHook>(
        smoap::sym::kStageSceneStateGetShineExeDemoGet);
    softInstallAtSymbol<MoonGetLabelMainHook>(
        smoap::sym::kStageSceneStateGetShineMainExeDemoGetStart);
    softInstallAtSymbol<MoonGetLabelGrandHook>(
        smoap::sym::kStageSceneStateGetShineGrandExeDemoGetStart);
}

}  // namespace smoap::hooks
