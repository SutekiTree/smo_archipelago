// Read-only trampoline on PlayerHackKeeper::endHack(HackEndParam const*).
//
// Drives the M7-A follow-up planned in
// C:\Users\maxwe\.claude\plans\can-we-move-the-lexical-brooks.md (Phase 1).
//
// Two things we learn from this hook, both passively (no behavior change):
//
//   1. HackEndParam layout. CLAUDE.md's M8 polish note says SMO uses
//      `quat.w = 1.0f` + `escapeScale = 1.0f` with everything else zero, and
//      that the struct contains a `sead::Vector3f` (12 B) and a `sead::Quatf`
//      (16 B, possibly 16-aligned). The struct is NOT declared in any vendored
//      header — OdysseyDecomp has it in PlayerHackKeeper.h but we don't vendor
//      OdysseyDecomp. By logging the first 64 bytes SMO passes on every Y-press
//      we get an authoritative byte template: look for 0x3f800000 (1.0f) at
//      the offsets that match `quat.w` and `escapeScale`, infer padding /
//      alignment, then mirror that exact layout in Phase 2.
//
//   2. Per-cap cinematic duration. CaptureStartHook stamps
//      `ApState::last_capture_start_ms` + `last_capture_hack_name` right after
//      its Orig populates the keeper. The delta logged here is the empirical
//      "how long does Mario actually need to be captured before voluntary
//      release works cleanly" for each cap — direct ground truth for whether
//      the current 4 s `kDeferredKillMs` is too aggressive (Goomba), about
//      right (Sherm), or too short (T-Rex, Bowser).
//
// Lifecycle: install on game-thread (via softInstallAtSymbol in main.cpp).
// Trampoline Callback runs on the game frame thread (player Y-press inline);
// Orig is invoked first so any logging side effect can't perturb SMO's
// release path.
//
// Removal: this entire file is removable in Phase 2 once endHack-direct ships.
// Leaving it in won't hurt — it's read-only — but pruning keeps the log clean.

#include "lib.hpp"
#include "lib/nx/nx.h"
#include <cstddef>
#include <cstdint>

#include "../ap/ApState.hpp"
#include "../util/Log.hpp"
#include "HookSymbols.hpp"
#include "SoftInstall.hpp"

class PlayerHackKeeper;
struct HackEndParam;  // opaque to us — we treat *param as a const byte buffer

namespace smoap::hooks {

namespace {

// 64 bytes is enough headroom for sead::Vector3f (12) + sead::Quatf (16) +
// padding + escapeScale (4) + plausible extras. Aligned to keep the hex log
// line under 512 B (the Log buffer cap) with prefix + spaces: 64 * 3 + ~80 B
// ≈ 272 B per line.
constexpr std::size_t kDumpBytes = 64;

HOOK_DEFINE_TRAMPOLINE(EndHackProbeHook) {
    static void Callback(PlayerHackKeeper* self, const HackEndParam* param) {
        Orig(self, param);

        auto& st = smoap::ap::ApState::instance();

        // Phase 1.5c: belt-and-braces clear of pending_kill_keeper if SMO is
        // releasing the cap we'd queued for. Redundant with tickPendingUncapture's
        // re-verify (which would skip anyway when getCurrentHackName returns
        // null post-endHack), but makes the pending state observable the
        // instant SMO clears the capture rather than at the next deadline tick.
        // Self-pointer match — keeper is unique per player. Env-death paths
        // (Bullet Bill on a wall etc.) likely DON'T route through endHack;
        // those rely on the tickPendingUncapture name-check backstop instead.
        if (st.pending_kill_keeper.load(std::memory_order_acquire) == self) {
            st.pending_kill_keeper.store(nullptr, std::memory_order_release);
            st.pending_kill_hack_name[0] = '\0';
            SMOAP_LOG_INFO(
                "[hep] cleared pending forceKillHack — SMO endHack ran first "
                "(keeper=%p)", static_cast<void*>(self));
        }

        // (1) Timing delta. Only log if CaptureStartHook stamped a start.
        const std::int64_t start_ms =
            st.last_capture_start_ms.load(std::memory_order_acquire);
        if (start_ms != 0) {
            const std::int64_t now = smoap::ap::ApState::nowMs();
            const std::int64_t delta = now - start_ms;
            // Single-thread invariant: this Callback and CaptureStartHook's
            // Callback both run on the frame thread, so reading the char
            // buffer without synchronization is safe.
            SMOAP_LOG_INFO("[capture-timing] hack='%s' intro_to_end_ms=%lld",
                           st.last_capture_hack_name,
                           static_cast<long long>(delta));
            // Clear so we don't reuse a stale stamp if the player presses Y
            // somehow without a corresponding startHack having fired (defense
            // — shouldn't happen, but the log line would be misleading).
            st.last_capture_start_ms.store(0, std::memory_order_release);
        }

        // (2) HackEndParam bytes. Skip if SMO passes null (shouldn't, but
        // belt-and-braces — dereferencing would crash silently).
        if (!param) {
            SMOAP_LOG_INFO("[hep] param=NULL self=%p", static_cast<void*>(self));
            return;
        }

        const auto* b = reinterpret_cast<const std::uint8_t*>(param);
        // 16 bytes per row × 4 rows = 64 bytes total. Multi-line keeps each
        // log buffer comfortably under the 512 B cap and is easier to read
        // when grepping the Ryujinx log. Row offsets in the prefix let us
        // spot where `quat.w` (0x3f800000) and `escapeScale` (also 1.0f) land.
        SMOAP_LOG_INFO(
            "[hep] self=%p param=%p", static_cast<void*>(self),
            static_cast<const void*>(param));
        SMOAP_LOG_INFO(
            "[hep+00] %02x %02x %02x %02x  %02x %02x %02x %02x  "
            "%02x %02x %02x %02x  %02x %02x %02x %02x",
            b[0],  b[1],  b[2],  b[3],  b[4],  b[5],  b[6],  b[7],
            b[8],  b[9],  b[10], b[11], b[12], b[13], b[14], b[15]);
        SMOAP_LOG_INFO(
            "[hep+10] %02x %02x %02x %02x  %02x %02x %02x %02x  "
            "%02x %02x %02x %02x  %02x %02x %02x %02x",
            b[16], b[17], b[18], b[19], b[20], b[21], b[22], b[23],
            b[24], b[25], b[26], b[27], b[28], b[29], b[30], b[31]);
        SMOAP_LOG_INFO(
            "[hep+20] %02x %02x %02x %02x  %02x %02x %02x %02x  "
            "%02x %02x %02x %02x  %02x %02x %02x %02x",
            b[32], b[33], b[34], b[35], b[36], b[37], b[38], b[39],
            b[40], b[41], b[42], b[43], b[44], b[45], b[46], b[47]);
        SMOAP_LOG_INFO(
            "[hep+30] %02x %02x %02x %02x  %02x %02x %02x %02x  "
            "%02x %02x %02x %02x  %02x %02x %02x %02x",
            b[48], b[49], b[50], b[51], b[52], b[53], b[54], b[55],
            b[56], b[57], b[58], b[59], b[60], b[61], b[62], b[63]);
        static_assert(kDumpBytes == 64, "row breakdown above hard-codes 64 B");
    }
};

}  // namespace

void installEndHackProbeHook() {
    SMOAP_LOG_INFO("installing EndHackProbeHook -> %s",
                   smoap::sym::kPlayerHackKeeperEndHack);
    softInstallAtSymbol<EndHackProbeHook>(smoap::sym::kPlayerHackKeeperEndHack);
}

}  // namespace smoap::hooks
