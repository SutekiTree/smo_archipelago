# Building on Linux (Nix)

The Windows path uses the setup wizard (auto-installed LLVM/WinLibs under
`%LOCALAPPDATA%`) or a hand-installed toolchain — see
[`build-windows.md`](build-windows.md). On Linux the whole toolchain is
declared in [`flake.nix`](../flake.nix) instead; there is nothing to install
by hand and no wizard step:

```sh
nix develop
```

That shell provides everything the build and extraction scripts expect on
PATH:

| Tool | Why |
|---|---|
| clang/clang++ 19.1.x + ld.lld | Cross-compile for `aarch64-none-elf`. LibHakkun's libc++ is ABI-pinned to LLVM 19. The flake wraps nixpkgs' *unwrapped* clang with `-resource-dir` — a normal Nix-wrapped clang would inject host-glibc flags into the freestanding build. |
| gcc/g++ | Host compiler for sail (LibHakkun's symbol-DB tool). |
| cmake + ninja | Build drivers. |
| Python 3.12 with lz4, pyelftools, mmh3, pytest(-asyncio) | Hakkun's cmake glue shells out to bare `python` for `elf2nso.py` / `build_npdm.py`; the pytest pair runs the apworld test suite. |
| hactool | NSP/XCI → RomFS for `extract_shine_map.py`. |
| curl | `setup_libcxx_prepackaged.py` downloads Hakkun's prebuilt musl + libc++ tarball on first build. |

A `.envrc` (`use flake`) is included for direnv users.

## Build the Switch module

```sh
git submodule update --init --recursive   # --recursive: sys/tools/senobi is nested
nix develop

# One-time (and after changing data/items.json or data/locations.json):
python scripts/sync_capture_table.py
python scripts/sync_shine_table.py

python scripts/build_switchmod.py -DBRIDGE_HOST=<your PC's LAN IP>
```

`build_switchmod.py` detects the platform: on Linux it takes every tool from
PATH (failing fast with a `nix develop` hint if something is missing), builds
sail with the host g++, pre-downloads `lib/std/*.a`, and then runs the same
cmake configure+build as on Windows. Get your LAN IP with `ip -4 addr` (the
RFC-1918 address of your LAN interface).

Outputs land in `switch-mod/build/`:

- `switch-mod/build/exefs/subsdk9` + `main.npdm` — the module
- `switch-mod/build/sd/atmosphere/contents/0100000000010000/exefs/` — the
  same files pre-staged in SD-card layout

## Extract the moon / capture name maps

Same command as Windows — hactool and Python 3.12 come from the Nix shell:

```sh
python scripts/extract_shine_map.py --nsp <SMO_1.0.0.nsp>   # or --xci
```

`prod.keys` is expected at `~/.switch/prod.keys` (override with `--keys`).
The script bootstraps `scripts/.extract-venv/` (a pip venv with `oead`) on
first run; the flake's `LD_LIBRARY_PATH` export is what lets the manylinux
`oead` wheel load on NixOS. After extraction, re-run the two sync scripts
above so `capture_table.h` / `shine_table.h` pick up the real names, then
rebuild.

The maps are written to `apworld/smo_archipelago/client/data/` (gitignored —
Nintendo IP, never commit them). The client also probes
`~/.local/share/SMOArchipelago/data/` — the Linux equivalent of the wizard's
`%APPDATA%/SMOArchipelago/data/` — if you prefer keeping them out of the
tree.

## Deploy to Ryujinx

Ryujinx on Linux keeps its data under `~/.config/Ryujinx/` (or
`$XDG_CONFIG_HOME/Ryujinx`):

```sh
RYU=~/.config/Ryujinx/mods/contents/0100000000010000/smo-archipelago
mkdir -p "$RYU/exefs"
cp switch-mod/build/exefs/subsdk9 switch-mod/build/exefs/main.npdm "$RYU/exefs/"
```

For a real Switch, copy `switch-mod/build/sd/atmosphere/` onto the SD card
root (merging with the existing `atmosphere/` directory).

## Run the tests

```sh
nix develop --command python -m pytest apworld/smo_archipelago/tests/
```

The AP-server-dependent tests are gated behind `SMOAP_LIVE_AP=1` and the
extraction tests skip when the shine/capture maps are absent, so the suite
passes on a fresh checkout.

## What still assumes Windows

- The Kivy setup wizard's auto-installer pages (`_setup/installers.py`) —
  pointless under Nix; the prereq *detectors* are green inside `nix develop`.
- `scripts/setup_sail_winpath.py`, `scripts/*.ps1` — Windows-only helpers,
  not used by the Linux path.
- The C++ host tests' documented msys2 workflow (`smo-host-tests` skill);
  the tests themselves compile fine with the shell's g++.
