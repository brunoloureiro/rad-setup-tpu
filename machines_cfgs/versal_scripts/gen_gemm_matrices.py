#!/usr/bin/env python3
"""Generate procedural (not hardware-captured) A/B operand matrices for
the GeMM AIE benchmark, in the exact tiled memory layout
src/aie/kernels/gemm_blocked_kernel.cpp expects:

    A  [rowA][colA][TILE_M][TILE_K]  - A_TYPE, row-major within each tile,
                                        tiles row-major
    B  [rowB][colB][TILE_K][TILE_N]  - B_TYPE, same convention (rowB == colA)

Run by hand (never by the Makefile -- this is the "capture"-equivalent step
for input data, not the build-time "generate" step; see gen_input_data.py
for that) to (re)populate the REPEAT_N=1-equivalent base files
scripts/gen_input_data.py's `generate` subcommand reads at build time:

    src/ps/input_data_base_rowA_<rowA>_colA_<colA>_colB_<colB>_A.txt
    src/ps/input_data_base_rowA_<rowA>_colA_<colA>_colB_<colB>_B.txt

one pair per tile geometry, mirroring gen_golden_data.py's
golden_data_base_rowA_<rowA>_colA_<colA>_colB_<colB>.txt naming/format
convention exactly (same "# comment header" + 8-values-per-line body).

Every generated value is a NONZERO integer, uniformly sampled from the full
signed range of A_TYPE/B_TYPE (as parsed from aie_settings.hpp, or
overridden with --dtype) minus {0} -- a zero operand element would
trivially zero out whatever partial products it participates in, which is
exactly the kind of degenerate case real GeMM test data should exercise
around, not produce by construction. Originally int8-only (this repo's
first configs were all int8/int8/int16); generalized to also support int16
(int16/int16/int32 configs) once those were added to the sweep -- A and B
are always sampled from the SAME dtype (this project's kernel doesn't mix
A/B widths).

Deterministic: reruns with the same --seed reproduce byte-identical files
(a distinct sub-seed per geometry/operand, derived from --seed, keeps the
four geometries' and A/B's random streams from overlapping).
"""

import argparse
import os
import random
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gen_golden_data as ggd  # noqa: E402  (path insert must come first)

TILE_M_RE = re.compile(r"constexpr\s+int\s+TILE_M\s*=\s*(\d+)\s*;")
TILE_K_RE = re.compile(r"constexpr\s+int\s+TILE_K\s*=\s*(\d+)\s*;")
TILE_N_RE = re.compile(r"constexpr\s+int\s+TILE_N\s*=\s*(\d+)\s*;")
A_TYPE_RE = re.compile(r"using\s+A_TYPE\s*=\s*(\w+)\s*;")

# Signed range (inclusive) for each dtype this project's kernel supports.
DTYPE_RANGES = {
    "int8": (-128, 127),
    "int16": (-32768, 32767),
}


def parse_tile_dims(settings_path):
    text = open(settings_path).read()
    tile_m = ggd.parse_int_define(text, TILE_M_RE, "TILE_M", settings_path)
    tile_k = ggd.parse_int_define(text, TILE_K_RE, "TILE_K", settings_path)
    tile_n = ggd.parse_int_define(text, TILE_N_RE, "TILE_N", settings_path)
    return tile_m, tile_k, tile_n


def parse_a_dtype(settings_path):
    text = open(settings_path).read()
    m = A_TYPE_RE.search(text)
    if not m:
        sys.exit(f"error: could not find 'using A_TYPE = ...;' in {settings_path}")
    dtype = m.group(1)
    if dtype not in DTYPE_RANGES:
        sys.exit(f"error: {settings_path}'s A_TYPE is '{dtype}', not one of "
                  f"{sorted(DTYPE_RANGES)} -- add its range to DTYPE_RANGES first.")
    return dtype


def nonzero_value(rng, dtype):
    """Uniform over the nonzero values of dtype's signed range, excluding 0."""
    lo, hi = DTYPE_RANGES[dtype]
    v = rng.randint(lo, hi - 1)
    return v + 1 if v >= 0 else v


def gen_operand(seed, count, dtype):
    rng = random.Random(seed)
    return [nonzero_value(rng, dtype) for _ in range(count)]


def base_filename_for(rowA, colA, colB, dtype, operand):
    return f"input_data_base_rowA_{rowA}_colA_{colA}_colB_{colB}_{dtype}_{operand}.txt"


def write_base_file(out_path, operand, dims, rowA, colA, colB, seed, values, dtype):
    dim0, dim1, tile0, tile1 = dims
    lo, hi = DTYPE_RANGES[dtype]
    with open(out_path, "w") as f:
        f.write(
            f"# Procedurally generated {dtype} GeMM operand {operand} data "
            f"(NOT a hardware capture).\n"
            f"#\n"
            f"# Tiled layout: {operand}[{dim0}][{dim1}][{tile0}][{tile1}], {dtype}, "
            f"row-major within each\n"
            f"# tile, tiles row-major -- see the layout comment atop "
            f"src/aie/kernels/gemm_blocked_kernel.cpp.\n"
            f"# rowA={rowA} colA={colA} colB={colB} "
            f"(src/include/aie_settings.hpp). One chunk only (matches\n"
            f"# settings::input_a_size/input_b_size == A_SIZE/B_SIZE, NOT "
            f"A_TOTAL_SIZE/B_TOTAL_SIZE) --\n"
            f"# scripts/gen_input_data.py replicates this block "
            f"settings::input_count times at build\n"
            f"# time into build/<target>/ps/input_data.hpp, exactly like "
            f"scripts/gen_golden_data.py does\n"
            f"# for golden_data.hpp (there with REPEAT_N in place of "
            f"input_count).\n"
            f"#\n"
            f"# Generated by scripts/gen_gemm_matrices.py --rowA {rowA} "
            f"--colA {colA} --colB {colB} --dtype {dtype} --seed {seed}.\n"
            f"# Every value is a NONZERO {dtype} in [{lo},{hi}] (0 deliberately "
            f"excluded). To regenerate,\n"
            f"# re-run that script -- do not hand-edit this file or the "
            f"generated input_data.hpp.\n"
        )
        f.write(ggd.format_array(values, indent="") + "\n")
    print(f"wrote {len(values)} elements to {out_path}")


def generate_geometry(rowA, colA, colB, tile_dims, base_dir, seed, dtype):
    tile_m, tile_k, tile_n = tile_dims
    rowB = colA

    a_size = tile_m * tile_k * rowA * colA
    b_size = tile_k * tile_n * rowB * colB

    # Distinct, non-overlapping sub-seeds per geometry/operand so the four
    # geometries (and A vs B within one geometry) never share a random
    # stream -- mirrors input_data.hpp's old make_operand()'s distinct
    # seed/step per operand.
    a_seed = f"{seed}-A-{rowA}-{colA}-{colB}"
    b_seed = f"{seed}-B-{rowA}-{colA}-{colB}"

    a_values = gen_operand(a_seed, a_size, dtype)
    b_values = gen_operand(b_seed, b_size, dtype)

    a_path = os.path.join(base_dir, base_filename_for(rowA, colA, colB, dtype, "A"))
    b_path = os.path.join(base_dir, base_filename_for(rowA, colA, colB, dtype, "B"))

    write_base_file(a_path, "A", (rowA, colA, tile_m, tile_k), rowA, colA, colB, seed, a_values, dtype)
    write_base_file(b_path, "B", (rowB, colB, tile_k, tile_n), rowA, colA, colB, seed, b_values, dtype)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--geometries", default="4,8,12,14",
                     help="comma-separated list of N, one square rowA=colA=colB=N geometry each "
                          "(default: 4,8,12,14). Ignored if --rowA/--colA/--colB are given.")
    ap.add_argument("--rowA", type=int, help="explicit single geometry: A-tile rows per kernel")
    ap.add_argument("--colA", type=int, help="explicit single geometry: shared reduction dimension")
    ap.add_argument("--colB", type=int, help="explicit single geometry: B/C-tile columns per kernel")
    ap.add_argument("--settings", default="src/include/aie_settings.hpp",
                     help="path to aie_settings.hpp (read TILE_M/TILE_K/TILE_N and, unless --dtype "
                          "is given, A_TYPE from it)")
    ap.add_argument("--dtype", choices=sorted(DTYPE_RANGES), default=None,
                     help="operand dtype to sample values for (default: parsed from --settings' "
                          "A_TYPE -- override only if generating for a settings file that doesn't "
                          "yet reflect the geometry you're generating for)")
    ap.add_argument("--base-dir", default="src/ps", help="directory to write the base files into (default: src/ps)")
    ap.add_argument("--seed", type=int, default=0,
                     help="base RNG seed, mixed per-geometry/per-operand (default: 0)")
    args = ap.parse_args()

    tile_dims = parse_tile_dims(args.settings)
    dtype = args.dtype or parse_a_dtype(args.settings)

    if args.rowA or args.colA or args.colB:
        if not (args.rowA and args.colA and args.colB):
            sys.exit("error: --rowA/--colA/--colB must all be given together")
        generate_geometry(args.rowA, args.colA, args.colB, tile_dims, args.base_dir, args.seed, dtype)
        return

    for n in (int(x) for x in args.geometries.split(",")):
        generate_geometry(n, n, n, tile_dims, args.base_dir, args.seed, dtype)


if __name__ == "__main__":
    main()
