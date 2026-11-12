#!/bin/sh
# Force-pushes the branch of a folder made by rewrite-identities.sh to the
# original, overwriting the branch's history there.
#
#   force-push-rewrite.sh <rewritten folder>
#
# Asks first for the repository name, read from standard input. On GitHub it
# disables each active ruleset of the repository that blocks force pushes,
# pushes, and enables those rulesets again, also when the push fails; it
# stops beforehand if classic branch protection forbids force pushes. Other
# branches of the folder are listed, not pushed.

set -eu

usage() {
  sed -n '2,11p' "$0" | sed 's/^# \{0,1\}//' >&2
  exit 2
}
die() {
  echo "force-push-rewrite.sh: $*" >&2
  exit 1
}

[ $# -eq 1 ] || usage
dir=$1
url=$(git -C "$dir" config rewrite.source) ||
  die "$dir has no rewrite.source; it was not made by rewrite-identities.sh"
branch=$(git -C "$dir" symbolic-ref --short HEAD)
name=$(basename "$url" .git)

case $url in
git@github.com:*) slug=${url#git@github.com:} ;;
https://github.com/*) slug=${url#https://github.com/} ;;
*) slug= ;;
esac
slug=${slug%.git}

blocking=
if [ -n "$slug" ]; then
  allowed=$(gh api "repos/$slug/branches/$branch/protection" \
    --jq '.allow_force_pushes.enabled' 2>/dev/null) || allowed=unprotected
  [ "$allowed" != false ] ||
    die "the branch protection of $branch forbids force pushes; allow them on GitHub first"
  for id in $(gh api "repos/$slug/rulesets" \
    --jq '.[] | select(.enforcement == "active" and .source_type == "Repository") | .id'); do
    if [ "$(gh api "repos/$slug/rulesets/$id" \
      --jq 'any(.rules[]; .type == "non_fast_forward")')" = true ]; then
      blocking="$blocking $id"
    fi
  done
fi

printf 'Overwrite the history of %s on %s? Type %s to confirm: ' "$branch" "$url" "$name"
read -r answer || answer=
[ "$answer" = "$name" ] || die "not confirmed; nothing changed"

restore() {
  for id in $blocking; do
    gh api -X PUT "repos/$slug/rulesets/$id" -f enforcement=active --silent ||
      echo "force-push-rewrite.sh: could not enable ruleset $id again; enable it on GitHub" >&2
  done
}
trap restore EXIT
trap 'exit 1' INT TERM

for id in $blocking; do
  gh api -X PUT "repos/$slug/rulesets/$id" -f enforcement=disabled --silent
done

git -C "$dir" push --force "$url" "$branch:$branch"

others=$(git -C "$dir" for-each-ref --format='%(refname:short)' refs/heads |
  grep -vx "$branch" || true)
if [ -n "$others" ]; then
  echo "Not pushed, still on the old history on $url:"
  printf '%s\n' "$others" | sed 's/^/  /'
fi
