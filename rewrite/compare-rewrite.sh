#!/bin/sh
# Checks that a rewrite by rewrite-identities.sh changed nothing but the
# identities: the same number of commits, every author and committer date in
# the same order, and the same tree at the tip, compared with the branch on
# the original.
#
#   compare-rewrite.sh <rewritten folder>
#
# The branch is the one checked out in the folder, the default branch of a
# fresh clone. Exits with status 1 at the first difference.

set -eu

usage() {
  sed -n '2,10p' "$0" | sed 's/^# \{0,1\}//' >&2
  exit 2
}
die() {
  echo "compare-rewrite.sh: $*" >&2
  exit 1
}

[ $# -eq 1 ] || usage
dir=$1
url=$(git -C "$dir" config rewrite.source) ||
  die "$dir has no rewrite.source; it was not made by rewrite-identities.sh"
branch=$(git -C "$dir" symbolic-ref --short HEAD)

# The original's commits must not be replaced by rewritten ones in the view.
GIT_NO_REPLACE_OBJECTS=1
export GIT_NO_REPLACE_OBJECTS

tmp=$(mktemp -d "${TMPDIR:-/tmp}/compare-rewrite.XXXXXX")
trap 'git -C "$dir" update-ref -d refs/rewrite/original 2>/dev/null; rm -rf "$tmp"' EXIT

git -C "$dir" fetch --quiet --no-tags "$url" "+refs/heads/$branch:refs/rewrite/original"
git -C "$dir" log --format='%ad %cd' --date=raw refs/rewrite/original >"$tmp/original"
git -C "$dir" log --format='%ad %cd' --date=raw "$branch" >"$tmp/rewritten"

n=$(wc -l <"$tmp/original" | tr -d ' ')
m=$(wc -l <"$tmp/rewritten" | tr -d ' ')
[ "$n" = "$m" ] || die "$branch has $m commits, the original $n"
cmp -s "$tmp/original" "$tmp/rewritten" || die "the author or committer dates differ"
[ "$(git -C "$dir" rev-parse 'refs/rewrite/original^{tree}')" = \
  "$(git -C "$dir" rev-parse "$branch^{tree}")" ] || die "the tree at the tip differs"

echo "$branch: $n commits, dates and tree unchanged against $url"
