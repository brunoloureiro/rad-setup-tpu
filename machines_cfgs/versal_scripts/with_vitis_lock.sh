#!/usr/bin/env bash
# Serializes a heavy Vitis/Vivado command across every worktree of this repo.
#
# Usage:
#   scripts/with_vitis_lock.sh <lock-name> <command...>
#
# <lock-name> selects which lock to take:
#   tier-a           Global lock. Only one Vivado/aiecompiler synthesis (Tier A/B,
#                    i.e. `make build`/`make quick`) runs at a time across ALL
#                    worktrees -- this guards host RAM/CPU contention, not any
#                    particular build target, so it applies regardless of TARGET
#                    or KERNEL_NAME.
#   deploy:<board>   Per-board lock for JTAG operations (`make deploy`, `deploy-elf`,
#                    xsdb scripts). <board> should match whatever you pass as
#                    BOARD=<n> or BOARD_SERIAL=<serial> so two different physical
#                    boards can be used concurrently, but the same board is
#                    never driven by two agents at once.
#
# The lock file lives under the shared git common dir (`git rev-parse
# --git-common-dir`), which resolves to the SAME physical .git directory no
# matter which worktree you run this from -- so the lock is effective across
# all of them, not just within one working copy.
#
# Optional: set VITIS_LOCK_TIMEOUT=<seconds> to fail instead of waiting forever
# if another agent is holding the lock.
#
# Examples:
#   scripts/with_vitis_lock.sh tier-a make build
#   scripts/with_vitis_lock.sh deploy:1 make deploy
#   VITIS_LOCK_TIMEOUT=60 scripts/with_vitis_lock.sh tier-a make quick

set -euo pipefail

if [ $# -lt 2 ]; then
  echo "usage: $0 <tier-a|deploy:<board>> <command...>" >&2
  exit 1
fi

LOCK_NAME="$1"; shift

COMMON_DIR="$(git rev-parse --git-common-dir)"
LOCK_DIR="$COMMON_DIR/vitis-locks"
mkdir -p "$LOCK_DIR"
LOCK_FILE="$LOCK_DIR/${LOCK_NAME//[:\/]/_}.lock"

FLOCK_OPTS=()
if [ -n "${VITIS_LOCK_TIMEOUT:-}" ]; then
  FLOCK_OPTS+=(-w "$VITIS_LOCK_TIMEOUT")
fi

echo "[with_vitis_lock] waiting for '$LOCK_NAME' lock ($LOCK_FILE)..." >&2
exec flock "${FLOCK_OPTS[@]}" "$LOCK_FILE" "$@"
