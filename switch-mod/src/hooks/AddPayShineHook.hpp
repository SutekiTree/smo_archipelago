// M6 phase D — moon deposit detection.
//
// Two hooks together cover all paths Mario can spend moons through:
//   - AddPayShineHook:    per-toss debit (the common case)
//   - AddPayShineAllHook: "pay current kingdom in full" (less common — kingdom
//                         clear celebrations and similar bulk-payment events)
//
// Both write a DepositMsg into ApState's pending_deposits ring for the
// worker thread to ship to the bridge. See AddPayShineHook.cpp for details.

#pragma once

namespace smoap::hooks {

void installAddPayShineHook();
void installAddPayShineAllHook();

}  // namespace smoap::hooks
