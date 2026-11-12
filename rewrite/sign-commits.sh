#!/bin/sh
# Signs again the commits of the default branch that you committed yourself,
# and leaves the result to be checked and pushed; a rewrite by
# rewrite-identities.sh drops every signature.
#
#   sign-commits.sh <rewritten folder> <committer address>
#   sign-commits.sh <owner/repo | clone URL> <committer address> [folder]
#
# Given a folder that rewrite-identities.sh left, it signs there, so that the
# rewrite and the signing reach GitHub in one push. Given a repository, it
# signs in a fresh clone in <folder>, which must not exist yet, or else in a
# new temporary folder; owner/repo stands for git@github.com:owner/repo.git.
# Signs, with the signing key of your git configuration, each commit whose
# committer has <committer address>, and leaves the others unsigned: GitHub
# would show a commit that GitHub or someone else committed, signed with
# your key, as unverified. Names, addresses, dates, messages and merges stay
# as they are; signatures of other commits are dropped. Prints how many
# commits it signed, then the folder, which keeps the original's URL as
# rewrite.source for compare-rewrite.sh and force-push-rewrite.sh.

set -eu

usage() {
  sed -n '2,19p' "$0" | sed 's/^# \{0,1\}//' >&2
  exit 2
}
die() {
  echo "sign-commits.sh: $*" >&2
  exit 1
}

[ $# -ge 2 ] && [ $# -le 3 ] || usage

if [ -d "$1" ] && url=$(git -C "$1" config rewrite.source 2>/dev/null); then
  [ $# -eq 2 ] || usage
  dir=$1
else
  case $1 in
  */*/* | *:* | /* | .*) url=$1 ;;
  */*) url=git@github.com:$1.git ;;
  *) usage ;;
  esac
  dir=
fi
SIGN_EMAIL=$2
export SIGN_EMAIL

key=$(git config user.signingkey) || die "your git configuration has no user.signingkey"
if [ "$(git config gpg.format || true)" = ssh ]; then
  case $key in
  \~/*) pub=$HOME/${key#\~/} ;;
  *) pub=$key ;;
  esac
  [ -f "$pub" ] || die "no signing key at $pub"
  # A key with a passphrase has to be in the agent, or every commit asks.
  if ! ssh-keygen -y -P '' -f "${pub%.pub}" >/dev/null 2>&1 &&
    ! ssh-add -L 2>/dev/null | grep -qF "$(cut -d' ' -f2 "$pub")"; then
    die "the signing key is not in the agent; load it with: ssh-add --apple-use-keychain ${pub%.pub}"
  fi
fi

if [ -z "$dir" ]; then
  if [ $# -eq 3 ]; then
    dir=$3
    [ ! -e "$dir" ] || die "$dir exists already"
  else
    dir=$(mktemp -d "${TMPDIR:-/tmp}/sign-commits.XXXXXX")/$(basename "$url" .git)
  fi
  git clone --quiet "$url" "$dir"
  git -C "$dir" remote remove origin
fi
branch=$(git -C "$dir" symbolic-ref --short HEAD)

# filter-branch sets GIT_COMMITTER_* to each commit's own committer.
# shellcheck disable=SC2016 # the filter's variables expand in filter-branch
FILTER_BRANCH_SQUELCH_WARNING=1 git -C "$dir" filter-branch --commit-filter '
  if [ "$GIT_COMMITTER_EMAIL" = "$SIGN_EMAIL" ]; then
    git commit-tree -S "$@"
  else
    git commit-tree "$@"
  fi' -- "$branch" >/dev/null
git -C "$dir" for-each-ref --format='%(refname)' refs/original |
  while read -r ref; do git -C "$dir" update-ref -d "$ref"; done
git -C "$dir" config rewrite.source "$url"

total=0
signed=0
for c in $(git -C "$dir" rev-list "$branch"); do
  total=$((total + 1))
  if git -C "$dir" cat-file commit "$c" | sed '/^$/q' | grep -q '^gpgsig'; then
    signed=$((signed + 1))
  fi
done
echo "$branch: signed $signed of $total commits, those committed by $SIGN_EMAIL"
echo "$dir"
