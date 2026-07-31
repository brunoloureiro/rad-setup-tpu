#!/usr/bin/env bash
# deploy_versal_1_jtag.sh - (Re)deploy a Versal bare-metal PDI+ELF over JTAG, targeting board 1.
#
# Same as deploy_versal_jtag.sh (see that file for the full rationale), except this wrapper pins
# BOARD=1 so debug.tcl/deploy.tcl (via versal_scripts/board_select.tcl) target the first board in
# xsdb's enumeration order rather than whichever board happens to be BOARD's default (1) or
# whichever a caller's ambient BOARD env var says - this script is meant to be used verbatim as
# 'redeploy_cmd' for one specific physical board (see versal1_rowA14_colA14_colB14_N34.yaml) so it
# does not depend on the caller setting BOARD correctly. Use BOARD_SERIAL instead of BOARD (see
# board_select.tcl) if enumeration order is not stable enough for your setup.
#
# Mirrors versal-aie-dev's `make deploy` / `_post_bsp_deploy` targets: first
# switches the board's boot mode to JTAG and resets it via the PMC
# (debug.tcl), then programs the PDI and (optionally) downloads the ELF
# (deploy.tcl). Both steps are required on every call because debug.tcl's
# JTAG boot mode does not survive a power cycle (see its header comment) -
# after a hard reboot the board reverts to its normal (e.g. SD) boot mode.
#
# This script is used as 'redeploy_cmd' from a passive-mode Versal machine
# config (see machines_cfgs/versal1_rowA14_colA14_colB14_N34.yaml and CLAUDE.md's "DUT
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
export BOARD=1

: "${PDI_PATH:?PDI_PATH must be set in the environment}"

# Fields coming straight from the machine YAML (PDI_PATH/ELF_PATH) or the pull_versal_scripts.sh
# subtree (debug.tcl/deploy.tcl) are otherwise only discovered to be wrong deep inside an xsdb
# TCL error - check them up front so a typo'd path or an un-pulled subtree fails fast and clearly.
if [ ! -f "$PDI_PATH" ]; then
    echo "ERROR: PDI_PATH '$PDI_PATH' does not exist or is not a file (check the 'redeploy_cmd' PDI_PATH entry in this DUT's machine config)." >&2
    exit 1
fi

if [ -n "${ELF_PATH:-}" ] && [ ! -f "$ELF_PATH" ]; then
    echo "ERROR: ELF_PATH '$ELF_PATH' does not exist or is not a file (check the 'redeploy_cmd' ELF_PATH entry in this DUT's machine config)." >&2
    exit 1
fi

for tcl_script in "$VERSAL_SCRIPTS_DIR/debug.tcl" "$VERSAL_SCRIPTS_DIR/deploy.tcl"; do
    if [ ! -f "$tcl_script" ]; then
        echo "ERROR: expected TCL script not found: $tcl_script (has 'versal_scripts' been pulled? see pull_versal_scripts.sh)" >&2
        exit 1
    fi
done

if ! command -v xsdb >/dev/null 2>&1; then
    echo "ERROR: xsdb not found on PATH. Source the Vitis toolchain environment before running server.py (e.g. 'source ~/source_vitis.sh')." >&2
    exit 1
fi

hw_server_host="${HW_SERVER%%:*}"
hw_server_port="${HW_SERVER##*:}"
if ! timeout 3 bash -c "echo > /dev/tcp/${hw_server_host}/${hw_server_port}" 2>/dev/null; then
    echo "ERROR: cannot reach hw_server at ${HW_SERVER}. Is it running (e.g. 'hw_server' from the Vitis/Vivado install) and is the JTAG probe connected to it?" >&2
    exit 1
fi
echo ">>> hw_server reachable at ${HW_SERVER}"
echo ">>> BOARD=${BOARD}"
echo ">>> PDI_PATH=${PDI_PATH}"
echo ">>> ELF_PATH=${ELF_PATH:-<unset, ELF assumed embedded in PDI>}"

echo ">>> [1/2] Switching board to JTAG boot mode (debug.tcl)"
TERM=vt100 xsdb -eval "connect -url TCP:${HW_SERVER}; source ${VERSAL_SCRIPTS_DIR}/debug.tcl"
echo ">>> [1/2] Boot mode switch done"

sleep 5

echo ">>> [2/2] Loading PDI/ELF (deploy.tcl)"
TERM=vt100 xsdb -eval "connect -url TCP:${HW_SERVER}; source ${VERSAL_SCRIPTS_DIR}/deploy.tcl"
echo ">>> [2/2] PDI/ELF load done"
echo ">>> Redeploy finished successfully"
