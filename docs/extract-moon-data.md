# Extracting moon data (`shine_map.json`) from your SMO 1.0.0 dump

The bridge needs a `(stage_name, object_id) → (kingdom, shine_id)` table for
every moon in the game so `MoonGetHook` fires can be translated into
Archipelago `LocationCheck` messages. The data lives inside SMO's romfs and
is copyrighted — we can't ship it, so each user generates it locally on
first run.

## One command

From the repo root:

```pwsh
python scripts/extract_shine_map.py --nsp <path-to-SMO_1.0.0.nsp>
```

That writes:

- `bridge/smo_ap_bridge/data/shine_map.json` — the live lookup table (775 entries on 1.0.0).
- `bridge/smo_ap_bridge/data/shine_map_review.json` — diagnostic report.
- `.romfs-cache/` — extracted RomFS (~5 GB; reused on subsequent runs).
- `scripts/.extract-venv/` — Python 3.12 venv with `oead` (created once).

Both output files are gitignored. Re-running the script is fast (~5 s) since
the romfs and venv caches survive.

## Prereqs

The script self-bootstraps a Python 3.12 venv with `oead` — but you need the
following on disk first:

| Item | Default location | How to get |
|---|---|---|
| Python 3.12 | on the `py -3.12` launcher | `winget install -e --id Python.Python.3.12` |
| `hactool.exe` | PATH or `C:\Users\maxwe\Desktop\Switch\hactool.exe` | https://github.com/SciresM/hactool/releases |
| `prod.keys` | `~/.switch/prod.keys` | Lockpick_RCM on a hackable Switch |
| SMO 1.0.0 NSP | `--nsp` argument | dump from your own cart |

If your paths differ, override:

```pwsh
python scripts/extract_shine_map.py `
    --nsp     D:\dumps\SMO_1.0.0.nsp `
    --keys    D:\switch\prod.keys `
    --hactool D:\tools\hactool.exe
```

If you already have an unencrypted RomFS extracted (e.g. via Ryujinx's
"Dump RomFS" feature), skip hactool entirely:

```pwsh
python scripts/extract_shine_map.py --romfs <path-to-romfs-root>
```

## What the script does

1. **Bootstrap** (first run only, ~30 s): creates `scripts/.extract-venv/`
   from `py -3.12 -m venv`, installs `oead`, then re-execs itself in the venv.
2. **Romfs extract** (first run only, ~2 min): runs `hactool` twice — first
   to crack the NSP into PFS0 contents, then to extract RomFS from the
   largest NCA (the program NCA). Output lands in `.romfs-cache/`.
3. **Walk shine lists**: opens `SystemData/ShineInfo.szs` (Yaz0+SARC of
   17 BYML files, one `ShineList_<HomeStage>.byml` per kingdom). Each entry
   has `StageName`, `ObjId`, `UniqueId`, plus flags (`IsGrand`, `IsMoonRock`).
4. **Parse MSBT messages**: opens
   `LocalizedData/USen/MessageData/StageMessage.szs` (~201 `<StageName>.msbt`
   files). Each shine's display name is keyed `ScenarioName_<ObjId>` in the
   per-stage MSBT (NOT the HomeStage MSBT — sub-stages like `PushBlockExStage`
   own their own messages).
5. **Cross-validate against apworld**: every extracted `<Kingdom>: <Name>`
   should appear in `apworld/smo_archipelago/data/locations.json`. Mismatches
   are logged in the review file; misses are still emitted (the bridge
   handles unknown moons gracefully).

The MSBT parser is in-tree (no `pymsyt` — that tool only knows BotW's control
codes and chokes on SMO's). Moon names are plain text, so generically
stripping all `0x0E…` / `0x0F…` control sequences is enough.

## Expected output

```
raw shines:           775
resolved entries:     775  -> bridge/smo_ap_bridge/data/shine_map.json
  msbt misses:        0
  unknown home_stage: 0
  duplicate keys:     0
apworld moons:        436
  name mismatches:    339 (out-of-apworld-scope; still emitted)
  apworld unhit:      0
review report:        bridge/smo_ap_bridge/data/shine_map_review.json
```

- `apworld unhit: 0` is the success criterion — every moon the apworld asks
  about can be resolved live by the bridge.
- `name mismatches: 339` is expected: SMO has 775 moons, the apworld
  randomizes 436. The other 339 are story moons, racing-cup moons, Peach
  cameos, Dark/Darker Side, etc. — they're emitted into `shine_map.json`
  so the bridge can resolve them if a future apworld revision adds them.

## Troubleshooting

**`Python 3.12 not available via py -3.12`**

`winget install -e --id Python.Python.3.12`. The script needs 3.12 because
`oead` doesn't have prebuilt wheels for 3.13/3.14 yet.

**`hactool failed (exit N)`**

Most often a stale or wrong-version `prod.keys`. Re-dump with Lockpick_RCM
and confirm it has `header_key`, `key_area_key_application_*`, etc.
`hactool --disablekeywarns` is already passed; if you get key warnings
without `--disablekeywarns` they may be informational only.

**`apworld unhit > 0`**

A new SMO build (1.0.1, 1.1.0, etc.) shifted a moon name. Diff the unhit
list against the extracted candidates; the right fix is usually to update
`apworld/smo_archipelago/data/locations.json` to match Nintendo's MSBT
(MSBT is canonical — that's the string the player sees in-game).

**`raw shines < 775` on SMO 1.0.0**

Indicates one of the 17 `ShineList_<HomeStage>.byml` BYML files is missing
or malformed. Re-extract the romfs from a known-good NSP.

## Validating the result

```pwsh
cd bridge
.\.venv\Scripts\python -m pytest tests/test_shine_map_extraction.py -v
```

Five tests check the schema, count, dedup, and the M5.7 anchor entry
(`WaterfallWorldHomeStage / obj214 → "Cascade: Our First Power Moon"`).
They auto-skip when `shine_map.json` is missing (fresh checkout / CI).
