#!/bin/sh
# Tests the replay scripts of this folder against a source built in a
# temporary folder: a mirror with pull request refs, made by backup-mirror.sh,
# a fake gh that answers the source's API from JSON files the test writes, and
# a second fake gh that plays GitHub for the targets the replay writes to.
#
#   sh ~/vc/github-rewriter/replay/test-replay.sh
#
# Needs Python 3.10 or later and git 2.38 or later. The source is built once,
# at the top, and each script's checks follow in a section of their own. The
# folder is deleted at the end; KEEP=1 keeps it. Your own ~/.gitconfig is not
# read, and GitHub is never contacted: a fake gh comes first on PATH. The
# source's refuses, and the test fails on, every request but a GET; the
# targets' keeps each target in a folder of its own, with a bare repository
# that the replay pushes to.
# shellcheck disable=SC2016,SC2034 # each check is a single-quoted condition that check() evaluates later, so its variables are neither expanded nor used before

set -u

here=$(cd "$(dirname "$0")" && pwd)
rewrite=$(cd "$here/../rewrite" && pwd)

T=$(mktemp -d "${TMPDIR:-/tmp}/replay-test.XXXXXX")
if [ "${KEEP:-}" = 1 ]; then
  echo "source kept in $T"
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
# The time run-replay.py gives each recreated commit as committer date, fixed
# so that two runs build the same hashes; in UTC, so that its offset is +0000.
SOURCE_DATE_EPOCH=1794000000 TZ=UTC
export SOURCE_DATE_EPOCH TZ
unset GIT_DIR GIT_WORK_TREE GIT_TERMINAL_PROMPT

passed=0
failed=0
check() {
  if (eval "$2") >"$T/out" 2>&1; then
    passed=$((passed + 1))
    printf 'ok    %s\n' "$1"
  else
    failed=$((failed + 1))
    printf 'FAIL  %s\n' "$1"
    sed 's/^/      /' "$T/out" | tail -n 30
  fi
}
q() { "$@" >/dev/null 2>&1; }
# save <date> <message> [name email [committer name email]]: commits the
# index by that author, and by that committer or else the author, on that
# date. The committer is an argument, since macOS's sh, bash 3.2, keeps an
# assignment written before a function call after the call.
save() {
  GIT_AUTHOR_NAME=${3:-Ada Old} GIT_AUTHOR_EMAIL=${4:-ada.old@example.com} GIT_AUTHOR_DATE=$1 \
    GIT_COMMITTER_NAME=${5:-${3:-Ada Old}} GIT_COMMITTER_EMAIL=${6:-${4:-ada.old@example.com}} \
    GIT_COMMITTER_DATE=$1 git commit -q -m "$2"
}
# change <file> <date> <message> [name] [email]: appends the message to the
# file and commits it.
change() {
  mkdir -p "$(dirname "$1")" && echo "$3" >>"$1" && git add "$1"
  save "$2" "$3" "${4:-Ada Old}" "${5:-ada.old@example.com}"
}

# The source, as on GitHub: direct commits; #2 squash-merged; #3 merged with
# a merge commit; #5 closed unmerged, after its branch merged main past the
# opening of #6; issues #1, #4 and #6 between them. GitHub commits the
# merges; a committed .mailmap must not count. refs/pull/7/head merges a
# commit no pull request holds, for a check that uses another API.
git init -q --bare "$T/source.git"
q git clone "$T/source.git" "$T/work"
cd "$T/work" || exit 2
change README.md 2026-03-01T10:00:00+00:00 "Add the readme"
C1=$(git rev-parse HEAD)
git switch -q -c feat/2-thing
change thing.sh 2026-03-02T09:00:00+00:00 "Add thing"
B1=$(git rev-parse HEAD)
TREEB1=$(git rev-parse 'HEAD^{tree}')
change README.md 2026-03-02T09:30:00+00:00 "README: mention thing"
B2=$(git rev-parse HEAD)
q git push origin HEAD:refs/pull/2/head
git switch -q main
q git merge --squash feat/2-thing
save 2026-03-03T10:00:00+00:00 "Add thing (#2)

* Add thing

* README: mention thing" "Ada Old" ada.old@example.com GitHub noreply@github.com
M2=$(git rev-parse HEAD)
git switch -q -c fix/3-parser
change thing.sh 2026-03-04T09:00:00+00:00 "Repair the parser" "Bob Example" bob@example.com
F1=$(git rev-parse HEAD)
q git push origin HEAD:refs/pull/3/head
git switch -q main
GIT_AUTHOR_NAME="Bob Example" GIT_AUTHOR_EMAIL=bob@example.com \
  GIT_AUTHOR_DATE=2026-03-05T10:00:00+00:00 GIT_COMMITTER_DATE=2026-03-05T10:00:00+00:00 \
  GIT_COMMITTER_NAME=GitHub GIT_COMMITTER_EMAIL=noreply@github.com \
  git merge -q --no-ff -m "Merge pull request #3 from bob-example/fix/3-parser

Repair the parser" fix/3-parser
M3=$(git rev-parse HEAD)
TREE3=$(git rev-parse 'HEAD^{tree}')
change .github/workflows/test.yml 2026-03-05T11:00:00+00:00 "ci: add the test workflow"
C2=$(git rev-parse HEAD)
change tests/test-thing.sh 2026-03-05T14:00:00+02:00 "Update the tests"
C3=$(git rev-parse HEAD)
change thing.sh 2026-03-05T13:00:00+00:00 "Tidy the scripts

No change in behaviour."
C4=$(git rev-parse HEAD)
git switch -q -c docs/5-notes
change notes.md 2026-03-06T09:00:00+00:00 "Add notes"
N1=$(git rev-parse HEAD)
q git push origin HEAD:refs/pull/5/head
git switch -q main
echo 'Wrong Name <wrong@example.com> <ada.old@example.com>' >.mailmap
git add .mailmap
change thing.sh 2026-03-07T12:00:00+00:00 "Rewrite thing in POSIX sh"
C5=$(git rev-parse HEAD)
q git push origin main
git switch -q docs/5-notes
q git merge --no-ff --no-commit main
save 2026-03-07T13:00:00+00:00 "Merge main into docs/5-notes"
N2=$(git rev-parse HEAD)
q git push origin HEAD:refs/pull/5/head
git switch -q -c side "$C1"
change side.md 2026-03-08T09:00:00+00:00 "Add a side note"
S1=$(git rev-parse HEAD)
git switch -q -c feat/7-side "$C5"
q git merge --no-ff --no-commit side
save 2026-03-08T10:00:00+00:00 "Merge the side note"
H7=$(git rev-parse HEAD)
q git push origin HEAD:refs/pull/7/head
cd "$T" || exit 2
export C1 B1 TREEB1 B2 M2 F1 M3 TREE3 C2 C3 C4 N1 C5 N2 S1

mirror=$("$rewrite/backup-mirror.sh" "$T/source.git" "$T/backup") || exit 2

printf '%s\n' \
  'Ada Example <ada@example.com> <ada.old@example.com>' \
  'Ada Example <ada@example.com> GitHub <noreply@github.com>' >"$T/mailmap"
printf '%s\n' '# tidy-ups are chores' "$(echo "$C4" | cut -c1-9) chore" >"$T/types"
printf '%s\n' '3 summary Repairs the parser on empty input.' >"$T/summaries"

# The API of the source, ada-example/tool. GitHub lists issues newest first,
# so page 1 holds #6 to #4.
mkdir "$T/api"
api=$T/api/repos_ada-example_tool
echo '{"default_branch": "main"}' >"$api.json"
cat >"${api}_labels-1.json" <<'EOF'
[{"name": "docs", "color": "0075ca", "description": "Documentation"},
 {"name": "bug", "color": "d73a4a", "description": "Something isn't working"}]
EOF
cat >"${api}_issues-1.json" <<'EOF'
[{"number": 6, "title": "Thing breaks on Sundays", "body": "Seen twice.", "state": "open",
  "state_reason": null, "labels": [{"name": "bug"}, {"name": "docs"}],
  "assignees": [{"login": "ada-example"}], "user": {"login": "bob-example"},
  "created_at": "2026-03-07T11:00:00Z", "closed_at": null},
 {"number": 5, "title": "Notes", "body": null, "state": "closed", "state_reason": null,
  "labels": [], "assignees": [], "user": {"login": "ada-example"},
  "created_at": "2026-03-06T10:00:00Z", "closed_at": "2026-03-08T10:00:00Z",
  "pull_request": {"merged_at": null}},
 {"number": 4, "title": "Support tabs", "body": "Tabs would help.", "state": "closed",
  "state_reason": "not_planned", "labels": [{"name": "bug"}], "assignees": [],
  "user": {"login": "bob-example"}, "created_at": "2026-03-04T11:00:00Z",
  "closed_at": "2026-03-06T11:00:00Z"}]
EOF
cat >"${api}_issues-2.json" <<'EOF'
[{"number": 3, "title": "Repair the parser",
  "body": "Fixes #4\r\n\r\n## Why\r\n\r\nThe parser had two faults:\r\n\r\nThe parser failed on empty input. It now returns an empty list for it, as the readme says, and a test covers the case, so that a later change cannot break it again without the test failing; input of blanks alone, which it read as one empty field until now, it now skips as well, as the readme also says.\r\n\r\nDetails follow here.",
  "state": "closed", "state_reason": null, "labels": [], "assignees": [],
  "user": {"login": "bob-example"}, "created_at": "2026-03-04T10:00:00Z",
  "closed_at": "2026-03-05T10:00:00Z", "pull_request": {"merged_at": "2026-03-05T10:00:00Z"}},
 {"number": 2, "title": "Add thing", "body": "Adds thing.\n\nCloses #1", "state": "closed",
  "state_reason": null, "labels": [], "assignees": [], "user": {"login": "ada-example"},
  "created_at": "2026-03-02T10:00:00Z", "closed_at": "2026-03-03T10:00:00Z",
  "pull_request": {"merged_at": "2026-03-03T10:00:00Z"}},
 {"number": 1, "title": "Explain the tool", "body": "The readme is empty.", "state": "closed",
  "state_reason": "completed", "labels": [], "assignees": [], "user": {"login": "bob-example"},
  "created_at": "2026-03-01T11:00:00Z", "closed_at": "2026-03-03T11:00:00Z"}]
EOF
cat >"${api}_pulls-1.json" <<EOF
[{"number": 5, "head": {"ref": "docs/5-notes", "sha": "$N2"}, "base": {"ref": "main"},
  "merged_at": null, "merge_commit_sha": "0123456789abcdef0123456789abcdef01234567",
  "draft": false, "created_at": "2026-03-06T10:00:00Z"},
 {"number": 3, "head": {"ref": "fix/3-parser", "sha": "$F1"}, "base": {"ref": "main"},
  "merged_at": "2026-03-05T10:00:00Z", "merge_commit_sha": "$M3", "draft": false,
  "created_at": "2026-03-04T10:00:00Z"},
 {"number": 2, "head": {"ref": "feat/2-thing", "sha": "$B2"}, "base": {"ref": "main"},
  "merged_at": "2026-03-03T10:00:00Z", "merge_commit_sha": "$M2", "draft": false,
  "created_at": "2026-03-02T10:00:00Z"}]
EOF
cat >"${api}_issues_comments-1.json" <<'EOF'
[{"id": 101, "issue_url": "https://api.github.com/repos/ada-example/tool/issues/1",
  "body": "Seen in the readme.", "user": {"login": "ada-example"},
  "created_at": "2026-03-02T12:00:00Z"},
 {"id": 102, "issue_url": "https://api.github.com/repos/ada-example/tool/issues/3",
  "body": "Looks right.", "user": {"login": "ada-example"}, "created_at": "2026-03-04T12:00:00Z"},
 {"id": 103, "issue_url": "https://api.github.com/repos/ada-example/tool/issues/4",
  "body": "Not needed after all.", "user": {"login": "bob-example"},
  "created_at": "2026-03-06T12:00:00Z"}]
EOF
# The same API, with a pull request #7 whose branch merges a commit that
# neither the default branch nor a pull request holds.
cp -R "$T/api" "$T/api-stray"
{
  printf '%s\n' '[{"number": 7, "head": {"ref": "feat/7-side", "sha": "'"$H7"'"}, "base": {"ref": "main"},' \
    '  "merged_at": null, "merge_commit_sha": null, "draft": false, "created_at": "2026-03-08T11:00:00Z"},'
  tail -c +2 "${api}_pulls-1.json"
} >"$T/api-stray/repos_ada-example_tool_pulls-1.json"

# The fake gh answers "gh api <endpoint>" from $FAKE_GH_API, a listed page
# that has no file with an empty list. It logs every call, and refuses, and
# records in $FAKE_GH_REFUSED, every method but GET, every field and every
# other option, --paginate included.
mkdir "$T/bin"
cat >"$T/bin/gh" <<'EOF'
#!/bin/sh
echo "$*" >>"$FAKE_GH_LOG"
refuse() {
  echo "$*" >>"$FAKE_GH_REFUSED"
  echo "fake gh: refused: $*" >&2
  exit 1
}
[ "${1:-}" = api ] || refuse "$@"
shift
method=GET endpoint=
while [ $# -gt 0 ]; do
  case $1 in
  -X | --method) method=${2:-}; shift ;;
  -X* | --method=*) method=${1#-X}; method=${method#--method=} ;;
  -*) refuse "option $1" ;;
  *) endpoint=$1 ;;
  esac
  shift
done
[ "$method" = GET ] || refuse "$method $endpoint"
path=$(printf '%s' "${endpoint%%\?*}" | tr / _)
case $endpoint in
*[?\&]page=*)
  page=$(printf '%s\n' "$endpoint" | sed 's/.*[?&]page=\([0-9]*\).*/\1/')
  if [ -f "$FAKE_GH_API/$path-$page.json" ]; then cat "$FAKE_GH_API/$path-$page.json"; else echo '[]'; fi
  ;;
*)
  [ -f "$FAKE_GH_API/$path.json" ] || { echo '{"message": "Not Found"}'; exit 1; }
  cat "$FAKE_GH_API/$path.json"
  ;;
esac
EOF
chmod +x "$T/bin/gh"
PATH=$T/bin:$PATH
FAKE_GH_API=$T/api FAKE_GH_LOG=$T/gh-calls FAKE_GH_REFUSED=$T/gh-refused
export PATH FAKE_GH_API FAKE_GH_LOG FAKE_GH_REFUSED

# condition.py holds holds(), which evaluates a Python condition in a
# namespace; when it is false, it prints each false part of an "and", with
# the values compared.
cat >"$T/condition.py" <<'EOF'
import ast
import sys


def holds(source, namespace):
    tree = ast.parse(source, mode="eval").body
    is_and = isinstance(tree, ast.BoolOp) and isinstance(tree.op, ast.And)
    parts = tree.values if is_and else [tree]

    def value(node):
        return eval(compile(ast.Expression(node), "<check>", "eval"), namespace)

    for part in parts:
        try:
            if value(part):
                continue
            print("false:", ast.get_source_segment(source, part))
            if isinstance(part, ast.Compare):
                for side in [part.left, *part.comparators]:
                    print("  ", ast.get_source_segment(source, side), "=", repr(value(side))[:400])
        except Exception as error:
            print("error:", ast.get_source_segment(source, part), "->", repr(error))
        sys.exit(1)
EOF

# expect <condition>: a Python condition on the plan in $plan_file, with H its header, E
# its events, the source's hashes in S, of(kind[, number]) the events of a
# kind, commit(sha) a planned commit and title(sha) its first line.
plan_file=$T/events.jsonl
expect() {
  python3 - "$plan_file" "$1" "$T" <<'EOF'
import json, os, sys
sys.path.insert(0, sys.argv[3])
from condition import holds
with open(sys.argv[1], encoding="utf-8") as f:
    H, *E = [json.loads(line) for line in f]
S = os.environ
def of(kind, number=None):
    return [e for e in E if e["kind"] == kind and number in (None, e.get("number"))]
def commit(sha):
    return next(c for e in E for c in e.get("commits", []) if c["sha"] == sha)
def title(sha):
    return commit(sha)["message"].partition("\n")[0]
holds(sys.argv[2], globals())
EOF
}
pcheck() {
  condition=$2
  check "$1" 'expect "$condition"'
}

# plan-replay.py
plan() { python3 "$here/plan-replay.py" "$@"; }
plan --types "$T/types" "$mirror" ada-example/tool "$T/mailmap" "$T/events.jsonl" \
  >"$T/plan-out" 2>"$T/plan-err"
status=$?
check "plan-replay.py writes the plan and prints the totals, without warnings" \
  '[ "$status" = 0 ] || { echo "exit status $status"; cat "$T/plan-err"; exit 1; }
  [ ! -s "$T/plan-err" ] || { echo "standard error:"; cat "$T/plan-err"; exit 1; }
  last=$(tail -n 1 "$T/plan-out")
  [ "$last" = "$T/events.jsonl" ] || { echo "last line \"$last\", expected \"$T/events.jsonl\""; exit 1; }
  for t in "items +6" "issues +3" "pull requests +3" "comments +3" "labels +2" "commits +10" "squash merges +2" "merge commits +0" "events +22" "events out of time order +3"; do
    grep -Eqx "  $t" "$T/plan-out" || { echo "no line \"$t\" in:"; cat "$T/plan-out"; exit 1; }
  done'
pcheck "plan-replay.py creates the items in number order, issues and pull requests interleaved" \
  '[(e["number"], e["kind"]) for e in E if e["kind"] in ("create-issue", "create-pull")] == [(1, "create-issue"), (2, "create-pull"), (3, "create-pull"), (4, "create-issue"), (5, "create-pull"), (6, "create-issue")]'
pcheck "plan-replay.py orders the events by time, after the labels" \
  '[e["seq"] for e in E] == list(range(1, len(E) + 1)) and [e["kind"] for e in E[:2]] == ["create-label"] * 2 and all(e["time"] for e in E[2:]) and (rest := [e["time"] for e in E[2:] if (e["kind"], e.get("number")) not in [("push-branch", 5), ("create-pull", 5), ("create-issue", 6)]]) == sorted(rest)'
pcheck "plan-replay.py places a pull request whose branch merges a later commit of the default branch after that commit" \
  'E.index(of("push-branch", 5)[0]) == E.index(of("push-commits")[-1]) + 1 and commit(S["N2"])["parents"] == [S["N1"], S["C5"]] and [(E[i]["kind"], E[i].get("number")) for i in range(3, len(E)) if E[i]["time"] < max(e["time"] for e in E[2:i])] == [("push-branch", 5), ("create-pull", 5), ("create-issue", 6)]'
pcheck "plan-replay.py pushes a branch right before its pull request and comments after the item" \
  'all(E.index(of("push-branch", n)[0]) + 1 == E.index(of("create-pull", n)[0]) for n in (2, 3, 5)) and all(E.index(e) > E.index((of("create-issue", e["number"]) + of("create-pull", e["number"]))[0]) for e in of("add-comment"))'
pcheck "plan-replay.py applies the mailmap to author and committer, not the committed .mailmap" \
  '{(p["name"], p["email"]) for e in E for c in e.get("commits", []) for p in (c["author"], c["committer"])} == {("Ada Example", "ada@example.com"), ("Bob Example", "bob@example.com")} and commit(S["F1"])["committer"]["email"] == "bob@example.com"'
pcheck "plan-replay.py keeps the original dates, trees and parents" \
  'commit(S["C1"])["author"]["date"] == "2026-03-01T10:00:00+00:00" and commit(S["C3"])["committer"]["date"] == "2026-03-05T14:00:00+02:00" and commit(S["B1"])["tree"] == S["TREEB1"] and commit(S["F1"])["parents"] == [S["M2"]] and of("push-branch", 3)[0]["base_commit"] == S["M2"] and of("merge-pull", 3)[0]["tree"] == S["TREE3"]'
pcheck "plan-replay.py takes the type from the branch prefix" \
  'title(S["B1"]) == "feat: add thing" and of("create-pull", 3)[0]["title"] == "fix: repair the parser" and title(S["N1"]) == "docs: add notes" and commit(S["B1"])["type_from"] == "branch"'
pcheck "plan-replay.py keeps a type that is present" \
  'title(S["C2"]) == "ci: add the test workflow" and commit(S["C2"])["type_from"] == "present"'
pcheck "plan-replay.py guesses and marks the type of a direct commit" \
  '[(title(S[k]), commit(S[k])["type_from"]) for k in ("C1", "C3", "C5")] == [("docs: add the readme", "guess"), ("test: update the tests", "guess"), ("feat: rewrite thing in POSIX sh", "guess")]'
pcheck "plan-replay.py respects the override file" \
  'title(S["C4"]) == "chore: tidy the scripts" and commit(S["C4"])["type_from"] == "override"'
pcheck "plan-replay.py lowercases only a capitalised ordinary first word" \
  'title(S["B2"]) == "feat: README: mention thing" and title(S["C5"]).endswith("POSIX sh") and of("create-pull", 2)[0]["title"] == "feat: add thing"'
pcheck "plan-replay.py keeps bodies as they are" \
  'of("create-pull", 2)[0]["body"] == "Adds thing.\n\nCloses #1" and of("create-pull", 3)[0]["body"].count("\r\n") == 8 and of("create-issue", 4)[0]["body"] == "Tabs would help." and [e["body"] for e in of("add-comment", 3)] == ["Looks right."] and commit(S["B1"])["message"] == "feat: add thing\n" and commit(S["C4"])["message"] == "chore: tidy the scripts\n\nNo change in behaviour.\n"'
pcheck "plan-replay.py squash-merges a squashed pull request with its typed title and body" \
  'of("merge-pull", 2)[0]["commit_title"] == "feat: add thing (#2)" and of("merge-pull", 2)[0]["commit_message"] == "* Add thing\n\n* README: mention thing" and of("merge-pull", 2)[0]["source_commit"] == S["M2"]'
pcheck "plan-replay.py turns a merge commit into a squash merge, summing up the description past keywords, headings and lead-ins" \
  '(m := of("merge-pull", 3)[0]) and (m["method"], m["source_method"], m["commit_title"], m["commit_message"]) == ("squash", "merge", "fix: repair the parser (#3)", "The parser failed on empty input.\n\n{pr_url}")'
pcheck "plan-replay.py gives a closed unmerged pull request a branch, create and close but no merge" \
  '[c["sha"] for c in of("push-branch", 5)[0]["commits"]] == [S["N1"], S["N2"]] and of("create-pull", 5)[0]["state"] == "closed" and len(of("close-item", 5)) == 1 and not of("merge-pull", 5)'
pcheck "plan-replay.py closes issues with their state reason and keeps labels and assignees" \
  '[(e["number"], e["state_reason"]) for e in of("close-item")] == [(1, "completed"), (4, "not_planned"), (5, None)] and (of("create-issue", 6)[0]["labels"], of("create-issue", 6)[0]["assignees"]) == (["bug", "docs"], ["ada-example"])'
pcheck "plan-replay.py pushes direct commits in a row as one push" \
  '[[c["sha"] for c in e["commits"]] for e in of("push-commits")] == [[S["C1"]], [S["C2"], S["C3"], S["C4"]], [S["C5"]]]'
pcheck "plan-replay.py lists every recreated source commit in the header" \
  'H["kind"] == "header" and H["source"] == "ada-example/tool" and sorted(H["source_commits"]) == sorted(S[k] for k in ("C1", "B1", "B2", "M2", "F1", "M3", "C2", "C3", "C4", "N1", "C5", "N2"))'
check "plan-replay.py prints every changed title, marking guessed types" \
  'c1=$(echo "$C1" | cut -c1-7) && grep -Fqx "  $c1  guessed  Add the readme  ->  docs: add the readme" "$T/plan-out" && grep -Fqx "  #3                Repair the parser  ->  fix: repair the parser" "$T/plan-out" && ! grep -q "ci: add the test workflow" "$T/plan-out" && grep -qx "Changed titles: 14" "$T/plan-out" || { cat "$T/plan-out"; exit 1; }'
check "plan-replay.py prints every squash message it writes for a merge commit" \
  'grep -qx "Squash messages written for merge commits: 1" "$T/plan-out" && grep -Fqx "  #3  fix: repair the parser (#3)" "$T/plan-out" && grep -Fqx "      The parser failed on empty input." "$T/plan-out" && grep -Fqx "      {pr_url}" "$T/plan-out" || { cat "$T/plan-out"; exit 1; }'

plan --no-types --types "$T/summaries" "$mirror" ada-example/tool "$T/mailmap" "$T/plain.jsonl" \
  >"$T/plain-out" 2>"$T/plain-err"
status_plain=$?
plan --keep-merges --types "$T/types" "$mirror" ada-example/tool "$T/mailmap" "$T/merges.jsonl" \
  >"$T/merges-out" 2>"$T/merges-err"
status_merges=$?
# --no-types changes only the first line of the squash merge of #3, to its pull request's title.
check "plan-replay.py plans with --no-types and with --keep-merges, without warnings" \
  '[ "$status_plain$status_merges" = 00 ] && [ ! -s "$T/plain-err" ] && [ ! -s "$T/merges-err" ] && grep -qx "Changed titles: 1" "$T/plain-out" && grep -Eqx "  squash merges +1" "$T/merges-out" && grep -Eqx "  merge commits +1" "$T/merges-out" && grep -qx "Squash messages written for merge commits: 0" "$T/merges-out" || { cat "$T/plain-err" "$T/plain-out" "$T/merges-err" "$T/merges-out"; exit 1; }'
plan --no-types --types "$T/types" "$mirror" ada-example/tool "$T/mailmap" "$T/plain-typed.jsonl" \
  >"$T/plain-typed-out" 2>"$T/plain-typed-err"
status_plain_typed=$?
check "plan-replay.py --no-types ignores the type lines of the override file without a warning" \
  '[ "$status_plain_typed" = 0 ] && [ ! -s "$T/plain-typed-err" ] || { cat "$T/plain-typed-err"; exit 1; }'
plan_file=$T/plain.jsonl
pcheck "plan-replay.py --no-types keeps every title as it is" \
  'title(S["B1"]) == "Add thing" and title(S["C2"]) == "ci: add the test workflow" and of("create-pull", 3)[0]["title"] == "Repair the parser" and of("merge-pull", 2)[0]["commit_title"] == "Add thing (#2)" and {(c["type"], c["type_from"]) for e in E for c in e.get("commits", [])} == {(None, None)}'
pcheck "plan-replay.py takes the summary of a squash message from the override file" \
  '(m := of("merge-pull", 3)[0]) and (m["commit_title"], m["commit_message"]) == ("Repair the parser (#3)", "Repairs the parser on empty input.\n\n{pr_url}")'
plan_file=$T/merges.jsonl
pcheck "plan-replay.py --keep-merges merges a merge commit with its message and tree" \
  '(m := of("merge-pull", 3)[0]) and (m["method"], m["source_method"], m["commit_title"], m["commit_message"], m["tree"], m["type"]) == ("merge", "merge", "Merge pull request #3 from bob-example/fix/3-parser", "Repair the parser", S["TREE3"], None) and of("merge-pull", 2)[0]["method"] == "squash" and of("create-pull", 3)[0]["title"] == "fix: repair the parser"'
plan_file=$T/events.jsonl

check "plan-replay.py reads every page and calls gh only with GET requests" \
  '[ ! -e "$T/gh-refused" ] && grep -q "issues?state=all&per_page=100&page=3" "$T/gh-calls" && ! grep -v "^api repos/ada-example/tool" "$T/gh-calls" || { cat "$T/gh-calls" "$T/gh-refused" 2>&1; exit 1; }'
check "the fake gh refuses writing requests" \
  '(FAKE_GH_REFUSED=$T/guard; export FAKE_GH_REFUSED; ! gh api -X POST repos/a/b/issues && ! gh api repos/a/b/issues -f title=x && ! gh api --method PATCH repos/a/b/issues/1) && [ "$(wc -l <"$T/guard")" -eq 3 ]'
check "plan-replay.py stops with a message at a branch that merges a commit no pull request holds" \
  '(FAKE_GH_API=$T/api-stray; export FAKE_GH_API; ! plan "$mirror" ada-example/tool "$T/mailmap" "$T/stray.jsonl" 2>"$T/stray-err") && s1=$(echo "$S1" | cut -c1-7) && grep -q "the branch of pull request #7 merges $s1, which is neither" "$T/stray-err" && ! grep -q Traceback "$T/stray-err" && [ ! -e "$T/stray.jsonl" ] || { cat "$T/stray-err"; exit 1; }'
check "plan-replay.py refuses an existing event file and a missing folder" \
  '! plan "$mirror" ada-example/tool "$T/mailmap" "$T/events.jsonl" && [ "$(wc -l <"$T/events.jsonl")" -eq 23 ] && ! plan "$mirror" ada-example/tool "$T/mailmap" "$T/nodir/out.jsonl" 2>"$T/nodir-err" && grep -q "^plan-replay.py: no folder .*/nodir for the event file$" "$T/nodir-err" && ! grep -q Traceback "$T/nodir-err" || { cat "$T/nodir-err"; exit 1; }'
check "plan-replay.py refuses a missing mailmap and a wrong line in the override file" \
  '! plan "$mirror" ada-example/tool "$T/nothing" "$T/other.jsonl" && printf "%s\n" "1 feature" >"$T/bad-types" && ! plan --types "$T/bad-types" "$mirror" ada-example/tool "$T/mailmap" "$T/other.jsonl" && printf "%s\n" "abc1234 summary Text" >"$T/bad-summary" && ! plan --types "$T/bad-summary" "$mirror" ada-example/tool "$T/mailmap" "$T/other.jsonl" && [ ! -e "$T/other.jsonl" ]'

# run-replay.py
# The plan it applies gets a fourth comment, on #6, after every merge, that
# names a direct commit and a squash merge by their hashes, and a word of hex
# characters that is no commit.
cp -R "$T/api" "$T/api-run"
python3 - "$T/api-run/repos_ada-example_tool_issues_comments-1.json" "$C4" "$M2" <<'EOF'
import json, sys
path, c4, m2 = sys.argv[1:]
with open(path, encoding="utf-8") as f:
    comments = json.load(f)
comments.append({"id": 104, "issue_url": "https://api.github.com/repos/ada-example/tool/issues/6",
                 "body": f"Tidied in {c4[:7]}, after {m2[:10]}; abcdef0 is no commit.",
                 "user": {"login": "ada-example"}, "created_at": "2026-03-08T12:00:00Z"})
with open(path, "w", encoding="utf-8") as f:
    json.dump(comments, f)
EOF
(FAKE_GH_API=$T/api-run && export FAKE_GH_API && plan --types "$T/types" "$mirror" ada-example/tool "$T/mailmap" "$T/run.jsonl") >"$T/run-plan-out" 2>&1
status_run_plan=$?

# What a replay leaves behind: a copy of the mirror with a lightweight and an
# annotated tag and four branches, those of #2 and #3 at their pull requests'
# heads, that of #5 at another commit than its pull request's head, and one of
# no pull request; and a copy of the run's API with a release and a draft.
# api-extra-del is the same source deleting head branches on merge.
mirror_extra=$T/mirror-extra.git
cp -R "$mirror" "$mirror_extra"
for ref in "wip/idea $C5" "feat/2-thing $B2" "fix/3-parser $F1" "docs/5-notes $N1"; do
  git --git-dir="$mirror_extra" update-ref "refs/heads/${ref% *}" "${ref#* }"
done
git --git-dir="$mirror_extra" tag v0.1 "$M2"
git --git-dir="$mirror_extra" tag -a v0.2 -m "Second" "$C5"
cp -R "$T/api-run" "$T/api-extra"
cat >"$T/api-extra/repos_ada-example_tool_releases-1.json" <<'EOF'
[{"id": 2, "tag_name": "v0.3", "name": "Next", "draft": true, "prerelease": false},
 {"id": 1, "tag_name": "v0.2", "name": "Second", "draft": false, "prerelease": false}]
EOF
cp -R "$T/api-extra" "$T/api-extra-del"
echo '{"default_branch": "main", "delete_branch_on_merge": true}' >"$T/api-extra-del/repos_ada-example_tool.json"
printf '%s\n' '# left to the archive' 'branch docs/5-notes' 'branch wip/idea' 'tag v0.1' 'tag v0.2' \
  'release v0.2' 'release v0.3' 'tag v9' >"$T/leave"
# plan_extra <API folder> <event file> [<option>...]: plans the copy of the mirror.
plan_extra() {
  api_folder=$1 events=$2
  shift 2
  (FAKE_GH_API=$api_folder && export FAKE_GH_API && plan --types "$T/types" "$@" "$mirror_extra" ada-example/tool "$T/mailmap" "$events")
}
plan_extra "$T/api-extra" "$T/extra-stop.jsonl" >"$T/extra-stop-out" 2>"$T/extra-stop-err"
status_extra_stop=$?
plan_extra "$T/api-extra" "$T/extra.jsonl" --leave-behind "$T/leave" >"$T/extra-out" 2>"$T/extra-err"
status_extra=$?
plan_extra "$T/api-extra-del" "$T/extra-del.jsonl" >"$T/extra-del-out" 2>"$T/extra-del-err"
status_extra_del=$?
export N1 N2
check "plan-replay.py stops, and writes no event file, at each tag, release and branch it leaves behind that --leave-behind does not accept" \
  'n1=$(echo "$N1" | cut -c1-7) n2=$(echo "$N2" | cut -c1-7) c5=$(echo "$C5" | cut -c1-7) m2=$(echo "$M2" | cut -c1-7) && [ "$status_extra_stop" = 1 ] && [ ! -e "$T/extra-stop.jsonl" ] && grep -q "^plan-replay.py: the replay leaves behind 6 of the source'"'"'s tags, releases and branches that --leave-behind does not accept" "$T/extra-stop-err" && for line in "  branch   docs/5-notes  # at $n1; the replay pushes the head of #5, $n2, under its name" "  branch   wip/idea      # at $c5, the head of no pull request" "  tag      v0.1          # lightweight, at $m2; the replay pushes no tags" "  tag      v0.2          # annotated, at $c5; the replay pushes no tags" "  release  v0.2          # published, named '"'"'Second'"'"'; the replay creates no releases" "  release  v0.3          # draft, named '"'"'Next'"'"'; the replay creates no releases"; do grep -Fqx "$line" "$T/extra-stop-err" || { echo "no line: $line"; exit 1; }; done && ! grep -q "feat/2-thing\|fix/3-parser\|Traceback" "$T/extra-stop-err" || { cat "$T/extra-stop-err"; exit 1; }'
plan_file=$T/extra.jsonl
pcheck "plan-replay.py records what --leave-behind accepts in the header, and plans nothing else differently" \
  '[(x["kind"], x["name"]) for x in H["left_behind"]] == [("branch", "docs/5-notes"), ("branch", "wip/idea"), ("tag", "v0.1"), ("tag", "v0.2"), ("release", "v0.2"), ("release", "v0.3")] and [x["sha"] for x in H["left_behind"]] == [S["N1"], S["C5"], S["M2"], S["C5"], None, None] and E == [json.loads(line) for line in open(os.path.join(os.path.dirname(sys.argv[1]), "run.jsonl"), encoding="utf-8").read().splitlines()[1:]]'
plan_file=$T/events.jsonl
check "plan-replay.py prints what it leaves behind, counts it, and warns of an accepted line that names nothing it leaves behind" \
  '[ "$status_extra" = 0 ] && grep -qx "Left behind: 6" "$T/extra-out" && grep -Eqx "  left behind +6" "$T/extra-out" && grep -Eqx "  tag      v0.1          lightweight, at [0-9a-f]{7}; the replay pushes no tags" "$T/extra-out" && grep -qx "plan-replay.py: warning: .*/leave accepts tag v9, which the replay does not leave behind" "$T/extra-err" && [ "$(wc -l <"$T/extra-err")" -eq 1 ] && grep -qx "Left behind: 0" "$T/plan-out" && grep -Eqx "  left behind +0" "$T/plan-out" || { cat "$T/extra-err" "$T/extra-out"; exit 1; }'
check "plan-replay.py leaves behind the branch of a merged pull request where the source deletes head branches on merge" \
  '[ "$status_extra_del" = 1 ] && grep -q "^plan-replay.py: the replay leaves behind 8 of" "$T/extra-del-err" && grep -Fqx "  branch   feat/2-thing  # the head of #2, which the replay deletes on its merge, as the source deletes head branches" "$T/extra-del-err" && grep -Fqx "  branch   fix/3-parser  # the head of #3, which the replay deletes on its merge, as the source deletes head branches" "$T/extra-del-err" || { cat "$T/extra-del-err"; exit 1; }'
grep '^  [a-z]* ' "$T/extra-stop-err" >"$T/leave-pasted"
plan_extra "$T/api-extra" "$T/extra-pasted.jsonl" --leave-behind "$T/leave-pasted" >"$T/extra-pasted-out" 2>&1
status_extra_pasted=$?
check "plan-replay.py takes the lines it prints where it stops, with their comments, as lines of --leave-behind" \
  '[ "$status_extra_pasted" = 0 ] && [ "$(wc -l <"$T/leave-pasted")" -eq 6 ] && grep -qx "Left behind: 6" "$T/extra-pasted-out" || { cat "$T/leave-pasted" "$T/extra-pasted-out"; exit 1; }'
# A tag of the annotated tag v0.2, a tag of a tree, and a tag whose name holds
# a no-break space, which git allows.
mirror_odd=$T/mirror-odd.git
cp -R "$mirror_extra" "$mirror_odd"
git -c advice.nestedTag=false --git-dir="$mirror_odd" tag -a v0.3 -m "Third" v0.2
git --git-dir="$mirror_odd" tag tree-tag "$C5^{tree}"
nbsp=$(printf 'sp\302\240ace')
git --git-dir="$mirror_odd" tag "$nbsp" "$C5"
# plan_odd <event file> [<option>...]: plans that mirror.
plan_odd() {
  events=$1
  shift
  (FAKE_GH_API=$T/api-extra && export FAKE_GH_API && plan --types "$T/types" "$@" "$mirror_odd" ada-example/tool "$T/mailmap" "$events")
}
plan_odd "$T/odd-stop.jsonl" >/dev/null 2>"$T/odd-stop-err"
grep '^  [a-z]* ' "$T/odd-stop-err" >"$T/leave-odd"
plan_odd "$T/odd.jsonl" --leave-behind "$T/leave-odd" >"$T/odd-out" 2>&1
status_odd=$?
export nbsp
check "plan-replay.py peels a tag of a tag to its commit, names a tag of a tree as such, and takes back a name with a no-break space" \
  'c5=$(echo "$C5" | cut -c1-7) tree=$(git --git-dir="$mirror_odd" rev-parse "$C5^{tree}" | cut -c1-7) && grep -Eqx "  tag      v0\.3 +# annotated, at $c5; the replay pushes no tags" "$T/odd-stop-err" && grep -Eqx "  tag      tree-tag +# lightweight, at the tree $tree; the replay pushes no tags" "$T/odd-stop-err" && grep -Fq "  tag      $nbsp " "$T/odd-stop-err" && [ "$status_odd" = 0 ] && grep -qx "Left behind: 9" "$T/odd-out" || { cat "$T/odd-stop-err" "$T/odd-out"; exit 1; }'
plan_file=$T/odd.jsonl
pcheck "plan-replay.py records the commit a tag of a tag peels to in the header" \
  '[x["sha"] for x in H["left_behind"] if (x["kind"], x["name"]) == ("tag", "v0.3")] == [S["C5"]]'
plan_file=$T/events.jsonl
check "plan-replay.py refuses a line of --leave-behind other than a kind and a name" \
  'printf "%s\n" "tags v0.1" >"$T/bad-leave" && ! plan_extra "$T/api-extra" "$T/bad-leave.jsonl" --leave-behind "$T/bad-leave" 2>"$T/bad-leave-err" && grep -qx "plan-replay.py: .*/bad-leave:1: expected one of tag, release, branch and a name" "$T/bad-leave-err" && [ ! -e "$T/bad-leave.jsonl" ] || { cat "$T/bad-leave-err"; exit 1; }'

# The fake gh of the targets: "gh api --include --method M <endpoint>
# [--input -]" against the target named in $FAKE_GITHUB/name, whose items,
# comments and labels it keeps in JSON files in $FAKE_GITHUB and whose git
# repository is the bare $FAKE_GITHUB/repo.git. It numbers issues and pull
# requests in one sequence, merges as GitHub does, with GitHub as committer
# and fixed dates, and closes the issues a merged pull request names with a
# closing keyword. It logs every call, with its time, in $FAKE_GITHUB/calls
# and every closing in closes.json; a pull request gets refs/pull/<number>/head,
# as on GitHub. It answers a GET of another repository
# from the files in $FAKE_GH_API, as the fake gh of the source does, and a
# call without --include with the body alone, as gh does. Each FAKE_GH_* variable names a call
# "<method> <endpoint>" and acts on its first occurrence: RATE_LIMIT answers
# 403 with Retry-After: 1 and does nothing, DENY answers 403 without a rate
# limit and does nothing, INTERRUPT sends the caller a
# SIGINT, as a Ctrl-C does, LOSE does the call and answers 502; FAKE_GH_SKIP
# gives its number to an issue someone else creates, and FAKE_GH_LAG leaves
# the highest-numbered item and every pull request out of the first answer to
# the list of issues it names, as GitHub's list lags behind an item just
# created. It lists the signing keys
# of the account from ssh_signing_keys.json and gpg_keys.json, none where a
# file is missing; with FAKE_GH_NO_SCOPE, it refuses those lists as GitHub
# refuses a token without the scope they need. Where $FAKE_GITHUB/absent
# exists, the target does not exist until a POST user/repos or orgs/*/repos
# creates it, private where asked, with the default branch $FAKE_GH_DEFAULT,
# main where it is unset; PUT actions/permissions keeps Actions in
# actions.json, a PATCH of the repository keeps its settings in settings.json,
# but refuses a default branch the target lacks and records that in rejected,
# and a merge deletes the head branch where delete_branch_on_merge is on. It
# keeps the sub-issue links of every repository in links.json, by parent, as
# lists of issue ids, with the ids of the target's items 7000 plus the number
# and those of other repositories from their issues in $FAKE_GH_API; it gives
# each issue it lists from there its parent_issue_url and sub_issues_summary,
# and logs the body of each move of a sub-issue in priorities.
mkdir "$T/bin-target"
cat >"$T/bin-target/gh" <<'EOF'
#!/usr/bin/env python3
import json, os, re, signal, subprocess, sys, time
from pathlib import Path
from urllib.parse import parse_qs, unquote

root = Path(os.environ["FAKE_GITHUB"])
slug = (root / "name").read_text().strip()
repo = root / "repo.git"
REASONS = {200: "OK", 201: "Created", 204: "No Content", 403: "Forbidden", 404: "Not Found",
           405: "Method Not Allowed", 409: "Conflict", 422: "Unprocessable Entity", 502: "Bad Gateway"}
CLOSING = re.compile(r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?):?\s+#(\d+)\b", re.I)


def load(name, default):
    path = root / f"{name}.json"
    return json.loads(path.read_text()) if path.exists() else default


def save(name, value):
    (root / f"{name}.json").write_text(json.dumps(value, indent=1, sort_keys=True) + "\n")


def refuse(why):
    with (root / "refused").open("a") as f:
        f.write(why + "\n")
    sys.exit(f"fake gh: refused: {why}")


def once(knob, call):
    marker = root / ("once-" + knob + re.sub(r"\W", "_", call))
    if os.environ.get(knob) != call or marker.exists():
        return False
    marker.touch()
    return True


def git(*args, env=None, stdin=None):
    return subprocess.run(["git", "--git-dir", str(repo), *args], capture_output=True,
                          text=True, env=env, input=stdin)


def rev(ref):
    found = git("rev-parse", "-q", "--verify", f"{ref}^{{commit}}")
    return found.stdout.strip() if found.returncode == 0 else None


def invalid(text):
    return 422, {"message": "Validation Failed", "errors": [{"message": text}]}


def issue_view(it):
    view = {k: it[k] for k in ("number", "title", "body", "state", "state_reason")}
    view["id"] = 7000 + it["number"]
    view.update(labels=[{"name": x} for x in it["labels"]],
                assignees=[{"login": x} for x in it["assignees"]],
                html_url=f"https://github.com/{slug}/{'pull' if it['kind'] == 'pull' else 'issues'}/{it['number']}")
    if it["kind"] == "pull":
        view["pull_request"] = {"merged_at": it["merged_at"]}
    return view


def pull_view(it):
    view = {k: it[k] for k in ("number", "title", "body", "state", "draft", "merge_commit_sha")}
    view.update(merged=bool(it["merged_at"]), html_url=f"https://github.com/{slug}/pull/{it['number']}",
                head={"ref": it["head"], "sha": rev(f"refs/heads/{it['head']}")}, base={"ref": it["base"]})
    return view


def set_state(it, state, reason, closes):
    if state == it["state"]:
        return
    it["state"] = state
    if state == "closed":
        it["state_reason"] = (reason or "completed") if it["kind"] == "issue" else None
        closes.append([it["number"], it["state_reason"]])
    else:
        it["state_reason"] = "reopened" if it["kind"] == "issue" else None


def new_number(items):
    n = max(map(int, items), default=0) + 1
    if os.environ.get("FAKE_GH_SKIP") == str(n):
        items[str(n)] = {"number": n, "kind": "issue", "title": "Someone else's issue", "body": "",
                         "state": "open", "state_reason": None, "labels": [], "assignees": []}
        n += 1
    return n


def merge(it, body, items, closes):
    if it["kind"] != "pull" or it["state"] != "open":
        return 405, {"message": "Pull Request is not mergeable"}
    head, base = rev(f"refs/heads/{it['head']}"), rev(f"refs/heads/{it['base']}")
    if body.get("sha") and body["sha"] != head:
        return 409, {"message": "Head branch was modified. Review and try the merge again."}
    merged = git("merge-tree", "--write-tree", base, head)
    if merged.returncode:
        return 405, {"message": "Merge conflict"}
    tree = merged.stdout.split()[0]
    parents = ["-p", base] + (["-p", head] if body["merge_method"] == "merge" else [])
    title = body.get("commit_title") or it["title"]
    message = title + (f"\n\n{body['commit_message']}" if body.get("commit_message") else "")
    date = f"{1772900000 + it['number'] * 3600} +0000"
    env = dict(os.environ, GIT_AUTHOR_NAME="Ada Example", GIT_AUTHOR_EMAIL="ada@example.com",
               GIT_AUTHOR_DATE=date, GIT_COMMITTER_NAME="GitHub",
               GIT_COMMITTER_EMAIL="noreply@github.com", GIT_COMMITTER_DATE=date)
    sha = git("commit-tree", tree, *parents, env=env, stdin=message).stdout.strip()
    git("update-ref", f"refs/heads/{it['base']}", sha, base)
    if load("settings", {}).get("delete_branch_on_merge"):
        git("update-ref", "-d", f"refs/heads/{it['head']}")
    it.update(state="closed", merged_at="2026-11-01T00:00:00Z", merge_commit_sha=sha)
    closes.append([it["number"], None])
    for n in CLOSING.findall(it["body"] + "\n" + message):
        named = items.get(n)
        if named and named["kind"] == "issue":
            set_state(named, "closed", "completed", closes)
    return 200, {"sha": sha, "merged": True, "message": "Pull Request successfully merged"}


def from_files(path, q):
    name = Path(os.environ["FAKE_GH_API"]) / path.replace("/", "_")
    if "page" in q:
        page = name.with_name(f"{name.name}-{q['page']}.json")
        entries = json.loads(page.read_text()) if page.exists() else []
        if path.endswith("/issues"):
            links, repo = load("links", {}), path[len("repos/"):-len("/issues")]
            for it in entries:
                it["sub_issues_summary"] = {"total": len(links.get(f"{repo}#{it['number']}", []))}
                parent = next((k for k, ids in links.items() if it.get("id") in ids), None)
                # GitHub leaves the field out of an issue that is no sub-issue.
                if parent:
                    it["parent_issue_url"] = "https://api.github.com/repos/{}/issues/{}".format(*parent.split("#"))
        return 200, entries
    found = name.with_name(name.name + ".json")
    return (200, json.loads(found.read_text())) if found.exists() else (404, {"message": "Not Found"})


def known_issues():
    """Every issue the fake knows, by repository and number, with its repository_url."""
    found = {}
    for f in Path(os.environ.get("FAKE_GH_API", "/nonexistent")).glob("repos_*_issues-*.json"):
        owner, repo = re.fullmatch(r"repos_(.+?)_(.+)_issues-\d+\.json", f.name).groups()
        for it in json.loads(f.read_text()):
            found[(f"{owner}/{repo}", it["number"])] = it
    if not (root / "absent").exists():
        for it in load("items", {}).values():
            found[(slug, it["number"])] = issue_view(it)
    for (repo, _), it in found.items():
        it["repository_url"] = f"https://api.github.com/repos/{repo}"
    return found


def sub_issues(method, repo, n, what, body, q):
    issues = known_issues()
    by_id = {it["id"]: it for it in issues.values() if "id" in it}
    links, key = load("links", {}), f"{repo}#{n}"
    if (repo, n) not in issues:
        return 404, {"message": "Not Found"}
    children = links.setdefault(key, [])
    result = 404, {"message": "Not Found"}
    if method == "GET" and what == "parent":
        me = issues[(repo, n)].get("id")
        parent = next((k for k, ids in links.items() if me in ids), None)
        if parent:
            prepo, pn = parent.split("#")
            result = 200, issues[(prepo, int(pn))]
    elif method == "GET" and what == "sub_issues":
        per, number = int(q.get("per_page", 30)), int(q.get("page", 1))
        result = 200, [by_id[i] for i in children][(number - 1) * per:number * per]
    elif method == "POST" and what == "sub_issues":
        child = body["sub_issue_id"]
        held = next((k for k, ids in links.items() if child in ids), None)
        if child not in by_id or held == key or (held and not body.get("replace_parent")):
            result = invalid("the issue cannot be added as a sub-issue")
        else:
            if held:
                links[held].remove(child)
            children.append(child)
            result = 201, issues[(repo, n)]
    elif method == "PATCH" and what == "sub_issues/priority":
        child, other = body["sub_issue_id"], body.get("before_id") or body.get("after_id")
        if child not in children or other not in children or child == other:
            result = invalid("sub_issue_id, before_id or after_id is not a sub-issue")
        else:
            children.remove(child)
            children.insert(children.index(other) + ("after_id" in body), child)
            with (root / "priorities").open("a") as f:
                f.write(json.dumps(body, sort_keys=True) + "\n")
            result = 200, issues[(repo, n)]
    elif method == "DELETE" and what == "sub_issue" and body.get("sub_issue_id") in children:
        children.remove(body["sub_issue_id"])
        result = 200, issues[(repo, n)]
    save("links", links)
    return result


def create_repo(owner, body):
    if not (root / "absent").exists() or f"{owner}/{body['name']}" != slug:
        return invalid("name already exists on this account")
    (root / "absent").unlink()
    default = os.environ.get("FAKE_GH_DEFAULT", "main")
    save("settings", {"private": bool(body.get("private")), "default_branch": default})
    return 201, {"full_name": slug, "html_url": f"https://github.com/{slug}", "default_branch": default,
                 "private": bool(body.get("private"))}


def handle(method, endpoint, body):
    path, _, query = endpoint.partition("?")
    q = {k: v[-1] for k, v in parse_qs(query).items()}
    login = os.environ.get("FAKE_GH_LOGIN", "ada-example")
    if method == "GET" and path == "user":
        return 200, {"login": login}
    if method == "POST" and path == "user/repos":
        return create_repo(login, body)
    if method == "POST" and re.fullmatch(r"orgs/[^/]+/repos", path):
        return create_repo(path.split("/")[1], body)
    sub = re.fullmatch(r"repos/([^/]+/[^/]+)/issues/(\d+)/(parent|sub_issues|sub_issues/priority|sub_issue)", path)
    if sub:
        return sub_issues(method, sub[1], int(sub[2]), sub[3], body, q)
    if method == "GET" and path in ("user/ssh_signing_keys", "user/gpg_keys"):
        per, number = int(q.get("per_page", 30)), int(q.get("page", 1))
        return 200, load(path[len("user/"):], [])[(number - 1) * per:number * per]
    prefix = f"repos/{slug}"
    if (root / "absent").exists() and (path == prefix or path.startswith(prefix + "/")):
        return 404, {"message": "Not Found"}
    if path != prefix and not path.startswith(prefix + "/"):
        if method == "GET" and path.startswith("repos/") and os.environ.get("FAKE_GH_API"):
            return from_files(path, q)
        return 404, {"message": "Not Found"}
    parts = [unquote(p) for p in path[len(prefix):].split("/") if p]
    items, comments = load("items", {}), load("comments", [])
    labels, closes = load("labels", []), load("closes", [])
    names = [x["name"] for x in labels]
    route = (method, *[p if not p.isdigit() else "N" for p in parts])

    def page(entries):
        per, number = int(q.get("per_page", 30)), int(q.get("page", 1))
        return 200, entries[(number - 1) * per:number * per]

    def item(kind=None):
        it = items.get(parts[1])
        return it if it and kind in (None, it["kind"]) else None

    result = 404, {"message": "Not Found"}
    if route == ("GET",):
        result = 200, {"full_name": slug, "default_branch": "main", "clone_url": str(repo),
                       "ssh_url": str(repo), "html_url": f"https://github.com/{slug}",
                       "permissions": {"admin": True, "push": True}, **load("settings", {})}
    elif route == ("PATCH",) and "default_branch" in body and not rev(f"refs/heads/{body['default_branch']}"):
        with (root / "rejected").open("a") as f:
            f.write(f"{method} {endpoint}: no branch {body['default_branch']}\n")
        result = invalid("the default branch must exist")
    elif route == ("PATCH",):
        save("settings", {**load("settings", {}), **body})
        result = 200, {"full_name": slug, **load("settings", {})}
    elif route == ("PUT", "actions", "permissions"):
        save("actions", {"enabled": body["enabled"]})
        result = 204, None
    elif route == ("GET", "labels"):
        result = page(labels)
    elif route == ("GET", "releases"):
        result = page(load("releases", []))
    elif route == ("POST", "labels"):
        if body["name"] in names:
            result = 422, {"message": "Validation Failed",
                           "errors": [{"resource": "Label", "code": "already_exists", "field": "name"}]}
        else:
            labels.append({k: body.get(k) for k in ("name", "color", "description")})
            result = 201, labels[-1]
    elif route[:2] in (("PATCH", "labels"), ("DELETE", "labels")) and parts[1] in names:
        label = labels[names.index(parts[1])]
        if method == "DELETE":
            labels.remove(label)
            result = 204, None
        else:
            label.update({k: body[k] for k in ("color", "description") if k in body})
            result = 200, label
    elif route == ("GET", "issues"):
        wanted = q.get("state", "open")
        found = [issue_view(it) for it in items.values() if wanted in ("all", it["state"])]
        result = page(sorted(found, key=lambda v: v["number"], reverse=q.get("direction", "desc") == "desc"))
    elif route in (("POST", "issues"), ("POST", "pulls")):
        if any(x not in names for x in body.get("labels", [])):
            result = invalid("label does not exist")
        elif route[1] == "pulls" and not (rev(f"refs/heads/{body['head']}") and rev(f"refs/heads/{body['base']}")):
            result = invalid("head or base is not a branch")
        elif route[1] == "pulls" and git("rev-list", "--count", f"{body['base']}..{body['head']}").stdout.strip() == "0":
            result = invalid(f"No commits between {body['base']} and {body['head']}")
        else:
            n = new_number(items)
            it = {"number": n, "title": body["title"], "body": body.get("body") or "", "state": "open",
                  "state_reason": None, "labels": body.get("labels", []), "assignees": body.get("assignees", [])}
            if route[1] == "pulls":
                it.update(kind="pull", head=body["head"], base=body["base"], draft=body.get("draft", False),
                          merged_at=None, merge_commit_sha=None)
                git("update-ref", f"refs/pull/{n}/head", rev(f"refs/heads/{body['head']}"))
            else:
                it["kind"] = "issue"
            items[str(n)] = it
            result = 201, (pull_view(it) if it["kind"] == "pull" else issue_view(it))
    elif route == ("GET", "issues", "N") and item():
        result = 200, issue_view(item())
    elif route == ("GET", "pulls", "N") and item("pull"):
        result = 200, pull_view(item("pull"))
    elif route in (("PATCH", "issues", "N"), ("PATCH", "pulls", "N")) and item(None if parts[0] == "issues" else "pull"):
        it = item()
        if any(x not in names for x in body.get("labels", [])):
            result = invalid("label does not exist")
        else:
            it.update({k: body[k] for k in ("title", "body", "labels", "assignees") if k in body})
            if "state" in body:
                set_state(it, body["state"], body.get("state_reason"), closes)
            result = 200, (issue_view(it) if parts[0] == "issues" else pull_view(it))
    elif route == ("GET", "issues", "comments"):
        result = page([{**c, "issue_url": f"https://api.github.com/{prefix}/issues/{c['number']}"}
                       for c in comments])
    elif route == ("GET", "issues", "N", "comments") and item():
        result = page([c for c in comments if c["number"] == int(parts[1])])
    elif route == ("POST", "issues", "N", "comments") and item():
        comments.append({"id": 1000 + len(comments), "number": int(parts[1]), "body": body["body"]})
        result = 201, comments[-1]
    elif route == ("PUT", "pulls", "N", "merge") and item():
        result = merge(item(), body, items, closes)
    save("items", items)
    save("comments", comments)
    save("labels", labels)
    save("closes", closes)
    return result


args = sys.argv[1:]
if args == ["config", "get", "git_protocol"]:
    (root / "prompt").write_text(os.environ.get("GIT_TERMINAL_PROMPT", "unset"))
    print("https")
    sys.exit(0)
if args[:1] != ["api"]:
    refuse(" ".join(args))
method, endpoint, include, has_input, rest = "GET", None, False, False, args[1:]
while rest:
    arg = rest.pop(0)
    if arg in ("-i", "--include"):
        include = True
    elif arg in ("-X", "--method") and rest:
        method = rest.pop(0)
    elif arg == "--input" and rest[:1] == ["-"]:
        has_input = bool(rest.pop(0))
    elif arg.startswith("-") or endpoint:
        refuse(f"argument {arg}")
    else:
        endpoint = arg
if not endpoint:
    refuse("a call without an endpoint")
body = json.loads(sys.stdin.read()) if has_input else {}
call = f"{method} {endpoint}"
with (root / "calls").open("a") as f:
    f.write(f"{time.time():.3f} {call}\n")
headers = []
if once("FAKE_GH_RATE_LIMIT", call):
    status, data = 403, {"message": "You have exceeded a secondary rate limit."}
    headers = [("Retry-After", "1")]
elif once("FAKE_GH_DENY", call):
    status, data = 403, {"message": "Resource not accessible by personal access token"}
elif endpoint.startswith("user/") and os.environ.get("FAKE_GH_NO_SCOPE"):
    status, data = 404, {"message": "Not Found"}
    kind = endpoint.split("?")[0].split("/")[1][:-1]
    headers = [("X-OAuth-Scopes", "repo, read:org"),
               ("X-Accepted-OAuth-Scopes", f"admin:{kind}, read:{kind}, write:{kind}")]
else:
    if once("FAKE_GH_INTERRUPT", call):
        os.kill(os.getppid(), signal.SIGINT)
    status, data = handle(method, endpoint, body)
    if status == 200 and isinstance(data, list) and data and once("FAKE_GH_LAG", call):
        top = max(x["number"] for x in data)
        data = [d for d in data if d["number"] != top and "pull_request" not in d]
    if once("FAKE_GH_LOSE", call):
        status, data = 502, {"message": "Server Error"}
lines = [("Content-Type", "application/json; charset=utf-8"), *headers]
if include:
    sys.stdout.write(f"HTTP/1.1 {status} {REASONS[status]}\n" + "".join(f"{k}: {v}\r\n" for k, v in lines) + "\r\n")
if data is not None:
    sys.stdout.write(json.dumps(data))
if status >= 400:
    sys.exit(f"gh: {data.get('message', '')} (HTTP {status})")
EOF
chmod +x "$T/bin-target/gh"
# The PATH under which the scripts reach the fake gh of the targets.
target_path=$T/bin-target:$PATH

# target <folder> [<owner/repo>]: an empty target, ada-example/tool-new by
# default, with two labels as GitHub gives a new repository.
target() {
  mkdir "$1" && echo "${2:-ada-example/tool-new}" >"$1/name" && git init -q --bare "$1/repo.git" &&
    echo '[{"name": "bug", "color": "ee0701", "description": "Something is wrong"},
      {"name": "enhancement", "color": "a2eeef", "description": "New feature or request"}]' >"$1/labels.json"
}
# replay <folder> <answer> <argument>...: runs run-replay.py against the
# target in that folder, with the answer typed at the confirmation.
replay() {
  printf '%s\n' "$2" | (
    FAKE_GITHUB=$1 && PATH=$T/bin-target:$PATH && export FAKE_GITHUB PATH && shift 2 &&
      python3 "$here/run-replay.py" "$@"
  )
}
# writes <folder>: the calls that write, with their times.
writes() { grep -v ' GET ' "$1/calls" 2>/dev/null; }
# rexpect <folder> <state file> <condition>: a Python condition on the target
# in that folder, with items, comments (as (number, body)), labels and closes
# from the fake's files, M the map of source to target hashes from the state
# file, E the events of the plan, S the source's hashes and git() the output
# of git in the target's repository.
rexpect() {
  python3 - "$1" "$2" "$T/run.jsonl" "$3" "$T" <<'EOF'
import json, os, subprocess, sys
from pathlib import Path
sys.path.insert(0, sys.argv[5])
from condition import holds
root = Path(sys.argv[1])
def load(name, default):
    path = root / f"{name}.json"
    return json.loads(path.read_text()) if path.exists() else default
items = {int(k): v for k, v in load("items", {}).items()}
comments = [(c["number"], c["body"]) for c in load("comments", [])]
labels, closes = load("labels", []), load("closes", [])
M = json.loads(Path(sys.argv[2]).read_text())["hashes"]
with open(sys.argv[3], encoding="utf-8") as f:
    H, *E = [json.loads(line) for line in f]
S = os.environ
def git(*args):
    return subprocess.run(["git", "--git-dir", str(root / "repo.git"), *args],
                          capture_output=True, text=True, check=True).stdout.strip()
holds(sys.argv[4], globals())
EOF
}
rcheck() {
  folder=$2 state_file=$3 condition=$4
  check "$1" 'rexpect "$folder" "$state_file" "$condition"'
}

check "run-replay.py's plan has the fourth comment" \
  '[ "$status_run_plan" = 0 ] && grep -Eqx "  comments +4" "$T/run-plan-out" && grep -Eqx "  events +23" "$T/run-plan-out" || { cat "$T/run-plan-out"; exit 1; }'

target "$T/gh-refused"
replay "$T/gh-refused" tool-new --state "$T/refused.state.json" "$T/run.jsonl" "$mirror" ada-example/tool-new \
  >"$T/refused-out" 2>&1
status_refused=$?
check "run-replay.py writes nothing when the confirmation is not the target's owner/repo" \
  '[ "$status_refused" = 1 ] && grep -q "run-replay.py: not confirmed; nothing changed$" "$T/refused-out" && grep -Eqx "  issues +3" "$T/refused-out" && grep -q "labels the target has and the replay deletes: enhancement" "$T/refused-out" && ! writes "$T/gh-refused" && [ -z "$(git --git-dir="$T/gh-refused/repo.git" for-each-ref)" ] && [ ! -e "$T/refused.state.json" ] && [ ! -e "$T/refused.work.git" ] || { cat "$T/refused-out"; writes "$T/gh-refused"; exit 1; }'

# A: one uninterrupted run, paced at 0.1 s, that hits a rate limit once.
target "$T/gh-a"
(FAKE_GH_RATE_LIMIT="POST repos/ada-example/tool-new/issues/1/comments" &&
  export FAKE_GH_RATE_LIMIT &&
  replay "$T/gh-a" ada-example/tool-new --pace 0.1 --state "$T/a.state.json" "$T/run.jsonl" "$mirror" ada-example/tool-new) \
  >"$T/a-out" 2>"$T/a-err"
status_a=$?
check "run-replay.py replays the plan, with a line per event, the totals and the target's URL" \
  '[ "$status_a" = 0 ] && [ ! -s "$T/a-err" ] && [ "$(grep -Ec "^ *[0-9]+/23  " "$T/a-out")" = 23 ] && grep -Eqx "  merge-pull +2" "$T/a-out" && [ "$(tail -n 1 "$T/a-out")" = https://github.com/ada-example/tool-new ] && [ ! -e "$T/gh-a/refused" ] || { cat "$T/a-err" "$T/a-out" "$T/gh-a/refused" 2>&1; exit 1; }'
rcheck "run-replay.py gives every issue and pull request the number and title of the plan" "$T/gh-a" "$T/a.state.json" \
  '[(n, it["kind"], it["title"]) for n, it in sorted(items.items())] == [(e["number"], "pull" if e["kind"] == "create-pull" else "issue", e["title"]) for e in E if e["kind"] in ("create-issue", "create-pull")] and sorted(items) == [1, 2, 3, 4, 5, 6]'
check "run-replay.py leaves the target's default branch with the source's tree after each push and merge" \
  'git --git-dir="$mirror" rev-list --first-parent --reverse --format=%T main | grep -v "^commit" >"$T/trees-source" && git --git-dir="$T/gh-a/repo.git" rev-list --first-parent --reverse --format=%T main | grep -v "^commit" >"$T/trees-target" && [ "$(wc -l <"$T/trees-source")" -eq 7 ] && diff "$T/trees-source" "$T/trees-target"'
rcheck "run-replay.py pushes commits with the mapped identities, the original author dates, the time of the replay as committer date and the typed messages" "$T/gh-a" "$T/a.state.json" \
  'git("log", "-1", "--format=%an|%ae|%ad|%cn|%ce|%cd|%s", "--date=raw", M[S["C3"]]) == "Ada Example|ada@example.com|1772712000 +0200|Ada Example|ada@example.com|1794000000 +0000|test: update the tests" and json.loads(open(sys.argv[2]).read())["committer_dates"][S["C3"]] == "1794000000 +0000" and git("log", "-1", "--format=%an|%ae|%cn|%ce|%s", M[S["F1"]]) == "Bob Example|bob@example.com|Bob Example|bob@example.com|fix: repair the parser" and git("rev-parse", "fix/3-parser") == M[S["F1"]] and git("rev-parse", "docs/5-notes^2") == M[S["C5"]] and git("log", "-1", "--format=%B", M[S["C4"]]) == "chore: tidy the scripts\n\nNo change in behaviour."'
rcheck "run-replay.py squash-merges with the planned message and fills in {pr_url}" "$T/gh-a" "$T/a.state.json" \
  'git("log", "-1", "--format=%B", M[S["M3"]]) == "fix: repair the parser (#3)\n\nThe parser failed on empty input.\n\nhttps://github.com/ada-example/tool-new/pull/3" and git("log", "-1", "--format=%s|%cn", M[S["M2"]]) == "feat: add thing (#2)|GitHub"'
rcheck "run-replay.py replaces a hash of a recreated commit in a later comment, and nothing else" "$T/gh-a" "$T/a.state.json" \
  'comments[-1] == (6, "Tidied in " + M[S["C4"]][:7] + ", after " + M[S["M2"]][:10] + "; abcdef0 is no commit.") and M[S["C4"]][:7] != S["C4"][:7] and comments[0] == (1, "Seen in the readme.")'
rcheck "run-replay.py leaves an issue closed by a merge as it is and sets a different state reason" "$T/gh-a" "$T/a.state.json" \
  '[c for c in closes if c[0] == 1] == [[1, "completed"]] and [c for c in closes if c[0] == 4] == [[4, "completed"], [4, "not_planned"]] and [(n, it["state"], it["state_reason"]) for n, it in sorted(items.items()) if it["kind"] == "issue"] == [(1, "closed", "completed"), (4, "closed", "not_planned"), (6, "open", None)] and [(n, it["state"], bool(it["merged_at"])) for n, it in sorted(items.items()) if it["kind"] == "pull"] == [(2, "closed", True), (3, "closed", True), (5, "closed", False)]'
rcheck "run-replay.py creates and updates the planned labels, deletes the others and labels the items" "$T/gh-a" "$T/a.state.json" \
  'sorted((x["name"], x["color"], x["description"]) for x in labels) == [("bug", "d73a4a", "Something isn'"'"'t working"), ("docs", "0075ca", "Documentation")] and (items[6]["labels"], items[6]["assignees"]) == (["bug", "docs"], ["ada-example"])'
check "run-replay.py waits out a rate limit as Retry-After tells and retries the same call" \
  'grep -q "rate limited on POST repos/ada-example/tool-new/issues/1/comments; waiting 1 s before retry 1 of 5" "$T/a-out" && [ "$(grep -c " POST repos/ada-example/tool-new/issues/1/comments$" "$T/gh-a/calls")" = 2 ] || { cat "$T/a-out"; exit 1; }'
check "run-replay.py paces its writes by --pace" \
  'writes "$T/gh-a" | awk "NR > 1 && \$1 - last < 0.1 { print \"gap \" \$1 - last \" before \" \$0; bad = 1 } { last = \$1 } END { exit bad }"'

# B: the same replay, stopped by a Ctrl-C and by three answers lost after
# GitHub did the call, and resumed each time.
target "$T/gh-b"
# resume_b <interrupted call> <call whose answer is lost>: one run of B.
resume_b() {
  (FAKE_GH_INTERRUPT=$1 && FAKE_GH_LOSE=$2 && export FAKE_GH_INTERRUPT FAKE_GH_LOSE &&
    replay "$T/gh-b" ada-example/tool-new --pace 0 --state "$T/b.state.json" \
      "$T/run.jsonl" "$mirror" ada-example/tool-new) >>"$T/b-out" 2>&1
  echo $? >>"$T/b-status"
}
resume_b "PATCH repos/ada-example/tool-new/labels/bug" ""
resume_b "" "POST repos/ada-example/tool-new/pulls"
resume_b "" "POST repos/ada-example/tool-new/issues/3/comments"
resume_b "" "PUT repos/ada-example/tool-new/pulls/3/merge"
resume_b "" ""
# dump <folder>: the target's items, comments, labels, closings and refs.
dump() { cat "$1/items.json" "$1/comments.json" "$1/labels.json" "$1/closes.json" && git --git-dir="$1/repo.git" for-each-ref; }
check "run-replay.py stops after the event a Ctrl-C interrupts, and resumes there" \
  'grep -q "^run-replay.py: stopped after event 1 of 23; run the same command again to resume$" "$T/b-out" && grep -q "Resume the replay of ada-example/tool into ada-example/tool-new at event 2 of 23" "$T/b-out" || { cat "$T/b-out"; exit 1; }'
check "run-replay.py takes over what a call whose answer was lost did, when it resumes" \
  '[ "$(tr "\n" " " <"$T/b-status")" = "130 1 1 1 0 " ] && grep -q "#2 pull request feat/2-thing into main, found created" "$T/b-out" && grep -q "#3 comment, found created" "$T/b-out" && grep -q "#3 squash-merged into main as .*, found merged" "$T/b-out" || { cat "$T/b-status" "$T/b-out"; exit 1; }'
check "run-replay.py ends a stopped and resumed replay in the same target as an uninterrupted one" \
  'dump "$T/gh-a" >"$T/a-dump" && dump "$T/gh-b" >"$T/b-dump" && diff "$T/a-dump" "$T/b-dump"'

writes_a=$(writes "$T/gh-a" | wc -l)
replay "$T/gh-a" ada-example/tool-new --pace 0 --state "$T/a.state.json" "$T/run.jsonl" "$mirror" ada-example/tool-new \
  >"$T/again-out" 2>&1
status_again=$?
replay "$T/gh-a" ada-example/tool-new --pace 0 --state "$T/other.state.json" "$T/run.jsonl" "$mirror" ada-example/tool-new \
  >"$T/other-out" 2>&1
status_other=$?
check "run-replay.py checks a finished replay again without writing, and refuses a target that is not empty" \
  '[ "$status_again$status_other" = 01 ] && grep -q "^All 23 events of the replay .* are done" "$T/again-out" && grep -q "ada-example/tool-new is not empty: it has 8 refs and items up to #6" "$T/other-out" && [ "$(writes "$T/gh-a" | wc -l)" -eq "$writes_a" ] || { cat "$T/again-out" "$T/other-out"; exit 1; }'

reads_2=$(grep -c " GET repos/ada-example/tool-new/issues/2$" "$T/gh-a/calls")
reads_6=$(grep -c " GET repos/ada-example/tool-new/issues/6$" "$T/gh-a/calls")
(FAKE_GH_LAG="GET repos/ada-example/tool-new/issues?state=all&per_page=100&page=1" && export FAKE_GH_LAG &&
  replay "$T/gh-a" ada-example/tool-new --pace 0 --state "$T/a.state.json" "$T/run.jsonl" "$mirror" ada-example/tool-new) \
  >"$T/lag-out" 2>&1
status_lag=$?
check "run-replay.py reads by its number an issue or pull request the target's list lacks, before it calls the item missing" \
  '[ "$status_lag" = 0 ] && [ "$(grep -c " GET repos/ada-example/tool-new/issues/2$" "$T/gh-a/calls")" -gt "$reads_2" ] && [ "$(grep -c " GET repos/ada-example/tool-new/issues/6$" "$T/gh-a/calls")" -gt "$reads_6" ] && [ "$(writes "$T/gh-a" | wc -l)" -eq "$writes_a" ] || { cat "$T/lag-out"; exit 1; }'

# C: a replay into a target where someone else creates an issue, with the
# default state file and --with-times.
target "$T/gh-c" ada-example/tool-c
(FAKE_GH_SKIP=4 && export FAKE_GH_SKIP && replay "$T/gh-c" ada-example/tool-c --pace 0 --with-times "$T/run.jsonl" "$mirror" ada-example/tool-c) \
  >"$T/c-out" 2>&1
status_c=$?
check "run-replay.py stops at a number other than the planned one, before anything more" \
  '[ "$status_c" = 1 ] && grep -q "^run-replay.py: the issue planned as #4 got #5" "$T/c-out" && [ "$(writes "$T/gh-c" | tail -n 1 | cut -d" " -f2-)" = "POST repos/ada-example/tool-c/issues" ] && [ -f "$T/run.state.json" ] && [ -d "$T/run.work.git" ] || { cat "$T/c-out"; writes "$T/gh-c"; exit 1; }'
rcheck "run-replay.py --with-times appends the original creation time to bodies and comments" "$T/gh-c" "$T/run.state.json" \
  'items[1]["body"] == "The readme is empty.\n\n_Originally created 2026-03-01 11:00 UTC._" and comments[0] == (1, "Seen in the readme.\n\n_Originally created 2026-03-02 12:00 UTC._") and items[2]["title"] == "feat: add thing"'

check "run-replay.py runs gh with GIT_TERMINAL_PROMPT=0, so no call through run() waits for a password" \
  '[ "$(cat "$T/gh-a/prompt")" = 0 ] || { cat "$T/gh-a/prompt"; exit 1; }'

# D: a plan whose second merge expects the tree of the first; the mirror holds
# it, so only the check after the merge can see the difference.
python3 - "$T/run.jsonl" "$T/bad-tree.jsonl" <<'EOF'
import json, sys
lines = open(sys.argv[1], encoding="utf-8").read().splitlines()
merges = [i for i, line in enumerate(lines) if json.loads(line).get("kind") == "merge-pull"]
event = json.loads(lines[merges[1]])
event["tree"] = json.loads(lines[merges[0]])["tree"]
lines[merges[1]] = json.dumps(event)
open(sys.argv[2], "w", encoding="utf-8").write("\n".join(lines) + "\n")
EOF
target "$T/gh-d" ada-example/tool-d
replay "$T/gh-d" ada-example/tool-d --pace 0 --state "$T/d.state.json" "$T/bad-tree.jsonl" "$mirror" ada-example/tool-d \
  >"$T/d-out" 2>&1
status_d=$?
check "run-replay.py stops when the tree after a merge differs from the plan's, and names both" \
  '[ "$status_d" = 1 ] && grep -q "^run-replay.py: after the merge of #[0-9]*, the tree of main is [0-9a-f]\{7\}, the source'"'"'s [0-9a-f]\{7\}; the replay stops at the first difference" "$T/d-out" || { cat "$T/d-out"; exit 1; }'

# --final-name: E, an unsigned replay whose squash messages name the source,
# the name the target takes over; then a resume without the option.
target "$T/gh-e" ada-example/tool-e
replay "$T/gh-e" ada-example/tool-e --pace 0 --final-name ada-example/tool --state "$T/e.state.json" "$T/run.jsonl" "$mirror" ada-example/tool-e \
  >"$T/e-out" 2>&1
status_e=$?
rcheck "run-replay.py --final-name puts the given name in the URL of a squash message" "$T/gh-e" "$T/e.state.json" \
  'git("log", "-1", "--format=%B", M[S["M3"]]) == "fix: repair the parser (#3)\n\nThe parser failed on empty input.\n\nhttps://github.com/ada-example/tool/pull/3" and items[3]["title"] == "fix: repair the parser"'
check "run-replay.py names in the totals the URL {pr_url} gets, with --final-name and without" \
  '[ "$status_e" = 0 ] && grep -Fqx "  {pr_url} in 1 squash message: https://github.com/ada-example/tool/pull/<number>" "$T/e-out" && grep -Fqx "  {pr_url} in 1 squash message: https://github.com/ada-example/tool-new/pull/<number>" "$T/a-out" || { cat "$T/e-out"; exit 1; }'
replay "$T/gh-e" ada-example/tool-e --pace 0 --state "$T/e.state.json" "$T/run.jsonl" "$mirror" ada-example/tool-e \
  >"$T/e-again-out" 2>&1
status_e_again=$?
replay "$T/gh-e" ada-example/tool-e --final-name tool "$T/run.jsonl" "$mirror" ada-example/tool-e >/dev/null 2>&1
status_bad_name=$?
replay "$T/gh-e" ada-example/tool-e --sign ada.example.com "$T/run.jsonl" "$mirror" ada-example/tool-e >/dev/null 2>&1
status_bad_sign=$?
check "run-replay.py refuses a --final-name not of the form owner/repo, a --sign that is no address, and a resume with other options" \
  '[ "$status_bad_name$status_bad_sign$status_e_again" = 221 ] && grep -q "^run-replay.py: .*e.state.json records a run with --final-name ada-example/tool; resume with the same options$" "$T/e-again-out" || { echo "$status_bad_name$status_bad_sign$status_e_again"; cat "$T/e-again-out"; exit 1; }'

# compare-replay.py, against the finished targets of A and E and against a
# copy of A with five differences. compare <folder> <argument>...: runs it
# against the target in that folder, with the source's API of the run's plan.
compare() {
  folder=$1
  shift
  FAKE_GITHUB=$folder FAKE_GH_API=$T/api-run PATH=$target_path python3 "$here/compare-replay.py" "$@"
}
writes_before=$(writes "$T/gh-a" | wc -l)
compare "$T/gh-a" --state "$T/a.state.json" "$T/run.jsonl" "$mirror" ada-example/tool-new >"$T/cmp-a-out" 2>&1
status_cmp_a=$?
compare "$T/gh-e" --state "$T/e.state.json" "$T/run.jsonl" "$mirror" ada-example/tool-e >"$T/cmp-e-out" 2>&1
status_cmp_e=$?
check "compare-replay.py finds no difference in a finished replay, with --final-name and without, and writes nothing" \
  '[ "$status_cmp_a$status_cmp_e" = 00 ] && [ "$(tail -n 1 "$T/cmp-a-out")" = "No differences" ] && grep -qx "No differences" "$T/cmp-e-out" && for t in "items +6" "labels +2" "comments +4" "texts with a replaced hash +1" "commits on main +7" "recreated commits +12" "branches +4" "pull request heads +3"; do grep -Eqx "  $t" "$T/cmp-a-out" || { echo "no line \"$t\""; exit 1; }; done && [ "$(writes "$T/gh-a" | wc -l)" -eq "$writes_before" ] && [ ! -e "$T/gh-a/refused" ] || { cat "$T/cmp-a-out" "$T/cmp-e-out"; exit 1; }'
check "compare-replay.py notes each branch the target keeps and the source no longer has, and who authored the merges" \
  'for b in docs/5-notes feat/2-thing fix/3-parser; do grep -qx "  branch $b stays in the target; the source no longer has it" "$T/cmp-a-out" || exit 1; done && grep -qx "  merges authored by Ada Example <ada@example.com>" "$T/cmp-a-out" || { cat "$T/cmp-a-out"; exit 1; }'

# The copy of A: #4 closed as completed, a footer on the last comment, the
# colour of a label, a missing branch, the head of #3 at another commit, and
# a last commit on main with the tree of the one before.
cp -R "$T/gh-a" "$T/gh-diff"
python3 - "$T/gh-diff" <<'EOF'
import json, sys
from pathlib import Path
root = Path(sys.argv[1])
def edit(name, change):
    value = json.loads((root / f"{name}.json").read_text())
    change(value)
    (root / f"{name}.json").write_text(json.dumps(value))
edit("items", lambda items: items["4"].update(state_reason="completed"))
edit("comments", lambda comments: comments[-1].update(
    body=comments[-1]["body"] + "\n\n---\n_Generated by [Claude Code](https://claude.ai/code)_"))
edit("labels", lambda labels: [x.update(color="ee0701") for x in labels if x["name"] == "bug"])
EOF
d=$T/gh-diff/repo.git
git --git-dir="$d" update-ref -d refs/heads/fix/3-parser
git --git-dir="$d" update-ref refs/pull/3/head main~1
git --git-dir="$d" update-ref refs/heads/main "$(echo "same tree" | git --git-dir="$d" commit-tree "main~1^{tree}" -p main~1)"
compare "$T/gh-diff" --state "$T/a.state.json" "$T/run.jsonl" "$mirror" ada-example/tool-new >"$T/cmp-diff-out" 2>&1
status_cmp_diff=$?
check "compare-replay.py names every difference it finds and exits with 1" \
  '[ "$status_cmp_diff" = 1 ] && for line in "#4 is closed as completed, the source'"'"'s not_planned" "#6, comment 1: the body differs; it has a footer the source lacks" "label bug: colour ee0701, the source'"'"'s d73a4a" "branch fix/3-parser is missing in the target"; do grep -Fqx "  $line" "$T/cmp-diff-out" || { echo "no line \"$line\""; exit 1; }; done && grep -q "^  #3: the pull request head is [0-9a-f]\{7\}, the state file'"'"'s [0-9a-f]\{7\}$" "$T/cmp-diff-out" && grep -q "^  main, step 7 ([0-9a-f]\{7\}): tree [0-9a-f]\{7\}, the source'"'"'s [0-9a-f]\{7\}$" "$T/cmp-diff-out" && grep -q "^Differences: [0-9]*$" "$T/cmp-diff-out" || { cat "$T/cmp-diff-out"; exit 1; }'
compare "$T/gh-c" "$T/run.jsonl" "$mirror" ada-example/tool-c >"$T/cmp-c-out" 2>&1
status_cmp_c=$?
check "compare-replay.py refuses a replay that its state file records unfinished" \
  '[ "$status_cmp_c" = 2 ] && grep -q "^compare-replay.py: .*run.state.json records the replay unfinished, at event [0-9]* of 23; finish it with run-replay.py first$" "$T/cmp-c-out" || { cat "$T/cmp-c-out"; exit 1; }'

# X: the plan that leaves behind tags, a release, a draft and two branches,
# replayed; compared as it is, with a tag and a release that the source lacks,
# and with A's plan, which leaves nothing behind, against the same source.
# compare_extra <folder> <argument>...: compare against the source with them.
compare_extra() {
  folder=$1
  shift
  FAKE_GITHUB=$folder FAKE_GH_API=$T/api-extra PATH=$target_path python3 "$here/compare-replay.py" "$@"
}
target "$T/gh-x" ada-example/tool-x
replay "$T/gh-x" ada-example/tool-x --pace 0 "$T/extra.jsonl" "$mirror_extra" ada-example/tool-x >"$T/x-out" 2>&1
status_x=$?
compare_extra "$T/gh-x" "$T/extra.jsonl" "$mirror_extra" ada-example/tool-x >"$T/cmp-x-out" 2>&1
status_cmp_x=$?
cp -R "$T/gh-x" "$T/gh-x-more"
git --git-dir="$T/gh-x-more/repo.git" tag v9 main
echo '[{"id": 3, "tag_name": "v0.4", "name": "Later", "draft": false, "prerelease": false}]' >"$T/gh-x-more/releases.json"
compare_extra "$T/gh-x-more" "$T/extra.jsonl" "$mirror_extra" ada-example/tool-x >"$T/cmp-x-more-out" 2>&1
status_cmp_x_more=$?
compare_extra "$T/gh-a" --state "$T/a.state.json" "$T/run.jsonl" "$mirror_extra" ada-example/tool-new >"$T/cmp-a-extra-out" 2>&1
status_cmp_a_extra=$?
# A copy of A that carries v0.1 and v0.2 at the recreated commits, v0.2 as an
# annotated tag.
cp -R "$T/gh-a" "$T/gh-a-tags"
recreated() { python3 -c 'import json, sys; print(json.load(open(sys.argv[1]))["hashes"][sys.argv[2]])' "$T/a.state.json" "$1"; }
git --git-dir="$T/gh-a-tags/repo.git" tag v0.1 "$(recreated "$M2")"
git --git-dir="$T/gh-a-tags/repo.git" tag -a v0.2 -m "Second" "$(recreated "$C5")"
git -c advice.nestedTag=false --git-dir="$T/gh-a-tags/repo.git" tag -a -f v0.2 -m "Outer" v0.2 >/dev/null
compare_extra "$T/gh-a-tags" --state "$T/a.state.json" "$T/run.jsonl" "$mirror_extra" ada-example/tool-new >"$T/cmp-a-tags-out" 2>&1
status_cmp_a_tags=$?
# A copy of X without the branch of #3, which the replay pushed.
cp -R "$T/gh-x" "$T/gh-x-lost"
git --git-dir="$T/gh-x-lost/repo.git" update-ref -d refs/heads/fix/3-parser
compare_extra "$T/gh-x-lost" "$T/extra.jsonl" "$mirror_extra" ada-example/tool-x >"$T/cmp-x-lost-out" 2>&1
status_cmp_x_lost=$?
# Y: X's plan with a header that predates left_behind, replayed into a target
# that deletes head branches on merge.
python3 - "$T/extra.jsonl" "$T/old.jsonl" <<'EOF'
import json, sys
lines = open(sys.argv[1], encoding="utf-8").read().splitlines()
header = json.loads(lines[0])
del header["left_behind"]
open(sys.argv[2], "w", encoding="utf-8").write("\n".join([json.dumps(header), *lines[1:]]) + "\n")
EOF
target "$T/gh-y" ada-example/tool-y
echo '{"delete_branch_on_merge": true}' >"$T/gh-y/settings.json"
replay "$T/gh-y" ada-example/tool-y --pace 0 "$T/old.jsonl" "$mirror_extra" ada-example/tool-y >"$T/y-out" 2>&1
status_y=$?
compare_extra "$T/gh-y" "$T/old.jsonl" "$mirror_extra" ada-example/tool-y >"$T/cmp-y-out" 2>&1
status_cmp_y=$?
# Z: the plan of the source that deletes head branches on merge, which leaves
# behind the branches of #2 and #3 as well, replayed into a target that
# deletes them; and X compared with the source of the odd tags.
printf '%s\n' 'branch feat/2-thing' 'branch fix/3-parser' >"$T/leave-del"
cat "$T/leave" >>"$T/leave-del"
plan_extra "$T/api-extra-del" "$T/extra-del-ok.jsonl" --leave-behind "$T/leave-del" >/dev/null 2>&1
target "$T/gh-z" ada-example/tool-z
echo '{"delete_branch_on_merge": true}' >"$T/gh-z/settings.json"
replay "$T/gh-z" ada-example/tool-z --pace 0 "$T/extra-del-ok.jsonl" "$mirror_extra" ada-example/tool-z >"$T/z-out" 2>&1
status_z=$?
(FAKE_GITHUB=$T/gh-z FAKE_GH_API=$T/api-extra-del PATH=$target_path python3 "$here/compare-replay.py" "$T/extra-del-ok.jsonl" "$mirror_extra" ada-example/tool-z) >"$T/cmp-z-out" 2>&1
status_cmp_z=$?
compare_extra "$T/gh-x" "$T/extra.jsonl" "$mirror_odd" ada-example/tool-x >"$T/cmp-x-odd-out" 2>&1
status_cmp_x_odd=$?
check "compare-replay.py notes each tag, release and branch of the source that the plan left behind, and finds no difference" \
  '[ "$status_x$status_cmp_x" = 00 ] && grep -qx "No differences" "$T/cmp-x-out" && for line in "branch docs/5-notes" "branch wip/idea" "tag v0.1" "tag v0.2" "release v0.2" "release v0.3"; do grep -Fqx "  $line of the source is left behind, as planned" "$T/cmp-x-out" || { echo "no note for $line"; exit 1; }; done && grep -Eqx "  tags +0" "$T/cmp-x-out" && grep -Eqx "  releases +0" "$T/cmp-x-out" && ! grep -q "feat/2-thing of\|fix/3-parser of" "$T/cmp-x-out" || { cat "$T/x-out" "$T/cmp-x-out"; exit 1; }'
check "compare-replay.py names a tag and a release of the target that the source lacks as differences" \
  '[ "$status_cmp_x_more" = 1 ] && grep -Fqx "  tag v9 is in the target, not in the source" "$T/cmp-x-more-out" && grep -Fqx "  release v0.4 is in the target, not in the source" "$T/cmp-x-more-out" && grep -qx "Differences: 2" "$T/cmp-x-more-out" && grep -Eqx "  tags +1" "$T/cmp-x-more-out" || { cat "$T/cmp-x-more-out"; exit 1; }'
check "compare-replay.py names as a difference each tag, release and branch of the source that the target lacks and the plan did not leave behind" \
  '[ "$status_cmp_a_extra" = 1 ] && for line in "branch wip/idea of the source is missing in the target" "tag v0.1 of the source is missing in the target" "tag v0.2 of the source is missing in the target" "release v0.2 of the source is missing in the target" "release v0.3 of the source is missing in the target"; do grep -Fqx "  $line" "$T/cmp-a-extra-out" || { echo "no line: $line"; exit 1; }; done && grep -Eqx "  branch docs/5-notes of the source is at [0-9a-f]{7} in the target, not at the recreated [0-9a-f]{7}" "$T/cmp-a-extra-out" && grep -qx "Differences: 6" "$T/cmp-a-extra-out" && ! grep -q "left behind" "$T/cmp-a-extra-out" || { cat "$T/cmp-a-extra-out"; exit 1; }'
check "compare-replay.py takes a tag of the target at the recreated commit, lightweight or annotated, as carried" \
  '[ "$status_cmp_a_tags" = 1 ] && grep -qx "Differences: 4" "$T/cmp-a-tags-out" && grep -Eqx "  tags +2" "$T/cmp-a-tags-out" && ! grep -q "tag v0\.[12]" "$T/cmp-a-tags-out" || { cat "$T/cmp-a-tags-out"; exit 1; }'
check "compare-replay.py names a pushed branch the target lacks once, as a branch of the replay" \
  '[ "$status_cmp_x_lost" = 1 ] && grep -qx "Differences: 1" "$T/cmp-x-lost-out" && grep -Fqx "  branch fix/3-parser is missing in the target" "$T/cmp-x-lost-out" || { cat "$T/cmp-x-lost-out"; exit 1; }'
check "compare-replay.py notes an event file that predates left_behind, and takes the branches the target deleted on merge as carried" \
  '[ "$status_y$status_cmp_y" = 01 ] && grep -Fqx "  the event file predates left_behind: it accepts nothing as left behind" "$T/cmp-y-out" && grep -qx "Differences: 6" "$T/cmp-y-out" && ! grep -q "feat/2-thing of\|fix/3-parser of" "$T/cmp-y-out" || { cat "$T/y-out" "$T/cmp-y-out"; exit 1; }'
check "compare-replay.py notes as left behind a pushed branch that the plan left behind, since the target deletes it on merge" \
  '[ "$status_z$status_cmp_z" = 00 ] && grep -qx "No differences" "$T/cmp-z-out" && grep -Fqx "  branch feat/2-thing of the source is left behind, as planned" "$T/cmp-z-out" && grep -Fqx "  branch fix/3-parser of the source is left behind, as planned" "$T/cmp-z-out" || { cat "$T/z-out" "$T/cmp-z-out"; exit 1; }'
check "compare-replay.py names a tag of a tag, a tag of a tree and a tag whose name holds a no-break space, without a traceback" \
  '[ "$status_cmp_x_odd" = 1 ] && grep -qx "Differences: 3" "$T/cmp-x-odd-out" && for name in v0.3 tree-tag "$nbsp"; do grep -Fqx "  tag $name of the source is missing in the target" "$T/cmp-x-odd-out" || { echo "no line for $name"; exit 1; }; done && ! grep -q Traceback "$T/cmp-x-odd-out" || { cat "$T/cmp-x-odd-out"; exit 1; }'

# Committer dates: CL, a replay on the machine's clock; CE, one whose fixed
# time lies before the dates the fake gives its merges; and copies of A's
# state file, one that predates committer dates and one that maps the source
# commit of #3's branch to a commit made before its parent.
target "$T/gh-cl" ada-example/tool-cl
clock_from=$(date +%s)
(unset SOURCE_DATE_EPOCH && replay "$T/gh-cl" ada-example/tool-cl --pace 0 --state "$T/cl.state.json" "$T/run.jsonl" "$mirror" ada-example/tool-cl) >"$T/cl-out" 2>&1
status_cl=$?
clock_to=$(date +%s)
export clock_from clock_to
target "$T/gh-ce" ada-example/tool-ce
(SOURCE_DATE_EPOCH=1000000000 TZ=XXX-5:30 && export SOURCE_DATE_EPOCH TZ && replay "$T/gh-ce" ada-example/tool-ce --pace 0 --state "$T/ce.state.json" "$T/run.jsonl" "$mirror" ada-example/tool-ce) >"$T/ce-out" 2>&1
status_ce=$?
target "$T/gh-cb" ada-example/tool-cb
for epoch in "" 1.5 "$(printf '\302\262')" 99999999999999999999; do
  (SOURCE_DATE_EPOCH=$epoch && export SOURCE_DATE_EPOCH && replay "$T/gh-cb" ada-example/tool-cb --pace 0 --state "$T/cb.state.json" "$T/run.jsonl" "$mirror" ada-example/tool-cb) >>"$T/cb-out" 2>&1
  echo $? >>"$T/cb-status"
done
# LS: a run that started before committer dates were the time of the replay,
# made by refusing the first push to main once and removing from the state
# file the dates it records; the resumed run keeps the original dates.
target "$T/gh-ls" ada-example/tool-ls
cat >"$T/gh-ls/repo.git/hooks/pre-receive" <<'EOF'
#!/bin/sh
grep -q ' refs/heads/main$' || exit 0
[ ! -e ../refused-once ] || exit 0
touch ../refused-once
echo "refused once" >&2
exit 1
EOF
chmod +x "$T/gh-ls/repo.git/hooks/pre-receive"
replay "$T/gh-ls" ada-example/tool-ls --pace 0 --state "$T/ls.state.json" "$T/run.jsonl" "$mirror" ada-example/tool-ls >"$T/ls-out" 2>&1
echo $? >"$T/ls-status"
python3 - "$T/ls.state.json" <<'EOF'
import json, sys
state = json.load(open(sys.argv[1]))
for sha in state.pop("committer_dates"):
    state["hashes"].pop(sha, None)
json.dump(state, open(sys.argv[1], "w"))
EOF
replay "$T/gh-ls" ada-example/tool-ls --pace 0 --state "$T/ls.state.json" "$T/run.jsonl" "$mirror" ada-example/tool-ls >>"$T/ls-out" 2>&1
echo $? >>"$T/ls-status"
python3 - "$T/a.state.json" "$T/old-dates.state.json" <<'EOF'
import json, sys
state = json.load(open(sys.argv[1]))
del state["committer_dates"]
json.dump(state, open(sys.argv[2], "w"))
EOF
compare "$T/gh-a" --state "$T/old-dates.state.json" "$T/run.jsonl" "$mirror" ada-example/tool-new >"$T/cmp-old-dates-out" 2>&1
status_cmp_old_dates=$?
cp -R "$T/gh-a" "$T/gh-order"
early=$(echo "Repair the parser" | GIT_AUTHOR_NAME="Bob Example" GIT_AUTHOR_EMAIL=bob@example.com GIT_AUTHOR_DATE="1000000000 +0000" \
  GIT_COMMITTER_NAME="Bob Example" GIT_COMMITTER_EMAIL=bob@example.com GIT_COMMITTER_DATE="1000000000 +0000" \
  git --git-dir="$T/gh-order/repo.git" commit-tree "$(recreated "$F1")^{tree}" -p "$(recreated "$M2")")
git --git-dir="$T/gh-order/repo.git" update-ref refs/heads/fix/3-parser "$early"
python3 - "$T/a.state.json" "$T/order.state.json" "$F1" "$early" <<'EOF'
import json, sys
state = json.load(open(sys.argv[1]))
state["hashes"][sys.argv[3]] = sys.argv[4]
state["committer_dates"][sys.argv[3]] = "1000000000 +0000"
json.dump(state, open(sys.argv[2], "w"))
EOF
compare "$T/gh-order" --state "$T/order.state.json" "$T/run.jsonl" "$mirror" ada-example/tool-new >"$T/cmp-order-out" 2>&1
status_cmp_order=$?
export early
# CK: a replay killed after its push of feat/2-thing, by a hook of the
# target's repository, and resumed at a later time, which has to rebuild the
# pushed commits with the committer dates the state file records.
target "$T/gh-ck" ada-example/tool-ck
cat >"$T/gh-ck/repo.git/hooks/post-receive" <<'EOF'
#!/bin/sh
grep -q ' refs/heads/feat/2-thing$' || exit 0
[ ! -e ../killed ] || exit 0
touch ../killed
pid=$PPID
while [ "${pid:-1}" -gt 1 ]; do
  case $(ps -o args= -p "$pid") in
  *run-replay.py*)
    kill -9 "$pid"
    exit 0
    ;;
  esac
  pid=$(ps -o ppid= -p "$pid" | tr -d ' ')
done
EOF
chmod +x "$T/gh-ck/repo.git/hooks/post-receive"
replay "$T/gh-ck" ada-example/tool-ck --pace 0 --state "$T/ck.state.json" "$T/run.jsonl" "$mirror" ada-example/tool-ck >"$T/ck-out" 2>&1
echo $? >"$T/ck-status"
sleep 1
(SOURCE_DATE_EPOCH=1794009999 && export SOURCE_DATE_EPOCH && replay "$T/gh-ck" ada-example/tool-ck --pace 0 --state "$T/ck.state.json" "$T/run.jsonl" "$mirror" ada-example/tool-ck) >>"$T/ck-out" 2>&1
echo $? >>"$T/ck-status"
rcheck "run-replay.py resumes a push its kill interrupted with the committer dates the state file records, and dates the commits after it anew" "$T/gh-ck" "$T/ck.state.json" \
  'open(os.path.join(sys.argv[5], "ck-status")).read().split() == ["137", "0"] and git("log", "-1", "--format=%ct", M[S["B2"]]) == "1794000000" and git("rev-parse", "feat/2-thing") == M[S["B2"]] and git("log", "-1", "--format=%ct", M[S["C5"]]) == "1794009999"'
rcheck "run-replay.py gives each recreated commit the machine's time as committer date where SOURCE_DATE_EPOCH is not set" "$T/gh-cl" "$T/cl.state.json" \
  'int(os.environ["clock_from"]) <= int(git("log", "-1", "--format=%ct", M[S["C3"]])) <= int(os.environ["clock_to"]) and git("log", "-1", "--format=%ad", "--date=raw", M[S["C3"]]) == "1772712000 +0200"'
check "run-replay.py's replay on the machine's clock passes the comparison" \
  '[ "$status_cl" = 0 ] && FAKE_GITHUB=$T/gh-cl FAKE_GH_API=$T/api-run PATH=$target_path python3 "$here/compare-replay.py" --state "$T/cl.state.json" "$T/run.jsonl" "$mirror" ada-example/tool-cl >"$T/cmp-cl-out" 2>&1 && grep -qx "No differences" "$T/cmp-cl-out" || { cat "$T/cl-out" "$T/cmp-cl-out"; exit 1; }'
rcheck "run-replay.py commits no recreated commit before its parent, which GitHub's clock may date later" "$T/gh-ce" "$T/ce.state.json" \
  'git("log", "-1", "--format=%ct", M[S["F1"]]) == git("log", "-1", "--format=%ct", M[S["M2"]]) != "1000000000" and git("log", "-1", "--format=%cd", "--date=raw", M[S["C1"]]) == "1000000000 +0530"'
check "run-replay.py stops before the confirmation, without a write, at a SOURCE_DATE_EPOCH that is no whole number of seconds" \
  '[ "$(tr "\n" " " <"$T/cb-status")" = "1 1 1 1 " ] && [ "$(grep -c "^run-replay.py: SOURCE_DATE_EPOCH is .*, not a whole number of seconds$" "$T/cb-out")" = 3 ] && grep -q "^run-replay.py: SOURCE_DATE_EPOCH .* is no time this machine can date$" "$T/cb-out" && ! grep -q "Traceback\|to confirm" "$T/cb-out" && ! writes "$T/gh-cb" || { cat "$T/cb-out"; exit 1; }'
rcheck "run-replay.py resumes a run started before committer dates were the time of the replay with the original ones, and records none" "$T/gh-ls" "$T/ls.state.json" \
  'open(os.path.join(sys.argv[5], "ls-status")).read().split() == ["1", "0"] and "committer_dates" not in json.loads(open(sys.argv[2]).read()) and all(git("log", "-1", "--format=%cI", M[S[k]]) == next(c for e in E for c in e.get("commits", []) if c["sha"] == S[k])["committer"]["date"] for k in ("C1", "C3", "F1", "N2"))'
check "compare-replay.py expects the original committer dates from a state file that predates committer dates at the time of the replay" \
  '[ "$status_cmp_old_dates" = 1 ] && grep -q "^  main, step 1 ([0-9a-f]\{7\}): committer Ada Example <ada@example.com> 1794000000 +0000, planned Ada Example <ada@example.com> 1772359200 +0000$" "$T/cmp-old-dates-out" && ! grep -q "committed before its" "$T/cmp-old-dates-out" || { cat "$T/cmp-old-dates-out"; exit 1; }'
check "compare-replay.py names a recreated commit that is committed before its parent" \
  '[ "$status_cmp_order" = 1 ] && grep -Fqx "  the recreated commit $(echo "$early" | cut -c1-7) of $(echo "$F1" | cut -c1-7) is committed before its parent $(recreated "$M2" | cut -c1-7)" "$T/cmp-order-out" || { cat "$T/cmp-order-out"; exit 1; }'

# --sign: the checks before the confirmation, which stop a run before it
# writes anything. nothing_written <folder> <state file>: no write, no ref,
# no state file and no work repository.
nothing_written() {
  ! writes "$1" && [ -z "$(git --git-dir="$1/repo.git" for-each-ref)" ] && [ ! -e "$2" ] && [ ! -e "${2%.state.json}.work.git" ]
}
target "$T/gh-nokey"
replay "$T/gh-nokey" ada-example/tool-new --sign ada@example.com --state "$T/nokey.state.json" "$T/run.jsonl" "$mirror" ada-example/tool-new \
  >"$T/nokey-out" 2>&1
status_nokey=$?
check "run-replay.py --sign stops without a user.signingkey, before writing" \
  '[ "$status_nokey" = 1 ] && grep -q "^run-replay.py: --sign needs a user.signingkey in your git configuration$" "$T/nokey-out" && nothing_written "$T/gh-nokey" "$T/nokey.state.json" || { cat "$T/nokey-out"; exit 1; }'

# A GPG key, through a fake gpg that knows one secret key, with a signing
# subkey; no real key is involved.
mkdir "$T/bin-gpg"
cat >"$T/bin-gpg/gpg" <<'EOF'
#!/bin/sh
for last; do :; done
[ "$last" = 0123456789ABCDEF ] || { echo "gpg: error reading key: No secret key" >&2; exit 2; }
printf '%s\n' 'sec:u:255:22:0123456789ABCDEF:1772000000:::u:::scESC:::+:::ed25519:::0:' \
  'fpr:::::::::FEDCBA98765432100123456789ABCDEF:' \
  'ssb:u:255:22:1111222233334444:1772000000::::::s:::+:::ed25519::' \
  'fpr:::::::::AAAABBBBCCCCDDDD1111222233334444:'
EOF
chmod +x "$T/bin-gpg/gpg"
cat "$T/global" - >"$T/global-gpg" <<EOF
[user]
	signingkey = 0123456789ABCDEF
[gpg]
	program = $T/bin-gpg/gpg
EOF
target "$T/gh-gpg"
(GIT_CONFIG_GLOBAL=$T/global-gpg && export GIT_CONFIG_GLOBAL &&
  replay "$T/gh-gpg" ada-example/tool-new --sign ada@example.com --state "$T/gpg.state.json" "$T/run.jsonl" "$mirror" ada-example/tool-new) \
  >"$T/gpg-out" 2>&1
status_gpg=$?
echo '[{"id": 3, "key_id": "FEDCBA9876543210", "can_sign": false, "subkeys": [{"id": 4, "key_id": "1111222233334444", "can_sign": true}]}]' >"$T/gh-gpg/gpg_keys.json"
(GIT_CONFIG_GLOBAL=$T/global-gpg && export GIT_CONFIG_GLOBAL &&
  replay "$T/gh-gpg" no --sign ada@example.com --state "$T/gpg.state.json" "$T/run.jsonl" "$mirror" ada-example/tool-new) \
  >"$T/gpg-known-out" 2>&1
status_gpg_known=$?
check "run-replay.py --sign stops before writing where GitHub does not list the GPG key as one that signs" \
  '[ "$status_gpg" = 1 ] && grep -q "^run-replay.py: GitHub does not list the GPG key 0123456789ABCDEF among your GPG keys that sign" "$T/gpg-out" && grep -q " GET user/gpg_keys?per_page=100&page=1$" "$T/gh-gpg/calls" && nothing_written "$T/gh-gpg" "$T/gpg.state.json" || { cat "$T/gpg-out"; exit 1; }'
check "run-replay.py --sign takes a GPG key whose signing subkey GitHub lists, and says a stopped push cannot resume with it" \
  '[ "$status_gpg_known" = 1 ] && grep -q "run-replay.py: not confirmed; nothing changed$" "$T/gpg-known-out" && grep -Eqx "  commits to sign +9" "$T/gpg-known-out" && grep -qx "  signed: the commits committed by ada@example.com, with the GPG key 0123456789ABCDEF" "$T/gpg-known-out" && grep -q "^  this key does not sign a commit the same way twice" "$T/gpg-known-out" && nothing_written "$T/gh-gpg" "$T/gpg.state.json" || { cat "$T/gpg-known-out"; exit 1; }'

# An SSH key: a throwaway Ed25519 key without a passphrase, which GitHub
# lists in the targets that know it, and an allowed-signers file for git log.
if command -v ssh-keygen >/dev/null 2>&1; then
  ssh-keygen -q -t ed25519 -N '' -C test -f "$T/sign-key"
  # The folder as Python prints a path, without the double slash that a
  # TMPDIR ending in a slash, as on macOS, leaves in it.
  P=$(printf '%s\n' "$T" | tr -s /)
  SIGNERS=$T/allowed-signers
  export SIGNERS
  echo "ada@example.com $(cut -d' ' -f1,2 "$T/sign-key.pub")" >"$SIGNERS"
  cat "$T/global" - >"$T/global-sign" <<EOF
[gpg]
	format = ssh
[user]
	signingkey = $T/sign-key.pub
EOF
  # sign_target <folder>: a target whose account lists the key.
  sign_target() {
    target "$1" && printf '[{"id": 1, "key": "%s", "title": "test", "created_at": "2026-11-01T00:00:00Z"}]\n' "$(cut -d' ' -f1,2 "$T/sign-key.pub")" >"$1/ssh_signing_keys.json"
  }
  # sign_replay <folder> <answer> <state file>: a replay that signs Ada's commits.
  sign_replay() {
    (GIT_CONFIG_GLOBAL=$T/global-sign && export GIT_CONFIG_GLOBAL &&
      replay "$1" "$2" --pace 0 --sign ada@example.com --state "$3" "$T/run.jsonl" "$mirror" ada-example/tool-new)
  }

  # A key with a passphrase that no agent holds would ask at every commit.
  ssh-keygen -q -t ed25519 -N x -C test -f "$T/pass-key"
  sed "s#sign-key.pub#pass-key.pub#" "$T/global-sign" >"$T/global-pass"
  sign_target "$T/gh-pass"
  (GIT_CONFIG_GLOBAL=$T/global-pass && export GIT_CONFIG_GLOBAL && unset SSH_AUTH_SOCK &&
    replay "$T/gh-pass" ada-example/tool-new --pace 0 --sign ada@example.com --state "$T/pass.state.json" "$T/run.jsonl" "$mirror" ada-example/tool-new) \
    >"$T/pass-out" 2>&1
  status_pass=$?
  check "run-replay.py --sign stops before writing when the key has a passphrase and no agent holds it" \
    '[ "$status_pass" = 1 ] && grep -q "the signing key is not in the agent" "$T/pass-out" && nothing_written "$T/gh-pass" "$T/pass.state.json" || { cat "$T/pass-out"; exit 1; }'

  target "$T/gh-unknown"
  sign_replay "$T/gh-unknown" ada-example/tool-new "$T/unknown.state.json" >"$T/unknown-out" 2>&1
  status_unknown=$?
  check "run-replay.py --sign stops before writing where GitHub does not list the SSH key as a signing key" \
    '[ "$status_unknown" = 1 ] && grep -Fqx "run-replay.py: GitHub does not list $P/sign-key.pub among your SSH signing keys, so it would show the signed commits as unverified; add it with: gh ssh-key add $P/sign-key.pub --type signing" "$T/unknown-out" && grep -q " GET user/ssh_signing_keys?per_page=100&page=1$" "$T/gh-unknown/calls" && nothing_written "$T/gh-unknown" "$T/unknown.state.json" || { cat "$T/unknown-out"; exit 1; }'
  sign_target "$T/gh-scope"
  (FAKE_GH_NO_SCOPE=1 && export FAKE_GH_NO_SCOPE && sign_replay "$T/gh-scope" ada-example/tool-new "$T/scope.state.json") >"$T/scope-out" 2>&1
  status_scope=$?
  check "run-replay.py --sign names the scope gh lacks to list the signing keys, and stops before writing" \
    '[ "$status_scope" = 1 ] && grep -Fqx "run-replay.py: GitHub refused to list your SSH signing keys (HTTP 404), which gh may read only with the scope read:ssh_signing_key; add it with: gh auth refresh -s read:ssh_signing_key" "$T/scope-out" && nothing_written "$T/gh-scope" "$T/scope.state.json" || { cat "$T/scope-out"; exit 1; }'

  # SA: one uninterrupted signed run.
  sign_target "$T/gh-sa"
  sign_replay "$T/gh-sa" ada-example/tool-new "$T/sa.state.json" >"$T/sa-out" 2>&1
  status_sa=$?
  check "run-replay.py --sign says in the totals how many commits it signs and with which key, and in each push how many it signed" \
    '[ "$status_sa" = 0 ] && grep -Eqx "  commits to sign +9" "$T/sa-out" && grep -Fqx "  signed: the commits committed by ada@example.com, with the SSH key $P/sign-key.pub (ssh-ed25519)" "$T/sa-out" && ! grep -q "same way twice" "$T/sa-out" && grep -q "#3 branch fix/3-parser, 1 commit, 0 signed, at " "$T/sa-out" && grep -q " 3 commits to main, 3 signed, now at " "$T/sa-out" && grep -q "#2 branch feat/2-thing, 2 commits, 2 signed, at " "$T/sa-out" || { cat "$T/sa-out"; exit 1; }'
  rcheck "run-replay.py --sign signs exactly the recreated commits whose committer has the address" "$T/gh-sa" "$T/sa.state.json" \
    '(marks := {c["sha"]: (c["committer"]["email"], git("-c", "gpg.ssh.allowedSignersFile=" + S["SIGNERS"], "log", "-1", "--format=%G?", M[c["sha"]])) for e in E for c in e.get("commits", [])}) and all(mark == ("G" if email == "ada@example.com" else "N") for email, mark in marks.values()) and sorted(mark for _, mark in marks.values()) == ["G"] * 9 + ["N"] and marks[S["F1"]] == ("bob@example.com", "N") and [git("log", "-1", "--format=%G?", M[S[k]]) for k in ("M2", "M3")] == ["N", "N"]'
  # shape <folder>: every commit of the target, without its hash.
  shape() { git --git-dir="$1/repo.git" log --all --format='%T %an %ae %ad %cn %ce %cd %s' --date=raw | sort; }
  check "run-replay.py --sign changes no tree, identity, date or subject" \
    'shape "$T/gh-a" >"$T/a-shape" && shape "$T/gh-sa" >"$T/sa-shape" && [ "$(wc -l <"$T/a-shape")" -eq 12 ] && diff "$T/a-shape" "$T/sa-shape"'

  # SB: the same signed run, killed right after it pushed the branch of #2,
  # as a crash would, then resumed; and SC, a copy of that target resumed
  # from a state file that records another hash for the branch's second
  # commit, as a key that signs differently each time would leave it.
  sign_target "$T/gh-sb"
  cat >"$T/gh-sb/repo.git/hooks/post-receive" <<'EOF'
#!/bin/sh
# Kills the run-replay.py that pushes, once, after its push of feat/2-thing.
grep -q ' refs/heads/feat/2-thing$' || exit 0
[ ! -e ../killed ] || exit 0
touch ../killed
pid=$PPID
while [ "${pid:-1}" -gt 1 ]; do
  case $(ps -o args= -p "$pid") in
  *run-replay.py*)
    kill -9 "$pid"
    exit 0
    ;;
  esac
  pid=$(ps -o ppid= -p "$pid" | tr -d ' ')
done
EOF
  chmod +x "$T/gh-sb/repo.git/hooks/post-receive"
  sign_replay "$T/gh-sb" ada-example/tool-new "$T/sb.state.json" >"$T/sb-out" 2>&1
  echo $? >"$T/sb-status"
  # The push the kill left running ends on its own; then the copy.
  sleep 1
  cp -R "$T/gh-sb" "$T/gh-sc"
  python3 - "$T/sb.state.json" "$T/sc.state.json" "$B2" <<'EOF'
import json, sys
with open(sys.argv[1], encoding="utf-8") as f:
    state = json.load(f)
assert sys.argv[3] in state["hashes"], "the killed run saved no hash before its push"
state["hashes"][sys.argv[3]] = "0123456789abcdef0123456789abcdef01234567"
with open(sys.argv[2], "w", encoding="utf-8") as f:
    json.dump(state, f)
EOF
  sc_refs=$(git --git-dir="$T/gh-sc/repo.git" for-each-ref)
  sc_writes=$(writes "$T/gh-sc" | wc -l)
  sign_replay "$T/gh-sb" ada-example/tool-new "$T/sb.state.json" >>"$T/sb-out" 2>&1
  echo $? >>"$T/sb-status"
  sign_replay "$T/gh-sc" ada-example/tool-new "$T/sc.state.json" >"$T/sc-out" 2>&1
  status_sc=$?
  check "run-replay.py --sign ends a run killed after a push and resumed with the same hashes as an uninterrupted one" \
    '[ "$(tr "\n" " " <"$T/sb-status")" = "137 0 " ] && grep -q "Resume the replay of ada-example/tool into ada-example/tool-new at event 5 of 23" "$T/sb-out" && [ -n "$(git --git-dir="$T/gh-sc/repo.git" for-each-ref refs/heads/feat/2-thing)" ] && dump "$T/gh-sa" >"$T/sa-dump" && dump "$T/gh-sb" >"$T/sb-dump" && diff "$T/sa-dump" "$T/sb-dump" && python3 -c "import json, sys; a, b = (json.load(open(f))[\"hashes\"] for f in sys.argv[1:]); sys.exit(a != b)" "$T/sa.state.json" "$T/sb.state.json" || { cat "$T/sb-status" "$T/sb-out"; exit 1; }'
  check "run-replay.py stops before pushing where a rebuilt commit gets another hash than the state file records" \
    'b2=$(echo "$B2" | cut -c1-7) && [ "$status_sc" = 1 ] && grep -q "run-replay.py: commit $b2 was rebuilt as [0-9a-f]\{7\}, but $P/sc.state.json records 0123456; its signature differs from the one the first run made: the signing key signs differently each time, or it is another key. The run stops before it pushes a second history$" "$T/sc-out" && grep -q "^run-replay.py: stopped in event 5 of 23" "$T/sc-out" && [ "$(git --git-dir="$T/gh-sc/repo.git" for-each-ref)" = "$sc_refs" ] && [ "$(writes "$T/gh-sc" | wc -l)" -eq "$sc_writes" ] || { cat "$T/sc-out"; exit 1; }'
else
  echo "ssh-keygen is missing; run-replay.py --sign with an SSH key not tested"
fi

# replay.py, from a run file, into a target that does not exist yet, with
# sub-issue links: #1 and #4 of the source under ada-example/plans#9, #6 under
# #4, and ada-example/plans#11 under #6. replay_setup <folder> [<owner/repo>
# [<links>]]: that target, ada-example/tool-replay-20261116 by default, with
# those links or the ones given as JSON, and next to it <folder>-api, the
# source's API of the run's plan with issue ids, settings, Actions and the
# issues of ada-example/plans.
links_all='{"ada-example/plans#9": [9001, 8010, 9004], "ada-example/tool#4": [9006], "ada-example/tool#6": [8011]}'
replay_setup() {
  target "$1" "${2:-ada-example/tool-replay-20261116}" && touch "$1/absent" &&
    echo "${3:-$links_all}" >"$1/links.json" &&
    cp -R "$T/api-run" "$1-api" && python3 - "$1-api" <<'EOF'
import json, sys
from pathlib import Path
api = Path(sys.argv[1])
for page in api.glob("repos_ada-example_tool_issues-*.json"):
    issues = json.loads(page.read_text())
    for it in issues:
        it["id"] = 9000 + it["number"]
    page.write_text(json.dumps(issues))
(api / "repos_ada-example_tool.json").write_text(json.dumps({
    "default_branch": "main", "delete_branch_on_merge": True, "allow_merge_commit": False,
    "allow_squash_merge": True, "allow_rebase_merge": False, "description": "A small tool"}))
(api / "repos_ada-example_tool_actions_permissions.json").write_text('{"enabled": true}')
(api / "repos_ada-example_plans_issues-1.json").write_text(json.dumps(
    [{"id": 8000 + n, "number": n, "title": f"Plan {n}", "state": "open"} for n in (9, 10, 11)]))
EOF
}
# run_file <file> <backup folder> [<field>=<JSON value>]...: a run file for the
# replay of ada-example/tool that sets every type the plan would guess; a
# field with an empty value is left out.
run_file() {
  mkdir -p "$(dirname "$1")" && python3 - "$T" "$@" <<'EOF'
import json, os, sys
T, path, backup, *changes = sys.argv[1:]
S = os.environ
fields = {
    "source": "ada-example/tool",
    "target": "ada-example/tool-replay-20261116",
    "mailmap": ["Ada Example <ada@example.com> <ada.old@example.com>",
                "Ada Example <ada@example.com> GitHub <noreply@github.com>"],
    "types": [f"{S['C1'][:7]} docs", f"{S['C3'][:7]} test", f"{S['C4'][:9]} chore",
              f"{S['C5'][:7]} feat"],
    "pace": 0,
    "backup": backup,
    "clone_url": f"{T}/source.git",
}
for change in changes:
    key, _, value = change.partition("=")
    if value:
        fields[key] = json.loads(value)
    else:
        del fields[key]
with open(path, "w", encoding="utf-8") as f:
    json.dump(fields, f, indent=1)
EOF
}
# one <folder> <answer> <run file>: replay.py against the target in that
# folder, with the answer typed at the confirmation.
one() {
  printf '%s\n' "$2" | FAKE_GITHUB=$1 FAKE_GH_API=$1-api PATH=$target_path python3 "$here/replay.py" "$3"
}
# links_hold <folder> [<links>]: the sub-issue links as the replay leaves
# them, each replayed item in the place of the source's, or else the links
# given as JSON.
links_hold() {
  python3 - "$1/links.json" "${2:-}" <<'EOF'
import json, sys
links = {k: v for k, v in json.load(open(sys.argv[1])).items() if v}
expected = json.loads(sys.argv[2]) if sys.argv[2] else {
    "ada-example/plans#9": [7001, 8010, 7004], "ada-example/tool#4": [9006],
    "ada-example/tool-replay-20261116#4": [7006], "ada-example/tool-replay-20261116#6": [8011]}
sys.exit(0 if links == expected else f"links {links}, expected {expected}")
EOF
}
S6=$(echo "$C5" | cut -c1-7)
export S6

# RA: one uninterrupted run.
replay_setup "$T/ra"
run_file "$T/runs-a/tool.run.json" "$T/backup-ra"
one "$T/ra" ada-example/tool-replay-20261116 "$T/runs-a/tool.run.json" >"$T/ra-out" 2>"$T/ra-err"
status_ra=$?
check "replay.py runs every step from a run file after one confirmation, and the comparison finds no difference" \
  '[ "$status_ra" = 0 ] && [ ! -s "$T/ra-err" ] && for n in "1 of 8, mirror" "2 of 8, plan" "3 of 8, create" "4 of 8, settings" "5 of 8, replay" "6 of 8, compare" "7 of 8, links" "8 of 8, commands"; do grep -q "^Step $n: " "$T/ra-out" || { echo "no step $n"; exit 1; }; done && [ "$(grep -c "to confirm: " "$T/ra-out")" = 2 ] && grep -qx "Type ada-example/tool-replay-20261116 to confirm: ada-example/tool-replay-20261116, as --confirmed gives it" "$T/ra-out" && grep -qx "No differences" "$T/ra-out" && grep -Eqx "  guessed types +0" "$T/ra-out" && [ ! -e "$T/ra/refused" ] || { cat "$T/ra-err" "$T/ra-out" "$T/ra/refused" 2>&1; exit 1; }'
check "replay.py creates the target private after the confirmation, with Actions off and head branches deleted on merge as in the source" \
  '[ "$(writes "$T/ra" | head -n 1 | cut -d" " -f2-)" = "POST user/repos" ] && [ ! -e "$T/ra/absent" ] && python3 -c "import json, sys; s, a = (json.load(open(sys.argv[1] + f)) for f in (\"/settings.json\", \"/actions.json\")); sys.exit(not (s[\"private\"] and s[\"delete_branch_on_merge\"] and a == {\"enabled\": False}))" "$T/ra" && [ "$(git --git-dir="$T/ra/repo.git" for-each-ref --format="%(refname:short)" refs/heads/ | tr "\n" " ")" = "docs/5-notes main " ] || { writes "$T/ra"; cat "$T/ra/settings.json" "$T/ra/actions.json"; exit 1; }'
check "replay.py moves each sub-issue link into the place of the source's item, and links the sub-issues of the source's items" \
  'links_hold "$T/ra" && grep -qx "  #1 under ada-example/plans#9, in the place of the source'"'"'s" "$T/ra-out" && grep -qx "  ada-example/plans#11 under the replay'"'"'s #6" "$T/ra-out"'
check "replay.py moves a link after the sub-issue before the source's, or before the one after it where the source's is first" \
  '[ "$(tr "\n" " " <"$T/ra/priorities")" = "{\"before_id\": 8010, \"sub_issue_id\": 7001} {\"after_id\": 8010, \"sub_issue_id\": 7004} " ] || { cat "$T/ra/priorities"; exit 1; }'
check "replay.py prints, without running them, the commands that archive the source, rename the replay and restore its settings" \
  'for line in "gh api -X PATCH repos/ada-example/tool -f name=tool-archive" "gh api -X PATCH repos/ada-example/tool-archive -F archived=true" "gh api -X PATCH repos/ada-example/tool-replay-20261116 -f name=tool" "gh api -X PUT repos/ada-example/tool/actions/permissions -F enabled=true" "gh api -X PATCH repos/ada-example/tool -F allow_merge_commit=false -F allow_squash_merge=true -F allow_rebase_merge=false -F delete_branch_on_merge=true -f '"'"'description=A small tool'"'"'" "gh api -X DELETE repos/ada-example/tool/git/refs/heads/docs/5-notes"; do grep -Fqx "$line" "$T/ra-out" || { echo "no line: $line"; exit 1; }; done && ! grep -q "archived\|name=tool" "$T/ra/calls" || { cat "$T/ra-out"; exit 1; }'

check "replay.py prints the reads of what the comparison cannot see in the source before the archive, and after it the commands that replace the local clone" \
  'for line in "gh api repos/ada-example/tool/actions/secrets --jq .total_count" "gh api repos/ada-example/tool/actions/variables --jq .total_count" "gh api repos/ada-example/tool/hooks --jq length" "gh api repos/ada-example/tool/keys --jq length" "gh api repos/ada-example/tool/collaborators --jq '"'"'.[].login'"'"'" "test ! -d ~/vc/tool || { git -C ~/vc/tool status --short; mv ~/vc/tool ~/vc/tool-old; }" "gh repo clone ada-example/tool ~/vc/tool"; do grep -Fqx "$line" "$T/ra-out" || { echo "no line: $line"; exit 1; }; done && ! grep -q "secret_scanning\|has_wiki" "$T/ra-out" && [ "$(grep -e "/actions/secrets --jq" -e "archived=true$" -e "^gh repo clone " "$T/ra-out" | sed -e "s/.*secrets.*/reads/" -e "s/.*archived.*/archive/" -e "s/^gh repo clone.*/clone/" | tr "\n" " ")" = "reads archive clone " ] || { cat "$T/ra-out"; exit 1; }'

# RG, a run file that leaves a type to guess; RW, a wrong confirmation.
replay_setup "$T/rg"
run_file "$T/runs-g/tool.run.json" "$T/backup-rg" "types=[\"$(echo "$C4" | cut -c1-9) chore\", \"$(echo "$C1" | cut -c1-7) docs\", \"$(echo "$C3" | cut -c1-7) test\"]"
one "$T/rg" ada-example/tool-replay-20261116 "$T/runs-g/tool.run.json" >"$T/rg-out" 2>&1
status_rg=$?
check "replay.py stops after the plan, before any write and before the confirmation, where a type would be guessed" \
  '[ "$status_rg" = 1 ] && grep -q "^replay.py: 1 title would get a guessed type, marked guessed above; give each its type in types of " "$T/rg-out" && grep -q "^  $S6  guessed  " "$T/rg-out" && grep -q "^replay.py: stopped in step 2 of 8, plan, before any write to GitHub in this run" "$T/rg-out" && ! grep -q "to confirm" "$T/rg-out" && ! writes "$T/rg" && [ -e "$T/rg/absent" ] && [ ! -e "$T/runs-g/tool.progress.json" ] || { cat "$T/rg-out"; exit 1; }'
replay_setup "$T/rw"
run_file "$T/runs-w/tool.run.json" "$T/backup-rw"
one "$T/rw" tool-replay-20261116 "$T/runs-w/tool.run.json" >"$T/rw-out" 2>&1
status_rw=$?
check "replay.py lists what it will do, sub-issue links included, and writes nothing on a wrong confirmation" \
  '[ "$status_rw" = 1 ] && grep -q "replay.py: not confirmed; nothing changed on GitHub$" "$T/rw-out" && grep -qx "  7. move sub-issue links: 4" "$T/rw-out" && grep -qx "       #1: in ada-example/plans#9, links the replay'"'"'s #1 in the place of the source'"'"'s and unlinks the source'"'"'s (writes in ada-example/plans)" "$T/rw-out" && grep -qx "       the replay'"'"'s #6 gets the sub-issues of the source'"'"'s: ada-example/plans#11, taken from the source'"'"'s #6 with replace_parent (writes in ada-example/plans and in the source)" "$T/rw-out" && grep -qx "  3. create ada-example/tool-replay-20261116, private and empty" "$T/rw-out" && grep -qx "  5. run run-replay.py --pace 0 --final-name ada-example/tool, and make main the default branch where GitHub names another" "$T/rw-out" && ! writes "$T/rw" && [ -e "$T/rw/absent" ] && [ ! -e "$T/runs-w/tool.progress.json" ] || { cat "$T/rw-out"; writes "$T/rw"; exit 1; }'
mkdir -p "$T/runs-v"
run_file "$T/work/tool.run.json" "$T/backup-rv"
run_file "$T/runs-v/colour.run.json" "$T/backup-rv" 'colour="blue"'
run_file "$T/runs-v/name.run.json" "$T/backup-rv" 'target="ada-example/tool-new"'
for f in "$T/work/tool.run.json" "$T/runs-v/colour.run.json" "$T/runs-v/name.run.json"; do
  one "$T/rw" ada-example/tool-replay-20261116 "$f" >>"$T/rv-out" 2>&1
  echo $? >>"$T/rv-status"
done
check "replay.py refuses a run file in a git work tree, with an unknown field, or with a target not named for the day of the replay" \
  '[ "$(tr "\n" " " <"$T/rv-status")" = "1 1 1 " ] && grep -q "tool.run.json lies in a git work tree; keep it outside any repository, since it holds the mailmap$" "$T/rv-out" && grep -q "colour.run.json has fields replay.py does not know: colour$" "$T/rv-out" && grep -q "name.run.json: target must be ada-example/tool-replay-<YYYYMMDD-HHMM>" "$T/rv-out" && ! writes "$T/rw" || { cat "$T/rv-status" "$T/rv-out"; exit 1; }'

# RB: a run stopped by a Ctrl-C in the replay, resumed into a difference the
# comparison finds, since the source's label changed meanwhile, and resumed
# once more after the label is back.
replay_setup "$T/rb"
run_file "$T/runs-b/tool.run.json" "$T/backup-rb"
labels_b=$T/rb-api/repos_ada-example_tool_labels-1.json
(FAKE_GH_INTERRUPT="POST repos/ada-example/tool-replay-20261116/issues" && export FAKE_GH_INTERRUPT &&
  one "$T/rb" ada-example/tool-replay-20261116 "$T/runs-b/tool.run.json") >"$T/rb-out" 2>&1
echo $? >"$T/rb-status"
cp "$labels_b" "$T/rb-labels"
sed 's/0075ca/123456/' "$T/rb-labels" >"$labels_b"
one "$T/rb" ada-example/tool-replay-20261116 "$T/runs-b/tool.run.json" >>"$T/rb-out" 2>&1
echo $? >>"$T/rb-status"
cp "$T/rb-labels" "$labels_b"
one "$T/rb" ada-example/tool-replay-20261116 "$T/runs-b/tool.run.json" >>"$T/rb-out" 2>&1
echo $? >>"$T/rb-status"
check "replay.py stops where run-replay.py stops, and the same command resumes there after a new confirmation" \
  '[ "$(tr "\n" " " <"$T/rb-status")" = "1 1 0 " ] && grep -q "^run-replay.py: stopped after event [0-9]* of 23; run the same command again to resume$" "$T/rb-out" && grep -q "^replay.py: stopped in step 5 of 8, replay; run the same command again to resume there once the cause is removed$" "$T/rb-out" && grep -q "^Resume the replay of ada-example/tool into ada-example/tool-replay-20261116 at step 5, replay, from .*tool.progress.json:$" "$T/rb-out" && grep -q "^Resume the replay of ada-example/tool into ada-example/tool-replay-20261116 at event [0-9]* of 23" "$T/rb-out" && [ "$(grep -c " POST user/repos$" "$T/rb/calls")" = 1 ] || { cat "$T/rb-status" "$T/rb-out"; exit 1; }'
check "replay.py stops at a difference the comparison finds, before it moves a sub-issue link" \
  'grep -Fqx "  label docs: colour 0075ca, the source'"'"'s 123456" "$T/rb-out" && grep -q "^replay.py: stopped in step 6 of 8, compare; run the same command again to resume there" "$T/rb-out" && [ "$(grep -c "^Step 7 of 8, links" "$T/rb-out")" = 1 ]'
check "replay.py ends a stopped and resumed run with the links and the target of an uninterrupted one" \
  'links_hold "$T/rb" && grep -qx "No differences" "$T/rb-out" && dump "$T/ra" >"$T/ra-dump" && dump "$T/rb" >"$T/rb-dump" && diff "$T/ra-dump" "$T/rb-dump"'

# RM: a target that GitHub creates with the default branch master, and lets
# no one change while it lacks the branch, with #1 the only sub-issue of
# ada-example/plans#9 and no other link; stopped by a Ctrl-C in the replay
# after the first push, and resumed; signed in as bob-example, a member of the
# organisation ada-example.
replay_setup "$T/rm" ada-example/tool-replay-20261116 '{"ada-example/plans#9": [9001]}'
run_file "$T/runs-m/tool.run.json" "$T/backup-rm"
(FAKE_GH_DEFAULT=master FAKE_GH_LOGIN=bob-example FAKE_GH_INTERRUPT="POST repos/ada-example/tool-replay-20261116/issues" &&
  export FAKE_GH_DEFAULT FAKE_GH_LOGIN FAKE_GH_INTERRUPT && one "$T/rm" ada-example/tool-replay-20261116 "$T/runs-m/tool.run.json") >"$T/rm-out" 2>&1
echo $? >"$T/rm-status"
one "$T/rm" ada-example/tool-replay-20261116 "$T/runs-m/tool.run.json" >>"$T/rm-out" 2>&1
echo $? >>"$T/rm-status"
check "replay.py gives the target the source's default branch once it has it, where GitHub names another at the creation" \
  '[ "$(tr "\n" " " <"$T/rm-status")" = "1 0 " ] && grep -q "^replay.py: stopped in step 5 of 8, replay; run the same command again" "$T/rm-out" && grep -qx "  default branch main, where GitHub had named it master" "$T/rm-out" && [ ! -e "$T/rm/rejected" ] && grep -qx "No differences" "$T/rm-out" && python3 -c "import json, sys; sys.exit(json.load(open(sys.argv[1]))[\"default_branch\"] != \"main\")" "$T/rm/settings.json" && links_hold "$T/rm" "{\"ada-example/plans#9\": [7001]}" || { cat "$T/rm-status" "$T/rm-out" "$T/rm/rejected" 2>&1; exit 1; }'

# RN: the same target named master, replayed without a stop, from a public
# source.
replay_setup "$T/rn"
python3 - "$T/rn-api/repos_ada-example_tool.json" <<'EOF'
import json, sys
info = json.load(open(sys.argv[1]))
info.update(private=False, visibility="public", has_wiki=True, has_projects=True, has_discussions=False,
            security_and_analysis={"secret_scanning": {"status": "enabled"},
                                   "secret_scanning_push_protection": {"status": "enabled"},
                                   "dependabot_security_updates": {"status": "disabled"}})
json.dump(info, open(sys.argv[1], "w"))
EOF
run_file "$T/runs-n/tool.run.json" "$T/backup-rn"
(FAKE_GH_DEFAULT=master && export FAKE_GH_DEFAULT && one "$T/rn" ada-example/tool-replay-20261116 "$T/runs-n/tool.run.json") >"$T/rn-out" 2>&1
check "replay.py gives the target the source's default branch after an uninterrupted replay into a target named master" \
  'grep -qx "  default branch main, where GitHub had named it master" "$T/rn-out" && [ ! -e "$T/rn/rejected" ] || { cat "$T/rn-out"; exit 1; }'
check "replay.py creates the target of a public source private, and prints the command that makes the renamed replay public, after the rename, only for such a source" \
  'python3 -c "import json, sys; s = json.load(open(sys.argv[1])); sys.exit(not s[\"private\"] or \"visibility\" in s)" "$T/rn/settings.json" && grep -Fqx "gh api -X PATCH repos/ada-example/tool -f visibility=public" "$T/rn-out" && [ "$(grep -e "-f name=tool$" -e "visibility=public$" "$T/rn-out" | sed -e "s/.*-f name=tool$/rename/" -e "s/.*visibility=public$/visibility/" | tr "\n" " ")" = "rename visibility " ] && ! grep -q "visibility=" "$T/ra-out" || { cat "$T/rn-out"; exit 1; }'
check "replay.py prints the source's wiki, projects and discussions with its settings, and its secret scanning after the visibility" \
  'grep -Fqx "gh api -X PATCH repos/ada-example/tool -F allow_merge_commit=false -F allow_squash_merge=true -F allow_rebase_merge=false -F delete_branch_on_merge=true -F has_wiki=true -F has_projects=true -F has_discussions=false -f '"'"'description=A small tool'"'"'" "$T/rn-out" && [ "$(grep -e "visibility=public$" -e "security_and_analysis" "$T/rn-out" | sed -e "s/.*visibility=public$/visibility/" -e "s/.*security_and_analysis.*/security/" | tr "\n" " ")" = "visibility security " ] && grep -Fqx "gh api -X PATCH repos/ada-example/tool -f '"'"'security_and_analysis[secret_scanning][status]=enabled'"'"' -f '"'"'security_and_analysis[secret_scanning_push_protection][status]=enabled'"'"'" "$T/rn-out" && ! grep -q dependabot "$T/rn-out" || { cat "$T/rn-out"; exit 1; }'

check "replay.py reads the parent only of an issue whose parent_issue_url names one, and skips the move of an only sub-issue" \
  'grep -q " GET repos/ada-example/tool/issues/1/parent$" "$T/rm/calls" && ! grep -q " GET repos/ada-example/tool/issues/[46]/parent$" "$T/rm/calls" && [ ! -e "$T/rm/priorities" ] || { grep parent "$T/rm/calls"; cat "$T/rm/priorities"; exit 1; }'

check "replay.py creates the target with orgs/<owner>/repos where its owner is not the account gh is signed in with" \
  '[ "$(writes "$T/rm" | head -n 1 | cut -d" " -f2-)" = "POST orgs/ada-example/repos" ] && ! grep -q " POST user/repos$" "$T/rm/calls" || { writes "$T/rm"; exit 1; }'

# RD: GitHub refuses the creation once, then the change of Actions once;
# each run stops in that step, and the next resumes there, the last one only
# up to a wrong confirmation.
replay_setup "$T/rd"
run_file "$T/runs-d/tool.run.json" "$T/backup-rd"
for deny in "POST user/repos" "PUT repos/ada-example/tool-replay-20261116/actions/permissions"; do
  (FAKE_GH_DENY=$deny && export FAKE_GH_DENY && one "$T/rd" ada-example/tool-replay-20261116 "$T/runs-d/tool.run.json") >>"$T/rd-out" 2>&1
  echo $? >>"$T/rd-status"
done
one "$T/rd" no "$T/runs-d/tool.run.json" >>"$T/rd-out" 2>&1
echo $? >>"$T/rd-status"
check "replay.py stops in step 3 where GitHub refuses the creation, and creates the target when the same command runs again" \
  '[ "$(tr "\n" " " <"$T/rd-status")" = "1 1 1 " ] && grep -qx "replay.py: POST user/repos answered HTTP 403: Resource not accessible by personal access token" "$T/rd-out" && grep -q "^replay.py: stopped in step 3 of 8, create; run the same command again to resume there" "$T/rd-out" && grep -q "^Resume the replay of ada-example/tool into ada-example/tool-replay-20261116 at step 3, create, from " "$T/rd-out" && [ "$(writes "$T/rd" | grep -c " POST user/repos$")" = 2 ] && [ ! -e "$T/rd/absent" ] || { cat "$T/rd-status" "$T/rd-out"; writes "$T/rd"; exit 1; }'
check "replay.py stops in step 4 where GitHub refuses a setting, and resumes there without creating the target again" \
  'grep -qx "replay.py: PUT repos/ada-example/tool-replay-20261116/actions/permissions answered HTTP 403: Resource not accessible by personal access token" "$T/rd-out" && grep -q "^replay.py: stopped in step 4 of 8, settings; run the same command again to resume there" "$T/rd-out" && grep -q "^Resume the replay of ada-example/tool into ada-example/tool-replay-20261116 at step 4, settings, from " "$T/rd-out" && [ "$(tail -n 1 "$T/rd-out")" = "replay.py: stopped in the confirmation, before any write to GitHub in this run; run the same command again to resume once the cause is removed" ] && [ ! -e "$T/rd/actions.json" ] && python3 -c "import json, sys; sys.exit(json.load(open(sys.argv[1]))[\"done\"] != [\"create\"])" "$T/runs-d/tool.progress.json" && [ "$(writes "$T/rd" | cut -d" " -f2- | tr "\n" "|")" = "POST user/repos|POST user/repos|PUT repos/ada-example/tool-replay-20261116/actions/permissions|" ] || { cat "$T/rd-out"; writes "$T/rd"; exit 1; }'

# RO: a replay under another owner than that of the repository of a parent
# and of a sub-issue from elsewhere.
replay_setup "$T/ro" bob-example/tool-replay-20261116-1215
run_file "$T/runs-o/tool.run.json" "$T/backup-ro" 'target="bob-example/tool-replay-20261116-1215"' 'final_name="bob-example/tool"'
one "$T/ro" bob-example/tool-replay-20261116-1215 "$T/runs-o/tool.run.json" >"$T/ro-out" 2>&1
status_ro=$?
check "replay.py stops before the confirmation, without a write, where a sub-issue link would cross owners" \
  '[ "$status_ro" = 1 ] && grep -Fqx "replay.py: GitHub links a sub-issue only to a parent of the same owner, and the target'"'"'s owner is bob-example: #1 under ada-example/plans#9; #4 under ada-example/plans#9; ada-example/plans#11 under #6. GitHub refuses such a link whoever makes it, so replay.py cannot carry it. Move or remove these links in the source first, or replay with plan-replay.py and run-replay.py alone, which leave links alone, and leave these links out of the first move in the README'"'"'s Taking over the source'"'"'s name" "$T/ro-out" && grep -q "^replay.py: stopped in the survey of the sub-issue links, before any write to GitHub in this run" "$T/ro-out" && ! grep -q "to confirm" "$T/ro-out" && ! writes "$T/ro" && [ -e "$T/ro/absent" ] && [ ! -e "$T/runs-o/tool.progress.json" ] || { cat "$T/ro-out"; writes "$T/ro"; exit 1; }'

# RL: a source with a tag, a release and a branch of no pull request; a run
# file that does not accept them stops in the plan, one that does replays.
git clone -q --mirror "$T/source.git" "$T/source-extra.git"
git --git-dir="$T/source-extra.git" tag v0.1 "$M2"
git --git-dir="$T/source-extra.git" update-ref refs/heads/wip/idea "$C5"
replay_setup "$T/rl"
echo '[{"id": 1, "tag_name": "v0.1", "name": "First", "draft": false, "prerelease": false}]' >"$T/rl-api/repos_ada-example_tool_releases-1.json"
run_file "$T/runs-l/stop.run.json" "$T/backup-rl" "clone_url=\"$T/source-extra.git\""
one "$T/rl" ada-example/tool-replay-20261116 "$T/runs-l/stop.run.json" >"$T/rl-stop-out" 2>&1
status_rl_stop=$?
check "replay.py stops in the plan, before any write, where the plan leaves behind what leave_behind does not accept" \
  '[ "$status_rl_stop" = 1 ] && grep -q "^plan-replay.py: the replay leaves behind 3 of the source'"'"'s tags, releases and branches that --leave-behind does not accept (leave_behind, in a run file of replay.py)" "$T/rl-stop-out" && grep -qx "replay.py: plan-replay.py stopped; its message stands above" "$T/rl-stop-out" && grep -q "^replay.py: stopped in step 2 of 8, plan, before any write to GitHub in this run" "$T/rl-stop-out" && ! writes "$T/rl" && [ -e "$T/rl/absent" ] || { cat "$T/rl-stop-out"; exit 1; }'
run_file "$T/runs-l/tool.run.json" "$T/backup-rl-2" "clone_url=\"$T/source-extra.git\"" 'leave_behind=["tag v0.1", "release v0.1", "branch wip/idea"]'
one "$T/rl" ada-example/tool-replay-20261116 "$T/runs-l/tool.run.json" >"$T/rl-out" 2>&1
status_rl=$?
check "replay.py passes leave_behind to the plan, and names in its last step what only the archive keeps" \
  '[ "$status_rl" = 0 ] && grep -qx "No differences" "$T/rl-out" && grep -Fqx "  tag v0.1 of the source is left behind, as planned" "$T/rl-out" && grep -Fqx "   note: only the archive keeps what the plan left behind: branch wip/idea, tag v0.1, release v0.1" "$T/rl-out" && [ "$(grep -e "^2\. Archive" -e "note: only the archive" -e "^gh api -X PATCH repos/ada-example/tool -f name=tool-archive$" "$T/rl-out" | cut -c1-12 | tr "\n" "|")" = "2. Archive t|   note: onl|gh api -X PA|" ] || { cat "$T/rl-out"; exit 1; }'

printf '\n%s passed, %s failed\n' "$passed" "$failed"
[ "$failed" = 0 ]
