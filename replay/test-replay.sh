#!/bin/sh
# Tests the replay scripts of this folder against a source built in a
# temporary folder: a mirror with pull request refs, made by backup-mirror.sh,
# and a fake gh that answers the GitHub API from JSON files the test writes.
#
#   sh ~/vc/github-rewriter/replay/test-replay.sh
#
# Needs Python 3.10 or later. The source is built once, at the top, and each
# script's checks follow in a section of their own. The folder is deleted at
# the end; KEEP=1 keeps it. Your own ~/.gitconfig is not read, and GitHub is
# never contacted: the fake gh comes first on PATH, and it refuses, and the
# test fails on, every request but a GET.
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

# expect <condition>: a Python condition on the plan in $plan_file, with H its header, E
# its events, the source's hashes in S, of(kind[, number]) the events of a
# kind, commit(sha) a planned commit and title(sha) its first line. When it
# is false, it prints each false part of an "and", with the values compared.
plan_file=$T/events.jsonl
expect() {
  python3 - "$plan_file" "$1" <<'EOF'
import ast, json, os, sys
with open(sys.argv[1], encoding="utf-8") as f:
    H, *E = [json.loads(line) for line in f]
S = os.environ
def of(kind, number=None):
    return [e for e in E if e["kind"] == kind and number in (None, e.get("number"))]
def commit(sha):
    return next(c for e in E for c in e.get("commits", []) if c["sha"] == sha)
def title(sha):
    return commit(sha)["message"].partition("\n")[0]
source = sys.argv[2]
tree = ast.parse(source, mode="eval").body
parts = tree.values if isinstance(tree, ast.BoolOp) and isinstance(tree.op, ast.And) else [tree]
def value(node):
    return eval(compile(ast.Expression(node), "<check>", "eval"), globals())
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

printf '\n%s passed, %s failed\n' "$passed" "$failed"
[ "$failed" = 0 ]
