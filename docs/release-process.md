# Release process

For maintainers cutting a new SMO Archipelago release.

## TL;DR

```bash
git tag -a v0.2.0 -m "v0.2.0"
git push origin v0.2.0
```

`.github/workflows/release.yml` does the rest: builds the bundled
`meatballs.apworld`, computes a SHA-256, creates a GitHub Release with both
files attached, auto-generates the release notes from commit messages.

## What gets shipped

The release artifact is a single file, `meatballs.apworld`, plus a sidecar
`meatballs.apworld.sha256` for download verification. The .apworld is a normal
zip with three logical regions:

| Inside the zip | Source | What for |
|---|---|---|
| `meatballs/...` | `apworld/smo_archipelago/` (default install) | The apworld itself — items, locations, regions, hooks, SMOClient |
| `meatballs/_setup/switch_mod/...` | `switch-mod/` + LibHakkun (`sys/`) + OdysseyHeaders (`lib/OdysseyHeaders/`) submodules | C++ source tree the wizard compiles on the user's machine |
| `meatballs/_setup/scripts/...` | `scripts/extract_shine_map.py` + `sync_capture_table.py` + `sync_shine_table.py` + `build_switchmod.py` + `patch_hakkun.py` + `setup_sail_winpath.py` | Extractor + Switch-build wrappers the wizard invokes |

Size budget is about 25 MB compressed (most of it OdysseyHeaders + LibHakkun sources).

## What never gets shipped (IP discipline)

The release CI explicitly audits for these and fails the build if any leak
in:

- `shine_map.json` / `capture_map.json` (extracted Nintendo USen strings)
- `*_review.json` diagnostics that include those strings
- Any compiled NSO binary

The blocklist lives in `scripts/install_apworld.py::CLIENT_DATA_IP_BLOCKLIST`
and the CI gate is the `IP-discipline audit` step in
`.github/workflows/release.yml`. Keep both in sync if you add more
extractor outputs.

## Tag conventions

| Tag pattern | Result |
|---|---|
| `v1.0.0` | Full release. Marked stable in the GitHub Releases UI. |
| `v1.0.0-rc1`, `v0.2.0-alpha2`, etc. (any tag containing `-`) | Pre-release. Shown lower in the Releases UI; doesn't update "Latest". |
| Anything not matching `v*.*.*` | CI doesn't trigger. |

## Dry-running before tagging

The release workflow has `workflow_dispatch` enabled, so you can fire it
manually from the GitHub Actions UI without pushing a tag. The
`build-apworld` job runs end-to-end; the `publish-release` job skips
itself when there's no tag. Download the produced `smo-apworld` artifact
from the run page to inspect it.

To dry-run locally:

```pwsh
# Make sure submodules are populated
git submodule update --init --recursive

# Sync capture_table.h (release CI does this; needed for --bundle-mod)
python scripts/sync_capture_table.py

# Build the full release zip
python scripts/install_apworld.py --bundle-mod --bundle-scripts

# Output ends up at vendor/Archipelago/custom_worlds/meatballs.apworld
# Inspect with:
python -c "import zipfile; zipfile.ZipFile('vendor/Archipelago/custom_worlds/meatballs.apworld').printdir()"
```

## Pre-tag local audit

The `clean-windows-audit` CI job that used to gate `publish-release` was
disabled — cold-cache LLVM tar.xz downloads to `windows-2022` runners
consistently exceeded the job timeout, and `actions/cache` never
populated. The replacement is a local PowerShell harness that sandboxes
`%APPDATA%\SMOArchipelago\` + the switch-mod build dirs, narrows PATH to
the vendored toolchain, and runs `release_audit.py --all` against the
result.

**One-time setup** (after each fresh clone):

```pwsh
powershell -ExecutionPolicy Bypass -File scripts\install_hooks.ps1
```

This sets `core.hooksPath = .githooks` so the tracked `pre-push` hook is
picked up.

**What happens on tag push:** `git push origin v0.X.Y-alpha` triggers
`.githooks/pre-push`, which detects the tag refspec, runs
`scripts\local_release_audit.ps1`, and blocks the push if the audit
fails. Wall time: ~5–10 min on a warm-build machine (no toolchain
download; the build itself is the slow step).

**Run standalone any time:**

```pwsh
powershell -ExecutionPolicy Bypass -File scripts\local_release_audit.ps1
```

**Bypass (use sparingly — only if you've already audited manually):**

```pwsh
git push --no-verify origin v0.X.Y-alpha
```

The harness expects the wizard's portable LLVM + WinLibs to already be
installed at `%LOCALAPPDATA%\SMOArchipelago\{llvm,winlibs}\`. If either
is missing, it exits with a clear error pointing at the wizard's prereq
install step.

## Pre-release checklist

Before pushing a release tag, verify:

- `python -m pytest apworld/smo_archipelago/tests/` is green
- `SMOAP_LIVE_AP=1 SMOAP_GEN_TEST_FAST=1 python -m pytest apworld/smo_archipelago/tests/test_apworld_generation.py` is green
- `scripts\local_release_audit.ps1` exits clean (the pre-push hook runs
  this automatically; this line is for when you want to validate before
  even tagging)
- `docs/first-time-setup.md` reflects any prereq changes
- `CLAUDE.md` and the active plan file have been updated if architecture
  shifted

## Versioning

Semantic versioning where:

- **MAJOR** bumps on wire-protocol breaks (Switch mod ↔ SMOClient) — these
  force users to re-run setup, so flag prominently in release notes
- **MINOR** bumps on user-visible features (new logic options, new
  apworld items, new wizard pages, new commands)
- **PATCH** bumps on bug fixes, dependency updates, doc-only changes

The current version is implicit in the most-recent tag; bump from there.
There is no `__version__` constant we maintain outside the tag (we should
add one in a future cleanup; see TODO note in
`apworld/smo_archipelago/client/__init__.py`).

## Manual release (if CI is broken)

```pwsh
# Build the artifact locally as above
python scripts/install_apworld.py --bundle-mod --bundle-scripts

# Generate checksum
$hash = (Get-FileHash vendor\Archipelago\custom_worlds\meatballs.apworld -Algorithm SHA256).Hash.ToLower()
"$hash  meatballs.apworld" | Out-File -Encoding ascii meatballs.apworld.sha256

# Tag + push
git tag -a v0.2.0 -m "v0.2.0"
git push origin v0.2.0

# Create the release manually with gh
gh release create v0.2.0 `
    vendor/Archipelago/custom_worlds/meatballs.apworld meatballs.apworld.sha256 `
    --title "v0.2.0" `
    --generate-notes
```
