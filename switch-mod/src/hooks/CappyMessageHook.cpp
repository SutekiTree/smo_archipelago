// Hooks that intercept SMO's CapMessage text lookup path + runtime resolution
// of the rs:: CapMessage entry points used by CappyMessenger.
//
// Three pieces:
//
//   1. Four trampolines on the top-level MSBT lookup pair
//      (isExistLabelIn{Stage,System}Message + get{Stage,System}MessageString)
//      that CapMessageLayout::exeDelay calls. When the label matches
//      kArchipelagoLabel and CappyMessenger has a buffer ready, return
//      true / our UTF-16 buffer. Otherwise tail-call Orig.
//
//      Why these four and NOT MessageHolder::tryGetText: empirically (Ryujinx
//      2026-05-16) the layout uses these higher-level free functions directly
//      and bypasses MessageHolder::tryGetText. Hooking only the latter let
//      CapMessage render as "NULL" (no text found) with a near-zero duration
//      (calcShowTextTime(0)). All 4 hooks fire only for our magic label so
//      the per-call overhead is one strcmp.
//
//   2. installCappyMessengerSymbols(). Resolves rs::tryShowCapMessage
//      PriorityLow and rs::isActiveCapMessage via nn::ro::LookupSymbol and
//      hands the function pointers to CappyMessenger via setCappy
//      MessengerRsCalls. No trampolines on these — we call them, not the
//      other way around (same pattern as M6 phase B's addHackDictionary).
//
// If symbol resolution fails (theoretically impossible — verified in
// scripts/check_nso_symbols.py — but the soft-install pattern is a guard
// against unknown SMO versions), the function pointers stay null and
// CappyMessenger::tryPump short-circuits. Items still enqueue and the
// [cappy] enqueue log lines still emit — Switch-side observability for
// "did the bridge route this through?" stays intact.

#include "lib.hpp"
#include "lib/nx/nx.h"  // result.h via the extern "C" wrapper
#include "nn/ro.h"

#include "../ui/CappyMessenger.hpp"
#include "../util/Log.hpp"
#include "HookSymbols.hpp"
#include "SoftInstall.hpp"

// Opaque forward decl. We never deref these pointers — just pass them to
// Orig — so the layouts don't need to be known here.
namespace al { class IUseMessageSystem; }

namespace smoap::ui {
using TryShowCapMessagePriorityLowFn =
    bool (*)(const void*, const char*, int, int);
using IsActiveCapMessageFn = bool (*)(const void*);
void setCappyMessengerRsCalls(TryShowCapMessagePriorityLowFn tryShow,
                              IsActiveCapMessageFn isActive);
}  // namespace smoap::ui

namespace smoap::hooks {

namespace {

// One-time log gate so each unique label trip through our hook gets a single
// diagnostic line. Without throttling, the bool-existence-check fires on
// every frame of an active CapMessage and floods the log. We only really
// want to see when our magic label gets exercised.
bool s_logged_is_exist = false;
bool s_logged_get_str  = false;

// ---- isExistLabelInSystemMessage ----------------------------------------
HOOK_DEFINE_TRAMPOLINE(IsExistLabelInSystemMessageHook) {
    static bool Callback(const al::IUseMessageSystem* sys,
                         const char* mstxt,
                         const char* label) {
        const char16_t* sub =
            smoap::ui::CappyMessenger::instance().lookupSubstitution(label);
        if (sub) {
            if (!s_logged_is_exist) {
                SMOAP_LOG_INFO("[cappy-hook] isExistLabelInSystemMessage "
                               "mstxt='%s' label='%s' -> SYNTHESIZED true",
                               mstxt ? mstxt : "<null>", label);
                s_logged_is_exist = true;
            }
            return true;
        }
        return Orig(sys, mstxt, label);
    }
};

// ---- getSystemMessageString ---------------------------------------------
HOOK_DEFINE_TRAMPOLINE(GetSystemMessageStringHook) {
    static const char16_t* Callback(const al::IUseMessageSystem* sys,
                                    const char* mstxt,
                                    const char* label) {
        const char16_t* sub =
            smoap::ui::CappyMessenger::instance().lookupSubstitution(label);
        if (sub) {
            if (!s_logged_get_str) {
                SMOAP_LOG_INFO("[cappy-hook] getSystemMessageString "
                               "mstxt='%s' label='%s' -> SUBSTITUTED ourBuf",
                               mstxt ? mstxt : "<null>", label);
                s_logged_get_str = true;
            }
            return sub;
        }
        return Orig(sys, mstxt, label);
    }
};

// ---- isExistLabelInStageMessage (defensive — priority-low doesn't hit) --
HOOK_DEFINE_TRAMPOLINE(IsExistLabelInStageMessageHook) {
    static bool Callback(const al::IUseMessageSystem* sys,
                         const char* mstxt,
                         const char* label) {
        if (smoap::ui::CappyMessenger::instance().lookupSubstitution(label)) {
            return true;
        }
        return Orig(sys, mstxt, label);
    }
};

// ---- getStageMessageString (defensive) ----------------------------------
HOOK_DEFINE_TRAMPOLINE(GetStageMessageStringHook) {
    static const char16_t* Callback(const al::IUseMessageSystem* sys,
                                    const char* mstxt,
                                    const char* label) {
        const char16_t* sub =
            smoap::ui::CappyMessenger::instance().lookupSubstitution(label);
        if (sub) return sub;
        return Orig(sys, mstxt, label);
    }
};

}  // namespace

void installCappyMessageTextHooks() {
    // Two trampolines on the SYSTEM message accessor pair (used by
    // rs::tryShowCapMessagePriorityLow which passes isStageMessage=false).
    SMOAP_LOG_INFO("installing IsExistLabelInSystemMessageHook -> %s",
                   smoap::sym::kAlIsExistLabelInSystemMessage);
    softInstallAtSymbol<IsExistLabelInSystemMessageHook>(
        smoap::sym::kAlIsExistLabelInSystemMessage);
    SMOAP_LOG_INFO("installing GetSystemMessageStringHook -> %s",
                   smoap::sym::kAlGetSystemMessageString);
    softInstallAtSymbol<GetSystemMessageStringHook>(
        smoap::sym::kAlGetSystemMessageString);

    // Two more on the STAGE message accessor pair. Not strictly needed for
    // the priority-low path, but covers other rs:: variants that pass
    // isStageMessage=true (e.g. rs::tryShowCapMessageFromStageMsg). Cheap
    // — one strcmp per Cap-message text lookup.
    SMOAP_LOG_INFO("installing IsExistLabelInStageMessageHook -> %s",
                   smoap::sym::kAlIsExistLabelInStageMessage);
    softInstallAtSymbol<IsExistLabelInStageMessageHook>(
        smoap::sym::kAlIsExistLabelInStageMessage);
    SMOAP_LOG_INFO("installing GetStageMessageStringHook -> %s",
                   smoap::sym::kAlGetStageMessageString);
    softInstallAtSymbol<GetStageMessageStringHook>(
        smoap::sym::kAlGetStageMessageString);
}

void installCappyMessengerSymbols() {
    uintptr_t addr_tryShow = 0;
    const auto rc1 = nn::ro::LookupSymbol(&addr_tryShow,
        smoap::sym::kRsTryShowCapMessagePriorityLow);
    if (R_FAILED(rc1)) {
        SMOAP_LOG_ERROR("[cappy] LookupSymbol FAILED rc=0x%x sym=%s",
                        rc1, smoap::sym::kRsTryShowCapMessagePriorityLow);
        return;
    }
    SMOAP_LOG_INFO("[cappy] LookupSymbol OK @ 0x%lx sym=%s",
                   addr_tryShow, smoap::sym::kRsTryShowCapMessagePriorityLow);

    uintptr_t addr_isActive = 0;
    const auto rc2 = nn::ro::LookupSymbol(&addr_isActive,
        smoap::sym::kRsIsActiveCapMessage);
    if (R_FAILED(rc2)) {
        SMOAP_LOG_ERROR("[cappy] LookupSymbol FAILED rc=0x%x sym=%s",
                        rc2, smoap::sym::kRsIsActiveCapMessage);
        return;
    }
    SMOAP_LOG_INFO("[cappy] LookupSymbol OK @ 0x%lx sym=%s",
                   addr_isActive, smoap::sym::kRsIsActiveCapMessage);

    smoap::ui::setCappyMessengerRsCalls(
        reinterpret_cast<smoap::ui::TryShowCapMessagePriorityLowFn>(addr_tryShow),
        reinterpret_cast<smoap::ui::IsActiveCapMessageFn>(addr_isActive));
    SMOAP_LOG_INFO("[cappy] rs:: function pointers wired into CappyMessenger");
}

}  // namespace smoap::hooks
