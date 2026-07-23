#!/usr/bin/env bash
# Pulls the latest scripts/ subdirectory from the versal_aie repo
# (https://github.com/brunoloureiro/versal_aie) into machine_cfgs/versal_scripts,
# as a git-subtree (see: git help subtree).
#
# Usage: ./pull_versal_scripts.sh
#
# This only updates the local working tree/history with a new commit;
# it does not push anything. Review with `git show` before pushing.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"

REMOTE_URL=https://github.com/brunoloureiro/versal_aie.git
REMOTE_BRANCH=main
PREFIX=machine_cfgs/versal_scripts
SOURCE_SUBDIR=scripts
SPLIT_BRANCH=tmp-versal-scripts-split

# `git subtree split` requires the prefix to exist in the *current* working
# tree, so it can't be pointed at a foreign remote's history directly. Instead,
# clone versal_aie into a throwaway temp dir and split scripts/ out there.
TMP_CLONE=$(mktemp -d)
trap 'rm -rf "$TMP_CLONE"' EXIT

git clone --quiet --branch "$REMOTE_BRANCH" --single-branch "$REMOTE_URL" "$TMP_CLONE"
git -C "$TMP_CLONE" subtree split -q --prefix="$SOURCE_SUBDIR" -b "$SPLIT_BRANCH"

git fetch --quiet "$TMP_CLONE" "$SPLIT_BRANCH"
git subtree merge --prefix="$PREFIX" --squash FETCH_HEAD \
    -m "Update $PREFIX from $REMOTE_URL ($REMOTE_BRANCH)"

echo
echo "Done. If nothing changed upstream, the merge above will say 'Already up to date'."
echo "Review with 'git show' or 'git log -p -1' before pushing."
