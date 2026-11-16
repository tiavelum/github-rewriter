#!/bin/sh
# Tests the scripts of this folder in throwaway repositories, one of which
# plays the original on GitHub.
#
#   sh ~/vc/github-rewriter/rewrite/test-history-rewrite.sh
#
# It needs git filter-repo and skips everything without it. The
# repositories live in a temporary folder that is deleted at the end; KEEP=1
# keeps it. Your own ~/.gitconfig is not read, and nothing is pushed
# anywhere but to the temporary folder. GitHub is never contacted: an
# original given as a path has no rulesets.
#
# Each check is a condition in single quotes that check() evaluates later,
# so the variables in it expand only then, and shellcheck sees them neither
# expanded (SC2016) nor used (SC2034).
# shellcheck disable=SC2016,SC2034

set -u

here=$(cd "$(dirname "$0")" && pwd)

if ! git filter-repo --version >/dev/null 2>&1; then
  echo "git filter-repo is missing; nothing tested"
  exit 0
fi

T=$(mktemp -d "${TMPDIR:-/tmp}/history-rewrite-test.XXXXXX")
if [ "${KEEP:-}" = 1 ]; then
  echo "repositories kept in $T"
else
  trap 'rm -rf "$T"' EXIT
fi

cat >"$T/global" <<EOF
[user]
	name = Test
	email = test@example.com
[commit]
	gpgsign = false
[init]
	defaultBranch = main
[advice]
	detachedHead = false
EOF
export GIT_CONFIG_GLOBAL="$T/global" GIT_CONFIG_NOSYSTEM=1
unset GIT_DIR GIT_WORK_TREE

passed=0
failed=0
check() {
  if (eval "$2") >"$T/out" 2>&1; then
    passed=$((passed + 1))
    printf 'ok    %s\n' "$1"
  else
    failed=$((failed + 1))
    printf 'FAIL  %s\n' "$1"
    sed 's/^/      /' "$T/out" | tail -n 5
  fi
}
q() { "$@" >/dev/null 2>&1; }
# commit <message> <name> <email> <date>: an empty commit by that identity,
# as author and committer, on that date.
commit() {
  GIT_AUTHOR_NAME=$2 GIT_AUTHOR_EMAIL=$3 GIT_AUTHOR_DATE=$4 \
    GIT_COMMITTER_NAME=$2 GIT_COMMITTER_EMAIL=$3 GIT_COMMITTER_DATE=$4 \
    git commit -q --allow-empty -m "$1"
}

# The original, as on GitHub, with a main and a feature branch, and the
# maintainer's clone of it.
git init -q --bare "$T/tool.git"
q git clone "$T/tool.git" "$T/work"
cd "$T/work" || exit 2
commit one AdaE old@example.com 2026-01-01T10:00:00
echo content >file.txt && git add file.txt
commit two "Ada Example" old@example.com 2026-01-02T10:00:00
commit three ada-example new@example.com 2026-01-03T10:00:00
q git push origin main
git switch -q -c feature
commit four AdaE old@example.com 2026-01-04T10:00:00
q git push origin feature
git switch -q main
before=$(git log --format='%ad %cd' --date=raw main)
tree=$(git rev-parse 'main^{tree}')
cd "$T" || exit 2

printf '%s\n' \
  'Ada Example <new@example.com> <old@example.com>' \
  'Ada Example <new@example.com> <new@example.com>' >"$T/mailmap"

check "backup-mirror.sh mirrors every branch" \
  'm=$("$here/backup-mirror.sh" "$T/tool.git" "$T/backup") && git -C "$m" rev-parse -q --verify refs/heads/feature && case $m in "$T/backup/tool-"*.git) ;; *) false ;; esac'

out=$("$here/rewrite-identities.sh" "$T/tool.git" "$T/mailmap" "$T/rewritten" 2>&1)
check "rewrite-identities.sh maps every identity and prints the folder" \
  'printf "%s\n" "$out" | grep -qx " *4 author    Ada Example <new@example.com>" && ! printf "%s\n" "$out" | grep -q -e AdaE -e ada-example -e old@ && [ "$(printf "%s\n" "$out" | tail -n 1)" = "$T/rewritten" ]'
check "rewrite-identities.sh keeps dates and tree" \
  '[ "$(git -C "$T/rewritten" log --format="%ad %cd" --date=raw main)" = "$before" ] && [ "$(git -C "$T/rewritten" rev-parse "main^{tree}")" = "$tree" ]'
check "rewrite-identities.sh refuses an existing folder" \
  '! "$here/rewrite-identities.sh" "$T/tool.git" "$T/mailmap" "$T/rewritten"'
check "rewrite-identities.sh refuses a missing mailmap" \
  '! "$here/rewrite-identities.sh" "$T/tool.git" "$T/nothing" "$T/other"'

check "compare-rewrite.sh passes an identity-only rewrite" \
  '"$here/compare-rewrite.sh" "$T/rewritten" | grep -q "main: 3 commits, dates and tree unchanged"'
check "compare-rewrite.sh leaves no extra ref behind" \
  '[ -z "$(git -C "$T/rewritten" for-each-ref refs/rewrite)" ]'
q "$here/rewrite-identities.sh" "$T/tool.git" "$T/mailmap" "$T/changed"
(cd "$T/changed" && echo more >>file.txt &&
  GIT_COMMITTER_DATE=2026-01-03T10:00:00 git commit -q --amend -a --no-edit)
check "compare-rewrite.sh fails when content changed" \
  '! "$here/compare-rewrite.sh" "$T/changed"'
check "compare-rewrite.sh fails on a folder it did not make" \
  '! "$here/compare-rewrite.sh" "$T/work"'

check "force-push-rewrite.sh pushes nothing unconfirmed" \
  '! echo wrong | "$here/force-push-rewrite.sh" "$T/rewritten" && [ "$(git -C "$T/tool.git" log -1 --format=%an main)" = ada-example ]'
out=$(echo tool | "$here/force-push-rewrite.sh" "$T/rewritten" 2>&1)
check "force-push-rewrite.sh overwrites the branch once confirmed" \
  '[ "$(git -C "$T/tool.git" rev-parse main)" = "$(git -C "$T/rewritten" rev-parse main)" ]'
check "force-push-rewrite.sh leaves other branches and lists them" \
  '[ "$(git -C "$T/tool.git" log -1 --format=%an feature)" = AdaE ] && printf "%s\n" "$out" | grep -qx "  feature"'

echo dirty >>"$T/work/file.txt"
check "reset-clone.sh stops at uncommitted changes" \
  '! "$here/reset-clone.sh" "$T/work" && grep -q dirty "$T/work/file.txt"'
git -C "$T/work" checkout -q -- file.txt
git -C "$T/work" switch -q feature
out=$("$here/reset-clone.sh" "$T/work" 2>&1)
check "reset-clone.sh moves the clone onto the rewritten default branch" \
  '[ "$(git -C "$T/work" branch --show-current)" = main ] && [ "$(git -C "$T/work" rev-parse main)" = "$(git -C "$T/tool.git" rev-parse main)" ]'
check "reset-clone.sh makes the branch track origin and lists the branches" \
  '[ "$(git -C "$T/work" rev-parse --abbrev-ref "main@{upstream}")" = origin/main ] && printf "%s\n" "$out" | grep -q "feature"'

# Signing: an original with a merge, where GitHub committed one commit.
if command -v ssh-keygen >/dev/null 2>&1; then
  git init -q --bare "$T/signed.git"
  q git clone "$T/signed.git" "$T/sign-work"
  cd "$T/sign-work" || exit 2
  commit one Me me@example.com 2026-02-01T10:00:00
  GIT_COMMITTER_NAME=GitHub GIT_COMMITTER_EMAIL=noreply@github.com \
    GIT_COMMITTER_DATE=2026-02-02T10:00:00 GIT_AUTHOR_DATE=2026-02-02T10:00:00 \
    git -c user.name=Me -c user.email=me@example.com commit -q --allow-empty -m two
  git switch -q -c side HEAD~1
  commit side Me me@example.com 2026-02-03T10:00:00
  git switch -q main
  GIT_AUTHOR_DATE=2026-02-04T10:00:00 GIT_COMMITTER_DATE=2026-02-04T10:00:00 \
    git -c user.name=Me -c user.email=me@example.com merge -q --no-ff -m merge side
  q git push origin main
  identities=$(git log --format='%an %ae %cn %ce %ad %cd %s' --date=raw main)
  cd "$T" || exit 2

  check "sign-commits.sh refuses without a signing key" \
    '! "$here/sign-commits.sh" "$T/signed.git" me@example.com "$T/unsigned"'
  ssh-keygen -q -t ed25519 -N '' -C test -f "$T/key"
  git config --global gpg.format ssh
  git config --global user.signingkey "$T/key.pub"

  out=$("$here/sign-commits.sh" "$T/signed.git" me@example.com "$T/signing" 2>&1)
  check "sign-commits.sh signs only the commits of the given committer" \
    'printf "%s\n" "$out" | grep -q "main: signed 3 of 4 commits" && for c in $(git -C "$T/signing" rev-list main); do s=no; git -C "$T/signing" cat-file commit "$c" | sed "/^\$/q" | grep -q "^gpgsig" && s=yes; case $(git -C "$T/signing" log -1 --format=%ce "$c")/$s in me@example.com/yes | noreply@github.com/no) ;; *) exit 1 ;; esac; done'
  check "sign-commits.sh keeps identities, dates, messages and merges" \
    '[ "$(git -C "$T/signing" log --format="%an %ae %cn %ce %ad %cd %s" --date=raw main)" = "$identities" ] && [ "$(git -C "$T/signing" rev-list --merges --count main)" = 1 ]'
  check "sign-commits.sh leaves no backup refs and no remote" \
    '[ -z "$(git -C "$T/signing" for-each-ref refs/original)" ] && [ -z "$(git -C "$T/signing" remote)" ]'
  check "compare-rewrite.sh passes a signed history" \
    '"$here/compare-rewrite.sh" "$T/signing"'

  # One pass: rewrite, then sign the same folder before anything is pushed.
  printf '%s\n' 'New <new@example.com> <me@example.com>' >"$T/mailmap-sign"
  q "$here/rewrite-identities.sh" "$T/signed.git" "$T/mailmap-sign" "$T/one-pass"
  out=$("$here/sign-commits.sh" "$T/one-pass" new@example.com 2>&1)
  check "sign-commits.sh signs a rewritten folder in place" \
    'printf "%s\n" "$out" | grep -q "main: signed 3 of 4 commits" && [ "$(printf "%s\n" "$out" | tail -n 1)" = "$T/one-pass" ]'
  check "sign-commits.sh keeps the rewritten identities" \
    '[ -z "$(git -C "$T/one-pass" log --format="%an%ae%cn%ce" main | grep -e Me -e me@)" ] && [ "$(git -C "$T/one-pass" config rewrite.source)" = "$T/signed.git" ]'
  check "compare-rewrite.sh passes a rewrite signed in one pass" \
    '"$here/compare-rewrite.sh" "$T/one-pass"'
  check "sign-commits.sh refuses a folder argument after a rewritten folder" \
    '! "$here/sign-commits.sh" "$T/one-pass" new@example.com "$T/other-folder"'
else
  echo "ssh-keygen is missing; sign-commits.sh not tested"
fi

printf '\n%s passed, %s failed\n' "$passed" "$failed"
[ "$failed" = 0 ]
