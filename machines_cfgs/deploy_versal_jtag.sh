#!/usr/bin/env bash
# deploy_versal_jtag.sh - (Re)deploy a Versal bare-metal PDI+ELF over JTAG.
#
# Mirrors versal-aie-dev's `make deploy` / `_post_bsp_deploy` targets: first
# switches the board's boot mode to JTAG and resets it via the PMC
# (debug.tcl), then programs the PDI and (optionally) downloads the ELF
# (deploy.tcl). Both steps are required on every call because debug.tcl's
# JTAG boot mode does not survive a power cycle (see its header comment) -
# after a hard reboot the board reverts to its normal (e.g. SD) boot mode.
#
# This script is used as 'redeploy_cmd' from a passive-mode Versal machine
# config (see machines_cfgs/versal_bm_*_passive.yaml and CLAUDE.md's "DUT
# console connection" section). redeploy_cmd is run as a single argv list
# with no shell involved (server/dut_deployment.py), so the two xsdb
# invocations + the sleep between them (both required by the Makefile flow)
# are wrapped here rather than expressed directly in the YAML.
#
# The debug.tcl/deploy.tcl scripts themselves live under versal_scripts/,
# a git subtree pulled from the versal_aie repo (see pull_versal_scripts.sh)
# - this script is kept outside that directory so it survives future pulls.
#
# Required env: PDI_PATH. Optional: ELF_PATH (see deploy.tcl), HW_SERVER
# (defaults to localhost:3121, matching the Makefile's default).
#
# Assumes the Vitis toolchain environment (xsdb on PATH) has already been
# sourced by the caller before starting server.py, e.g.:
#   source ~/source_vitis.sh && python3 server.py
# This script does not source it itself.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VERSAL_SCRIPTS_DIR="$SCRIPT_DIR/versal_scripts"
HW_SERVER="${HW_SERVER:-localhost:3121}"

: "${PDI_PATH:?PDI_PATH must be set in the environment}"

if ! command -v xsdb >/dev/null 2>&1; then
    echo "ERROR: xsdb not found on PATH. Source the Vitis toolchain environment before running server.py (e.g. 'source ~/source_vitis.sh')." >&2
    exit 1
fi

echo ">>> Switching board to JTAG boot mode (debug.tcl)"
TERM=vt100 xsdb -eval "connect -url TCP:${HW_SERVER}; source ${VERSAL_SCRIPTS_DIR}/debug.tcl"

sleep 5

echo ">>> Loading PDI/ELF (deploy.tcl)"
TERM=vt100 xsdb -eval "connect -url TCP:${HW_SERVER}; source ${VERSAL_SCRIPTS_DIR}/deploy.tcl"
