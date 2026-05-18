// HackEndParam — argument to `PlayerHackKeeper::endHack(HackEndParam const*)`.
//
// Layout reverse-engineered via EndHackProbeHook (M7-A Phase 1, 2026-05-17)
// from real bytes SMO passes on both forceKillHack-induced and voluntary-Y
// endHack calls. See plan can-we-move-the-lexical-brooks.md for the raw
// byte dumps.
//
// Cross-call invariants:
//   - Total size: 64 bytes (0x40)
//   - escapeScale (1.0f) at offset 0x34 — stable across all observed calls
//   - Mario's world position vec3 at offsets 0x28..0x33 — stable
//   - Bytes at 0x10, 0x18, 0x20 are INTERNAL PADDING:
//       * voluntary-Y call: tiny denormals (uninitialized stack garbage)
//       * forceKillHack-induced call: zero
//     → SMO does not read them. We can leave them uninitialized or zero them.
//   - Bytes at 0x0C, 0x14, 0x1C, 0x24 contain real data:
//       * Always 2 normalized 2D vectors (magnitude ≈ 1.0)
//       * Look like 2 (cos, sin) yaw/pitch pairs — Mario's facing direction
//
// Our Phase 2 construction strategy:
//   - Zero everything (matches the safer forceKillHack-induced byte pattern,
//     which SMO ALREADY accepted and released Mario cleanly from)
//   - Set escapeScale = 1.0f (matches both observed calls + matches the M8
//     polish note hypothesis)
//   - Leave rotation fields ZERO. The forceKillHack-induced dump showed SMO
//     accepting THAT call (which had its own non-zero rotation values) and
//     successfully releasing Mario. Our zero-rotation pattern is a SUBSET of
//     what forceKillHack does internally — if endHack reads these fields,
//     zero is a defined value (no NaN risk); if it doesn't, no behavior change.
//   - Position vec3 left zero. forceKillHack's bytes had real Mario coords
//     but Mario didn't teleport on uncapture, so it's likely SMO ignores this
//     field OR uses it as reference (zero is fine either way).
//
// Failure mode: if endHack reads any of these fields differently than
// forceKillHack and refuses to release Mario, CaptureStartHook's post-call
// re-verify (Phase 2d) catches it and falls back to s_forceKillHack for
// the rest of the session.

#pragma once

#include <cstddef>

namespace smoap::game {

struct HackEndParam {
    float vel[3];          // +0x00..0x0B  — observed zero in all dumps
    float rot_a_cos;       // +0x0C        — observed real cos(θ)
    float _pad0;           // +0x10        — internal padding
    float rot_a_sin;       // +0x14        — observed real sin(θ)
    float _pad1;           // +0x18        — internal padding
    float rot_b_cos;       // +0x1C        — observed real cos(φ)
    float _pad2;           // +0x20        — internal padding
    float rot_b_sin;       // +0x24        — observed real sin(φ)
    float pos[3];          // +0x28..0x33  — Mario's world position
    float escapeScale;     // +0x34        — observed 1.0f
    float _tail0;          // +0x38        — observed zero
    float _tail1;          // +0x3C        — observed zero
};

static_assert(sizeof(HackEndParam) == 0x40, "HackEndParam must be 64 bytes");
static_assert(offsetof(HackEndParam, rot_a_cos)   == 0x0C, "rot_a_cos @ 0x0C");
static_assert(offsetof(HackEndParam, rot_a_sin)   == 0x14, "rot_a_sin @ 0x14");
static_assert(offsetof(HackEndParam, rot_b_cos)   == 0x1C, "rot_b_cos @ 0x1C");
static_assert(offsetof(HackEndParam, rot_b_sin)   == 0x24, "rot_b_sin @ 0x24");
static_assert(offsetof(HackEndParam, pos)         == 0x28, "pos @ 0x28");
static_assert(offsetof(HackEndParam, escapeScale) == 0x34, "escapeScale @ 0x34");

}  // namespace smoap::game
