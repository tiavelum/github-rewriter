"""The fixtures and helpers of the suite that tests the replay scripts.

The suite runs each script as a process, as a user runs it, with the
interpreter that runs pytest, against a source it builds once per session in
a temporary folder: a mirror with pull request refs, made by
rewrite/backup-mirror.sh, and a fake gh, first on PATH, that answers the
source's API from JSON files the fixtures write. GitHub is never contacted,
and the developer's own git configuration is not read.
"""

import json
import os
import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

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


def run(args, env, cwd):
    done = subprocess.run(
        [str(a) for a in args],
        env=env,
        cwd=cwd,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    return Result(done.returncode, done.stdout, done.stderr)


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

    def plan(*args, env):
        return run([sys.executable, REPLAY / "plan-replay.py", *args], env, root)

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
