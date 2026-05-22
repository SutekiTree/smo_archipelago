// On-Switch ImGui-backed debug console — see ApDebugConsole.hpp for the
// visibility rule. Mirrors the upstream Hakkun-Example imgui-branch
// pattern (2 MB sead::ExpHeap + ImGuiBackendNvn::tryInitialize, then
// NewFrame/Render/draw per frame).

#include "ApDebugConsole.hpp"

#include <atomic>
#include <cstdint>
#include <cstdio>
#include <cstring>

#include "../ap/ApDiscovery.hpp"
#include "../ap/ApState.hpp"
#include "../util/Log.hpp"

#ifdef SMOAP_HAS_IMGUI
// These headers only resolve once switch-mod/sys is bumped to the
// LibHakkun `imgui` branch and switch-mod/lib/imgui is checked out.
// See CMakeLists.txt — SMOAP_HAS_IMGUI is set when both addons are
// present at configure time.
#  include "imgui.h"
#  include "hk/gfx/ImGuiBackendNvn.h"

#  include <sead/heap/seadExpHeap.h>

#  include "al/Library/Memory/HeapUtil.h"
#  include "game/System/Application.h"
#  include "agl/common/aglDrawContext.h"
#endif

namespace smoap::ui {

namespace {

// Boot-time + connect-time grace windows (ms). See header comment.
constexpr std::int64_t kBootGraceMs       = 5000;
constexpr std::int64_t kDisconnectGraceMs = 5000;

// State machine inputs. Written from any thread; read by drawDebugConsole
// on the frame thread.
std::atomic<bool>         s_tcp_connected{false};
std::atomic<std::int64_t> s_last_connect_ms{0};
std::atomic<std::int64_t> s_boot_ms{0};

#ifdef SMOAP_HAS_IMGUI
sead::Heap* s_imgui_heap = nullptr;
bool        s_init_attempted = false;
bool        s_init_ok = false;
#endif

bool overlayShouldShow() {
    const std::int64_t boot_ms = s_boot_ms.load(std::memory_order_relaxed);
    if (boot_ms == 0) return false;  // initDebugConsole hasn't fired
    const std::int64_t now = ap::ApState::nowMs();
    const std::int64_t since_boot = now - boot_ms;
    if (since_boot < kBootGraceMs) return false;
    if (s_tcp_connected.load(std::memory_order_acquire)) return false;
    const std::int64_t last_conn = s_last_connect_ms.load(std::memory_order_relaxed);
    const std::int64_t since_disconnect =
        (last_conn == 0) ? since_boot : (now - last_conn);
    return since_disconnect > kDisconnectGraceMs;
}

#ifdef SMOAP_HAS_IMGUI
// Format an IP (host byte order: high octet in MSB) into out.
void formatIp(char* out, std::size_t cap, std::uint32_t ip_ho) {
    std::snprintf(out, cap, "%u.%u.%u.%u",
                  (ip_ho >> 24) & 0xFF, (ip_ho >> 16) & 0xFF,
                  (ip_ho >> 8)  & 0xFF, (ip_ho >> 0)  & 0xFF);
}

void renderOverlayWindow() {
    ap::DiscoveryReport rep{};
    ap::snapshotDiscoveryReport(rep);

    char self_ip_s[24]      = "?";
    char subnet_s[24]       = "/24";
    char mask_s[24]         = "?";
    if (rep.self_ip != 0) {
        formatIp(self_ip_s, sizeof(self_ip_s), rep.self_ip);
        formatIp(mask_s, sizeof(mask_s), rep.subnet_mask);
    }

    const auto& st = ap::ApState::instance();
    const bool tcp_up = s_tcp_connected.load(std::memory_order_acquire);
    const std::int64_t now = ap::ApState::nowMs();
    const std::int64_t since_boot = now - s_boot_ms.load(std::memory_order_relaxed);

    ImGui::SetNextWindowPos(ImVec2(20, 20), ImGuiCond_Always);
    ImGui::SetNextWindowSize(ImVec2(640, 360), ImGuiCond_FirstUseEver);
    constexpr int kFlags = ImGuiWindowFlags_NoMove
                         | ImGuiWindowFlags_NoCollapse
                         | ImGuiWindowFlags_NoFocusOnAppearing
                         | ImGuiWindowFlags_NoNav;
    if (!ImGui::Begin("Spicy Meatball Overdrive — debug", nullptr, kFlags)) {
        ImGui::End();
        return;
    }

    ImGui::Text("Connection: %s", tcp_up ? "OK (TCP up)" : "DISCONNECTED");
    ImGui::Text("Switch IP: %s   mask %s", self_ip_s, mask_s);
    ImGui::Text("Last sweep: probed=%u replies=%u  loopback=%s",
                static_cast<unsigned>(rep.probed_count),
                static_cast<unsigned>(rep.replies),
                rep.loopback_used ? "yes" : "no");
    if (rep.last_bridge_port != 0) {
        ImGui::Text("Last bridge reply: %s:%u  (at %lldms)",
                    rep.last_bridge_host, rep.last_bridge_port,
                    static_cast<long long>(rep.last_success_ms));
    } else {
        ImGui::Text("Last bridge reply: (none received yet)");
    }
    ImGui::Text("Uptime: %llds", static_cast<long long>(since_boot / 1000));
    ImGui::Separator();
    ImGui::Text("Recent log (last ~200 lines):");

    // 16 KiB scratch lives at file scope (NOT on the frame-thread stack
    // — drawMain's stack is shared with SMO's own rendering and we don't
    // want to push it close to a guard page). Only ever read by this
    // single per-frame callsite on the frame thread, so a static is safe.
    static char s_log_buf[16 * 1024];
    std::size_t log_len = 0;
    util::snapshotRecentLogs(s_log_buf, sizeof(s_log_buf) - 1, &log_len);
    s_log_buf[log_len] = '\0';

    ImGui::BeginChild("log_scroll", ImVec2(0, 0), false,
                      ImGuiWindowFlags_HorizontalScrollbar);
    ImGui::TextUnformatted(s_log_buf, s_log_buf + log_len);
    // Auto-scroll to bottom on every frame.
    if (ImGui::GetScrollY() >= ImGui::GetScrollMaxY() - 10.0f) {
        ImGui::SetScrollHereY(1.0f);
    }
    ImGui::EndChild();

    ImGui::End();
}
#endif  // SMOAP_HAS_IMGUI

}  // namespace

void notifyConnectChange(bool connected_now) {
    const bool was = s_tcp_connected.exchange(connected_now, std::memory_order_acq_rel);
    if (connected_now != was) {
        s_last_connect_ms.store(ap::ApState::nowMs(), std::memory_order_relaxed);
        SMOAP_LOG_INFO("[overlay] TCP %s -> %s",
                       was ? "up" : "down",
                       connected_now ? "up" : "down");
    }
}

void initDebugConsole() {
    s_boot_ms.store(ap::ApState::nowMs(), std::memory_order_release);
#ifdef SMOAP_HAS_IMGUI
    if (s_init_attempted) return;
    s_init_attempted = true;

    s_imgui_heap = sead::ExpHeap::create(
        2 * 1024 * 1024,                // 2 MiB — matches Hakkun-Example
        "ApImGuiHeap",
        al::getStationedHeap(),
        8,
        sead::Heap::cHeapDirection_Forward,
        false);
    if (!s_imgui_heap) {
        SMOAP_LOG_ERROR("[overlay] sead::ExpHeap::create failed; overlay disabled");
        return;
    }

    auto* backend = hk::gfx::ImGuiBackendNvn::instance();
    backend->setAllocator({
        [](::size sz, ::size align) -> void* {
            return s_imgui_heap->tryAlloc(sz, align);
        },
        [](void* p) -> void {
            if (s_imgui_heap) s_imgui_heap->free(p);
        },
    });
    if (!backend->tryInitialize()) {
        SMOAP_LOG_ERROR("[overlay] ImGuiBackendNvn::tryInitialize failed; overlay disabled");
        return;
    }
    s_init_ok = true;
    SMOAP_LOG_INFO("[overlay] ImGui NVN backend ready");
#else
    SMOAP_LOG_INFO("[overlay] built without SMOAP_HAS_IMGUI — debug overlay disabled");
#endif
}

void drawDebugConsole() {
#ifdef SMOAP_HAS_IMGUI
    if (!s_init_ok) return;
    if (!overlayShouldShow()) return;

    // Belt-and-braces null checks. Real HW has been observed to feed
    // mid-init draw frames where one of these is briefly null even
    // though Ryujinx makes them always-present. The Hakkun-Example
    // demo skips the checks; our overlay only fires when the player
    // is actively struggling, so taking a small per-frame cost to
    // avoid a NULL-deref crash is worth it.
    auto* app = Application::instance();
    if (!app || !app->mDrawSystemInfo) return;
    auto* drawContext = app->mDrawSystemInfo->drawContext;
    if (!drawContext) return;
    auto* cmdBuf = drawContext->getCommandBuffer();
    if (!cmdBuf) return;
    auto* nvnCmdBuf = cmdBuf->ToData()->pNvnCommandBuffer;
    if (!nvnCmdBuf) return;

    static bool s_logged_first_frame = false;
    if (!s_logged_first_frame) {
        s_logged_first_frame = true;
        SMOAP_LOG_INFO("[overlay] first visible frame — NVN cmd buf %p", nvnCmdBuf);
    }

    ImGui::NewFrame();
    renderOverlayWindow();
    ImGui::Render();

    hk::gfx::ImGuiBackendNvn::instance()->draw(ImGui::GetDrawData(), nvnCmdBuf);
#endif
}

}  // namespace smoap::ui
