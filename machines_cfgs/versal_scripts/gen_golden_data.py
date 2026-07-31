#!/usr/bin/env python3
"""Generate build/<target>/ps/golden_data.hpp from a REPEAT_N=1 base data
file plus the CURRENT REPEAT_N value in src/include/aie_settings.hpp.

Invoked by the Makefile, never by hand for the `generate` subcommand -- see
the rule building $(GOLDEN_DATA_HDR) in Makefile.

Why this exists: the GeMM AIE graph's REPEAT_N (aie_settings.hpp) makes
each kernel instance fire REPEAT_N times per graph.run(1), consuming an
identical replicated A/B chunk each firing (see fill_inputs() in
src/ps/aie_graph_control.cpp) and producing REPEAT_N concatenated but
IDENTICAL output chunks (the kernel is a stateless, pure function of its
input -- confirmed against a real REPEAT_N=2 hardware capture, see
golden_data_base_rowA_14_colA_13_colB_14.txt's header). So the golden
reference for any REPEAT_N is just the REPEAT_N=1 base block repeated
REPEAT_N times; this script does that concatenation instead of
hand-maintaining a differently-sized golden_data.hpp every time REPEAT_N
changes.

This ONE REPEAT_N-chunk block is also reused, unreplicated, as the golden
reference for EVERY one of the KERNEL_INSTANCES compute tiles -- under
USE_STATIC_AB (the only mode this project builds today) every tile computes
from the SAME compile-time A/B constants (kernels/gemm_blocked_kernel.cpp),
so every instance's output is expected to be identical too. Benchmark::
has_error() (src/ps/benchmark.cpp) is the layer that knows about
KERNEL_INSTANCES: it hashes each instance's own slice of the drained AIE
output separately (aie_graph_control.cpp's per-instance digest loop) and
only element-compares a mismatching instance's slice against this same
golden_data.hpp block -- so golden_data.hpp itself never needs to grow with
KERNEL_INSTANCES.

The REPEAT_N=1 base block itself, however, is tied to rowA/colA/colB (it's
C_SIZE elements, and C_SIZE = C_BLOCK_SIZE * rowA * colB) -- so there is one
base file PER tile geometry, named
src/ps/golden_data_base_rowA_<rowA>_colA_<colA>_colB_<colB>.txt, and this
script's `generate` subcommand picks the one matching aie_settings.hpp's
CURRENT rowA/colA/colB automatically. If a geometry has never been run on
real hardware yet, that file won't exist -- use this script's `capture`
subcommand first (see PIPELINE_HARDWARE_TIMING.md for the full workflow):
build+deploy once with DEBUG and VERBOSE_ELEMENT_DEBUG both defined
(src/ps/settings.hpp), capture the resulting UART output to a log file, and
run `gen_golden_data.py capture --uart-log <log> --settings
src/include/aie_settings.hpp --base-dir src/ps` to turn the real
hardware-measured "Output [i]: value" lines from that log into a new,
correctly-named base file.
"""

import argparse
import os
import re
import sys

REPEAT_N_RE = re.compile(r"constexpr\s+unsigned\s+REPEAT_N\s*=\s*(\d+)\s*;")
ROWA_RE = re.compile(r"constexpr\s+unsigned\s+rowA\s*=\s*(\d+)\s*;")
COLA_RE = re.compile(r"constexpr\s+unsigned\s+colA\s*=\s*(\d+)\s*;")
COLB_RE = re.compile(r"constexpr\s+unsigned\s+colB\s*=\s*(\d+)\s*;")
TILE_M_RE = re.compile(r"constexpr\s+int\s+TILE_M\s*=\s*(\d+)\s*;")
TILE_N_RE = re.compile(r"constexpr\s+int\s+TILE_N\s*=\s*(\d+)\s*;")
A_TYPE_RE = re.compile(r"using\s+A_TYPE\s*=\s*(\w+)\s*;")
C_TYPE_RE = re.compile(r"using\s+C_TYPE\s*=\s*(\w+)\s*;")

# Matches src/ps/benchmark.cpp's VERBOSE_ELEMENT_DEBUG output-dump line
# format exactly: "Output [<i>]: <value>" (see run_inference()). Real UART
# captures occasionally garble a byte or two of unrelated PLM boot text at
# high baud (see PIPELINE_HARDWARE_TIMING.md) but never the app's own
# well-formed log lines, so a strict per-line match is safe and lets
# corrupted boot-log noise around it just not match instead of crashing.
OUTPUT_LINE_RE = re.compile(r"Output \[(\d+)\]:\s*(-?\d+)")


def parse_int_define(text, pattern, name, path):
    m = pattern.search(text)
    if not m:
        sys.exit(f"error: could not find 'constexpr unsigned {name} = N;' in {path}")
    return int(m.group(1))


def parse_geometry(settings_path):
    text = open(settings_path).read()
    repeat_n = parse_int_define(text, REPEAT_N_RE, "REPEAT_N", settings_path)
    rowA = parse_int_define(text, ROWA_RE, "rowA", settings_path)
    colA = parse_int_define(text, COLA_RE, "colA", settings_path)
    colB = parse_int_define(text, COLB_RE, "colB", settings_path)
    return rowA, colA, colB, repeat_n


def parse_dtype(settings_path, pattern, label):
    text = open(settings_path).read()
    m = pattern.search(text)
    if not m:
        sys.exit(f"error: could not find 'using {label} = ...;' in {settings_path}")
    return m.group(1)


def parse_a_type(settings_path):
    """A_TYPE (== B_TYPE, this project's kernel never mixes operand widths)
    -- the dtype input_data_base_*/static-A/B base files are sampled in."""
    return parse_dtype(settings_path, A_TYPE_RE, "A_TYPE")


def parse_c_type(settings_path):
    """C_TYPE -- the dtype golden_data_base_* files (the GeMM kernel's own
    output) are captured in. Different from A_TYPE/B_TYPE: e.g.
    int8/int8/int16 configs have A_TYPE=int8 but C_TYPE=int16."""
    return parse_dtype(settings_path, C_TYPE_RE, "C_TYPE")


def parse_c_block_size(settings_path):
    """C_BLOCK_SIZE = TILE_M * TILE_N (aie_settings.hpp) -- one MMUL C-tile's
    element count, parsed rather than hardcoded so this stays correct across
    configs with different tile shapes (e.g. 8x8x4 for int8/int8/int16 vs
    4x4x8 for int16/int16/int32 -- both happen to give C_BLOCK_SIZE=32 today,
    but that's a coincidence of this sweep's specific configs, not something
    to bake in as a constant)."""
    text = open(settings_path).read()
    tile_m = parse_int_define(text, TILE_M_RE, "TILE_M", settings_path)
    tile_n = parse_int_define(text, TILE_N_RE, "TILE_N", settings_path)
    return tile_m * tile_n


def base_filename_for(rowA, colA, colB, c_type):
    return f"golden_data_base_rowA_{rowA}_colA_{colA}_colB_{colB}_{c_type}.txt"


def parse_base_data(base_path):
    lines = []
    with open(base_path) as f:
        for line in f:
            if line.strip().startswith("#"):
                continue
            lines.append(line)
    values = [int(x) for x in re.findall(r"-?\d+", "".join(lines))]
    if not values:
        sys.exit(f"error: no data found in {base_path}")
    return values


def format_array(values, indent="            "):
    lines = []
    for i in range(0, len(values), 8):
        lines.append(indent + ", ".join(str(v) for v in values[i:i + 8]) + ",")
    return "\n".join(lines)


def render(base_path, settings_path, repeat_n, base_values):
    measured = base_values * repeat_n
    return f"""// Auto-generated by scripts/gen_golden_data.py from {base_path}
// (REPEAT_N=1 base data) and the REPEAT_N value in {settings_path} -- DO
// NOT EDIT. To change the golden reference, edit {base_path}; to pick up a
// new REPEAT_N, just rebuild (this file is a regular Make prerequisite of
// both of those).
//
// Generated for REPEAT_N={repeat_n}: {len(base_values)}-element base block
// repeated {repeat_n} time(s) -> {len(measured)} elements.

#pragma once

#include "settings.hpp"
#include "common.hpp"

#include <array>

namespace aie_benchmark::data {{
    namespace detail {{
        inline constexpr std::array<BenchmarkOutput, {len(measured)}> measured_output = {{
{format_array(measured)}
        }};

        static_assert(measured_output.size() == static_cast<std::size_t>(settings::golden_size),
            "golden_data.hpp: measured_output size doesn't match settings::golden_size -- "
            "regenerate (make clean/build), or if C_SIZE itself changed (rowA/colA/colB/TILE_* "
            "edited in aie_settings.hpp), {base_path} needs re-capturing against the new tile "
            "geometry (see gen_golden_data.py's `capture` subcommand), not just a regen against "
            "the new REPEAT_N.");

        constexpr std::array<BenchmarkOutput, settings::output_count * settings::golden_size>
        make_golden() {{
            std::array<BenchmarkOutput, settings::output_count * settings::golden_size> values{{}};
            for (int golden_index = 0; golden_index < settings::output_count; ++golden_index) {{
                for (int element_index = 0; element_index < settings::golden_size; ++element_index) {{
                    values[(golden_index * settings::golden_size) + element_index] = measured_output[element_index];
                }}
            }}
            return values;
        }}
    }}

    inline constexpr auto golden_data = detail::make_golden();
}}
"""


def cmd_generate(args):
    rowA, colA, colB, repeat_n = parse_geometry(args.settings)
    c_type = parse_c_type(args.settings)
    base_path = args.base
    if base_path is None:
        base_path = os.path.join(args.base_dir, base_filename_for(rowA, colA, colB, c_type))
    if not os.path.exists(base_path):
        sys.exit(
            f"error: no captured golden data for rowA={rowA} colA={colA} colB={colB} C_TYPE={c_type} -- "
            f"expected {base_path}. Capture it first, e.g.:\n"
            f"  {sys.argv[0]} capture --uart-log <uart_capture.log> "
            f"--settings {args.settings} --base-dir {os.path.dirname(base_path) or '.'}"
        )
    base_values = parse_base_data(base_path)
    content = render(base_path, args.settings, repeat_n, base_values)
    with open(args.output, "w") as f:
        f.write(content)


def cmd_capture(args):
    """Turn a real hardware UART capture (from a DEBUG_PS_APP+VERBOSE_ELEMENT_DEBUG
    build/deploy, see src/ps/settings.hpp and PIPELINE_HARDWARE_TIMING.md)
    into a new golden_data_base_rowA_<rowA>_colA_<colA>_colB_<colB>_<C_TYPE>.txt
    for aie_settings.hpp's CURRENT tile geometry/C_TYPE. Only the first
    C_SIZE "Output [i]: value" lines (one REPEAT_N=1 block) are kept -- every
    firing within one run_kernel() call consumes the identical replicated
    A/B chunk (fill_inputs(), src/ps/aie_graph_control.cpp) and the kernel
    is a stateless, pure function of its input, so all REPEAT_N repetitions
    in the capture are expected to be identical; this is verified below
    rather than assumed.
    """
    rowA, colA, colB, repeat_n = parse_geometry(args.settings)
    c_type = parse_c_type(args.settings)
    # C_SIZE = C_BLOCK_SIZE * rowA * colB, mirroring aie_settings.hpp --
    # C_BLOCK_SIZE (TILE_M * TILE_N) is parsed from the same settings file
    # rather than hardcoded, since different configs in this sweep genuinely
    # use different tile shapes (8x8x4 vs 4x4x8).
    c_block_size = parse_c_block_size(args.settings)
    c_size = c_block_size * rowA * colB

    with open(args.uart_log, "rb") as f:
        raw = f.read()
    # UART captures can contain a stray garbled byte or two from unrelated
    # PLM boot text at high baud (see PIPELINE_HARDWARE_TIMING.md) -- decode
    # permissively (errors="replace") rather than failing the whole capture
    # over a handful of non-UTF8 bytes nowhere near the lines this cares
    # about.
    text = raw.decode("utf-8", errors="replace")

    by_index = {}
    for m in OUTPUT_LINE_RE.finditer(text):
        i, v = int(m.group(1)), int(m.group(2))
        # Keep the FIRST occurrence of each index (index 0..golden_size-1
        # repeats every run_inference() call in the captured log -- only
        # the first call's dump is wanted).
        if i not in by_index:
            by_index[i] = v
        if len(by_index) >= repeat_n * c_size:
            break

    missing = [i for i in range(repeat_n * c_size) if i not in by_index]
    if missing:
        sys.exit(
            f"error: {args.uart_log} only had {len(by_index)}/{repeat_n * c_size} "
            f"'Output [i]: value' lines (first missing index: {missing[0]}) -- capture "
            "more of the run (needs at least one full run_inference() call's worth: "
            "REPEAT_N * C_SIZE elements) and try again."
        )

    full = [by_index[i] for i in range(repeat_n * c_size)]
    blocks = [full[n * c_size:(n + 1) * c_size] for n in range(repeat_n)]
    if any(b != blocks[0] for b in blocks[1:]):
        sys.exit(
            f"error: the {repeat_n} REPEAT_N repetitions captured in {args.uart_log} are NOT "
            "byte-for-byte identical -- expected them to be, since fill_inputs() "
            "(src/ps/aie_graph_control.cpp) replicates the same A/B chunk into every firing "
            "and the kernel is a stateless, pure function of its input. Investigate before "
            "trusting this capture as a golden reference."
        )
    base_values = blocks[0]

    out_path = os.path.join(args.base_dir, base_filename_for(rowA, colA, colB, c_type))
    with open(out_path, "w") as f:
        f.write(
            f"# REPEAT_N=1 base golden data for the GeMM AIE benchmark.\n"
            f"#\n"
            f"# One AIE tile's single-firing output (C_SIZE = {c_size} {c_type} elements).\n"
            f"# REAL hardware-measured output, captured via JTAG/UART from {args.uart_log}\n"
            f"# against rowA={rowA} colA={colA} colB={colB} C_TYPE={c_type} (src/include/aie_settings.hpp),\n"
            f"# via scripts/gen_golden_data.py's `capture` subcommand. All {repeat_n} REPEAT_N\n"
            f"# repetitions in that capture were verified byte-for-byte identical before\n"
            f"# being trimmed to this single REPEAT_N=1 block (expected: fill_inputs() in\n"
            f"# src/ps/aie_graph_control.cpp replicates the SAME A/B chunk into every\n"
            f"# REPEAT_N firing, and the GeMM kernel is a stateless, pure function of its\n"
            f"# input with nothing carried between firings).\n"
            f"#\n"
            f"# scripts/gen_golden_data.py's `generate` subcommand reads this file plus the\n"
            f"# CURRENT REPEAT_N (from src/include/aie_settings.hpp) at build time to\n"
            f"# generate build/<target>/ps/golden_data.hpp, concatenating this block\n"
            f"# REPEAT_N times. To update the golden reference, re-run the `capture`\n"
            f"# subcommand against a fresh UART log -- do not hand-edit this file or the\n"
            f"# generated golden_data.hpp.\n"
        )
        f.write(format_array(base_values, indent="") + "\n")
    print(f"wrote {len(base_values)} elements to {out_path}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)

    gen = sub.add_parser("generate", help="generate golden_data.hpp from a base file (Makefile-invoked)")
    gen.add_argument("--base", help="explicit path to the REPEAT_N=1 base data file "
                                     "(default: auto-resolved from --base-dir + aie_settings.hpp's rowA/colA/colB)")
    gen.add_argument("--base-dir", default="src/ps", help="directory to auto-resolve the base file in (default: src/ps)")
    gen.add_argument("--settings", required=True, help="path to aie_settings.hpp (read rowA/colA/colB/REPEAT_N from it)")
    gen.add_argument("--output", required=True, help="path to write the generated golden_data.hpp")
    gen.set_defaults(func=cmd_generate)

    cap = sub.add_parser("capture", help="turn a real hardware UART capture into a new base file")
    cap.add_argument("--uart-log", required=True, help="path to a raw UART capture from a DEBUG+VERBOSE_ELEMENT_DEBUG run")
    cap.add_argument("--settings", required=True, help="path to aie_settings.hpp (read rowA/colA/colB/REPEAT_N from it)")
    cap.add_argument("--base-dir", default="src/ps", help="directory to write the new base file into (default: src/ps)")
    cap.set_defaults(func=cmd_capture)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
