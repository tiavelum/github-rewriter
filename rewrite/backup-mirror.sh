#!/bin/sh
# Mirrors a repository, with every branch, tag and pull request ref, into a
# backup folder, so that a rewrite of its history can be undone.
#
#   backup-mirror.sh <owner/repo | clone URL> [backup folder]
#
# owner/repo stands for git@github.com:owner/repo.git. The mirror lands in
# <backup folder>/<repo>-<date>-<time>.git, the folder defaulting to
# ~/vc-backup. Prints the mirror's path.

set -eu

usage() {
  sed -n '2,9p' "$0" | sed 's/^# \{0,1\}//' >&2
  exit 2
}
die() {
  echo "backup-mirror.sh: $*" >&2
  exit 1
}

[ $# -ge 1 ] && [ $# -le 2 ] || usage

case $1 in
*/*/* | *:* | /* | .*) url=$1 ;;
*/*) url=git@github.com:$1.git ;;
*) usage ;;
esac

dir=${2:-$HOME/vc-backup}
mkdir -p "$dir"
mirror=$dir/$(basename "$url" .git)-$(date +%Y-%m-%d-%H%M%S).git
[ ! -e "$mirror" ] || die "$mirror exists already"

git clone --quiet --mirror "$url" "$mirror"
echo "$mirror"
