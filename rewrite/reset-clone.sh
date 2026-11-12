#!/bin/sh
# Moves an existing clone in place onto a branch whose history was rewritten
# on its origin, so that a later pull does not merge the old history back.
#
#   reset-clone.sh <clone> [branch]
#
# The branch defaults to the default branch of origin. Fetches, checks the
# branch out, resets it hard to origin, makes it track origin again, and
# lists the local branches, since the others still carry the old history.
# Stops when tracked files have uncommitted changes.

set -eu

usage() {
  sed -n '2,10p' "$0" | sed 's/^# \{0,1\}//' >&2
  exit 2
}
die() {
  echo "reset-clone.sh: $*" >&2
  exit 1
}

[ $# -ge 1 ] && [ $# -le 2 ] || usage
clone=$1
git -C "$clone" rev-parse --git-dir >/dev/null 2>&1 || die "$clone is no git clone"
[ -z "$(git -C "$clone" status --porcelain --untracked-files=no)" ] ||
  die "$clone has uncommitted changes; commit or stash them first"

git -C "$clone" fetch --quiet --prune origin
if [ $# -eq 2 ]; then
  branch=$2
else
  git -C "$clone" remote set-head origin --auto >/dev/null
  branch=$(git -C "$clone" symbolic-ref --short refs/remotes/origin/HEAD)
  branch=${branch#origin/}
fi

git -C "$clone" switch --quiet "$branch"
git -C "$clone" reset --quiet --hard "origin/$branch"
git -C "$clone" branch --quiet --set-upstream-to="origin/$branch" "$branch"
git -C "$clone" branch -vv
