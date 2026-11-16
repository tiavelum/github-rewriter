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

# The fake gh of the targets: "gh api --include --method M <endpoint>
# [--input -]" against the target named in $FAKE_GITHUB/name, whose items,
# comments and labels it keeps in JSON files in $FAKE_GITHUB and whose git
# repository is the bare $FAKE_GITHUB/repo.git. It numbers issues and pull
# requests in one sequence, merges as GitHub does, with GitHub as committer
# and fixed dates, and closes the issues a merged pull request names with a
# closing keyword. It logs every call, with its time, in $FAKE_GITHUB/calls
# and every closing in closes.json. It answers a GET of another repository
# from the files in $FAKE_GH_API, as the fake gh of the source does, and a
# call without --include with the body alone, as gh does. Each FAKE_GH_* variable names a call
# "<method> <endpoint>" and acts on its first occurrence: RATE_LIMIT answers
# 403 with Retry-After: 1 and does nothing, INTERRUPT sends the caller a
# SIGINT, as a Ctrl-C does, LOSE does the call and answers 502; FAKE_GH_SKIP
# gives its number to an issue someone else creates. It lists the signing keys
# of the account from ssh_signing_keys.json and gpg_keys.json, none where a
# file is missing; with FAKE_GH_NO_SCOPE, it refuses those lists as GitHub
# refuses a token without the scope they need.
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
        return 200, json.loads(page.read_text()) if page.exists() else []
    found = name.with_name(name.name + ".json")
    return (200, json.loads(found.read_text())) if found.exists() else (404, {"message": "Not Found"})


def handle(method, endpoint, body):
    path, _, query = endpoint.partition("?")
    q = {k: v[-1] for k, v in parse_qs(query).items()}
    if method == "GET" and path in ("user/ssh_signing_keys", "user/gpg_keys"):
        per, number = int(q.get("per_page", 30)), int(q.get("page", 1))
        return 200, load(path[len("user/"):], [])[(number - 1) * per:number * per]
    prefix = f"repos/{slug}"
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
    elif route == ("GET", "labels"):
        result = page(labels)
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
elif endpoint.startswith("user/") and os.environ.get("FAKE_GH_NO_SCOPE"):
    status, data = 404, {"message": "Not Found"}
    kind = endpoint.split("?")[0].split("/")[1][:-1]
    headers = [("X-OAuth-Scopes", "repo, read:org"),
               ("X-Accepted-OAuth-Scopes", f"admin:{kind}, read:{kind}, write:{kind}")]
else:
    if once("FAKE_GH_INTERRUPT", call):
        os.kill(os.getppid(), signal.SIGINT)
    status, data = handle(method, endpoint, body)
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
rcheck "run-replay.py pushes commits with the mapped identities, the original dates and the typed messages" "$T/gh-a" "$T/a.state.json" \
  'git("log", "-1", "--format=%an|%ae|%ad|%cn|%ce|%cd|%s", "--date=raw", M[S["C3"]]) == "Ada Example|ada@example.com|1772712000 +0200|Ada Example|ada@example.com|1772712000 +0200|test: update the tests" and git("log", "-1", "--format=%an|%ae|%cn|%ce|%s", M[S["F1"]]) == "Bob Example|bob@example.com|Bob Example|bob@example.com|fix: repair the parser" and git("rev-parse", "fix/3-parser") == M[S["F1"]] and git("rev-parse", "docs/5-notes^2") == M[S["C5"]] and git("log", "-1", "--format=%B", M[S["C4"]]) == "chore: tidy the scripts\n\nNo change in behaviour."'
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
  '[ "$status_again$status_other" = 01 ] && grep -q "^All 23 events of the replay .* are done" "$T/again-out" && grep -q "ada-example/tool-new is not empty: it has 5 refs and items up to #6" "$T/other-out" && [ "$(writes "$T/gh-a" | wc -l)" -eq "$writes_a" ] || { cat "$T/again-out" "$T/other-out"; exit 1; }'

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
  '[ "$status_cmp_a$status_cmp_e" = 00 ] && [ "$(tail -n 1 "$T/cmp-a-out")" = "No differences" ] && grep -qx "No differences" "$T/cmp-e-out" && for t in "items +6" "labels +2" "comments +4" "texts with a replaced hash +1" "commits on main +7" "recreated commits +12" "branches +4"; do grep -Eqx "  $t" "$T/cmp-a-out" || { echo "no line \"$t\""; exit 1; }; done && [ "$(writes "$T/gh-a" | wc -l)" -eq "$writes_before" ] && [ ! -e "$T/gh-a/refused" ] || { cat "$T/cmp-a-out" "$T/cmp-e-out"; exit 1; }'
check "compare-replay.py notes each branch the target keeps and the source no longer has, and who authored the merges" \
  'for b in docs/5-notes feat/2-thing fix/3-parser; do grep -qx "  branch $b stays in the target; the source no longer has it" "$T/cmp-a-out" || exit 1; done && grep -qx "  merges authored by Ada Example <ada@example.com>" "$T/cmp-a-out" || { cat "$T/cmp-a-out"; exit 1; }'

# The copy of A: #4 closed as completed, a footer on the last comment, the
# colour of a label, a missing branch, and a last commit on main with the
# tree of the one before.
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
git --git-dir="$d" update-ref refs/heads/main "$(echo "same tree" | git --git-dir="$d" commit-tree "main~1^{tree}" -p main~1)"
compare "$T/gh-diff" --state "$T/a.state.json" "$T/run.jsonl" "$mirror" ada-example/tool-new >"$T/cmp-diff-out" 2>&1
status_cmp_diff=$?
check "compare-replay.py names every difference it finds and exits with 1" \
  '[ "$status_cmp_diff" = 1 ] && for line in "#4 is closed as completed, the source'"'"'s not_planned" "#6, comment 1: the body differs; it has a footer the source lacks" "label bug: colour ee0701, the source'"'"'s d73a4a" "branch fix/3-parser is missing in the target"; do grep -Fqx "  $line" "$T/cmp-diff-out" || { echo "no line \"$line\""; exit 1; }; done && grep -q "^  main, step 7 ([0-9a-f]\{7\}): tree [0-9a-f]\{7\}, the source'"'"'s [0-9a-f]\{7\}$" "$T/cmp-diff-out" && grep -q "^Differences: [0-9]*$" "$T/cmp-diff-out" || { cat "$T/cmp-diff-out"; exit 1; }'
compare "$T/gh-c" "$T/run.jsonl" "$mirror" ada-example/tool-c >"$T/cmp-c-out" 2>&1
status_cmp_c=$?
check "compare-replay.py refuses a replay that its state file records unfinished" \
  '[ "$status_cmp_c" = 2 ] && grep -q "^compare-replay.py: .*run.state.json records the replay unfinished, at event [0-9]* of 23; finish it with run-replay.py first$" "$T/cmp-c-out" || { cat "$T/cmp-c-out"; exit 1; }'

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

printf '\n%s passed, %s failed\n' "$passed" "$failed"
[ "$failed" = 0 ]
