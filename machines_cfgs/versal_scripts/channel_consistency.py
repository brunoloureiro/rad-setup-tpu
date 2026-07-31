#!/usr/bin/env python3
"""Shared logic for checking that src/config/system.cfg's PL-kernel
instance counts (nk=.../stream_connect lines) actually match what
src/include/aie_settings.hpp's KERNEL_INSTANCES implies.

Why this exists: system.cfg's mm2s_a/mm2s_b/s2mm_c nk= counts are NOT
free-standing -- they must equal N_A_CHANNELS/N_B_CHANNELS/N_C_CHANNELS,
which aie_settings.hpp computes as a function of KERNEL_INSTANCES via
clamp_channels()/N_MEM_COLUMNS. Every prebuilt_hw config archived so far
happens to have KERNEL_INSTANCES >= MAX_PLIO_OUTPUT_CHANNELS (9), so
N_C_CHANNELS clamps to 9 in every one of them and system.cfg never actually
needed to change between configs -- see prebuilt_hw/PLAN.md. That is a
coincidence of the values chosen for this sweep, not a general guarantee:
a future config with a smaller KERNEL_INSTANCES WOULD need a different
system.cfg. This module lets both import_prebuilt_config.py (at import
time) and restore_prebuilt_config.py (at restore time) verify that instead
of silently assuming it.

Only models the PLIO + (optionally) USE_STATIC_AB path this sweep
actually uses. USE_MEMTILE_RELAY_CHAIN uses a completely different
hub-and-spoke channel scheme (see aie_settings.hpp) and is deliberately
NOT modeled here -- expected_channel_counts() returns None for it, and
callers should treat that as "can't verify automatically, check by hand."
"""
import re

MAX_AB_CHANNELS = 6  # MAX_PLIO_INPUT_CHANNELS(12)/2 == MAX_GMIO_INPUT_CHANNELS(12)/2 today
MAX_C_CHANNELS_PLIO = 9  # MAX_PLIO_OUTPUT_CHANNELS
MAX_C_CHANNELS_GMIO = 7  # MAX_GMIO_OUTPUT_CHANNELS


def clamp_channels(n_instances: int, max_channels: int) -> int:
    return n_instances if n_instances < max_channels else max_channels


def expected_channel_counts(kernel_instances: int, impl: str, use_static_ab: bool, use_gmio: bool, use_relay: bool):
    """Mirrors aie_settings.hpp's N_A_CHANNELS/N_B_CHANNELS/N_C_CHANNELS
    derivation. Returns None if use_relay (different formula entirely, not
    modeled here)."""
    if use_relay:
        return None
    max_c = MAX_C_CHANNELS_GMIO if use_gmio else MAX_C_CHANNELS_PLIO
    n_c = clamp_channels(kernel_instances, max_c)
    if use_static_ab:
        # No inA/inB PLIO/GMIO port at all -- A/B are compile-time constants.
        return {"n_a_channels": 0, "n_b_channels": 0, "n_c_channels": n_c}
    if impl == "USE_DIRECT_BROADCAST":
        n_a = clamp_channels(kernel_instances, MAX_AB_CHANNELS)
    else:
        n_mem_columns = kernel_instances // 2
        n_a = clamp_channels(n_mem_columns, MAX_AB_CHANNELS)
    return {"n_a_channels": n_a, "n_b_channels": n_a, "n_c_channels": n_c}


_NK_RE_TEMPLATE = r"^\s*nk=%s:(\d+):"


def parse_system_cfg_channel_counts(text: str):
    """Returns {'mm2s_a': N or None, 'mm2s_b': N or None, 's2mm_c': N or None}
    -- None means no ACTIVE (uncommented) nk= line for that kernel, i.e. it
    isn't wired into the graph at all (expected when use_static_ab)."""
    counts = {}
    for kernel in ("mm2s_a", "mm2s_b", "s2mm_c"):
        m = re.search(_NK_RE_TEMPLATE % kernel, text, re.MULTILINE)
        counts[kernel] = int(m.group(1)) if m else None
    return counts


def check(kernel_instances: int, impl: str, use_static_ab: bool, use_gmio: bool, use_relay: bool, system_cfg_text: str, label: str):
    """Returns (ok: bool, message: str)."""
    expected = expected_channel_counts(kernel_instances, impl, use_static_ab, use_gmio, use_relay)
    if expected is None:
        return True, f"{label}: USE_MEMTILE_RELAY_CHAIN active -- channel-count formula not modeled here, verify system.cfg by hand"

    actual = parse_system_cfg_channel_counts(system_cfg_text)
    problems = []

    exp_a = expected["n_a_channels"]
    exp_b = expected["n_b_channels"]
    exp_c = expected["n_c_channels"]

    def check_one(name, expected_n, actual_n):
        if expected_n == 0:
            if actual_n is not None:
                problems.append(f"{name}: expected NO active nk= line (USE_STATIC_AB), but system.cfg has nk={name}:{actual_n}")
        else:
            if actual_n is None:
                problems.append(f"{name}: expected {expected_n} instances, but system.cfg has no active nk={name} line")
            elif actual_n != expected_n:
                problems.append(f"{name}: expected {expected_n} instances (KERNEL_INSTANCES={kernel_instances}), system.cfg has {actual_n}")

    check_one("mm2s_a", exp_a, actual["mm2s_a"])
    check_one("mm2s_b", exp_b, actual["mm2s_b"])
    check_one("s2mm_c", exp_c, actual["s2mm_c"])

    if problems:
        return False, f"{label}: MISMATCH -- " + "; ".join(problems)
    return True, f"{label}: OK (N_A={exp_a} N_B={exp_b} N_C={exp_c} channels, matches system.cfg)"
