"""The fixtures and helpers of the suite that tests the replay scripts.

The suite runs each script as a process, as a user runs it, with the
interpreter that runs pytest, against a source it builds once per session in
a temporary folder: a mirror with pull request refs, made by
rewrite/backup-mirror.sh, and a fake gh, first on PATH, that answers the
source's API from JSON files the fixtures write. GitHub is never contacted,
and the developer's own git configuration is not read.
"""

import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import pytest

HERE = Path(__file__).resolve().parent
REPLAY = HERE.parent
REWRITE = REPLAY.parent / "rewrite"

GLOBAL_CONFIG = """\
[user]
\tname = Test
\temail = test@example.com
[commit]
\tgpgsign = false
[init]
\tdefaultBranch = main
[advice]
\tdetachedHead = false
"""

ADA_OLD = ("Ada Old", "ada.old@example.com")
BOB = ("Bob Example", "bob@example.com")
GITHUB = ("GitHub", "noreply@github.com")


def lines(text):
    # Split at newlines alone, as grep does: str.splitlines() also splits at
    # a carriage return, so a line "x\r" would match "x" exactly.
    return text.removesuffix("\n").split("\n") if text else []


@dataclass(frozen=True)
class Result:
    """What a process left: its exit status, standard output and error,
    with their lines as grep reads them."""

    status: int
    out: str
    err: str

    @property
    def out_lines(self):
        return lines(self.out)

    @property
    def err_lines(self):
        return lines(self.err)

    @property
    def last_out_line(self):
        """The last line of standard output, as $(tail -n 1) gives it."""
        return (self.out_lines or [""])[-1]


def run(args, env, cwd, stdin=None, merged=False):
    """Runs a process and returns what it left. stdin, where given, is the
    text it reads, as printf piped into it; merged puts its standard error
    into its standard output, in the order written, as 2>&1 does."""
    done = subprocess.run(
        [str(a) for a in args],
        env=env,
        cwd=cwd,
        input=None if stdin is None else stdin.encode("utf-8"),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT if merged else subprocess.PIPE,
        check=False,
    )
    # Decoded here rather than in text mode, which would turn "\r\n" and a
    # lone "\r" into "\n", so that a line ending in "\r" fails an exact match
    # as it does with grep -x.
    return Result(
        done.returncode,
        done.stdout.decode("utf-8", errors="replace"),
        (done.stderr or b"").decode("utf-8", errors="replace"),
    )


class Git:
    """Runs git in one work tree, with the suite's environment."""

    def __init__(self, env, cwd):
        self.env = env
        self.cwd = Path(cwd)

    def __call__(self, *args, env=None):
        done = subprocess.run(
            ["git", *map(str, args)],
            env={**self.env, **(env or {})},
            cwd=self.cwd,
            capture_output=True,
            text=True,
            check=False,
        )
        if done.returncode:
            raise RuntimeError(f"git {' '.join(map(str, args))} failed:\n{done.stderr}")
        return done.stdout.strip()

    def head(self, rev="HEAD"):
        return self("rev-parse", rev)

    def save(self, date, message, author=ADA_OLD, committer=None):
        """Commits the index by that author, and by that committer or else the
        author, on that date."""
        committer = committer or author
        self(
            "commit",
            "-q",
            "-m",
            message,
            env={
                "GIT_AUTHOR_NAME": author[0],
                "GIT_AUTHOR_EMAIL": author[1],
                "GIT_AUTHOR_DATE": date,
                "GIT_COMMITTER_NAME": committer[0],
                "GIT_COMMITTER_EMAIL": committer[1],
                "GIT_COMMITTER_DATE": date,
            },
        )

    def change(self, file, date, message, author=ADA_OLD):
        """Appends the message to the file and commits it."""
        path = self.cwd / file
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(message + "\n")
        self("add", file)
        self.save(date, message, author)


@pytest.fixture(scope="session")
def root(tmp_path_factory):
    """The temporary folder of the session, $T of the shell test."""
    return tmp_path_factory.mktemp("replay-test")


@pytest.fixture(scope="session")
def base_env(root):
    """The environment of the scripts, without the fake gh.

    A git configuration of the suite's own, and SOURCE_DATE_EPOCH, the
    committer date run-replay.py gives each recreated commit, in UTC so that
    its offset is +0000: two runs build the same hashes.
    """
    config = root / "global"
    config.write_text(GLOBAL_CONFIG, encoding="utf-8")
    unset = ("GIT_DIR", "GIT_WORK_TREE", "GIT_TERMINAL_PROMPT")
    env = {k: v for k, v in os.environ.items() if k not in unset}
    env.update(
        GIT_CONFIG_GLOBAL=str(config),
        GIT_CONFIG_NOSYSTEM="1",
        SOURCE_DATE_EPOCH="1794000000",
        TZ="UTC",
    )
    return env


@dataclass(frozen=True)
class Source:
    """The source the session builds, and the files every plan of it reads."""

    root: Path
    bare: Path
    work: Path
    mirror: Path
    mailmap: Path
    types: Path
    summaries: Path
    hashes: dict


@pytest.fixture(scope="session")
def source(root, base_env):
    """The source, as on GitHub, mirrored by backup-mirror.sh.

    Direct commits; #2 squash-merged; #3 merged with a merge commit; #5 closed
    unmerged, after its branch merged main past the opening of #6; issues #1,
    #4 and #6 between them. GitHub commits the merges; a committed .mailmap
    must not count. refs/pull/7/head merges a commit no pull request holds,
    for a check that uses another API.
    """
    bare, work = root / "source.git", root / "work"
    Git(base_env, root)("init", "-q", "--bare", bare)
    Git(base_env, root)("clone", "-q", bare, work)
    git = Git(base_env, work)
    hashes = {}
    git.change("README.md", "2026-03-01T10:00:00+00:00", "Add the readme")
    hashes["C1"] = git.head()
    git("switch", "-q", "-c", "feat/2-thing")
    git.change("thing.sh", "2026-03-02T09:00:00+00:00", "Add thing")
    hashes["B1"] = git.head()
    hashes["TREEB1"] = git.head("HEAD^{tree}")
    git.change("README.md", "2026-03-02T09:30:00+00:00", "README: mention thing")
    hashes["B2"] = git.head()
    git("push", "-q", "origin", "HEAD:refs/pull/2/head")
    git("switch", "-q", "main")
    git("merge", "-q", "--squash", "feat/2-thing")
    git.save(
        "2026-03-03T10:00:00+00:00",
        "Add thing (#2)\n\n* Add thing\n\n* README: mention thing",
        ADA_OLD,
        GITHUB,
    )
    hashes["M2"] = git.head()
    git("switch", "-q", "-c", "fix/3-parser")
    git.change("thing.sh", "2026-03-04T09:00:00+00:00", "Repair the parser", BOB)
    hashes["F1"] = git.head()
    git("push", "-q", "origin", "HEAD:refs/pull/3/head")
    git("switch", "-q", "main")
    git(
        "merge",
        "-q",
        "--no-ff",
        "-m",
        "Merge pull request #3 from bob-example/fix/3-parser\n\nRepair the parser",
        "fix/3-parser",
        env={
            "GIT_AUTHOR_NAME": BOB[0],
            "GIT_AUTHOR_EMAIL": BOB[1],
            "GIT_AUTHOR_DATE": "2026-03-05T10:00:00+00:00",
            "GIT_COMMITTER_DATE": "2026-03-05T10:00:00+00:00",
            "GIT_COMMITTER_NAME": GITHUB[0],
            "GIT_COMMITTER_EMAIL": GITHUB[1],
        },
    )
    hashes["M3"] = git.head()
    hashes["TREE3"] = git.head("HEAD^{tree}")
    git.change(
        ".github/workflows/test.yml", "2026-03-05T11:00:00+00:00", "ci: add the test workflow"
    )
    hashes["C2"] = git.head()
    git.change("tests/test-thing.sh", "2026-03-05T14:00:00+02:00", "Update the tests")
    hashes["C3"] = git.head()
    git.change(
        "thing.sh", "2026-03-05T13:00:00+00:00", "Tidy the scripts\n\nNo change in behaviour."
    )
    hashes["C4"] = git.head()
    git("switch", "-q", "-c", "docs/5-notes")
    git.change("notes.md", "2026-03-06T09:00:00+00:00", "Add notes")
    hashes["N1"] = git.head()
    git("push", "-q", "origin", "HEAD:refs/pull/5/head")
    git("switch", "-q", "main")
    (work / ".mailmap").write_text(
        "Wrong Name <wrong@example.com> <ada.old@example.com>\n", encoding="utf-8"
    )
    git("add", ".mailmap")
    git.change("thing.sh", "2026-03-07T12:00:00+00:00", "Rewrite thing in POSIX sh")
    hashes["C5"] = git.head()
    git("push", "-q", "origin", "main")
    git("switch", "-q", "docs/5-notes")
    git("merge", "-q", "--no-ff", "--no-commit", "main")
    git.save("2026-03-07T13:00:00+00:00", "Merge main into docs/5-notes")
    hashes["N2"] = git.head()
    git("push", "-q", "origin", "HEAD:refs/pull/5/head")
    git("switch", "-q", "-c", "side", hashes["C1"])
    git.change("side.md", "2026-03-08T09:00:00+00:00", "Add a side note")
    hashes["S1"] = git.head()
    git("switch", "-q", "-c", "feat/7-side", hashes["C5"])
    git("merge", "-q", "--no-ff", "--no-commit", "side")
    git.save("2026-03-08T10:00:00+00:00", "Merge the side note")
    hashes["H7"] = git.head()
    git("push", "-q", "origin", "HEAD:refs/pull/7/head")

    mirrored = run([REWRITE / "backup-mirror.sh", bare, root / "backup"], base_env, root)
    assert mirrored.status == 0, mirrored.err
    mirror = Path(mirrored.out.strip())

    mailmap = root / "mailmap"
    mailmap.write_text(
        "Ada Example <ada@example.com> <ada.old@example.com>\n"
        "Ada Example <ada@example.com> GitHub <noreply@github.com>\n",
        encoding="utf-8",
    )
    types = root / "types"
    types.write_text(f"# tidy-ups are chores\n{hashes['C4'][:9]} chore\n", encoding="utf-8")
    summaries = root / "summaries"
    summaries.write_text("3 summary Repairs the parser on empty input.\n", encoding="utf-8")
    return Source(root, bare, work, mirror, mailmap, types, summaries, hashes)


@pytest.fixture(scope="session")
def hashes(source):
    """The source's hashes, by the names the shell test exports them under,
    such as C1, B1, M2 and TREE3."""
    return source.hashes


API_BASE = "repos_ada-example_tool"

LABELS = [
    {"name": "docs", "color": "0075ca", "description": "Documentation"},
    {"name": "bug", "color": "d73a4a", "description": "Something isn't working"},
]

# GitHub lists issues newest first, so page 1 holds #6 to #4.
ISSUES_1 = [
    {
        "number": 6,
        "title": "Thing breaks on Sundays",
        "body": "Seen twice.",
        "state": "open",
        "state_reason": None,
        "labels": [{"name": "bug"}, {"name": "docs"}],
        "assignees": [{"login": "ada-example"}],
        "user": {"login": "bob-example"},
        "created_at": "2026-03-07T11:00:00Z",
        "closed_at": None,
    },
    {
        "number": 5,
        "title": "Notes",
        "body": None,
        "state": "closed",
        "state_reason": None,
        "labels": [],
        "assignees": [],
        "user": {"login": "ada-example"},
        "created_at": "2026-03-06T10:00:00Z",
        "closed_at": "2026-03-08T10:00:00Z",
        "pull_request": {"merged_at": None},
    },
    {
        "number": 4,
        "title": "Support tabs",
        "body": "Tabs would help.",
        "state": "closed",
        "state_reason": "not_planned",
        "labels": [{"name": "bug"}],
        "assignees": [],
        "user": {"login": "bob-example"},
        "created_at": "2026-03-04T11:00:00Z",
        "closed_at": "2026-03-06T11:00:00Z",
    },
]

ISSUES_2 = [
    {
        "number": 3,
        "title": "Repair the parser",
        "body": "Fixes #4\r\n\r\n## Why\r\n\r\nThe parser had two faults:\r\n\r\n"
        "The parser failed on empty input. It now returns an empty list for it, as the readme "
        "says, and a test covers the case, so that a later change cannot break it again without "
        "the test failing; input of blanks alone, which it read as one empty field until now, it "
        "now skips as well, as the readme also says.\r\n\r\nDetails follow here.",
        "state": "closed",
        "state_reason": None,
        "labels": [],
        "assignees": [],
        "user": {"login": "bob-example"},
        "created_at": "2026-03-04T10:00:00Z",
        "closed_at": "2026-03-05T10:00:00Z",
        "pull_request": {"merged_at": "2026-03-05T10:00:00Z"},
    },
    {
        "number": 2,
        "title": "Add thing",
        "body": "Adds thing.\n\nCloses #1",
        "state": "closed",
        "state_reason": None,
        "labels": [],
        "assignees": [],
        "user": {"login": "ada-example"},
        "created_at": "2026-03-02T10:00:00Z",
        "closed_at": "2026-03-03T10:00:00Z",
        "pull_request": {"merged_at": "2026-03-03T10:00:00Z"},
    },
    {
        "number": 1,
        "title": "Explain the tool",
        "body": "The readme is empty.",
        "state": "closed",
        "state_reason": "completed",
        "labels": [],
        "assignees": [],
        "user": {"login": "bob-example"},
        "created_at": "2026-03-01T11:00:00Z",
        "closed_at": "2026-03-03T11:00:00Z",
    },
]

COMMENTS = [
    {
        "id": 101,
        "issue_url": "https://api.github.com/repos/ada-example/tool/issues/1",
        "body": "Seen in the readme.",
        "user": {"login": "ada-example"},
        "created_at": "2026-03-02T12:00:00Z",
    },
    {
        "id": 102,
        "issue_url": "https://api.github.com/repos/ada-example/tool/issues/3",
        "body": "Looks right.",
        "user": {"login": "ada-example"},
        "created_at": "2026-03-04T12:00:00Z",
    },
    {
        "id": 103,
        "issue_url": "https://api.github.com/repos/ada-example/tool/issues/4",
        "body": "Not needed after all.",
        "user": {"login": "bob-example"},
        "created_at": "2026-03-06T12:00:00Z",
    },
]


def pull(number, ref, sha, merged_at, merge_commit_sha, created_at):
    return {
        "number": number,
        "head": {"ref": ref, "sha": sha},
        "base": {"ref": "main"},
        "merged_at": merged_at,
        "merge_commit_sha": merge_commit_sha,
        "draft": False,
        "created_at": created_at,
    }


def pulls(hashes):
    return [
        pull(
            5,
            "docs/5-notes",
            hashes["N2"],
            None,
            "0123456789abcdef0123456789abcdef01234567",
            "2026-03-06T10:00:00Z",
        ),
        pull(
            3,
            "fix/3-parser",
            hashes["F1"],
            "2026-03-05T10:00:00Z",
            hashes["M3"],
            "2026-03-04T10:00:00Z",
        ),
        pull(
            2,
            "feat/2-thing",
            hashes["B2"],
            "2026-03-03T10:00:00Z",
            hashes["M2"],
            "2026-03-02T10:00:00Z",
        ),
    ]


def write_json(path, data):
    path.write_text(json.dumps(data, indent=1) + "\n", encoding="utf-8")


@pytest.fixture(scope="session")
def api(root, hashes):
    """The folder of the API of the source, ada-example/tool, that the fake gh answers from."""
    folder = root / "api"
    folder.mkdir()

    def file(name):
        return folder / f"{API_BASE}{name}"

    write_json(file(".json"), {"default_branch": "main"})
    # The content of the two assets of the release v0.2 that a later copy
    # of this API lists, which a download with Accept:
    # application/octet-stream gets; here, so that every copy has them. The
    # first holds bytes that are no text.
    file("_releases_assets_11.bin").write_bytes(b"\037\213\010\000tool\377\000\n")
    file("_releases_assets_12.bin").write_bytes(b"Notes for v0.2\n")
    write_json(file("_labels-1.json"), LABELS)
    write_json(file("_issues-1.json"), ISSUES_1)
    write_json(file("_issues-2.json"), ISSUES_2)
    write_json(file("_pulls-1.json"), pulls(hashes))
    write_json(file("_issues_comments-1.json"), COMMENTS)
    return folder


@pytest.fixture(scope="session")
def api_stray(root, api, hashes):
    """The same API, with a pull request #7 whose branch merges a commit that
    neither the default branch nor a pull request holds."""
    folder = root / "api-stray"
    shutil.copytree(api, folder)
    seven = pull(7, "feat/7-side", hashes["H7"], None, None, "2026-03-08T11:00:00Z")
    write_json(folder / f"{API_BASE}_pulls-1.json", [seven, *pulls(hashes)])
    return folder


@dataclass(frozen=True)
class FakeGh:
    """An environment with the fake gh of the source first on PATH."""

    env: dict
    log: Path
    refused: Path
    cwd: Path

    def run(self, *args):
        """Runs a command in this environment, from the session's folder."""
        return run(args, self.env, self.cwd)

    def using(self, **variables):
        """The environment with these variables set, such as another FAKE_GH_API."""
        return {**self.env, **{k: str(v) for k, v in variables.items()}}

    def calls(self):
        """The lines of the log, one per call; a missing log fails, as grep does."""
        return lines(self.log.read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def source_gh(root, base_env, api):
    """Makes an environment whose gh is the fake of the source, answering from
    the API folder, with the log and the refused-calls file named <name>-calls
    and <name>-refused in the session's folder."""
    bin_dir = root / "bin"
    bin_dir.mkdir()
    gh = bin_dir / "gh"
    python, fake = shlex.quote(sys.executable), shlex.quote(str(HERE / "fake-gh-source.py"))
    gh.write_text(f'#!/bin/sh\nexec {python} {fake} "$@"\n', encoding="utf-8")
    gh.chmod(0o755)

    def make(name="gh"):
        log, refused = root / f"{name}-calls", root / f"{name}-refused"
        env = {
            **base_env,
            "PATH": f"{bin_dir}{os.pathsep}{base_env.get('PATH', '')}",
            "FAKE_GH_API": str(api),
            "FAKE_GH_LOG": str(log),
            "FAKE_GH_REFUSED": str(refused),
        }
        return FakeGh(env, log, refused, root)

    return make


@pytest.fixture(scope="session")
def plan(root):
    """Runs plan-replay.py with these arguments in that environment, from the
    session's folder, with the interpreter that runs pytest."""

    def plan(*args, env, merged=False):
        return run([sys.executable, REPLAY / "plan-replay.py", *args], env, root, merged=merged)

    return plan


class Plan:
    """An event file: its header, and its events, in their order."""

    def __init__(self, path):
        with Path(path).open(encoding="utf-8") as f:
            self.header, *self.events = [json.loads(line) for line in f]

    def of(self, kind, number=None):
        """The events of a kind, of item number where one is given."""
        return [e for e in self.events if e["kind"] == kind and number in (None, e.get("number"))]

    def commit(self, sha):
        """The planned commit of that source commit."""
        return next(c for e in self.events for c in e.get("commits", []) if c["sha"] == sha)

    def title(self, sha):
        """The first line of the message of that planned commit."""
        return self.commit(sha)["message"].partition("\n")[0]


@pytest.fixture(scope="session")
def read_plan():
    """Reads an event file as a Plan."""
    return Plan


TOOL = "ada-example/tool"


@pytest.fixture(scope="session")
def plan_gh(source_gh):
    """The fake gh of the four plans of planned, and of the other checks of
    plan-replay.py on the source but the check of the fake itself, whose log
    the check of the calls to gh reads."""
    return source_gh("plan-gh")


@pytest.fixture(scope="session")
def planned(root, source, plan, plan_gh):
    """The four plans of the source that the checks of plan-replay.py read,
    events.jsonl first, made in the order of the shell test, since the check
    of the calls to gh reads the log of all four; later checks read what the
    first printed, as the shell test reads plan-out."""
    s, gh = source, plan_gh
    files = SimpleNamespace(
        events=root / "events.jsonl",
        plain=root / "plain.jsonl",
        merges=root / "merges.jsonl",
        plain_typed=root / "plain-typed.jsonl",
    )
    main = plan("--types", s.types, s.mirror, TOOL, s.mailmap, files.events, env=gh.env)
    plain = plan(
        "--no-types", "--types", s.summaries, s.mirror, TOOL, s.mailmap, files.plain, env=gh.env
    )
    merges = plan(
        "--keep-merges", "--types", s.types, s.mirror, TOOL, s.mailmap, files.merges, env=gh.env
    )
    plain_typed = plan(
        "--no-types", "--types", s.types, s.mirror, TOOL, s.mailmap, files.plain_typed, env=gh.env
    )
    return SimpleNamespace(
        files=files, main=main, plain=plain, merges=merges, plain_typed=plain_typed
    )


@dataclass(frozen=True)
class Planned:
    """A plan the session makes once: its event file, the API folder it was
    planned from, and what plan-replay.py printed, standard error included."""

    file: Path
    api: Path
    result: Result


@pytest.fixture(scope="session")
def run_plan(root, source, api, plan, source_gh):
    """The plan run-replay.py applies, run.jsonl: the source's, with a fourth
    comment, on #6, after every merge, that names a direct commit and a squash
    merge by their hashes, and a word of hex characters that is no commit. Its
    API, api-run, is a copy of the source's with that comment."""
    folder = root / "api-run"
    shutil.copytree(api, folder)
    page = folder / f"{API_BASE}_issues_comments-1.json"
    comments = json.loads(page.read_text(encoding="utf-8"))
    c4, m2 = source.hashes["C4"], source.hashes["M2"]
    comments.append(
        {
            "id": 104,
            "issue_url": "https://api.github.com/repos/ada-example/tool/issues/6",
            "body": f"Tidied in {c4[:7]}, after {m2[:10]}; abcdef0 is no commit.",
            "user": {"login": "ada-example"},
            "created_at": "2026-03-08T12:00:00Z",
        }
    )
    page.write_text(json.dumps(comments), encoding="utf-8")
    events = root / "run.jsonl"
    env = source_gh("run-plan-gh").using(FAKE_GH_API=folder)
    s = source
    result = plan("--types", s.types, s.mirror, TOOL, s.mailmap, events, env=env, merged=True)
    return Planned(events, folder, result)


# The labels GitHub gives a new repository, as the shell test writes them.
NEW_LABELS = (
    '[{"name": "bug", "color": "ee0701", "description": "Something is wrong"},\n'
    '      {"name": "enhancement", "color": "a2eeef", "description": "New feature or request"}]\n'
)


class Target:
    """A target of the fake gh of the targets: the folder that holds its
    name, its JSON files, its log of calls and its bare repository."""

    def __init__(self, folder, env):
        self.folder = Path(folder)
        self.env = env
        self.repo = self.folder / "repo.git"

    def load(self, name, default):
        """A JSON file the fake keeps, or default where it has none."""
        path = self.folder / f"{name}.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default

    def calls(self):
        """The lines of the log of calls, each its time and "<method> <endpoint>";
        none where the fake logged no call."""
        path = self.folder / "calls"
        return lines(path.read_text(encoding="utf-8")) if path.exists() else []

    def writes(self):
        """The calls that write, with their times, as writes() of the shell
        test greps them: every line without " GET "."""
        return [c for c in self.calls() if " GET " not in c]

    def git(self, *args):
        """The output of git in the target's repository, stripped; a failing
        git fails the caller, as check=True does in rexpect of the shell test."""
        done = run(["git", "--git-dir", self.repo, *args], self.env, self.folder)
        if done.status:
            raise RuntimeError(f"git {' '.join(map(str, args))} failed:\n{done.err}")
        return done.out.strip()

    def dump(self):
        """The target's items, comments, labels, closings and refs, as dump()
        of the shell test prints them; a missing file fails, as cat does."""
        files = ("items", "comments", "labels", "closes")
        content = b"".join((self.folder / f"{name}.json").read_bytes() for name in files)
        refs = run(["git", "--git-dir", self.repo, "for-each-ref"], self.env, self.folder)
        assert refs.status == 0, refs.err
        return content + refs.out.encode("utf-8")


class TargetView:
    """What rexpect of the shell test reads of a target: items by number,
    comments as (number, body), labels and closes from the fake's files, the
    state file and its map of source to target hashes, the events of the plan
    run-replay.py applied, and git in the target's repository."""

    def __init__(self, target, state_file, plan):
        self.items = {int(k): v for k, v in target.load("items", {}).items()}
        self.comments = [(c["number"], c["body"]) for c in target.load("comments", [])]
        self.labels, self.closes = target.load("labels", []), target.load("closes", [])
        self.state = json.loads(Path(state_file).read_text(encoding="utf-8"))
        self.recreated = self.state["hashes"]
        self.events = plan.events
        self.git = target.git


@pytest.fixture(scope="session")
def target_env(root, source_gh):
    """The environment under which the scripts reach the fake gh of the
    targets, first on PATH before the fake of the source, with $FAKE_GH_API
    the source's API, as the shell test exports it."""
    bin_dir = root / "bin-target"
    bin_dir.mkdir()
    gh = bin_dir / "gh"
    python, fake = shlex.quote(sys.executable), shlex.quote(str(HERE / "fake-gh-target.py"))
    # exec, so that the fake's parent, to which FAKE_GH_INTERRUPT sends a
    # SIGINT, is the script that ran gh.
    gh.write_text(f'#!/bin/sh\nexec {python} {fake} "$@"\n', encoding="utf-8")
    gh.chmod(0o755)
    env = source_gh("target-gh").env
    return {**env, "PATH": f"{bin_dir}{os.pathsep}{env['PATH']}"}


@pytest.fixture(scope="session")
def make_target(root, base_env):
    """Makes an empty target in a folder of the session, ada-example/tool-new
    by default, with two labels as GitHub gives a new repository."""

    def make(name, slug="ada-example/tool-new"):
        folder = root / name
        folder.mkdir()
        (folder / "name").write_text(slug + "\n", encoding="utf-8")
        Git(base_env, root)("init", "-q", "--bare", folder / "repo.git")
        (folder / "labels.json").write_text(NEW_LABELS, encoding="utf-8")
        return Target(folder, base_env)

    return make


@pytest.fixture(scope="session")
def replay(root, target_env):
    """Runs run-replay.py with these arguments against the target, with the
    answer typed at the confirmation and the FAKE_GH_* variables given, from
    the session's folder, with the interpreter that runs pytest."""

    def replay(target, answer, *args, merged=False, **variables):
        env = {**target_env, "FAKE_GITHUB": str(target.folder)}
        env.update({k: str(v) for k, v in variables.items()})
        script = [sys.executable, REPLAY / "run-replay.py", *args]
        return run(script, env, root, stdin=f"{answer}\n", merged=merged)

    return replay


@dataclass(frozen=True)
class Replayed:
    """A replay the session makes once: its target, its state file and what
    run-replay.py printed, with the log of calls and the dump of the target
    as the run left them, before later runs add to the log."""

    target: Target
    state: Path
    result: Result
    calls: list
    dump: bytes | None

    @property
    def writes(self):
        """The calls of this run that write, as Target.writes() reads them."""
        return [c for c in self.calls if " GET " not in c]


@pytest.fixture(scope="session")
def replay_a(root, source, run_plan, make_target, replay):
    """A: one uninterrupted run, paced at 0.1 s, that hits a rate limit once;
    its standard output and error apart."""
    target = make_target("gh-a")
    state = root / "a.state.json"
    slug = "ada-example/tool-new"
    result = replay(
        target,
        slug,
        *("--pace", "0.1", "--state", state, run_plan.file, source.mirror, slug),
        FAKE_GH_RATE_LIMIT="POST repos/ada-example/tool-new/issues/1/comments",
    )
    return Replayed(target, state, result, target.calls(), target.dump())


@pytest.fixture(scope="session")
def replay_c(root, source, run_plan, make_target, replay):
    """C: a replay into a target where someone else creates an issue, with the
    default state file, run.state.json, and --with-times; it stops at #4 and
    leaves the replay unfinished."""
    target = make_target("gh-c", "ada-example/tool-c")
    slug = "ada-example/tool-c"
    result = replay(
        target,
        slug,
        *("--pace", "0", "--with-times", run_plan.file, source.mirror, slug),
        merged=True,
        FAKE_GH_SKIP=4,
    )
    # No dump: no check compares this stopped target with another.
    return Replayed(target, root / "run.state.json", result, target.calls(), None)


@pytest.fixture(scope="session")
def replay_e(root, source, run_plan, make_target, replay):
    """E: an unsigned replay with --final-name, whose squash messages name the
    source, the name the target takes over."""
    target = make_target("gh-e", "ada-example/tool-e")
    state = root / "e.state.json"
    slug = "ada-example/tool-e"
    result = replay(
        target,
        slug,
        *("--pace", "0", "--final-name", TOOL, "--state", state),
        *(run_plan.file, source.mirror, slug),
        merged=True,
    )
    return Replayed(target, state, result, target.calls(), target.dump())


@pytest.fixture(scope="session")
def run_process(root, base_env):
    """Runs a command through run(), with the suite's environment, from the
    session's folder; merged as run() takes it."""

    def run_process(*args, merged=False):
        return run(args, base_env, root, merged=merged)

    return run_process


@pytest.fixture(scope="session")
def view(read_plan, run_plan):
    """Reads a target as rexpect of the shell test does, with the state file
    given and the events of run.jsonl."""
    plan = read_plan(run_plan.file)

    def view(target, state_file):
        return TargetView(target, state_file, plan)

    return view


# A tag name with a no-break space, which git allows in a ref's name.
NBSP_TAG = "sp\N{NO-BREAK SPACE}ace"


def as_committer(person, date):
    """The environment that makes git record that person and date as the
    committer, and so as the tagger of an annotated tag."""
    return {
        "GIT_COMMITTER_NAME": person[0],
        "GIT_COMMITTER_EMAIL": person[1],
        "GIT_COMMITTER_DATE": date,
    }


@pytest.fixture(scope="session")
def mirror_extra(root, source, base_env):
    """mirror-extra.git, what a replay leaves behind: a copy of the mirror with
    a lightweight tag v0.1 at the squash merge of #2, an annotated v0.2 at a
    direct commit, by Ada's old address and naming a commit by its hash, and
    an annotated v0.1.1 at the commit of #3's branch, by Bob; and four
    branches, those of #2 and #3 at their pull requests' heads, that of #5 at
    another commit than its pull request's head, and wip/idea, the head of no
    pull request."""
    h = source.hashes
    mirror = root / "mirror-extra.git"
    shutil.copytree(source.mirror, mirror, symlinks=True)
    git = Git(base_env, root)
    branches = {"wip/idea": "C5", "feat/2-thing": "B2", "fix/3-parser": "F1", "docs/5-notes": "N1"}
    for branch, name in branches.items():
        git("--git-dir", mirror, "update-ref", f"refs/heads/{branch}", h[name])
    git("--git-dir", mirror, "tag", "v0.1", h["M2"])
    git(
        *("--git-dir", mirror, "tag", "-a", "v0.2", "-m", f"Second, after {h['C4'][:7]}", h["C5"]),
        env=as_committer(ADA_OLD, "2026-03-07T15:00:00+02:00"),
    )
    git(
        *("--git-dir", mirror, "tag", "-a", "v0.1.1", "-m", "Parser fix", h["F1"]),
        env=as_committer(BOB, "2026-03-04T10:30:00+00:00"),
    )
    return mirror


def release(release_id, tag, name, draft, prerelease, target, body, created, published):
    """A release as GitHub lists it, by ada-example."""
    return {
        "id": release_id,
        "tag_name": tag,
        "name": name,
        "draft": draft,
        "prerelease": prerelease,
        "target_commitish": target,
        "body": body,
        "author": {"login": "ada-example"},
        "created_at": created,
        "published_at": published,
    }


RELEASES = f"{API_BASE}_releases"


@pytest.fixture(scope="session")
def api_extra(root, run_plan, hashes):
    """api-extra: a copy of the API of run.jsonl with three releases: v0.2,
    published and the latest, whose body names a commit by its hash, with two
    assets, one without a digest; v0.1.1, a pre-release; and v0.3, a draft for
    main, whose tag the source lacks."""
    folder = root / "api-extra"
    shutil.copytree(run_plan.api, folder)
    c4 = hashes["C4"]
    releases = [
        release(2, "v0.3", "Next", True, False, "main", "Planned.", "2026-03-08T13:00:00Z", None),
        release(
            *(1, "v0.2", "Second", False, False, "main", f"Built from {c4[:7]}."),
            *("2026-03-07T12:00:00Z", "2026-03-07T15:00:00Z"),
        ),
        release(
            *(3, "v0.1.1", "Parser fix", False, True, "fix/3-parser", ""),
            *("2026-03-04T09:00:00Z", "2026-03-04T11:00:00Z"),
        ),
    ]
    (folder / f"{RELEASES}-1.json").write_text(json.dumps(releases), encoding="utf-8")
    (folder / f"{RELEASES}_latest.json").write_text(json.dumps(releases[1]), encoding="utf-8")
    assets = []
    for asset_id, name, label, kind, digested in (
        (11, "tool.tar.gz", "", "application/gzip", True),
        (12, "notes.txt", "Release notes", "text/plain", False),
    ):
        data = (folder / f"{RELEASES}_assets_{asset_id}.bin").read_bytes()
        digest = "sha256:" + hashlib.sha256(data).hexdigest() if digested else None
        assets.append(
            {
                "id": asset_id,
                "name": name,
                "label": label,
                "content_type": kind,
                "size": len(data),
                "state": "uploaded",
                "digest": digest,
            }
        )
    (folder / f"{RELEASES}_1_assets-1.json").write_text(json.dumps(assets), encoding="utf-8")
    return folder


@pytest.fixture(scope="session")
def api_extra_del(root, api_extra):
    """api-extra-del: the same source deleting head branches on merge."""
    folder = root / "api-extra-del"
    shutil.copytree(api_extra, folder)
    (folder / f"{API_BASE}.json").write_text(
        '{"default_branch": "main", "delete_branch_on_merge": true}\n', encoding="utf-8"
    )
    return folder


@pytest.fixture(scope="session")
def leave(root):
    """$T/leave: a file of --leave-behind that accepts the two branches the
    plans of mirror-extra.git leave behind, two tags and two releases they
    carry, and a tag the source lacks."""
    path = root / "leave"
    path.write_text(
        "# left to the archive\nbranch docs/5-notes\nbranch wip/idea\ntag v0.1\ntag v0.2\n"
        "release v0.2\nrelease v0.3\ntag v9\n",
        encoding="utf-8",
    )
    return path


@pytest.fixture(scope="session")
def leave_branches(root):
    """leave-branches: a file of --leave-behind that accepts those two branches alone."""
    path = root / "leave-branches"
    path.write_text("branch docs/5-notes\nbranch wip/idea\n", encoding="utf-8")
    return path


@pytest.fixture(scope="session")
def plan_extra(source, plan, source_gh, mirror_extra):
    """Plans mirror-extra.git, or another mirror where one is given, against
    the API folder given, into the event file given, with --types and the
    options given, as plan_extra, plan_odd, plan_msg and plan_drafts of the
    shell test do; merged as run() takes it."""
    gh = source_gh("extra-gh")

    def plan_extra(api, events, *options, mirror=None, merged=False):
        mirror = mirror or mirror_extra
        return plan(
            *("--types", source.types, *options, mirror, TOOL, source.mailmap, events),
            env=gh.using(FAKE_GH_API=api),
            merged=merged,
        )

    return plan_extra


@pytest.fixture(scope="session")
def extra_plan(root, api_extra, leave, plan_extra):
    """extra.jsonl: the plan of mirror-extra.git that carries three tags and
    three releases and leaves behind two branches, as $T/leave accepts them;
    its standard output and error apart."""
    events = root / "extra.jsonl"
    return Planned(events, api_extra, plan_extra(api_extra, events, "--leave-behind", leave))


@dataclass(frozen=True)
class Pasted:
    """A plan that stops at what no --leave-behind accepts, its standard error
    apart; the file of --leave-behind made of the lines it printed; and the
    plan made again with that file, its output and error in one."""

    stop: Planned
    leave: Path
    planned: Planned


def leave_lines(text):
    """The lines of a stop's message that name what the replay leaves behind,
    each with its newline, as grep '^  [a-z]* ' prints them."""
    return "".join(f"{line}\n" for line in lines(text) if re.match(r"  [a-z]* ", line))


@pytest.fixture(scope="session")
def plan_pasted(root, plan_extra):
    """Plans a mirror against an API folder into the event file stop, writes
    the lines it stops with to the file leave, and plans it again with them
    as --leave-behind into the event file events; all three in the session's
    folder."""

    def plan_pasted(api, mirror, stop, leave, events):
        stop, leave, events = root / stop, root / leave, root / events
        stopped = plan_extra(api, stop, mirror=mirror)
        leave.write_text(leave_lines(stopped.err), encoding="utf-8")
        again = plan_extra(api, events, "--leave-behind", leave, mirror=mirror, merged=True)
        return Pasted(Planned(stop, api, stopped), leave, Planned(events, api, again))

    return plan_pasted


@pytest.fixture(scope="session")
def mirror_odd(root, base_env, hashes, mirror_extra):
    """mirror-odd.git: mirror-extra.git with a tag v0.3 of the annotated tag
    v0.2, a tag of a tree, and a tag whose name holds a no-break space, at a
    commit that only refs/pull/7/head holds, which the replay does not
    recreate. The first is named v0.3, so that the draft of that name stands
    on a tag the replay leaves behind."""
    mirror = root / "mirror-odd.git"
    shutil.copytree(mirror_extra, mirror, symlinks=True)
    git = Git(base_env, root)
    git(
        "-c",
        "advice.nestedTag=false",
        "--git-dir",
        mirror,
        "tag",
        "-a",
        "v0.3",
        "-m",
        "Third",
        "v0.2",
    )
    git("--git-dir", mirror, "tag", "tree-tag", f"{hashes['C5']}^{{tree}}")
    git("--git-dir", mirror, "tag", NBSP_TAG, hashes["S1"])
    return mirror


# The message of the tag notes: the lines of a signature in its text, which
# git takes for no signature, since text follows them.
NOTES_MESSAGE = (
    "Release notes\n\n-----BEGIN PGP SIGNATURE-----\nthis is documentation\n"
    "-----END PGP SIGNATURE-----\n\nmore text after\n"
)


@pytest.fixture(scope="session")
def mirror_msg(root, base_env, hashes, mirror_extra):
    """mirror-msg.git: mirror-extra.git with an annotated tag notes by Bob,
    whose message, in notes-message of the session's folder, holds the lines
    of a signature in its text; and two tags that git tag refuses to create,
    set with update-ref: HEAD, annotated, and -x, lightweight."""
    mirror = root / "mirror-msg.git"
    shutil.copytree(mirror_extra, mirror, symlinks=True)
    message = root / "notes-message"
    message.write_text(NOTES_MESSAGE, encoding="utf-8")
    git = Git(base_env, root)
    git(
        *("--git-dir", mirror, "tag", "-a", "-F", message, "notes", hashes["C5"]),
        env=as_committer(BOB, "2026-03-07T16:00:00+00:00"),
    )
    notes = git("--git-dir", mirror, "rev-parse", "refs/tags/notes")
    git("--git-dir", mirror, "update-ref", "refs/tags/HEAD", notes)
    git("--git-dir", mirror, "update-ref", "refs/tags/-x", hashes["C5"])
    return mirror


@pytest.fixture(scope="session")
def msg_plans(api_extra, mirror_msg, plan_pasted):
    """The plan of mirror-msg.git that stops, msg-stop.jsonl, and the plan with
    the lines it printed as --leave-behind, msg.jsonl."""
    return plan_pasted(api_extra, mirror_msg, "msg-stop.jsonl", "leave-msg", "msg.jsonl")


@pytest.fixture(scope="session")
def off_plan(root, api_extra, leave_branches, plan_extra):
    """off.jsonl: the plan of mirror-extra.git with --no-tags --no-releases,
    whose --leave-behind accepts its branches alone; its standard output and
    error apart."""
    events = root / "off.jsonl"
    options = ("--no-tags", "--no-releases", "--leave-behind", leave_branches)
    return Planned(events, api_extra, plan_extra(api_extra, events, *options))


@pytest.fixture(scope="session")
def api_drafts(root, api_extra, hashes):
    """api-drafts: api-extra with two more drafts whose tags the source lacks,
    v0.9 for a commit the replay recreates, named by a prefix of its hash,
    with an asset whose name needs percent-encoding in a URL, and v1.0-rc for
    the branch wip/idea, which it does not push; a draft on the tag v0.2,
    beside the published release of that tag; a published release on v0.1,
    published after v0.2, which stays the latest; and an asset of v0.2 that an
    upload left in the state starter."""
    folder = root / "api-drafts"
    shutil.copytree(api_extra, folder)
    page = folder / f"{RELEASES}-1.json"
    releases = json.loads(page.read_text(encoding="utf-8"))
    c4 = hashes["C4"]
    for release_id, tag, name, target, created in (
        (4, "v0.9", "Tidied", c4[:9], "2026-03-06T12:00:00Z"),
        (5, "v1.0-rc", "Candidate", "wip/idea", "2026-03-06T12:00:00Z"),
        (6, "v0.2", "Second, again", "main", "2026-03-07T12:00:00Z"),
    ):
        releases.append(
            {
                "id": release_id,
                "tag_name": tag,
                "name": name,
                "draft": True,
                "prerelease": False,
                "target_commitish": target,
                "body": "",
                "created_at": created,
                "published_at": None,
            }
        )
    releases.append(
        {
            "id": 7,
            "tag_name": "v0.1",
            "name": "First",
            "draft": False,
            "prerelease": False,
            "target_commitish": "main",
            "body": "",
            "created_at": "2026-03-02T10:00:00Z",
            "published_at": "2026-03-09T10:00:00Z",
        }
    )
    page.write_text(json.dumps(releases), encoding="utf-8")
    assets = folder / f"{RELEASES}_1_assets-1.json"
    listed = json.loads(assets.read_text(encoding="utf-8"))
    listed.append(
        {
            "id": 13,
            "name": "broken.zip",
            "label": "",
            "content_type": "application/zip",
            "size": 0,
            "state": "starter",
            "digest": None,
        }
    )
    assets.write_text(json.dumps(listed), encoding="utf-8")
    data = b"Tidied up\n"
    (folder / f"{RELEASES}_assets_14.bin").write_bytes(data)
    asset = {
        "id": 14,
        "name": "notes+v0.9.txt",
        "label": "",
        "content_type": "text/plain",
        "size": len(data),
        "state": "uploaded",
        "digest": "sha256:" + hashlib.sha256(data).hexdigest(),
    }
    (folder / f"{RELEASES}_4_assets-1.json").write_text(json.dumps([asset]), encoding="utf-8")
    return folder


@pytest.fixture(scope="session")
def drafts_plan(root, api_drafts, leave_branches, plan_extra):
    """drafts.jsonl: the plan of mirror-extra.git against api-drafts, whose
    --leave-behind, leave-drafts, accepts its branches and the draft
    v1.0-rc; its standard output and error apart."""
    leave = root / "leave-drafts"
    leave.write_text(
        leave_branches.read_text(encoding="utf-8") + "release v1.0-rc\n", encoding="utf-8"
    )
    events = root / "drafts.jsonl"
    return Planned(events, api_drafts, plan_extra(api_drafts, events, "--leave-behind", leave))
