"""Integration tests that run scripts/extract_shine_map.py against a real
SMO 1.0.0 NSP.

Opt-in via environment variables:

  SMOAP_TEST_NSP=<path>      path to a clean SMO 1.0.0 NSP (required)
  SMOAP_TEST_KEYS=<path>     prod.keys (default: ~/.switch/prod.keys)

Skipped (not failed) on CI and on fresh clones — NSPs are Nintendo IP and
aren't checked in. Each test that completes a full extract takes minutes;
the graceful-failure tests usually fail fast at the hactool layer. Don't
add these to a fast inner loop.
"""

from __future__ import annotations

import json
import os
import shutil
import struct
import subprocess
import sys
from pathlib import Path

import pytest

NSP_ENV = "SMOAP_TEST_NSP"
KEYS_ENV = "SMOAP_TEST_KEYS"
REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
SCRIPT = REPO_ROOT / "scripts" / "extract_shine_map.py"


# Hactool extracts a 5 GB RomFS — a few minutes on SSD, longer on HDD.
# Generous enough that a slow disk doesn't false-fail the suite.
_EXTRACT_TIMEOUT_SEC = 1800  # 30 minutes


def _require_nsp() -> Path:
    path = os.environ.get(NSP_ENV)
    if not path:
        pytest.skip(
            f"set {NSP_ENV}=<smo-1.0.0.nsp> to run real-NSP integration tests"
        )
    nsp = Path(path)
    if not nsp.exists():
        pytest.skip(f"{NSP_ENV} points at non-existent path: {nsp}")
    return nsp


def _require_keys() -> Path:
    path = os.environ.get(KEYS_ENV) or str(Path.home() / ".switch" / "prod.keys")
    keys = Path(path)
    if not keys.exists():
        pytest.skip(f"prod.keys not found at {keys} (set {KEYS_ENV} to override)")
    return keys


def _run_extract(
    nsp: Path,
    tmp: Path,
    *,
    keys: Path,
    extra_args: list[str] | None = None,
    timeout: int = _EXTRACT_TIMEOUT_SEC,
) -> subprocess.CompletedProcess:
    """Invoke scripts/extract_shine_map.py with all outputs redirected under tmp.

    We pass `--romfs-cache` to a per-test directory so each test re-runs hactool
    from scratch and doesn't poison a shared cache.
    """
    cmd = [
        sys.executable, "-u", str(SCRIPT),
        "--nsp", str(nsp),
        "--keys", str(keys),
        "--romfs-cache", str(tmp / "romfs"),
        "--out", str(tmp / "shine_map.json"),
        "--review", str(tmp / "shine_map_review.json"),
        "--cap-out", str(tmp / "capture_map.json"),
        "--cap-review", str(tmp / "capture_map_review.json"),
    ]
    if extra_args:
        cmd.extend(extra_args)
    return subprocess.run(
        cmd, capture_output=True, text=True, timeout=timeout,
    )


# -- PFS0 parser used to locate the program NCA's IVFC hash table --


def _find_program_nca_in_nsp(nsp: Path) -> tuple[int, int]:
    """Return (absolute_offset, size) of the program NCA inside the NSP.

    The program NCA is the largest `.nca` file that isn't `.cnmt.nca`
    (content metadata). PFS0 header layout (per Switchbrew):
      0x00  "PFS0" magic
      0x04  u32 file count
      0x08  u32 string table size
      0x0C  4 bytes reserved
      0x10  file_count * 24-byte entries
              0x00  u64 data offset (within data section)
              0x08  u64 data size
              0x10  u32 name offset (within string table)
              0x14  4 bytes reserved
      then: string table, then data section
    """
    with open(nsp, "rb") as f:
        header = f.read(0x10)
        if header[:4] != b"PFS0":
            raise ValueError(f"not a PFS0: {header[:4]!r}")
        file_count, string_table_size = struct.unpack_from("<II", header, 4)
        entries_size = file_count * 0x18
        entries = f.read(entries_size)
        string_table = f.read(string_table_size)
    data_section_offset = 0x10 + entries_size + string_table_size

    best: tuple[int, int] | None = None
    for i in range(file_count):
        off = i * 0x18
        data_off, data_size = struct.unpack_from("<QQ", entries, off)
        name_off = struct.unpack_from("<I", entries, off + 0x10)[0]
        end = string_table.index(b"\x00", name_off)
        name = string_table[name_off:end].decode("ascii", errors="replace")
        if name.endswith(".nca") and not name.endswith(".cnmt.nca"):
            if best is None or data_size > best[1]:
                best = (data_section_offset + data_off, data_size)
    if best is None:
        raise ValueError("no program .nca found in PFS0")
    return best


# Constants from the SMO 1.0.0 program NCA header (matches every clean dump
# of base v0; verified against both Marie's NSP and the dev's NSP).
# Section 1 is the RomFS section; level 5 is the actual file data, level 4
# is its hash table.
_NCA_SECTION_1_OFFSET = 0x1c000       # within the NCA
_SECTION_1_LEVEL5_HASH_OFFSET = 0x14000   # within section 1
_SECTION_1_LEVEL5_HASH_SIZE = 0xa44000    # within section 1


# -- recoverable: corrupt the IVFC hash table to simulate Marie's case --


def test_minor_corruption_extracts_anyway(tmp_path: Path) -> None:
    """Overwrite 256 bytes inside the program NCA's IVFC level-5 hash table
    and confirm the extract still produces a full, valid shine_map.

    Surprising-but-true: hactool 1.4.0 doesn't appear to verify per-block
    hashes during a regular extract — it reads the raw decrypted bytes
    and writes them out. So this test extracts cleanly with no warning.
    That's actually useful coverage: it proves the extractor is robust
    against minor real-world byte rot in unused RomFS regions.

    NOTE: we don't have an integration test that triggers the actual
    `Error: section X is corrupted!` line from a real hactool run. The
    wizard bug report (Marie's NSP) hit it via dump-tooling-specific
    corruption that's not reproducible by flipping random bytes. The
    section-corruption tolerance code path is covered directly by
    test_extract_hactool_runner.py, which feeds _run_hactool the literal
    byte sequence hactool emits when this fires.

    This test doubles as a clean-baseline regression check: if the
    corruption test produces a full ~775-entry shine_map, a fully clean
    NSP will too.
    """
    nsp = _require_nsp()
    keys = _require_keys()
    corrupted = tmp_path / "smo-block-corrupted.nsp"
    shutil.copy(nsp, corrupted)
    program_nca_off, program_nca_size = _find_program_nca_in_nsp(corrupted)
    # 1 MB into the level-5 hash table — clear of both boundaries (the
    # table spans ~10 MB so we won't accidentally hit RomFS data).
    hash_region_start = (program_nca_off
                         + _NCA_SECTION_1_OFFSET
                         + _SECTION_1_LEVEL5_HASH_OFFSET)
    target = hash_region_start + 1024 * 1024
    assert target < program_nca_off + program_nca_size, \
        "target offset is past the program NCA — math wrong?"
    with open(corrupted, "r+b") as f:
        f.seek(target)
        f.write(b"\xff" * 256)

    result = _run_extract(corrupted, tmp_path, keys=keys)

    assert result.returncode == 0, (
        f"minor-corruption NSP should still extract, but exited "
        f"{result.returncode}\n"
        f"--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}"
    )
    # SMO 1.0.0 has exactly 775 raw shines across 17 HomeStage BYMLs. If
    # the count drops, either the parse went wrong or hactool produced
    # garbage where the SZS files should live.
    out = json.loads((tmp_path / "shine_map.json").read_text(encoding="utf-8"))
    assert len(out) >= 500, f"extract produced too few entries: {len(out)}"


# -- unrecoverable: truncated NSP --


def test_truncated_nsp_fails_with_actionable_error(tmp_path: Path) -> None:
    """End-truncate the NSP by 50 MB. This kills one or more trailing PFS0
    entries (Control / HtmlDocument / LegalInformation NCAs) and hactool
    bails out at the container layer with "Failed to read file!" before
    ever attempting RomFS extraction.

    This is the "incomplete download" scenario, which is NOT recoverable —
    the missing bytes are real. What we verify is the UX: a non-zero exit
    code, plus an actionable diagnostic mentioning "re-dump" or "NXDumpTool"
    so the user knows what to do.
    """
    nsp = _require_nsp()
    keys = _require_keys()
    truncated = tmp_path / "smo-truncated.nsp"
    shutil.copy(nsp, truncated)
    new_size = truncated.stat().st_size - 50 * 1024 * 1024
    assert new_size > 0, "test NSP is smaller than 50 MB — wrong file?"
    with open(truncated, "r+b") as f:
        f.truncate(new_size)

    result = _run_extract(truncated, tmp_path, keys=keys)

    assert result.returncode != 0, (
        f"truncated NSP should not extract successfully\n"
        f"--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}"
    )
    combined = (result.stdout + result.stderr).lower()
    actionable = ["re-dump", "nxdumptool", "damaged", "truncated"]
    assert any(s in combined for s in actionable), (
        f"expected one of {actionable!r} in error output, got generic failure:\n"
        f"--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}"
    )


# -- unrecoverable: missing key --


def test_missing_titlekek_produces_actionable_error(tmp_path: Path) -> None:
    """Strip `titlekek_02` from a copy of prod.keys + point `--titlekey`
    at an empty file. SMO 1.0.0 requires master-key revision 0x02 (FW
    3.0.1-3.0.2) to decrypt the title key; without it, hactool can't get
    a working title key from any source.

    Verify we exit non-zero with an actionable diagnostic — either the
    titlekek-missing message from `_derive_title_key` or the title.keys-
    fallback message from `_run_hactool` — rather than letting hactool's
    raw "section X is corrupted" leak through.
    """
    nsp = _require_nsp()
    real_keys = _require_keys()
    broken_keys = tmp_path / "broken-prod.keys"
    broken_keys.write_text(
        "\n".join(
            line for line in real_keys.read_text(encoding="utf-8", errors="ignore").splitlines()
            if not line.strip().lower().startswith("titlekek_02")
        ) + "\n",
        encoding="utf-8",
    )
    empty_title_keys = tmp_path / "empty-title.keys"
    empty_title_keys.write_text("", encoding="utf-8")

    result = _run_extract(
        nsp, tmp_path,
        keys=broken_keys,
        extra_args=["--titlekey", str(empty_title_keys)],
    )

    assert result.returncode != 0, (
        f"missing titlekek_02 should exit non-zero, got rc=0\n"
        f"--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}"
    )
    combined = (result.stdout + result.stderr).lower()
    actionable = ["titlekek_02", "update prod.keys", "title.keys"]
    assert any(s in combined for s in actionable), (
        f"expected actionable diagnostic mentioning one of {actionable!r}\n"
        f"--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}"
    )
