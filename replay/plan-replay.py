#!/usr/bin/env python3
"""Plans the replay of a GitHub repository into an empty one: reads the
commits from a mirror and the issues, pull requests, comments, reviews and
labels from GitHub, and writes the ordered events that run-replay.py applies;
each review becomes a comment on its pull request.

  plan-replay.py [--types <file>] [--no-types] [--keep-merges]
                 [--leave-behind <file>] [--no-releases [--no-tags]]
                 [--no-reviews]
                 <mirror> <owner/repo> <mailmap> <event file>

<mirror> is a bare clone with refs/pull/*/head, as backup-mirror.sh makes.
<mailmap> maps the author and committer of every commit, in git's mailmap
format. <event file> must not exist yet; it gets JSON Lines: a header that
lists every source commit the replay recreates, what it leaves behind and
what it turns off, then one event per line, in the order run-replay.py
applies them. Reads GitHub through gh api with GET requests only. Prints
every title it changed, every squash message it wrote, what it leaves
behind, and the totals.

A default branch named master becomes main in the target, and so does the
base of each pull request and the target_commitish of each draft release that
name it; texts that name master stay as they are. A source with a branch main
beside its default branch master stops the plan.

The replay carries each tag that names a commit it recreates, under a name
git tag accepts, lightweight or annotated as in the source, an annotated one
with its message and its tagger mapped through <mailmap>. It carries each
release on a tag it carries, with its assets, and each draft whose tag the
source lacks where its target_commitish names the default branch or a
commit it recreates. It carries no other tag or release, and no branch other
than the default branch and those it pushes for pull requests at their
source tips. The plan stops, and writes no event file, unless the <file> of
--leave-behind accepts each of them with a line of its kind and name:
  tag      v1.0
  release  v1.0
  branch   wip/idea  # a "#" after the name starts a comment

--no-tags, --no-releases and --no-reviews turn off what the replay carries:
the first two plan no tag or no release and accept every one as left behind,
without a line of --leave-behind, and the third plans no review as a comment
and reads none. --no-tags needs --no-releases, since GitHub creates the missing tag of
a release it creates, so a replay with releases would still carry tags.

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
# What --no-<kind> turns off, in the order the header's turned_off lists it.
SWITCHES = ("tags", "releases", "reviews")
# The kind of left_behind each switch accepts whole.
SWITCH_OF = {"tag": "tags", "release": "releases"}
# The name the target's default branch takes for the source's, as #71 records
# the owner's request: older repositories use master, newer ones main, and a
# replay is where such a repository starts over.
RENAMED = {"master": "main"}
TYPES = ("feat", "fix", "docs", "chore", "refactor", "test", "build", "ci", "revert")
# Branch prefixes that are no type of GW-6 but name one.
BRANCH_ALIASES = {"feature": "feat", "bugfix": "fix", "hotfix": "fix", "doc": "docs"}
# At the same time, an event of a lower rank comes first: a branch is pushed
# before its pull request is created, an item exists before it is closed, and
# a tag, which marks a state reached, comes after all else but the release
# that stands on it.
RANK = {
    "create-label": 0,
    "push-commits": 1,
    "push-branch": 2,
    "create-issue": 3,
    "create-pull": 3,
    "add-comment": 4,
    "merge-pull": 5,
    "close-item": 6,
    "create-tag": 7,
    "create-release": 8,
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
IDENTITY = re.compile(r"^(?P<name>.*) <(?P<email>[^>]*)> (?P<date>\d+ [+-]\d{4})$")
# The lines that open a signature git appends to a signed tag's message; git
# takes the last of them as the start of the signature.
SIGNATURE = re.compile(
    r"^-----BEGIN (PGP SIGNATURE|PGP MESSAGE|SIGNED MESSAGE|SSH SIGNATURE)-----$", re.M
)


def unsigned(message):
    """A tag's message without the signature git appended to it, which would
    not hold for the recreated tag."""
    # Only where the text from the last opening line on ends with its closing
    # line: a message may hold such a line in its text.
    starts = list(SIGNATURE.finditer(message))
    if starts and message.rstrip("\n").endswith(f"-----END {starts[-1].group(1)}-----"):
        return message[: starts[-1].start()]
    return message


def refused_tag_name(name):
    """Whether git tag refuses to create a tag of that name, also after "--":
    one that starts with a dash, or HEAD, as check_tag_ref() of git's refs.c
    checks before the format a ref name of the mirror already has."""
    return name.startswith("-") or name == "HEAD"


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


def gh_found(endpoint):
    """What GitHub answers for endpoint, or None where it answers 404, as for
    the latest release of a repository that has none."""
    try:
        result = subprocess.run(
            ["gh", "api", endpoint],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except FileNotFoundError:
        die("gh is missing")
    if result.returncode == 0:
        return json.loads(result.stdout)
    if "(HTTP 404)" in result.stderr:
        return None
    die(f"gh api {endpoint} failed: {result.stderr.strip()}")


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
        it names, whether that is a tag object, and the object it peels to
        through every tag, with that object's type."""
        out = self.git(
            "for-each-ref", "--format=%(refname)%09%(objectname)%09%(objecttype)", prefix
        )
        # Only a newline ends a line: git allows other Unicode breaks in a name.
        listed = [line.split("\t") for line in out.split("\n") if line]
        # A tag of a tag peels one level in %(*objectname), so peel with ^{}.
        peeled = self.git(
            "cat-file",
            "--batch-check=%(objectname) %(objecttype)",
            stdin="".join(f"{name}^{{}}\n" for name, *_ in listed),
        ).splitlines()
        found = {}
        for (name, sha, kind), line in zip(listed, peeled, strict=True):
            target, target_type = line.split()
            found[name[len(prefix) :]] = {
                "sha": sha,
                "annotated": kind == "tag",
                "peeled": target,
                "type": target_type,
            }
        return found

    def tag(self, sha):
        """The type of the object the tag object sha names, its message
        without its signature, and its tagger, mapped through the mailmap,
        with the original date; None as tagger where the tag has none."""
        # The type comes from the object itself: git 2.50's for-each-ref peels
        # a tag of a tag through every level in %(*objecttype).
        head, _, message = self.git("cat-file", "tag", sha).partition("\n\n")
        fields = dict(x.split(" ", 1) for x in head.split("\n") if " " in x)
        found = IDENTITY.match(fields.get("tagger", ""))
        tag = {"names": fields.get("type"), "message": unsigned(message), "tagger": None}
        if found:
            mapped = self.git("check-mailmap", f"{found['name']} <{found['email']}>")
            name, _, email = mapped.rstrip("\n").rpartition(" <")
            tag["tagger"] = {"name": name, "email": email[:-1], "date": iso_date(found["date"])}
        return tag


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
        for count, line in enumerate(text.split("\n"), 1):
            # Only spaces and tabs part the fields, and only a newline ends a
            # line: git allows other Unicode blanks and breaks in a ref's name.
            fields = [f for f in re.split(r"[ \t]+", line.rstrip("\r")) if f]
            if not fields or fields[0].startswith("#"):
                continue
            # A name holds no space, so a "#" after one starts a comment, as in
            # the lines the plan prints where it stops.
            if len(fields) > 2 and fields[2].startswith("#"):
                fields = fields[:2]
            if len(fields) != 2 or fields[0] not in self.KINDS:
                die(f"{path}:{count}: expected one of {', '.join(self.KINDS)} and a name")
            self.accepted.add((fields[0], fields[1]))

    def check(self, left, off=()):
        """Stops at what the replay leaves behind and neither the file nor a
        switch of off accepts; warns of what the file accepts and the replay
        carries or the source lacks, and of what a switch accepts already."""
        found = {(x["kind"], x["name"]) for x in left}
        for kind, name in sorted(self.accepted):
            if (kind, name) not in found:
                warn(f"{self.path} accepts {kind} {name}, which the replay does not leave behind")
            elif SWITCH_OF.get(kind) in off:
                warn(f"{self.path} accepts {kind} {name}, which --no-{kind}s leaves behind already")
        missing = [
            x
            for x in left
            if (x["kind"], x["name"]) not in self.accepted and SWITCH_OF.get(x["kind"]) not in off
        ]
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


def source_tags(mirror, recreated, off=()):
    """The tags of the source: those the replay carries, each with the commit
    it names and, where annotated, its message and mapped tagger; and those
    it leaves behind, as left_behind() lists them. A tag carries over only
    where it names a commit the replay recreates, so that it can stand at the
    recreated one, and only under a name git tag accepts, so that the run can
    create it; off holds the kinds a switch turns off."""
    carried, left = [], []
    for name, ref in sorted(mirror.refs("refs/tags/").items()):
        sha = ref["peeled"]
        kind = "annotated" if ref["annotated"] else "lightweight"
        at = sha[:7] if ref["type"] == "commit" else f"the {ref['type']} {sha[:7]}"
        tag = mirror.tag(ref["sha"]) if ref["annotated"] and "tags" not in off else None
        if "tags" in off:
            reason = f"{kind}, at {at}; tags are turned off"
        elif ref["type"] != "commit":
            reason = f"{kind}, at {at}; the replay carries only tags of commits"
        elif tag and tag["names"] == "tag":
            reason = f"{kind}, at {at} through another tag; the replay carries no tag of a tag"
        elif sha not in recreated:
            reason = f"{kind}, at {at}, a commit the replay does not recreate"
        elif tag and tag["tagger"] is None:
            reason = (
                f"{kind}, at {at}, without a tagger; the replay recreates only one with a tagger"
            )
        elif refused_tag_name(name):
            reason = f"{kind}, at {at}; git tag refuses the name"
        else:
            carried.append(
                {
                    "name": name,
                    "commit": sha,
                    "annotated": ref["annotated"],
                    "message": tag["message"] if tag else None,
                    "tagger": tag["tagger"] if tag else None,
                }
            )
            continue
        left.append({"kind": "tag", "name": name, "sha": sha, "reason": reason})
    return carried, left


def source_releases(repo, releases, tags, carried, default, recreated, off=()):
    """The releases of the source: those the replay carries, each with what
    the run needs to recreate it and its assets; and those it leaves behind,
    as left_behind() lists them. tags holds the names of the mirror's tags,
    carried the commit of each tag the replay carries, by name, and off the
    kinds a switch turns off. A release carries over on a tag the replay
    carries, since GitHub creates a missing tag at the release's
    target_commitish, which would put it elsewhere; a draft, which GitHub tags
    only once it is published, carries over without its tag where its
    target_commitish names the default branch or a commit the replay
    recreates."""
    latest = None
    if releases and "releases" not in off:
        latest = (gh_found(f"repos/{repo}/releases/latest") or {}).get("id")
    kept, left = [], []
    for r in sorted(releases, key=lambda r: (r["tag_name"], r["id"])):
        tag = r["tag_name"]
        what = "draft" if r.get("draft") else "pre-release" if r.get("prerelease") else "published"
        target = r.get("target_commitish") or default
        commit, why = carried.get(tag), None
        if "releases" in off:
            why = "releases are turned off"
        elif tag in carried:
            pass
        elif tag in tags:
            why = "its tag is left behind"
        elif not r.get("draft"):
            why = "the mirror lacks its tag"
        elif target not in (default, f"refs/heads/{default}"):
            named = (
                [c for c in recreated if c.startswith(target)]
                if re.fullmatch(r"[0-9a-f]{7,40}", target)
                else []
            )
            commit = named[0] if len(named) == 1 else None
            if commit is None:
                why = (
                    f"its target_commitish {target!r} is neither the default branch nor a commit"
                    " the replay recreates"
                )
        if why:
            reason = f"{what}, named {r.get('name') or tag!r}; {why}"
            left.append({"kind": "release", "name": tag, "sha": None, "reason": reason})
            continue
        assets = []
        for a in gh_pages(f"repos/{repo}/releases/{r['id']}/assets"):
            # An upload that failed leaves an asset of no use behind.
            if a.get("state", "uploaded") != "uploaded":
                warn(f"asset {a['name']} of release {tag} is {a['state']}, not uploaded; left out")
                continue
            assets.append(
                {
                    "id": a["id"],
                    "name": a["name"],
                    "label": a.get("label") or "",
                    "content_type": a.get("content_type") or "application/octet-stream",
                    "size": a.get("size"),
                    "digest": a.get("digest"),
                }
            )
        kept.append(
            {
                "release_id": r["id"],
                "tag_name": tag,
                "on_tag": tag in carried,
                "commit": commit,
                "name": r.get("name") or "",
                "body": r.get("body") or "",
                "draft": bool(r.get("draft")),
                "prerelease": bool(r.get("prerelease")),
                "latest": r["id"] == latest,
                "author": (r.get("author") or {}).get("login"),
                "created_at": r.get("created_at"),
                "published_at": r.get("published_at"),
                "assets": assets,
            }
        )
    # Where the source's latest release stays behind, the newest carried one by
    # GitHub's own rule for the latest takes its place, so that the target has
    # a latest release the comparison can check.
    published = [k for k in kept if not k["draft"] and not k["prerelease"]]
    if latest is not None and published and not any(k["latest"] for k in kept):
        newest = max(published, key=lambda k: (k["created_at"] or "", k["release_id"]))
        newest["latest"] = True
        warn(
            f"the source's latest release is left behind; {newest['tag_name']}, the newest one"
            " the replay carries, becomes the target's latest"
        )
    return kept, left


def left_behind(mirror, info, releases, events, tags):
    """The tags, releases and branches of the source that the replay does not
    carry, each with its kind, name, the commit it names and why; tags and
    releases hold those left behind, as source_tags() and source_releases()
    give them."""
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
    return left + tags + releases


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


def plan(mirror, repo, overrides, typed=True, keep_merges=False, off=()):
    info = gh_get(f"repos/{repo}")
    default = info["default_branch"]
    labels = gh_pages(f"repos/{repo}/labels")
    items = {i["number"]: i for i in gh_pages(f"repos/{repo}/issues?state=all")}
    pulls = {p["number"]: p for p in gh_pages(f"repos/{repo}/pulls?state=all")}
    comments = gh_pages(f"repos/{repo}/issues/comments")

    if not mirror.has(f"refs/heads/{default}"):
        die(f"the mirror has no branch {default}, the default branch of {repo}")
    target = RENAMED.get(default, default)
    if target != default and mirror.has(f"refs/heads/{target}"):
        die(
            f"the source has a branch {target} beside its default branch {default}, which the"
            f" replay names {target}; it cannot give two branches one name. Rename or delete the"
            f" branch {target} in the source, then mirror and plan again"
        )
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
                branch=target,
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

    names, branch_names = {default, target}, {}
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
            base = target if p["base"]["ref"] == default else p["base"]["ref"]
            if base == target != default != p["base"]["ref"]:
                warn(
                    f"#{n} targets {base}, the name the replay gives the default branch {default};"
                    f" it is created against that branch"
                )
            elif p["base"]["ref"] != default:
                warn(f"#{n} targets {base}, a branch the replay does not create")
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
                base=base,
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

    # Each review of a pull request becomes a comment at its submission, since
    # a replay cannot submit a review for someone else; a pending review is
    # its author's draft, which GitHub shows nobody else.
    by_review = {}
    for rc in [] if "reviews" in off else gh_pages(f"repos/{repo}/pulls/comments"):
        by_review.setdefault(rc.get("pull_request_review_id"), []).append(rc)
    carried = set()
    for n in [] if "reviews" in off else sorted(pulls):
        for r in gh_pages(f"repos/{repo}/pulls/{n}/reviews"):
            if r.get("state") == "PENDING" or not r.get("submitted_at"):
                continue
            carried.add(r["id"])
            text = review_text(r, by_review.get(r["id"], []))
            if len(text) > COMMENT_LENGTH:
                warn(
                    f"review {r['id']} of #{n} has {len(text)} characters, more than the"
                    f" {COMMENT_LENGTH} a comment takes; the run stops at it"
                )
            add(
                ("review", r["id"]),
                "add-comment",
                utc(r["submitted_at"]),
                [("create", n)],
                number=n,
                body=text,
                author=(r.get("user") or {}).get("login"),
                created_at=r["submitted_at"],
                review_id=r["id"],
            )
    for rid, found in sorted(by_review.items(), key=lambda x: (x[0] is None, x[0] or 0)):
        if rid not in carried:
            which = (
                "without a review id"
                if rid is None
                else f"of review {rid}, which no submitted review of a listed pull request has,"
            )
            warn(f"{len(found)} review comment{'s' if len(found) > 1 else ''} {which} left out")

    # Each tag comes after the event that recreates its commit: an annotated
    # one at its tagger's date, a lightweight one, which has no date of its
    # own, right after that event.
    recreated = set(main_index) | set(owner)
    tags, left_tags = source_tags(mirror, recreated, off)
    for t in tags:
        add(
            ("tag", t["name"]),
            "create-tag",
            utc(t["tagger"]["date"]) if t["tagger"] else None,
            [producer(t["commit"])],
            **t,
        )
    # Each release comes after the event of its tag, or of the commit a
    # draft names, at its publication, or a draft at its created_at, which
    # GitHub documents as the date of the commit used for the release; a
    # draft that names the default branch needs only that branch.
    releases, left_releases = source_releases(
        repo,
        gh_pages(f"repos/{repo}/releases"),
        set(mirror.refs("refs/tags/")),
        {t["name"]: t["commit"] for t in tags},
        default,
        recreated,
        off,
    )
    for r in releases:
        if r["on_tag"]:
            deps = [("tag", r["tag_name"])]
        else:
            deps = [producer(r["commit"])] if r["commit"] else [("main", 0)]
        add(
            ("release", r["release_id"]),
            "create-release",
            utc(r["published_at"] or r["created_at"]),
            deps,
            **r,
        )
    left = left_behind(mirror, info, left_releases, events, left_tags)
    return default, target, events, left


# The longest comment GitHub takes, as its community reports; the REST
# documentation names no limit. A review with all its review comments in one
# comment can be longer than any comment of the source.
COMMENT_LENGTH = 65536
REVIEW_STATES = {
    "APPROVED": "approved",
    "CHANGES_REQUESTED": "changes requested",
    "COMMENTED": "commented",
    "DISMISSED": "dismissed",
}


def review_text(review, comments):
    """A review as the text of a comment: who reviewed, its state and the
    commit it was made on, its body, and each of its review comments under
    the file and lines it was made on."""
    who = (review.get("user") or {}).get("login") or "someone"
    state = REVIEW_STATES.get(review.get("state"), str(review.get("state", "")).lower())
    commit = (review.get("commit_id") or "")[:7]
    on = f", on {commit}" if commit else ""
    parts = [f"_Review by {who}: {state}{on}._"]
    if (review.get("body") or "").strip():
        parts.append(review["body"])
    for c in sorted(comments, key=lambda c: (c.get("created_at") or "", c["id"])):
        end = c.get("line") or c.get("original_line")
        start = c.get("start_line") or c.get("original_start_line")
        if c.get("subject_type") == "file" or not end:
            where = "file"
        elif start and start != end:
            where = f"lines {start} to {end}"
        else:
            where = f"line {end}"
        # On the LEFT side, the line is one of the file before the change.
        side = ", before the change" if c.get("side") == "LEFT" and where != "file" else ""
        reply = ", a reply" if c.get("in_reply_to_id") else ""
        parts.append(f"**`{c.get('path')}`, {where}{side}{reply}**\n\n{c.get('body') or ''}")
    return "\n\n".join(parts)


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
    types, typed, keep_merges, leave, off = None, True, False, None, set()
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
        elif option.startswith("--no-") and option[len("--no-") :] in SWITCHES:
            off.add(option[len("--no-") :])
        else:
            usage()
    if len(argv) != 4 or argv[0].startswith("-"):
        usage()
    mirror_path, repo, mailmap, output = Path(argv[0]), argv[1], Path(argv[2]), Path(argv[3])
    if not re.fullmatch(r"[\w.-]+/[\w.-]+", repo):
        usage()
    if "tags" in off and "releases" not in off:
        die(
            "--no-tags needs --no-releases (no_tags needs no_releases, in a run file of"
            " replay.py): GitHub creates the missing tag of a release it creates, at the commit"
            " the release's target_commitish names, so a replay with releases would still carry"
            " tags. Give --no-releases too, or leave out --no-tags"
        )
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
    default, target, events, left = plan(mirror, repo, overrides, typed, keep_merges, off)
    accepted.check(left, off)
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
        # An event file without target_default_branch was planned before the
        # rename, with the target's default branch named as the source's.
        "target_default_branch": target,
        "source_commits": source_commits,
        "left_behind": left,
        "reviews": "reviews" not in off,
        # An event file without turned_off was planned before the switches,
        # with every kind on.
        "turned_off": [k for k in SWITCHES if k in off],
    }
    partial = output.with_name(output.name + ".partial")
    with partial.open("w", encoding="utf-8") as file:
        for line in [header, *events]:
            file.write(json.dumps(line, ensure_ascii=False) + "\n")
    partial.replace(output)

    if target != default:
        print(f"Default branch: {default} in the source, {target} in the target")
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
        ("comments", sum(e["kind"] == "add-comment" and "review_id" not in e for e in events)),
        ("reviews", sum("review_id" in e for e in events)),
        ("labels", count("create-label")),
        ("tags", count("create-tag")),
        ("releases", count("create-release")),
        ("release assets", sum(len(e.get("assets", [])) for e in events)),
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
