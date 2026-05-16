// Lightweight logging.
//
// Writes to:
//   - SMO's debug output where available (sead::print)
//   - LunaKit's log buffer if loaded (so messages appear in its log window)
//   - sd:/atmosphere/contents/<TID>/logs/ap_<datetime>.log on init failure (M8)

#pragma once

#include <cstdarg>

namespace smoap::util {

enum class LogLevel { Debug, Info, Warn, Error };

void log(LogLevel lvl, const char* fmt, ...);

}  // namespace smoap::util

// Host-test builds (test_cappy_messenger.cpp, test_protocol.cpp, etc.) define
// SMOAP_HOST_TEST and link only the pure-logic .cpp files. Stub the macros to
// no-ops so we don't drag Log.cpp + every Switch dep in for tests.
#ifdef SMOAP_HOST_TEST
#  define SMOAP_LOG_DEBUG(...) ((void)0)
#  define SMOAP_LOG_INFO(...)  ((void)0)
#  define SMOAP_LOG_WARN(...)  ((void)0)
#  define SMOAP_LOG_ERROR(...) ((void)0)
#else
#  define SMOAP_LOG_DEBUG(...) ::smoap::util::log(::smoap::util::LogLevel::Debug, __VA_ARGS__)
#  define SMOAP_LOG_INFO(...)  ::smoap::util::log(::smoap::util::LogLevel::Info,  __VA_ARGS__)
#  define SMOAP_LOG_WARN(...)  ::smoap::util::log(::smoap::util::LogLevel::Warn,  __VA_ARGS__)
#  define SMOAP_LOG_ERROR(...) ::smoap::util::log(::smoap::util::LogLevel::Error, __VA_ARGS__)
#endif

namespace smoap::util {
// Mark FS as available. Call AFTER nn::fs::MountSdCardForDebug("sd") (done
// in GameSystemInit hook / DrawMain fallback). All log() calls before this
// are kept in the ring buffer and flushed on the next drainPendingToFile().
void markFsReady();

// Flush the ring buffer to sd:/atmosphere/contents/<TID>/smoap.log. MUST be
// called from a thread nn::fs accepts (frame thread). Call once per frame
// from inside drawMain — cheap when ring is empty.
void drainPendingToFile();
}  // namespace smoap::util
