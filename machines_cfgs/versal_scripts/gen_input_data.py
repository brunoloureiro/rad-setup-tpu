#!/usr/bin/env python3
"""Generate build/<target>/ps/input_data.hpp from the REPEAT_N=1-equivalent
A/B base data files plus the CURRENT settings::input_count value
(src/ps/settings.hpp).

Invoked by the Makefile, never by hand -- see the rule building
$(INPUT_DATA_HDR) in Makefile. To (re)create the base files this reads,
use scripts/gen_gemm_matrices.py, not this script.

Why this exists: mirrors gen_golden_data.py's own reasoning exactly, one
level up the pipeline -- settings::input_a_size/input_b_size (ONE chunk,
A_SIZE/B_SIZE) are tied to the CURRENT rowA/colA/colB tile geometry
(src/include/aie_settings.hpp), so there is one base file pair per
geometry, named

    src/ps/input_data_base_rowA_<rowA>_colA_<colA>_colB_<colB>_<A_TYPE>_A.txt
    src/ps/input_data_base_rowA_<rowA>_colA_<colA>_colB_<colB>_<A_TYPE>_B.txt

(A_TYPE included since this project now has both int8 and int16 operand
configs -- without it, two configs sharing a geometry but not a dtype would
collide on the same filename.) This script's `generate` subcommand picks the pair matching
aie_settings.hpp's CURRENT rowA/colA/colB automatically -- exactly
gen_golden_data.py's own base-file resolution, imported here rather than
reimplemented. Unlike golden_data.hpp (replicated REPEAT_N times, since the
AIE kernel fires REPEAT_N times per graph.run(1) on an internally
replicated copy of the same chunk -- see aie_graph_control.cpp's
fill_inputs()), input_data.hpp is replicated settings::input_count times
instead: input_count is "how many different inputs we have total"
(settings.hpp), each currently given the SAME operand data (deliberate,
matching the original make_operand()'s behavior it replaces -- see
input_data.hpp's git history), and input_a_size/input_b_size already stay
at the ONE-chunk A_SIZE/B_SIZE regardless of REPEAT_N (settings.hpp's own
comment on this).
"""

import argparse
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gen_golden_data as ggd  # noqa: E402  (path insert must come first)

INPUT_COUNT_RE = re.compile(r"#define\s+INPUT_COUNT_VALUE\s+(\d+)")
USE_STATIC_AB_RE = re.compile(r"#define\s+USE_STATIC_AB\b")


def is_static_ab(aie_settings_path):
    # Same //-stripping reasoning as parse_input_count() below -- aie_settings.hpp
    # comments out USE_STATIC_AB's sibling flags right next to it (e.g. an
    # earlier "// #define USE_CHUNK_PIPELINE"-style line), so a plain regex
    # search needs those stripped first or it could match a commented-out
    # #define instead of the real, active one.
    lines = (l for l in open(aie_settings_path) if not l.strip().startswith("//"))
    text = "".join(lines)
    return USE_STATIC_AB_RE.search(text) is not None


def parse_input_count(benchmark_settings_path, aie_settings_path):
    # settings.hpp's own INPUT_COUNT_VALUE block encodes "if static inputs,
    # then input count is 1" as a REAL #ifdef USE_STATIC_AB override
    # (#undef + redefine to DEFINITELY_ONE) that fires AFTER the plain
    # '#define INPUT_COUNT_VALUE 2' textually above it -- the real compiled
    # settings::input_count correctly resolves to 1 in that case (the C
    # preprocessor evaluates the file top-to-bottom), but a regex search
    # alone can't evaluate that #ifdef, so it would always match the first,
    # pre-override literal (2) instead. Checking USE_STATIC_AB directly
    # here, before ever looking at INPUT_COUNT_VALUE, avoids that mismatch
    # entirely rather than trying to regex around the override.
    if is_static_ab(aie_settings_path):
        return 1

    # settings.hpp keeps old INPUT_COUNT_VALUE choices around as commented-out
    # "//#define" lines right next to the live one (see its INPUT_COUNT_VALUE
    # comment) -- strip //-commented lines first so a plain regex search can't
    # match one of those instead of the real, active #define.
    lines = (l for l in open(benchmark_settings_path) if not l.strip().startswith("//"))
    text = "".join(lines)
    m = INPUT_COUNT_RE.search(text)
    if not m:
        sys.exit(f"error: could not find an active '#define INPUT_COUNT_VALUE N' in {benchmark_settings_path}")
    return int(m.group(1))


def base_filename_for(rowA, colA, colB, dtype, operand):
    return f"input_data_base_rowA_{rowA}_colA_{colA}_colB_{colB}_{dtype}_{operand}.txt"


def resolve_base(explicit, base_dir, rowA, colA, colB, dtype, operand):
    if explicit is not None:
        return explicit
    return os.path.join(base_dir, base_filename_for(rowA, colA, colB, dtype, operand))


def require_base(base_path, rowA, colA, colB, operand, settings_path):
    if not os.path.exists(base_path):
        sys.exit(
            f"error: no generated input data for rowA={rowA} colA={colA} colB={colB} "
            f"operand {operand} -- expected {base_path}. Generate it first, e.g.:\n"
            f"  python3 {os.path.join(os.path.dirname(__file__), 'gen_gemm_matrices.py')} "
            f"--rowA {rowA} --colA {colA} --colB {colB} "
            f"--settings {settings_path} --base-dir {os.path.dirname(base_path) or '.'}"
        )


def render(base_a, base_b, benchmark_settings_path, input_count, a_values, b_values):
    return f"""// Auto-generated by scripts/gen_input_data.py from {base_a} and {base_b}
// (single-chunk base data) and the INPUT_COUNT_VALUE in {benchmark_settings_path} --
// DO NOT EDIT. To change the operands, regenerate the base files with
// scripts/gen_gemm_matrices.py; to pick up a new input_count, just rebuild
// (this file is a regular Make prerequisite of both).
//
// Generated for input_count={input_count}: {len(a_values)} A-operand elements
// ({len(a_values) // input_count}-element base chunk x{input_count}), {len(b_values)}
// B-operand elements ({len(b_values) // input_count}-element base chunk x{input_count}).

#pragma once

#include "settings.hpp"
#include "common.hpp"

#include <array>

namespace aie_benchmark::data {{
    namespace detail {{
        inline constexpr std::array<BenchmarkInput, {len(a_values)}> measured_input_a = {{
{ggd.format_array(a_values)}
        }};
        inline constexpr std::array<BenchmarkInput, {len(b_values)}> measured_input_b = {{
{ggd.format_array(b_values)}
        }};

        static_assert(measured_input_a.size() == static_cast<std::size_t>(settings::input_count) *
                          static_cast<std::size_t>(settings::input_a_size),
            "input_data.hpp: measured_input_a size doesn't match settings::input_count * "
            "settings::input_a_size -- regenerate (make clean/build), or if A_SIZE itself changed "
            "(rowA/colA/TILE_* edited in aie_settings.hpp), {base_a} needs regenerating for the new "
            "tile geometry (scripts/gen_gemm_matrices.py), not just a regen against the new input_count.");
        static_assert(measured_input_b.size() == static_cast<std::size_t>(settings::input_count) *
                          static_cast<std::size_t>(settings::input_b_size),
            "input_data.hpp: measured_input_b size doesn't match settings::input_count * "
            "settings::input_b_size -- see measured_input_a's static_assert above; {base_b} needs "
            "regenerating (scripts/gen_gemm_matrices.py) if B_SIZE itself changed.");
    }}

    inline constexpr auto input_data_a = detail::measured_input_a;
    inline constexpr auto input_data_b = detail::measured_input_b;
}}
"""


def cmd_generate(args):
    rowA, colA, colB, _repeat_n = ggd.parse_geometry(args.settings)
    dtype = ggd.parse_a_type(args.settings)
    input_count = parse_input_count(args.benchmark_settings, args.settings)

    base_a = resolve_base(args.base_a, args.base_dir, rowA, colA, colB, dtype, "A")
    base_b = resolve_base(args.base_b, args.base_dir, rowA, colA, colB, dtype, "B")
    require_base(base_a, rowA, colA, colB, "A", args.settings)
    require_base(base_b, rowA, colA, colB, "B", args.settings)

    a_chunk = ggd.parse_base_data(base_a)
    b_chunk = ggd.parse_base_data(base_b)
    a_values = a_chunk * input_count
    b_values = b_chunk * input_count

    content = render(base_a, base_b, args.benchmark_settings, input_count, a_values, b_values)
    with open(args.output, "w") as f:
        f.write(content)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)

    gen = sub.add_parser("generate", help="generate input_data.hpp from base files (Makefile-invoked)")
    gen.add_argument("--base-a", help="explicit path to the A-operand base data file "
                                       "(default: auto-resolved from --base-dir + aie_settings.hpp's rowA/colA/colB)")
    gen.add_argument("--base-b", help="explicit path to the B-operand base data file (same default rule as --base-a)")
    gen.add_argument("--base-dir", default="src/ps", help="directory to auto-resolve the base files in (default: src/ps)")
    gen.add_argument("--settings", required=True, help="path to aie_settings.hpp (read rowA/colA/colB from it)")
    gen.add_argument("--benchmark-settings", required=True, help="path to settings.hpp (read INPUT_COUNT_VALUE from it)")
    gen.add_argument("--output", required=True, help="path to write the generated input_data.hpp")
    gen.set_defaults(func=cmd_generate)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
