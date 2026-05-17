"""Pure-function helpers for the wizard/launch handoff.

Lives in `client/` rather than `_setup/` because SMOClient (`client/main.py`)
imports these on every launch to decide where to find maps and whether
setup has happened. Keeping it here means SMOClient never has to import
the `_setup` package — which is important because `_setup.wizard` pulls
in Kivy.

Imported by:
  - `client/main.py`        for map search + the is_setup_complete check
                            consumed by the apworld root __init__.py's
                            launch_smo_client routing
  - `apworld/.../__init__.py` indirectly via re-export through client/main.py
"""

from __future__ import annotations

import os
from pathlib import Path


def _user_data_dir() -> Path:
    """Per-user data dir for wizard-generated maps.

    Mirrors `_setup.__init__.data_dir()` but without importing `_setup` —
    `_setup.wizard` would pull in Kivy and we don't want SMOClient startup
    blocked on Kivy availability for environments that should never see
    the wizard (e.g. headless AP generation host).
    """
    base = os.environ.get("APPDATA")
    if base:
        return Path(base) / "SMOArchipelago" / "data"
    return Path.home() / ".local" / "share" / "SMOArchipelago" / "data"


def _user_build_dir() -> Path:
    """Per-user build-output dir produced by the wizard's cmake step.

    `cmake/` subdir mirrors `_setup.build.run_cmake_*` which builds in
    `%APPDATA%/SMOArchipelago/build/cmake/`. Kept synced manually here
    because importing `_setup.build` would drag in extra modules unrelated
    to map loading.
    """
    base = os.environ.get("APPDATA")
    if base:
        return Path(base) / "SMOArchipelago" / "build" / "cmake"
    return Path.home() / ".local" / "share" / "SMOArchipelago" / "build" / "cmake"


def _resolve_map_path(explicit: str, filename: str) -> Path | None:
    """Locate a shine_map.json / capture_map.json file on the filesystem.

    Search order (first hit wins):
      1. `explicit` host.yaml / CLI override path
      2. `%APPDATA%/SMOArchipelago/data/<filename>` (where the setup
         wizard writes its extractor output)
      3. legacy bundled-with-source `client/data/<filename>` (dev-only;
         release zips do NOT contain these — they'd be Nintendo IP)

    Returning None means the caller falls through to the `from_package`
    lookup in `client/main.py` (importlib.resources inside the zip).
    On a release zip that also misses (we never ship extracted maps), at
    which point the maps are simply empty and SMOClient logs warnings
    when moons don't resolve — that's the "user hasn't run setup yet"
    signal.
    """
    if explicit:
        return Path(explicit)
    user_data = _user_data_dir() / filename
    if user_data.exists():
        return user_data
    here = Path(__file__).resolve().parent / "data" / filename
    return here if here.exists() else None


def is_setup_complete() -> bool:
    """Returns True iff the first-run setup has produced everything
    SMOClient needs to operate against a real Switch.

    The wizard's outputs land under `%APPDATA%/SMOArchipelago/`:
      - data/shine_map.json + capture_map.json (extracted from user's NSP)
      - build/cmake/subsdk9 + main.npdm        (compiled Switch mod)

    Called by `launch_smo_client` (in `apworld/.../__init__.py`) to route
    a `.smoap` double-click either to the wizard (first time) or straight
    into SMOClient (subsequent times). Also surfaced by the `/setup`
    slash command for explicit re-run.
    """
    data = _user_data_dir()
    build = _user_build_dir()
    needed = (
        data / "shine_map.json",
        data / "capture_map.json",
        build / "subsdk9",
        build / "main.npdm",
    )
    return all(p.exists() for p in needed)
