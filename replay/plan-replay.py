#!/usr/bin/env python3
"""Plans the replay of a GitHub repository into an empty one: reads the
commits from a mirror and the issues, pull requests, comments and labels from
GitHub, and writes the ordered events that run-replay.py applies.

  plan-replay.py [--types <file>] [--no-types] [--keep-merges]
                 [--leave-behind <file>]
                 <mirror> <owner/repo> <mailmap> <event file>

<mirror> is a bare clone with refs/pull/*/head, as backup-mirror.sh makes.
<mailmap> maps the author and committer of every commit, in git's mailmap
format. <event file> must not exist yet; it gets JSON Lines: a header that
lists every source commit the replay recreates and what it leaves behind,
then one event per line, in the order run-replay.py applies them. Reads
GitHub through gh api with GET requests only. Prints every title it
changed, every squash message it wrote, what it leaves behind, and the
totals.

The replay carries no tag and no release, and no branch other than the
default branch and those it pushes for pull requests at their source tips.
The plan stops, and writes no event file, unless the <file> of
--leave-behind accepts each of them with a line of its kind and name:
  tag      v1.0
  release  v1.0
  branch   wip/idea  # a "#" after the name starts a comment

Each commit title and pull request title without a type gets one: from
--types, else from the prefix of the pull request's branch, else guessed
from the changed files; --no-types keeps every title as it is. A pull
request merged with a merge commit is squash-merged, with its title, a
summary of its description and its URL as the message; --keep-merges
merges it with its merge commit's message instead. The <file> of --types
holds one line per pull request number or commit hash of at least 7
characters, with a type; or a pull request number, "summary" and the
summary that replaces the one taken from the description:
  12       fix
  3f2a9c1  docs
  10       summary Signs commits and tags with the SSH key.
"""

import heapq
import json
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

PROG = "plan-replay.py"
FORMAT = 1
TYPES = ("feat", "fix", "docs", "chore", "refactor", "test", "build", "ci", "revert")
# Branch prefixes that are no type of GW-6 but name one.
BRANCH_ALIASES = {"feature": "feat", "bugfix": "fix", "hotfix": "fix", "doc": "docs"}
# At the same time, an event of a lower rank comes first: a branch is pushed
# before its pull request is created, and an item exists before it is closed.
RANK = {
    "create-label": 0,
    "push-commits": 1,
    "push-branch": 2,
    "create-issue": 3,
    "create-pull": 3,
    "add-comment": 4,
    "merge-pull": 5,
    "close-item": 6,
}
TYPED = re.compile(r"(?P<type>[A-Za-z]+)(?:\([^)]*\))?!?: ")
ORDINARY_WORD = re.compile(r"[A-Z][a-z]+")
TEST_NAME = re.compile(r"(^tests?[-_.]|[-_.]tests?\.[^.]+$|_spec\.[^.]+$)")
# A paragraph of closing keywords alone, such as "Closes #5" or "Fixes o/r#7 (Title)".
CLOSING = re.compile(
    r"((close[sd]?|fix(e[sd])?|resolve[sd]?):?\s+([\w.-]+/[\w.-]+)?#\d+(\s*\([^)]*\))?[\s,.;]*)+",
    re.IGNORECASE,
)
SENTENCE_END = re.compile(r"[.!?](?=\s)")
# A summary longer than this many characters is cut to its first sentence.
SUMMARY_LENGTH = 300
# Dates are read raw: git 2.45 changed how %aI writes UTC, "Z" for "+00:00".
COMMIT_FORMAT = "%H%x1f%T%x1f%aN%x1f%aE%x1f%ad%x1f%cN%x1f%cE%x1f%cd%x1f%B"


def die(message):
    print(f"{PROG}: {message}", file=sys.stderr)
    sys.exit(1)


def warn(message):
    print(f"{PROG}: warning: {message}", file=sys.stderr)


def usage(status=2):
    print(__doc__.strip("\n"), file=sys.stderr if status else sys.stdout)
    sys.exit(status)


def run(args, stdin=None):
    try:
        result = subprocess.run(
            args, input=stdin, capture_output=True, text=True, encoding="utf-8", errors="replace"
        )
    except FileNotFoundError:
        die(f"{args[0]} is missing")
    if result.returncode:
        die(f"{' '.join(args[:4])} … failed: {result.stderr.strip()}")
    return result.stdout


def gh_get(endpoint):
    return json.loads(run(["gh", "api", endpoint]))


def gh_pages(endpoint):
    """All pages of a list endpoint, read up to the first empty page, since
    --paginate fails through some proxies."""
    joiner = "&" if "?" in endpoint else "?"
    entries, page = [], 1
    while True:
        batch = gh_get(f"{endpoint}{joiner}per_page=100&page={page}")
        if not batch:
            return entries
        entries.extend(batch)
        page += 1


def iso_date(raw):
    """A raw git date, seconds and offset, as ISO 8601 with that offset."""
    seconds, offset = raw.split()
    sign = -1 if offset.startswith("-") else 1
    zone = timezone(sign * timedelta(hours=int(offset[1:3]), minutes=int(offset[3:5])))
    return datetime.fromtimestamp(int(seconds), zone).isoformat()


def utc(stamp):
    """An ISO 8601 time in UTC, in the form GitHub gives, so times compare as text."""
    if stamp is None:
        return None
    time = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    return time.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class Mirror:
    def __init__(self, path, mailmap):
        self.path = path
        # An empty mailmap.blob keeps a bare mirror from also applying the
        # .mailmap committed at its HEAD.
        self.config = ["-c", f"mailmap.file={mailmap}", "-c", "mailmap.blob="]

    def git(self, *args, stdin=None):
        return run(["git", "-C", str(self.path), *self.config, *args], stdin)

    def lines(self, *args):
        return self.git(*args).split()

    def has(self, rev):
        found = subprocess.run(
            ["git", "-C", str(self.path), "rev-parse", "-q", "--verify", f"{rev}^{{commit}}"],
            capture_output=True,
            text=True,
        )
        return found.stdout.strip() if found.returncode == 0 else None

    def parents(self):
        """The parents of every commit the mirror holds, refs/pull/* included."""
        parents = {}
        for line in self.git("rev-list", "--parents", "--all").splitlines():
            sha, *rest = line.split()
            parents[sha] = rest
        return parents

    def details(self, shas):
        """Tree, mapped identities, dates and message of each commit."""
        out = self.git(
            "log",
            "--no-walk=unsorted",
            "--stdin",
            "-z",
            "--date=raw",
            f"--format={COMMIT_FORMAT}",
            stdin="\n".join(shas) + "\n",
        )
        details = {}
        for record in out.split("\0"):
            if not record:
                continue
            sha, tree, an, ae, ad, cn, ce, cd, message = record.split("\x1f", 8)
            details[sha] = {
                "tree": tree,
                "author": {"name": an, "email": ae, "date": iso_date(ad)},
                "committer": {"name": cn, "email": ce, "date": iso_date(cd)},
                "message": message,
            }
        return details

    def changed_files(self, sha, parents):
        if parents:
            return self.lines("diff", "--name-only", parents[0], sha)
        return self.lines("diff-tree", "-r", "--root", "--no-commit-id", "--name-only", sha)

    def diff_files(self, base, head):
        return self.lines("diff", "--name-only", base, head)

    def refs(self, prefix):
        """The refs under prefix by their short names, each with the object
        it names and, for an annotated tag, the object the tag points to."""
        found = {}
        for line in self.git(
            "for-each-ref", "--format=%(refname)%09%(objectname)%09%(*objectname)", prefix
        ).splitlines():
            name, sha, peeled = line.split("\t")
            found[name[len(prefix) :]] = {"sha": sha, "peeled": peeled or None}
        return found


class Overrides:
    """The types --types sets, by pull request number and by commit hash
    prefix, and the summaries it sets by pull request number."""

    def __init__(self, path):
        self.numbers, self.hashes, self.summaries, self.used = {}, {}, {}, set()
        if path is None:
            return
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as error:
            die(f"cannot read {path}: {error.strerror}")
        for count, line in enumerate(text.splitlines(), 1):
            fields = line.split(None, 2)
            if not fields or fields[0].startswith("#"):
                continue
            key = fields[0]
            is_number = key.isdigit() and len(key) < 7
            if len(fields) == 3 and fields[1] == "summary":
                if not is_number:
                    die(f"{path}:{count}: a summary needs a pull request number, not {key}")
                self.summaries[int(key)] = fields[2].strip()
                continue
            if len(fields) != 2 or fields[1] not in TYPES:
                die(
                    f"{path}:{count}: expected a number or hash and one of {', '.join(TYPES)},"
                    " or a number, summary and the summary"
                )
            if is_number:
                self.numbers[int(key)] = fields[1]
            elif re.fullmatch(r"[0-9a-fA-F]{7,40}", key):
                self.hashes[key.lower()] = fields[1]
            else:
                die(f"{path}:{count}: {key} is neither a number nor a hash of 7 or more characters")

    def number(self, n):
        if n in self.numbers:
            self.used.add(("type", n))
            return self.numbers[n]
        return None

    def commit(self, sha):
        for key, kind in self.hashes.items():
            if sha.startswith(key):
                self.used.add(("type", key))
                return kind
        return None

    def summary(self, n):
        if n in self.summaries:
            self.used.add(("summary", n))
            return self.summaries[n]
        return None

    def unused(self, typed=True):
        """What the file sets and the replay has no use for, in words; without
        typing, type lines are ignored by choice, not for want of a title."""
        return [
            *(
                f"a type for {k}, which the replay has no title for"
                for k in [*self.numbers, *self.hashes]
                if typed and ("type", k) not in self.used
            ),
            *(
                f"a summary for #{n}, which the replay writes no squash message for"
                for n in self.summaries
                if ("summary", n) not in self.used
            ),
        ]


class LeaveBehind:
    """The tags, releases and branches --leave-behind accepts the replay
    leaves behind, as (kind, name)."""

    KINDS = ("tag", "release", "branch")

    def __init__(self, path):
        self.path, self.accepted = path, set()
        if path is None:
            return
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as error:
            die(f"cannot read {path}: {error.strerror}")
        for count, line in enumerate(text.splitlines(), 1):
            fields = line.split()
            if not fields or fields[0].startswith("#"):
                continue
            # A name holds no blank, so a "#" after one starts a comment, as in
            # the lines the plan prints where it stops.
            if len(fields) > 2 and fields[2].startswith("#"):
                fields = fields[:2]
            if len(fields) != 2 or fields[0] not in self.KINDS:
                die(f"{path}:{count}: expected one of {', '.join(self.KINDS)} and a name")
            self.accepted.add((fields[0], fields[1]))

    def check(self, left):
        """Stops at what the replay leaves behind and the file does not
        accept; warns of what the file accepts and the replay carries or
        the source lacks."""
        found = {(x["kind"], x["name"]) for x in left}
        for kind, name in sorted(self.accepted - found):
            warn(f"{self.path} accepts {kind} {name}, which the replay does not leave behind")
        missing = [x for x in left if (x["kind"], x["name"]) not in self.accepted]
        if missing:
            width = max(len(x["name"]) for x in missing)
            lines = "\n".join(
                f"  {x['kind']:<8} {x['name']:<{width}}  # {x['reason']}" for x in missing
            )
            die(
                f"the replay leaves behind {len(missing)} of the source's tags, releases and"
                " branches that --leave-behind does not accept (leave_behind, in a run file of"
                " replay.py). Accept each with its line, so that only the archive of the source"
                f" keeps it:\n{lines}"
            )


def left_behind(mirror, info, releases, events):
    """The tags, releases and branches of the source that the replay does not
    carry, each with its kind, name, the commit it names and why."""
    default = info["default_branch"]
    deletes = bool(info.get("delete_branch_on_merge"))
    merged = {e["number"] for e in events if e["kind"] == "merge-pull"}
    pushed = {}
    for e in events:
        if e["kind"] == "push-branch":
            head = e["commits"][-1]["sha"] if e["commits"] else e["base_commit"]
            pushed[e["branch"]] = (e["number"], head)
    left = []
    for name, ref in sorted(mirror.refs("refs/heads/").items()):
        tip = ref["sha"]
        if name == default:
            continue
        if name not in pushed:
            reason = f"at {tip[:7]}, the head of no pull request"
        elif pushed[name][1] != tip:
            n, head = pushed[name]
            reason = f"at {tip[:7]}; the replay pushes the head of #{n}, {head[:7]}, under its name"
        elif deletes and pushed[name][0] in merged:
            reason = (
                f"the head of #{pushed[name][0]}, which the replay deletes on its merge, as the"
                " source deletes head branches"
            )
        else:
            continue
        left.append({"kind": "branch", "name": name, "sha": tip, "reason": reason})
    for name, ref in sorted(mirror.refs("refs/tags/").items()):
        sha = ref["peeled"] or ref["sha"]
        kind = "annotated" if ref["peeled"] else "lightweight"
        reason = f"{kind}, at {sha[:7]}; the replay pushes no tags"
        left.append({"kind": "tag", "name": name, "sha": sha, "reason": reason})
    for r in sorted(releases, key=lambda r: r["tag_name"]):
        what = "draft" if r.get("draft") else "pre-release" if r.get("prerelease") else "published"
        reason = f"{what}, named {r.get('name') or r['tag_name']!r}; the replay creates no releases"
        left.append({"kind": "release", "name": r["tag_name"], "sha": None, "reason": reason})
    return left


def branch_type(ref):
    prefix = ref.split("/", 1)[0] if "/" in ref else ""
    return prefix if prefix in TYPES else BRANCH_ALIASES.get(prefix)


def is_test_file(path):
    parts = path.split("/")
    if parts[0] == ".github":
        return False
    return any(p in ("test", "tests", "spec") for p in parts[:-1]) or bool(
        TEST_NAME.search(parts[-1])
    )


def guess_type(files):
    if files and all(f.lower().endswith(".md") for f in files):
        return "docs"
    if files and all(f.startswith(".github/workflows/") for f in files):
        return "ci"
    if files and all(is_test_file(f) for f in files):
        return "test"
    return "feat"


def present_type(title):
    match = TYPED.match(title)
    return match if match and match["type"].lower() in TYPES else None


def typed_title(title, resolve):
    """The title in the form <type>: <summary>, and the type with where it
    came from. resolve() gives the type for a title without one."""
    match = present_type(title)
    if match:
        kind, source = match["type"].lower(), "present"
        head = kind + title[len(match["type"]) : match.end()]
        summary = title[match.end() :]
    else:
        kind, source = resolve()
        head, summary = f"{kind}: ", title
    if ORDINARY_WORD.fullmatch(summary.split(" ", 1)[0]):
        summary = summary[0].lower() + summary[1:]
    return head + summary, kind, source


def split_message(message):
    title, _, rest = message.partition("\n")
    return title, ("\n" + rest if rest or message.endswith("\n") else "")


def summary(body):
    """A short summary of a description, for GW-40: its first paragraph that
    is not a heading, an HTML block, a horizontal rule, closing keywords
    alone or a lead-in that ends in a colon; cut to its first sentence where
    it is longer than SUMMARY_LENGTH characters."""
    for paragraph in re.split(r"\n\s*\n", (body or "").replace("\r\n", "\n")):
        text = paragraph.strip()
        if (
            not text
            or text.startswith(("#", "<", "---", "***"))
            or text.endswith(":")
            or CLOSING.fullmatch(text)
        ):
            continue
        end = SENTENCE_END.search(text)
        if len(text) > SUMMARY_LENGTH and end:
            text = text[: end.start() + 1]
        return text
    return ""


def order(events):
    """The events in time order, each after the events it depends on; among
    those ready, the earliest first."""
    by_key = {e["key"]: e for e in events}
    waiting = {e["key"]: 0 for e in events}
    followers = {e["key"]: [] for e in events}
    for e in events:
        for dep in set(e["deps"]):
            if dep not in by_key:
                die(f"internal error: {e['key']} depends on missing {dep}")
            waiting[e["key"]] += 1
            followers[dep].append(e["key"])

    def entry(e):
        return (e["time"] or "", RANK[e["kind"]], e.get("number", 0), e["index"], e["key"])

    ready = [entry(e) for e in events if waiting[e["key"]] == 0]
    heapq.heapify(ready)
    ordered = []
    while ready:
        *_, key = heapq.heappop(ready)
        ordered.append(by_key[key])
        for follower in followers[key]:
            waiting[follower] -= 1
            if waiting[follower] == 0:
                heapq.heappush(ready, entry(by_key[follower]))
    if len(ordered) != len(events):
        stuck = sorted({e["number"] for e in events if waiting[e["key"]] and "number" in e})
        die(
            "the events cannot keep both the number order and the order of the default branch;"
            f" a pull request's branch probably starts on a commit that a later item brought."
            f" Items involved: {', '.join(f'#{n}' for n in stuck[:10])}"
        )
    return ordered


def join_direct_pushes(events):
    """Direct commits that follow each other without another event between
    them become one push."""
    joined = []
    for e in events:
        if e["kind"] == "push-commits" and joined and joined[-1]["kind"] == "push-commits":
            joined[-1]["commits"].extend(e["commits"])
            joined[-1]["time"] = e["time"]
        else:
            joined.append(e)
    return joined


def plan(mirror, repo, overrides, typed=True, keep_merges=False):
    info = gh_get(f"repos/{repo}")
    default = info["default_branch"]
    labels = gh_pages(f"repos/{repo}/labels")
    items = {i["number"]: i for i in gh_pages(f"repos/{repo}/issues?state=all")}
    pulls = {p["number"]: p for p in gh_pages(f"repos/{repo}/pulls?state=all")}
    comments = gh_pages(f"repos/{repo}/issues/comments")

    if not mirror.has(f"refs/heads/{default}"):
        die(f"the mirror has no branch {default}, the default branch of {repo}")
    parents = mirror.parents()
    main = mirror.lines("rev-list", "--first-parent", "--reverse", f"refs/heads/{default}")
    main_index = {sha: i for i, sha in enumerate(main)}

    for n, item in items.items():
        if "pull_request" in item and n not in pulls:
            die(f"#{n} is a pull request, but the pulls endpoint does not list it")

    merge_of = {}
    for n, p in sorted(pulls.items()):
        if not p.get("merged_at"):
            continue
        sha = p["merge_commit_sha"]
        if p["base"]["ref"] != default or sha not in main_index:
            die(f"pull request #{n} was merged into {p['base']['ref']}, not into {default}")
        merge_of[sha] = n

    # Each pull request's branch: its first-parent chain from the head back to
    # the default branch or to a commit an earlier pull request's branch holds.
    owner, branches = {}, {}
    for n, p in sorted(pulls.items()):
        head = (
            p["head"]["sha"] if p["head"]["sha"] in parents else mirror.has(f"refs/pull/{n}/head")
        )
        if not head:
            die(
                f"the head of pull request #{n} is not in the mirror; make it with backup-mirror.sh"
            )
        chain, sha = [], head
        while sha not in main_index and sha not in owner:
            chain.append(sha)
            if not parents[sha]:
                die(f"pull request #{n} has a root commit {sha[:7]} outside {default}")
            sha = parents[sha][0]
        for c in chain:
            owner[c] = n
        branches[n] = {"base": sha, "head": head, "chain": chain[::-1]}
        if not chain:
            warn(f"pull request #{n} has no commits of its own; GitHub refuses such a pull request")

    details = mirror.details(main + [c for b in branches.values() for c in b["chain"]])

    def retitle(title, resolve):
        return typed_title(title, resolve) if typed else (title, None, None)

    pull_types = {}

    def pull_type(n):
        if n not in pull_types:
            kind, source = overrides.number(n), "override"
            if not kind:
                kind, source = branch_type(pulls[n]["head"]["ref"]), "branch"
            if not kind and present_type(items[n]["title"]):
                kind, source = present_type(items[n]["title"])["type"].lower(), "present"
            if not kind:
                b = branches[n]
                kind, source = guess_type(mirror.diff_files(b["base"], b["head"])), "guess"
            pull_types[n] = (kind, source)
        return pull_types[n]

    def commit(sha, kept_parents, resolve):
        d = details[sha]
        title, rest = split_message(d["message"])
        new_title, kind, source = retitle(title, resolve)
        return {
            "sha": sha,
            "tree": d["tree"],
            "parents": kept_parents,
            "message": new_title + rest,
            "original_title": title,
            "type": kind,
            "type_from": source,
            "author": d["author"],
            "committer": d["committer"],
        }

    def producer(sha):
        return ("main", main_index[sha]) if sha in main_index else ("branch", owner[sha])

    events = []

    def add(key, kind, time, deps, **fields):
        events.append(
            {"key": key, "index": len(events), "deps": deps, "kind": kind, "time": time, **fields}
        )

    for label in sorted(labels, key=lambda x: x["name"]):
        add(
            ("label", label["name"]),
            "create-label",
            None,
            [],
            name=label["name"],
            color=label.get("color"),
            description=label.get("description"),
        )

    for i, sha in enumerate(main):
        deps = [("main", i - 1)] if i else []
        n = merge_of.get(sha)
        if n is None:
            if len(parents[sha]) > 1:
                warn(
                    f"{sha[:7]} on {default} merges without a pull request; replayed as one commit"
                )

            def resolve(sha=sha):
                kind = overrides.commit(sha)
                if kind:
                    return kind, "override"
                return guess_type(mirror.changed_files(sha, parents[sha])), "guess"

            c = commit(sha, parents[sha][:1], resolve)
            add(
                ("main", i),
                "push-commits",
                utc(c["committer"]["date"]),
                deps,
                branch=default,
                commits=[c],
            )
            continue
        deps.append(("create", n))
        d = details[sha]
        title, rest = split_message(d["message"])
        source_method = "merge" if len(parents[sha]) > 1 else "squash"
        method = "merge" if keep_merges and source_method == "merge" else "squash"

        def resolve_merge(sha=sha, n=n):
            kind = overrides.commit(sha)
            return (kind, "override") if kind else pull_type(n)

        if source_method == "merge" and pulls[n]["head"]["sha"] not in parents[sha][1:]:
            warn(f"the merge commit of #{n} does not merge its head; its tree is the merge's")
        if method == "merge":
            commit_title, kind, source = title, None, None
            commit_message = rest.strip("\n")
        elif source_method == "squash":
            commit_title, kind, source = retitle(title, resolve_merge)
            commit_message = rest.strip("\n")
        else:
            pull_title, kind, source = retitle(items[n]["title"], resolve_merge)
            commit_title = f"{pull_title} (#{n})"
            text = overrides.summary(n) or summary(items[n].get("body"))
            commit_message = f"{text}\n\n{{pr_url}}" if text else "{pr_url}"
        add(
            ("main", i),
            "merge-pull",
            utc(pulls[n]["merged_at"]),
            deps,
            number=n,
            method=method,
            source_method=source_method,
            source_commit=sha,
            tree=d["tree"],
            original_title=title,
            commit_title=commit_title,
            commit_message=commit_message,
            type=kind,
            type_from=source,
        )

    names, branch_names = {default}, {}
    for n, b in sorted(branches.items()):
        chain = set(b["chain"])
        outside = {p for c in b["chain"] for p in parents[c] if p not in chain}
        unknown = sorted(p for p in outside if p not in main_index and p not in owner)
        if unknown:
            die(
                f"the branch of pull request #{n} merges {unknown[0][:7]}, which is neither on"
                f" the first-parent line of {default} nor on the branch of a pull request"
            )
        deps = sorted({producer(p) for p in outside | {b["base"]}})

        def resolve_branch(sha, n=n):
            kind = overrides.commit(sha)
            return (kind, "override") if kind else pull_type(n)

        commits = [commit(c, parents[c], lambda c=c: resolve_branch(c)) for c in b["chain"]]
        ref = pulls[n]["head"]["ref"]
        name = ref if ref not in names else f"{ref}-{n}"
        names.add(name)
        branch_names[n] = name
        add(
            ("branch", n),
            "push-branch",
            utc(pulls[n]["created_at"]),
            deps,
            number=n,
            branch=name,
            source_branch=ref,
            base_commit=b["base"],
            commits=commits,
        )

    last = max(items, default=0)
    for n in range(1, last + 1):
        deps = [("create", n - 1)] if n > 1 else []
        item = items.get(n)
        if item is None:
            time = utc(items[min(k for k in items if k > n)]["created_at"])
            warn(f"#{n} is missing in the source; a closed placeholder issue keeps its number")
            add(
                ("create", n),
                "create-issue",
                time,
                deps,
                number=n,
                placeholder=True,
                title=f"Placeholder for #{n}, which the source no longer has",
                body="",
                labels=[],
                assignees=[],
                state="closed",
                state_reason="not_planned",
                author=None,
                created_at=None,
            )
            add(
                ("close", n),
                "close-item",
                time,
                [("create", n)],
                number=n,
                state_reason="not_planned",
            )
            continue
        common = {
            "number": n,
            "body": item.get("body") or "",
            "labels": [x["name"] for x in item.get("labels", [])],
            "assignees": [x["login"] for x in item.get("assignees", [])],
            "author": (item.get("user") or {}).get("login"),
            "created_at": item["created_at"],
        }
        time = utc(item["created_at"])
        if n in pulls:
            title, kind, source = retitle(item["title"], lambda n=n: pull_type(n))
            p = pulls[n]
            state = "merged" if p.get("merged_at") else item["state"]
            if p["base"]["ref"] != default:
                warn(f"#{n} targets {p['base']['ref']}, a branch the replay does not create")
            add(
                ("create", n),
                "create-pull",
                time,
                [*deps, ("branch", n)],
                title=title,
                original_title=item["title"],
                type=kind,
                type_from=source,
                head=branch_names[n],
                base=p["base"]["ref"],
                draft=bool(p.get("draft")),
                state=state,
                **common,
            )
        else:
            state = item["state"]
            add(
                ("create", n),
                "create-issue",
                time,
                deps,
                title=item["title"],
                state=state,
                state_reason=item.get("state_reason"),
                **common,
            )
        if state == "closed":
            add(
                ("close", n),
                "close-item",
                utc(item["closed_at"]),
                [("create", n)],
                number=n,
                state_reason=item.get("state_reason"),
            )

    for c in comments:
        n = int(c["issue_url"].rsplit("/", 1)[1])
        if n not in items:
            warn(f"comment {c['id']} belongs to #{n}, which the source does not list; left out")
            continue
        add(
            ("comment", c["id"]),
            "add-comment",
            utc(c["created_at"]),
            [("create", n)],
            number=n,
            body=c.get("body") or "",
            author=(c.get("user") or {}).get("login"),
            created_at=c["created_at"],
            source_id=c["id"],
        )

    left = left_behind(mirror, info, gh_pages(f"repos/{repo}/releases"), events)
    return default, events, left


def review(events):
    """The changed titles, as (reference, old, new, guessed), in event order."""
    rows = []
    for e in events:
        guessed = e.get("type_from") == "guess"
        if e["kind"] == "create-pull":
            rows.append((f"#{e['number']}", e["original_title"], e["title"], guessed))
        elif e["kind"] == "merge-pull":
            rows.append((e["source_commit"][:7], e["original_title"], e["commit_title"], guessed))
        for c in e.get("commits", []):
            title = c["message"].partition("\n")[0]
            rows.append((c["sha"][:7], c["original_title"], title, c["type_from"] == "guess"))
    return [r for r in rows if r[1] != r[2]]


def written_messages(events):
    """The squash messages written for pull requests merged with a merge
    commit, as (reference, first line, body)."""
    return [
        (f"#{e['number']}", e["commit_title"], e["commit_message"])
        for e in events
        if e["kind"] == "merge-pull" and e["method"] == "squash" and e["source_method"] == "merge"
    ]


def main(argv):
    if argv[:1] in (["-h"], ["--help"]):
        usage(0)
    types, typed, keep_merges, leave = None, True, False, None
    while argv[:1] and argv[0].startswith("--"):
        option, argv = argv[0], argv[1:]
        if option == "--types" and argv:
            types, argv = Path(argv[0]), argv[1:]
        elif option == "--no-types":
            typed = False
        elif option == "--keep-merges":
            keep_merges = True
        elif option == "--leave-behind" and argv:
            leave, argv = Path(argv[0]), argv[1:]
        else:
            usage()
    if len(argv) != 4 or argv[0].startswith("-"):
        usage()
    mirror_path, repo, mailmap, output = Path(argv[0]), argv[1], Path(argv[2]), Path(argv[3])
    if not re.fullmatch(r"[\w.-]+/[\w.-]+", repo):
        usage()
    if not mirror_path.is_dir():
        die(f"no mirror at {mirror_path}")
    if not mailmap.is_file():
        die(f"no mailmap at {mailmap}")
    if output.exists():
        die(f"{output} exists already; remove it to plan again")
    if not output.parent.is_dir():
        die(f"no folder {output.parent} for the event file")
    overrides = Overrides(types)
    accepted = LeaveBehind(leave)

    mirror = Mirror(mirror_path, mailmap.resolve())
    default, events, left = plan(mirror, repo, overrides, typed, keep_merges)
    accepted.check(left)
    events = join_direct_pushes(order(events))
    for unused in overrides.unused(typed):
        warn(f"{types} sets {unused}")

    source_commits, latest, late = [], "", 0
    for seq, e in enumerate(events, 1):
        source_commits.extend(c["sha"] for c in e.get("commits", []))
        if e["kind"] == "merge-pull":
            source_commits.append(e["source_commit"])
        if e["time"]:
            late += e["time"] < latest
            latest = max(latest, e["time"])
        for internal in ("key", "index", "deps"):
            del e[internal]
        events[seq - 1] = {"seq": seq, **e}
    header = {
        "kind": "header",
        "format": FORMAT,
        "source": repo,
        "default_branch": default,
        "source_commits": source_commits,
        "left_behind": left,
    }
    partial = output.with_name(output.name + ".partial")
    with partial.open("w", encoding="utf-8") as file:
        for line in [header, *events]:
            file.write(json.dumps(line, ensure_ascii=False) + "\n")
    partial.replace(output)

    rows = review(events)
    print(f"Changed titles: {len(rows)}")
    width = max((len(r[0]) for r in rows), default=0)
    for ref, old, new, guessed in rows:
        print(f"  {ref:<{width}}  {'guessed' if guessed else '       '}  {old}  ->  {new}")
    messages = written_messages(events)
    print(f"Squash messages written for merge commits: {len(messages)}")
    for ref, first, body in messages:
        print(f"  {ref}  {first}")
        for line in body.split("\n"):
            print(f"      {line}" if line else "")

    print(f"Left behind: {len(left)}")
    width = max((len(x["name"]) for x in left), default=0)
    for x in left:
        print(f"  {x['kind']:<8} {x['name']:<{width}}  {x['reason']}")

    def count(*kinds):
        return sum(e["kind"] in kinds for e in events)

    def merges(method):
        return sum(e["kind"] == "merge-pull" and e["method"] == method for e in events)

    pushed = sum(len(e.get("commits", [])) for e in events)
    totals = [
        ("items", count("create-issue", "create-pull")),
        ("issues", count("create-issue")),
        ("pull requests", count("create-pull")),
        ("comments", count("add-comment")),
        ("labels", count("create-label")),
        ("commits", pushed),
        ("squash merges", merges("squash")),
        ("merge commits", merges("merge")),
        ("events", len(events)),
        ("guessed types", sum(r[3] for r in rows)),
        ("events out of time order", late),
        ("left behind", len(left)),
    ]
    print("Totals:")
    for name, value in totals:
        print(f"  {name:<25}{value:>6}")
    # As given, as the shell scripts print paths; Path drops a "//" in it.
    print(argv[3])


if __name__ == "__main__":
    main(sys.argv[1:])
