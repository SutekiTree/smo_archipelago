"""First-time setup wizard for the SMO Archipelago client.

A user double-clicks a `.smoap` file → Archipelago Launcher routes to
`launch_smo_client` (registered in `apworld/smo_archipelago/__init__.py`) →
if setup hasn't been completed yet, the launcher spawns
`_setup.wizard.run_setup_wizard` instead of the regular SMOClient.

The wizard's job is to turn a fresh machine into one that can:
  - resolve raw SMO identifiers to apworld names (extract shine/capture maps
    from the user's own SMO 1.0.0 NSP — Nintendo IP cannot be shipped)
  - run a Switch module compiled for the user's bridge PC IP (bake the IP
    into `subsdk9` via the devkitPro/lunakit cross-compile)
  - deploy the result either to a real Switch's SD card or to Ryujinx's
    mods directory.

The packages here are organized so each step is independently testable:

  - `smoap_file.py`  — JSON metadata read/write (no I/O dependencies)
  - `net.py`         — LAN-IP autodetect
  - `prereqs.py`     — detect devkitPro, hactool, prod.keys, Python 3.12, …
  - `build.py`       — drive `cmake` + `extract_shine_map` + `sync_capture_table`
  - `deploy.py`      — copy outputs to SD card or Ryujinx
  - `wizard.py`      — Kivy multi-page UI (imports Kivy lazily so the rest
                       of the package stays importable on AP-gen hosts)

Output destinations on the user's machine (all under %APPDATA%, off-repo so
nothing accidentally enters version control):

  %APPDATA%/SMOArchipelago/data/{shine_map,capture_map}.json
  %APPDATA%/SMOArchipelago/build/{subsdk9,main.npdm,ap_config.json}
  %APPDATA%/SMOArchipelago/setup_state.json   ← remembers last deploy target
"""

from __future__ import annotations

import os
from pathlib import Path


def appdata_root() -> Path:
    """Per-user output root: `%APPDATA%/SMOArchipelago/` on Windows,
    `~/.local/share/SMOArchipelago/` elsewhere.

    Created on first access. Subdirs (`data/`, `build/`) are created by the
    individual modules that write into them.
    """
    base = os.environ.get("APPDATA")
    if base:
        root = Path(base) / "SMOArchipelago"
    else:
        root = Path.home() / ".local" / "share" / "SMOArchipelago"
    root.mkdir(parents=True, exist_ok=True)
    return root


def data_dir() -> Path:
    d = appdata_root() / "data"
    d.mkdir(parents=True, exist_ok=True)
    return d


def build_dir() -> Path:
    d = appdata_root() / "build"
    d.mkdir(parents=True, exist_ok=True)
    return d


def setup_state_path() -> Path:
    return appdata_root() / "setup_state.json"
