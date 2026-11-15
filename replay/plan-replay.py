#!/usr/bin/env python3
"""Plans the replay of a GitHub repository into an empty one: reads the
commits from a mirror and the issues, pull requests, comments and labels from
GitHub, and writes the ordered events that run-replay.py applies.

  plan-replay.py [--types <file>] <mirror> <owner/repo> <mailmap> <event file>

<mirror> is a bare clone with refs/pull/*/head, as backup-mirror.sh makes.
<mailmap> maps the author and committer of every commit, in git's mailmap
format. <event file> must not exist yet; it gets JSON Lines: a header that
lists every source commit the replay recreates, then one event per line, in
the order run-replay.py applies them. Reads GitHub through gh api with GET
requests only. Prints every title it changed, and the totals.

Each commit title and pull request title without a type gets one: from
--types, else from the prefix of the pull request's branch, else guessed
from the changed files. The <file> of --types holds one type per line, for
a pull request number or a commit hash of at least 7 characters:
  12       fix
  3f2a9c1  docs
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


class Overrides:
    """The types --types sets, by pull request number and by commit hash prefix."""

    def __init__(self, path):
        self.numbers, self.hashes, self.used = {}, {}, set()
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
            if len(fields) != 2 or fields[1] not in TYPES:
                die(f"{path}:{count}: expected a number or hash and one of {', '.join(TYPES)}")
            key, kind = fields
            if key.isdigit() and len(key) < 7:
                self.numbers[int(key)] = kind
            elif re.fullmatch(r"[0-9a-fA-F]{7,40}", key):
                self.hashes[key.lower()] = kind
            else:
                die(f"{path}:{count}: {key} is neither a number nor a hash of 7 or more characters")

    def number(self, n):
        if n in self.numbers:
            self.used.add(str(n))
            return self.numbers[n]
        return None

    def commit(self, sha):
        for key, kind in self.hashes.items():
            if sha.startswith(key):
                self.used.add(key)
                return kind
        return None

    def unused(self):
        return [k for k in [*map(str, self.numbers), *self.hashes] if k not in self.used]


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


def first_paragraph(body):
    """The first paragraph of a description that is prose, not a heading,
    an HTML block or a horizontal rule."""
    for paragraph in re.split(r"\n\s*\n", (body or "").replace("\r\n", "\n")):
        text = paragraph.strip()
        if text and not text.startswith(("#", "<", "---", "***")):
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


def plan(mirror, repo, overrides):
    default = gh_get(f"repos/{repo}")["default_branch"]
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
        new_title, kind, source = typed_title(title, resolve)
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
        method = "merge" if len(parents[sha]) > 1 else "squash"

        def resolve_merge(sha=sha, n=n):
            kind = overrides.commit(sha)
            return (kind, "override") if kind else pull_type(n)

        if method == "squash":
            commit_title, kind, source = typed_title(title, resolve_merge)
            commit_message = rest.strip("\n")
        else:
            pull_title, kind, source = typed_title(items[n]["title"], resolve_merge)
            commit_title = f"{pull_title} (#{n})"
            summary = first_paragraph(items[n].get("body"))
            commit_message = f"{summary}\n\n{{pr_url}}" if summary else "{pr_url}"
            if pulls[n]["head"]["sha"] not in parents[sha][1:]:
                warn(f"the merge commit of #{n} does not merge its head; its tree is the merge's")
        add(
            ("main", i),
            "merge-pull",
            utc(pulls[n]["merged_at"]),
            deps,
            number=n,
            method="squash",
            source_method=method,
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
            title, kind, source = typed_title(item["title"], lambda n=n: pull_type(n))
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

    return default, events


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


def main(argv):
    if argv[:1] in (["-h"], ["--help"]):
        usage(0)
    types = None
    if argv[:1] == ["--types"] and len(argv) >= 2:
        types, argv = Path(argv[1]), argv[2:]
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
    overrides = Overrides(types)

    default, events = plan(Mirror(mirror_path, mailmap.resolve()), repo, overrides)
    events = join_direct_pushes(order(events))
    for unused in overrides.unused():
        warn(f"{types} sets a type for {unused}, which the replay has no title for")

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

    def count(*kinds):
        return sum(e["kind"] in kinds for e in events)

    pushed = sum(len(e.get("commits", [])) for e in events)
    totals = [
        ("items", count("create-issue", "create-pull")),
        ("issues", count("create-issue")),
        ("pull requests", count("create-pull")),
        ("comments", count("add-comment")),
        ("labels", count("create-label")),
        ("commits", pushed),
        ("squash merges", count("merge-pull")),
        ("events", len(events)),
        ("guessed types", sum(r[3] for r in rows)),
        ("events out of time order", late),
    ]
    print("Totals:")
    for name, value in totals:
        print(f"  {name:<25}{value:>6}")
    # As given, as the shell scripts print paths; Path drops a "//" in it.
    print(argv[3])


if __name__ == "__main__":
    main(sys.argv[1:])
