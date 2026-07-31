#!/usr/bin/env python3
"""Import an already-archived prebuilt_hw config from another checkout of
this repo into this repo's own prebuilt_hw/<name>/.

Why this exists: prebuilt_hw/PLAN.md's sweep only ever archived BUILD
ARTIFACTS (binary_container_1.xsa, libadf.a, boot.pdi, ...) plus a
free-prose config.md -- never the actual src/include/aie_settings.hpp (and,
for one config, several other source files) that produced them. Restoring
an old config's artifacts into a live tree whose committed aie_settings.hpp
has since moved on to a DIFFERENT config's values left the source tree
silently inconsistent with the binary it was supposedly describing.

This script closes that gap by parsing the settings table every config.md
in this sweep already contains (see any prebuilt_hw/<name>/config.md for
the exact table shape this expects) and applying it to THIS repo's current
aie_settings.hpp as a template, via targeted line-level substitution -- not
a wholesale rewrite, so every comment/derivation/static_assert in the
template survives untouched. The result is written to
prebuilt_hw/<name>/snapshot/src/include/aie_settings.hpp: a verbatim,
ready-to-restore source file, not prose a human has to re-transcribe by
hand. restore_prebuilt_config.py (repo root) is the counterpart that
overlays this snapshot (plus the archived build/bsp artifacts) back onto
the live tree.

Usage:
    scripts/import_prebuilt_config.py --source /path/to/other/checkout/prebuilt_hw/<name>
    scripts/import_prebuilt_config.py --source /path/to/other/checkout/prebuilt_hw/<name> \\
        --name <override-name> \\
        --extra-file src/pl/sha256_hash/sha256_hash.hpp --extra-file src/pl/sha256_hash/sha256_hash.cpp \\
        --extra-source-root /path/to/other/checkout

--source is only ever READ from (cp -a copies out of it, this script never
writes there) -- safe to point at another checkout/worktree.

--extra-file is for configs whose config.md documents source changes
beyond aie_settings.hpp (e.g. a new kernel data type needing a generalized
HLS kernel) -- see config.md's "Repo changes required" section, if
present, for which files. Paths are repo-relative; read from
--extra-source-root (default: --source's grandparent, i.e. the other
checkout's own root) and copied verbatim into snapshot/<path>.

The sha256_hash PL kernel (+ its PS control glue + generator scripts,
HASH_KERNEL_FILES below) is handled automatically, NOT via --extra-file:
it was hardcoded to C_TYPE=int16 until HASH_KERNEL_GENERALIZATION_COMMIT
generalized it to any element width (see that commit's message and
int16_rowA10_colA10_colB10_N34/config.md's "Repo changes required"
section). Every C_TYPE=int16 config in this sweep was built one commit
before that generalization, using the hardcoded implementation -- silently
leaving today's generalized source in its snapshot would misdescribe what
actually produced that config's archived sha256_hash.xo (same drift
problem this whole script exists to close for aie_settings.hpp). This
script picks the matching era automatically from the config's parsed
C_TYPE (override with --hash-kernel-era if a future config needs something
else).
"""
import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import channel_consistency

REPO_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_SETTINGS = REPO_ROOT / "src/include/aie_settings.hpp"
PREBUILT_HW_DIR = REPO_ROOT / "prebuilt_hw"

# The commit that generalized the sha256_hash PL kernel (+ pl_hash_control
# + its two generator scripts) from a hardcoded C_TYPE=int16 assumption to
# a parameterized ELEMENT_BYTES one. Every config archived with
# C_TYPE=int16 was built one commit before this (the hardcoded
# implementation); confirmed byte-identical between that commit's parent
# and the actual build commit (ebbd184) via `git diff` -- no intervening
# commit touched these files. Anything else (currently just C_TYPE=int32)
# needs the generalized implementation this commit introduced.
HASH_KERNEL_GENERALIZATION_COMMIT = "bd75a47"
HASH_KERNEL_OLD_REF = f"{HASH_KERNEL_GENERALIZATION_COMMIT}~1"
HASH_KERNEL_FILES = [
    "src/pl/sha256_hash/sha256_hash.hpp",
    "src/pl/sha256_hash/sha256_hash.cpp",
    "src/ps/pl_hash_control.hpp",
    "src/ps/pl_hash_control.cpp",
    "scripts/gen_sha256_num_elements.py",
    "scripts/gen_golden_hash.py",
]


# ---------------------------------------------------------------------
# config.md table parsing
# ---------------------------------------------------------------------
def _row(field_pattern):
    return re.compile(r"\|\s*" + field_pattern + r"\s*\|([^\|]*)\|")


ROWA_COLA_COLB = re.compile(r"\|\s*`rowA`\s*/\s*`colA`\s*/\s*`colB`\s*\|\s*(\d+)\s*/\s*(\d+)\s*/\s*(\d+)\s*\|")
KERNEL_INSTANCES = re.compile(r"\|\s*`KERNEL_INSTANCES`\s*\|\s*(\d+)\s*\|")
TYPES = re.compile(r"\|\s*`A_TYPE`\s*/\s*`B_TYPE`\s*/\s*`C_TYPE`\s*\|\s*(\w+)\s*/\s*(\w+)\s*/\s*(\w+)\s*\|")
TILE = re.compile(r"\|\s*`TILE_M`\s*/\s*`TILE_K`\s*/\s*`TILE_N`\s*\|\s*(\d+)\s*/\s*(\d+)\s*/\s*(\d+)\s*\|")
REPEAT_N = re.compile(r"\|\s*`REPEAT_N`\s*\|\s*(\d+)\s*\|")
A_WORDS = re.compile(r"\|\s*`A_WORDS_INNER`/`OUTER`\s*\|\s*(\d+)\s*/\s*(\d+)")
B_WORDS = re.compile(r"\|\s*`B_WORDS_INNER`/`OUTER`\s*\|\s*(\d+)\s*/\s*(\d+)")
C_WORDS = re.compile(r"\|\s*`C_WORDS_INNER`/`OUTER`\s*\|\s*(\d+)\s*/\s*(\d+)")
AB_WORDS = re.compile(r"\|\s*`AB_WORDS_INNER`/`OUTER`\s*\|\s*(\d+)\s*/\s*(\d+)")
IMPL = re.compile(r"\|\s*Data-movement impl\s*\|\s*`(\w+)`")
USE_GMIO = re.compile(r"\|\s*`USE_GMIO_KERNEL`\s*\|\s*(defined|not defined)")
USE_STATIC_AB = re.compile(r"\|\s*`USE_STATIC_AB`\s*\|\s*(defined|not defined)")
USE_RELAY = re.compile(r"\|\s*`USE_MEMTILE_RELAY_CHAIN`\s*\|\s*(defined|not defined)")
TARGET_LINE = re.compile(r"`TARGET=(\w+)`")
KERNEL_NAME_LINE = re.compile(r"`KERNEL_NAME=(\w+)`")


def require(pattern, text, label, path):
    m = pattern.search(text)
    if not m:
        sys.exit(f"error: could not find '{label}' row in {path} -- config.md format may have changed, see this script's parsing regexes")
    return m


def parse_config_md(path: Path) -> dict:
    text = path.read_text()
    rowA, colA, colB = require(ROWA_COLA_COLB, text, "rowA/colA/colB", path).groups()
    (kernel_instances,) = require(KERNEL_INSTANCES, text, "KERNEL_INSTANCES", path).groups()
    a_type, b_type, c_type = require(TYPES, text, "A_TYPE/B_TYPE/C_TYPE", path).groups()
    tile_m, tile_k, tile_n = require(TILE, text, "TILE_M/K/N", path).groups()
    (repeat_n,) = require(REPEAT_N, text, "REPEAT_N", path).groups()
    impl_m = require(IMPL, text, "Data-movement impl", path)
    gmio_m = require(USE_GMIO, text, "USE_GMIO_KERNEL", path)
    static_ab_m = require(USE_STATIC_AB, text, "USE_STATIC_AB", path)
    relay_m = require(USE_RELAY, text, "USE_MEMTILE_RELAY_CHAIN", path)

    settings = {
        "rowA": int(rowA), "colA": int(colA), "colB": int(colB),
        "kernel_instances": int(kernel_instances),
        "a_type": a_type, "b_type": b_type, "c_type": c_type,
        "tile_m": int(tile_m), "tile_k": int(tile_k), "tile_n": int(tile_n),
        "repeat_n": int(repeat_n),
        "impl": impl_m.group(1),
        "use_gmio": gmio_m.group(1) == "defined",
        "use_static_ab": static_ab_m.group(1) == "defined",
        "use_relay": relay_m.group(1) == "defined",
    }

    for name, pat in (("a_words", A_WORDS), ("b_words", B_WORDS), ("c_words", C_WORDS), ("ab_words", AB_WORDS)):
        m = pat.search(text)
        settings[name] = (int(m.group(1)), int(m.group(2))) if m else None

    target_m = TARGET_LINE.search(text)
    kernel_name_m = KERNEL_NAME_LINE.search(text)
    settings["target"] = target_m.group(1) if target_m else "default"
    settings["kernel_name"] = kernel_name_m.group(1) if kernel_name_m else "gemm_blocked_kernel"

    return settings


# ---------------------------------------------------------------------
# aie_settings.hpp reconstruction (targeted line substitution, not a
# wholesale rewrite -- every comment/derivation in the template survives)
# ---------------------------------------------------------------------
def sub_one(text, pattern, replacement, label):
    new_text, n = re.subn(pattern, replacement, text, count=1)
    if n != 1:
        sys.exit(f"error: expected exactly 1 match substituting {label}, found {n} -- template may have drifted from this script's assumptions")
    return new_text


def set_define_state(text, macro, defined: bool, label):
    pattern = rf"^([ \t]*)(// )?#define {re.escape(macro)}\b"
    new_text, n = re.subn(
        pattern,
        lambda m: f"{m.group(1)}{'' if defined else '// '}#define {macro}",
        text, count=1, flags=re.MULTILINE,
    )
    if n != 1:
        sys.exit(f"error: expected exactly 1 match toggling {label}, found {n}")
    return new_text


def render_words_pair(name, inner, outer):
    return f"constexpr unsigned {name}_WORDS_INNER = {inner}, {name}_WORDS_OUTER = {outer};  // {inner}*{outer}={inner * outer}"


def reconstruct_aie_settings(template_text: str, s: dict, config_name: str) -> str:
    text = template_text

    text = sub_one(text, r"using A_TYPE = \w+;", f"using A_TYPE = {s['a_type']};", "A_TYPE")
    text = sub_one(text, r"using B_TYPE = \w+;", f"using B_TYPE = {s['b_type']};", "B_TYPE")
    text = sub_one(text, r"using C_TYPE = \w+;", f"using C_TYPE = {s['c_type']};", "C_TYPE")

    text = sub_one(text, r"constexpr int TILE_M = \d+;", f"constexpr int TILE_M = {s['tile_m']};", "TILE_M")
    text = sub_one(text, r"constexpr int TILE_K = \d+;", f"constexpr int TILE_K = {s['tile_k']};", "TILE_K")
    text = sub_one(text, r"constexpr int TILE_N = \d+;", f"constexpr int TILE_N = {s['tile_n']};", "TILE_N")

    text = sub_one(text, r"(constexpr unsigned rowA = )\d+(;)", rf"\g<1>{s['rowA']}\g<2>", "rowA")
    text = sub_one(text, r"(constexpr unsigned colA = )\d+(;)", rf"\g<1>{s['colA']}\g<2>", "colA")
    text = sub_one(text, r"(constexpr unsigned colB = )\d+(;)", rf"\g<1>{s['colB']}\g<2>", "colB")

    text = sub_one(text, r"#define KERNEL_INSTANCES \d+", f"#define KERNEL_INSTANCES {s['kernel_instances']}", "KERNEL_INSTANCES")

    text = sub_one(text, r"constexpr unsigned REPEAT_N = \d+;", f"constexpr unsigned REPEAT_N = {s['repeat_n']};", "REPEAT_N")

    for name in ("A", "B", "C", "AB"):
        key = f"{name.lower()}_words"
        pair = s[key]
        if pair is None:
            # config.md didn't list an override -- only valid if this
            # config's rowA matches the template's own checked-in rowA
            # (the factor pairs are only ever a function of rowA/colA/colB
            # for a fixed A/B/C_TYPE+TILE combo), otherwise the template's
            # stale factors would silently miscompile/underrun DMA wraps.
            template_rowa = int(require(re.compile(r"constexpr unsigned rowA = (\d+);"), template_text, "rowA (template)", TEMPLATE_SETTINGS).group(1))
            if s["rowA"] != template_rowa:
                sys.exit(
                    f"error: {config_name}'s config.md has no {name}_WORDS_INNER/OUTER row, but "
                    f"its rowA ({s['rowA']}) differs from the template's ({template_rowa}) -- "
                    f"cannot safely reuse the template's factor pair. Add the row to config.md "
                    f"or pass it explicitly."
                )
            continue
        inner, outer = pair
        pattern = rf"constexpr unsigned {name}_WORDS_INNER = \d+, {name}_WORDS_OUTER = \d+;[^\n]*"
        text = sub_one(text, pattern, render_words_pair(name, inner, outer), f"{name}_WORDS_INNER/OUTER")

    text = set_define_state(text, "USE_GMIO_KERNEL", s["use_gmio"], "USE_GMIO_KERNEL")
    text = set_define_state(text, "USE_STATIC_AB", s["use_static_ab"], "USE_STATIC_AB")
    text = set_define_state(text, "USE_MEMTILE_RELAY_CHAIN", s["use_relay"], "USE_MEMTILE_RELAY_CHAIN")

    impl = s["impl"]
    if impl not in ("USE_ONCHIP_REPETITION", "USE_CHUNK_PIPELINE", "USE_DIRECT_BROADCAST"):
        sys.exit(f"error: unrecognized data-movement impl '{impl}' parsed from config.md")
    for candidate in ("USE_ONCHIP_REPETITION", "USE_CHUNK_PIPELINE", "USE_DIRECT_BROADCAST"):
        text = set_define_state(text, candidate, candidate == impl, candidate)

    return text


# ---------------------------------------------------------------------
# sha256_hash kernel era (hardcoded-int16 vs generalized) auto-selection
# ---------------------------------------------------------------------
def git_show(ref: str, rel_path: str) -> bytes:
    result = subprocess.run(
        ["git", "show", f"{ref}:{rel_path}"],
        cwd=REPO_ROOT, capture_output=True,
    )
    if result.returncode != 0:
        sys.exit(f"error: 'git show {ref}:{rel_path}' failed: {result.stderr.decode(errors='replace')}")
    return result.stdout


def hash_kernel_era(c_type: str) -> str:
    """'old' == hardcoded C_TYPE=int16 (every config before
    HASH_KERNEL_GENERALIZATION_COMMIT); 'new' == generalized (parameterized
    on ELEMENT_BYTES, currently exercised by C_TYPE=int32 configs)."""
    return "old" if c_type == "int16" else "new"


def snapshot_hash_kernel_files(target: Path, c_type: str, era_override: str) -> list:
    era = hash_kernel_era(c_type) if era_override == "auto" else era_override
    if era not in ("old", "new"):
        sys.exit(f"error: --hash-kernel-era must be 'auto', 'old', or 'new', got '{era_override}'")
    reason = (
        f"C_TYPE={c_type}, hardcoded pre-{HASH_KERNEL_GENERALIZATION_COMMIT} implementation ({HASH_KERNEL_OLD_REF})"
        if era == "old" else
        f"C_TYPE={c_type}, generalized implementation (current tree)"
    )
    print(f"  hash kernel era: {era} ({reason})")
    for rel in HASH_KERNEL_FILES:
        content = git_show(HASH_KERNEL_OLD_REF, rel) if era == "old" else (REPO_ROOT / rel).read_bytes()
        dst = target / "snapshot" / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(content)
    print(f"  wrote {len(HASH_KERNEL_FILES)} hash-kernel snapshot files (era={era})")
    return era


# ---------------------------------------------------------------------
# Archive copy + manifest
# ---------------------------------------------------------------------
def check_channel_consistency(settings: dict, system_cfg_text: str, config_name: str):
    ok, message = channel_consistency.check(
        kernel_instances=settings["kernel_instances"],
        impl=settings["impl"],
        use_static_ab=settings["use_static_ab"],
        use_gmio=settings["use_gmio"],
        use_relay=settings["use_relay"],
        system_cfg_text=system_cfg_text,
        label=config_name,
    )
    print(f"  channel consistency: {message}")
    if not ok:
        sys.exit(
            f"error: {config_name}'s system.cfg does not match its aie_settings.hpp's implied "
            f"channel counts (see message above) -- this config's system.cfg must have genuinely "
            f"differed from the current repo default; re-import with the ACTUAL system.cfg used at "
            f"build time (pass it via a future --system-cfg override, not yet supported -- for now, "
            f"manually place the correct file at the printed snapshot path)."
        )


def cp_a(src: Path, dst: Path):
    dst.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["cp", "-a", str(src), str(dst.parent) + "/"], check=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source", required=True, help="path to the OTHER checkout's prebuilt_hw/<name>/ dir (read-only)")
    ap.add_argument("--name", help="override the imported config's name (default: --source's basename)")
    ap.add_argument("--extra-file", action="append", default=[], help="repo-relative path of an extra source file this config needs beyond aie_settings.hpp (repeatable) -- NOT needed for the sha256_hash kernel files, see --hash-kernel-era")
    ap.add_argument("--extra-source-root", help="root to resolve --extra-file paths against (default: --source's parent's parent, i.e. the other checkout's root)")
    ap.add_argument("--hash-kernel-era", choices=["auto", "old", "new"], default="auto", help="which sha256_hash kernel implementation to snapshot: 'auto' (default) picks 'old' for C_TYPE=int16, 'new' otherwise -- see HASH_KERNEL_GENERALIZATION_COMMIT")
    args = ap.parse_args()

    source = Path(args.source).resolve()
    if not source.is_dir():
        sys.exit(f"error: --source '{source}' is not a directory")
    config_md = source / "config.md"
    if not config_md.is_file():
        sys.exit(f"error: no config.md found at {config_md}")

    name = args.name or source.name
    target = PREBUILT_HW_DIR / name

    # In-place mode: --source IS this repo's own prebuilt_hw/<name>/ (build/
    # bsp/config.md already live there, from a build done directly in this
    # checkout) -- just add snapshot/+manifest.json alongside, don't try to
    # copy the archive onto itself.
    in_place = target.resolve() == source
    if target.exists():
        if in_place:
            if (target / "manifest.json").is_file():
                sys.exit(f"error: {target} already has a manifest.json -- already imported, remove it first to re-import")
        else:
            sys.exit(f"error: {target} already exists -- remove it first if you want to re-import")

    print(f"Importing '{name}' from {source}" + (" (in-place: adding snapshot/manifest.json only)" if in_place else " (read-only)"))
    settings = parse_config_md(config_md)
    print(f"  parsed settings: rowA={settings['rowA']} colA={settings['colA']} colB={settings['colB']} "
          f"KERNEL_INSTANCES={settings['kernel_instances']} types={settings['a_type']}/{settings['b_type']}/{settings['c_type']} "
          f"TILE={settings['tile_m']}/{settings['tile_k']}/{settings['tile_n']} REPEAT_N={settings['repeat_n']}")

    if not in_place:
        target.mkdir(parents=True)

        # Archived build/bsp artifacts -- straight cp -a, mtimes preserved.
        for sub in ("build", "bsp"):
            src_sub = source / sub
            if src_sub.is_dir():
                cp_a(src_sub, target / sub)
                print(f"  copied {sub}/ ({sum(1 for _ in src_sub.rglob('*') if _.is_file())} files)")

        shutil.copy2(config_md, target / "config.md")

    # Reconstructed source snapshot.
    template_text = TEMPLATE_SETTINGS.read_text()
    reconstructed = reconstruct_aie_settings(template_text, settings, name)
    snapshot_settings_path = target / "snapshot/src/include/aie_settings.hpp"
    snapshot_settings_path.parent.mkdir(parents=True, exist_ok=True)
    snapshot_settings_path.write_text(reconstructed)
    print(f"  wrote {snapshot_settings_path.relative_to(REPO_ROOT)}")

    # system.cfg's PL-kernel instance counts (nk=s2mm_c:N:..., stream_connect
    # lines) are NOT free-standing -- they must match N_A/B/C_CHANNELS, which
    # are a function of KERNEL_INSTANCES (see aie_settings.hpp's
    # clamp_channels()/N_MEM_COLUMNS). Every config in this sweep so far has
    # KERNEL_INSTANCES >= MAX_PLIO_OUTPUT_CHANNELS (9), so N_C_CHANNELS
    # clamps to 9 regardless and system.cfg never actually needed to change
    # -- confirmed by every config.md's "no other tracked-file changes" and
    # verified again here (see check_channel_consistency below). But that's
    # a coincidence of THIS sweep's values, not a general guarantee -- a
    # future config with KERNEL_INSTANCES < 9 WOULD need a different
    # system.cfg, so this is snapshotted unconditionally (not assumed
    # identical) so restore_prebuilt_config.py always has a config-specific
    # copy to restore, and so its consistency check (see that script) has
    # something concrete to verify against.
    system_cfg_src = REPO_ROOT / "src/config/system.cfg"
    system_cfg_dst = target / "snapshot/src/config/system.cfg"
    system_cfg_dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(system_cfg_src, system_cfg_dst)
    print(f"  wrote {system_cfg_dst.relative_to(REPO_ROOT)}")
    check_channel_consistency(settings, system_cfg_src.read_text(), name)

    # sha256_hash kernel (+ PS glue + generator scripts): auto-selected era,
    # see snapshot_hash_kernel_files()'s docstring above.
    hash_era = snapshot_hash_kernel_files(target, settings["c_type"], args.hash_kernel_era)

    extra_files = []
    if args.extra_file:
        extra_root = Path(args.extra_source_root).resolve() if args.extra_source_root else source.parent.parent
        for rel in args.extra_file:
            if rel in HASH_KERNEL_FILES:
                print(f"  skipping --extra-file '{rel}': already handled automatically by hash-kernel-era selection above")
                continue
            src_file = extra_root / rel
            if not src_file.is_file():
                sys.exit(f"error: --extra-file '{rel}' not found at {src_file}")
            dst_file = target / "snapshot" / rel
            dst_file.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_file, dst_file)
            extra_files.append(rel)
            print(f"  copied extra snapshot file {rel}")

    has_deploy_files = (target / "build/hw/boot.pdi").is_file() and (target / "build/ps/app.elf").is_file()

    manifest = {
        "name": name,
        "target": settings["target"],
        "kernel_name": settings["kernel_name"],
        "has_deploy_files": has_deploy_files,
        "hash_kernel_era": hash_era,
        "snapshot_files": ["src/include/aie_settings.hpp", "src/config/system.cfg"] + HASH_KERNEL_FILES + extra_files,
        "aie_settings": {k: v for k, v in settings.items() if k not in ("target", "kernel_name")},
        "imported_from": str(source),
    }
    (target / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"  wrote {(target / 'manifest.json').relative_to(REPO_ROOT)}")
    print(f"  has_deploy_files={has_deploy_files}")
    print(f"Done: {target.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
