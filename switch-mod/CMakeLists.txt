cmake_minimum_required(VERSION 3.16)

set(CMAKE_TOOLCHAIN_FILE "${CMAKE_SOURCE_DIR}/sys/cmake/toolchain.cmake")
project(smo_archipelago VERSION 1.0 LANGUAGES ASM C CXX)
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

include(config/config.cmake)

# ---------------------------------------------------------------------------
# Version + bridge defines. The strings land verbatim in HELLO + log lines
# so the bridge can correlate sessions.
#
# BRIDGE_HOST has NO default on purpose — it must be the LAN IP of the PC
# running SMOClient, and a stale default IP silently produces a binary that
# fails to TCP-fallback when UDP discovery misses. The wizard auto-detects
# the user's LAN IP and passes it via -DBRIDGE_HOST=...; manual / CI builds
# must pass it explicitly. See `.claude/skills/smo-build/SKILL.md` for the
# autodetect one-liner. Pass it like:
#   python scripts/build_switchmod.py -DBRIDGE_HOST=192.168.x.x
# ---------------------------------------------------------------------------
set(SMO_VERSION            "1.0.0"         CACHE STRING "Target SMO version")
set(SMO_AP_MOD_VERSION     "0.1.0"         CACHE STRING "Module version baked into HELLO")
set(BRIDGE_HOST            ""              CACHE STRING "PC LAN IP for the bridge (REQUIRED; pass -DBRIDGE_HOST=<ip>)")
set(BRIDGE_PORT            17777           CACHE STRING "Bridge TCP port")
set(BRIDGE_RETRY_MS        3000            CACHE STRING "Reconnect backoff seed (ms)")
set(BRIDGE_RECV_TIMEOUT_MS 200             CACHE STRING "Per-iteration recv timeout (ms)")
set(DISCOVERY_PORT         17776           CACHE STRING "UDP discovery probe port (Switch -> bridge; bridge -> Switch reply)")

if(NOT BRIDGE_HOST)
    message(FATAL_ERROR
        "BRIDGE_HOST is not set. Pass the PC's LAN IP at configure time:\n"
        "    python scripts/build_switchmod.py -DBRIDGE_HOST=192.168.x.x\n"
        "Get this machine's LAN IP via PowerShell:\n"
        "    (Get-NetIPAddress -AddressFamily IPv4 | Where-Object {\n"
        "        $_.IPAddress -notlike '169.254.*' -and $_.IPAddress -ne '127.0.0.1' -and\n"
        "        ($_.PrefixOrigin -eq 'Dhcp' -or $_.PrefixOrigin -eq 'Manual')\n"
        "    }).IPAddress\n"
        "The wizard auto-detects it; only manual / CI builds need to pass it.")
endif()

add_compile_definitions(
    SMO_VERSION_STRING="${SMO_VERSION}"
    SMO_AP_MOD_VERSION_STRING="${SMO_AP_MOD_VERSION}"
    BRIDGE_HOST_STRING="${BRIDGE_HOST}"
    BRIDGE_PORT_VALUE=${BRIDGE_PORT}
    BRIDGE_RETRY_MS_VALUE=${BRIDGE_RETRY_MS}
    BRIDGE_RECV_TIMEOUT_MS_VALUE=${BRIDGE_RECV_TIMEOUT_MS}
    DISCOVERY_PORT_VALUE=${DISCOVERY_PORT}
)

# Optional boot-time SD-card log capture. When ON, util/Log.cpp accumulates
# log output in an in-memory ring buffer and drains it once to
# sd:/smo_ap.txt at drawMain frame ~300 (~5s in). Diagnostic for cases
# where Ryujinx's svcOutputDebugString surface and Atmosphere's lm log
# are both invisible (the latter does NOT redirect to a per-title file
# on real Switch despite what older docs claimed). Off by default — the
# nn::fs link deps only resolve through sail when this is on.
option(SMOAP_DEBUG_SD_LOG "Enable boot-time SD-card log dump to sd:/smo_ap.txt" OFF)
if(SMOAP_DEBUG_SD_LOG)
    add_compile_definitions(SMOAP_DEBUG_SD_LOG=1)
endif()

file(GLOB_RECURSE SOURCES_ASM ${PROJECT_SOURCE_DIR}/src/*.S)
file(GLOB_RECURSE SOURCES_C ${PROJECT_SOURCE_DIR}/src/*.c)
file(GLOB_RECURSE SOURCES_CXX ${PROJECT_SOURCE_DIR}/src/*.cpp)
set(SOURCES ${SOURCES_ASM} ${SOURCES_C} ${SOURCES_CXX})
add_executable(${PROJECT_NAME} ${SOURCES})

# OdysseyHeaders provides SMO's class layouts (sead, al, agl, game, nn, nvn,
# vapours, etc.). Linking the INTERFACE target propagates the include paths.
add_subdirectory(lib/OdysseyHeaders)
target_link_libraries(${PROJECT_NAME} PRIVATE OdysseyHeaders)

include(sys/cmake/module.cmake)
include(sys/cmake/deploy.cmake)
include(sys/cmake/sail.cmake)
usesail(${PROJECT_NAME})
