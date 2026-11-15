#!/bin/sh
# Rewrites the author and committer of every commit of a repository through
# a mailmap, in a fresh clone, and leaves the result there to be checked
# and pushed.
#
#   rewrite-identities.sh <owner/repo | clone URL> <mailmap> [folder]
#
# owner/repo stands for git@github.com:owner/repo.git. The clone goes into
# <folder>, which must not exist yet, or else into a new temporary folder.
# Dates, messages and content stay as they are; signatures are dropped.
# Prints how many author and committer entries each identity has after the
# rewrite, then the folder. The folder keeps the URL as rewrite.source for
# compare-rewrite.sh and force-push-rewrite.sh, since git filter-repo
# removes the remote.
#
# Each mailmap line maps one identity, for authors and committers alike:
#   New Name <new@example.com> <old@example.com>          any name, this address
#   New Name <new@example.com> Old Name <old@example.com> only this name and address
#   <new@example.com> <old@example.com>                   the address, keeping the name

set -eu

usage() {
  sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//' >&2
  exit 2
}
die() {
  echo "rewrite-identities.sh: $*" >&2
  exit 1
}

[ $# -ge 2 ] && [ $# -le 3 ] || usage

case $1 in
*/*/* | *:* | /* | .*) url=$1 ;;
*/*) url=git@github.com:$1.git ;;
*) usage ;;
esac

[ -f "$2" ] || die "no mailmap at $2"
mailmap=$(cd "$(dirname "$2")" && pwd)/$(basename "$2")

git filter-repo --version >/dev/null 2>&1 ||
  die "git filter-repo is missing; install it with: brew install git-filter-repo"

if [ $# -eq 3 ]; then
  dir=$3
  [ ! -e "$dir" ] || die "$dir exists already"
else
  dir=$(mktemp -d "${TMPDIR:-/tmp}/rewrite-identities.XXXXXX")/$(basename "$url" .git)
fi

git clone --quiet --no-single-branch "$url" "$dir"
git -C "$dir" filter-repo --quiet --mailmap "$mailmap"
git -C "$dir" config rewrite.source "$url"

git -C "$dir" log --all --format='author    %an <%ae>%ncommitter %cn <%ce>' |
  sort | uniq -c | sort -rn
echo "$dir"
