#!/usr/bin/env python3
"""Replays a GitHub repository into a new one with one command: reads a run
file, mirrors and plans the source, asks once for confirmation, then creates
the target, replays the source into it, compares the two and moves the
sub-issue links on its own, and prints the commands that give the replay the
source's name, which stay yours to run.

  replay.py <name>.run.json

The run file holds JSON with the fields that replay/README.md lists; keep it
outside any repository, since it holds the mailmap. Before the confirmation
replay.py writes nothing on GitHub, and it stops where a title would get a
guessed type or the target exists already. It runs backup-mirror.sh,
plan-replay.py, run-replay.py and compare-replay.py as processes, writes to
GitHub through gh api and run-replay.py only, and keeps its progress in
<name>.progress.json next to the run file, so that the same command resumes
a stopped run.
"""

import hashlib
import json
import os
import re
import shlex
import signal
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

PROG = "replay.py"
HERE = Path(__file__).resolve().parent
MIRROR_SCRIPT = HERE.parent / "rewrite" / "backup-mirror.sh"
FORMAT = 1
SLUG = re.compile(r"[\w.-]+/[\w.-]+")
ADDRESS = re.compile(r"[^@\s]+@[^@\s]+")
STEPS = ("mirror", "plan", "create", "settings", "replay", "compare", "links", "commands")
REQUIRED = ("source", "target", "mailmap")
DEFAULTS = {
    "final_name": None,
    "types": [],
    "sign": None,
    "keep_merges": False,
    "with_times": False,
    "no_types": False,
    "pace": 1,
    "backup": "~/vc-backup",
    "clone_url": None,
}
# The settings of the source that the replay takes over at the end.
SETTINGS = (
    "allow_merge_commit",
    "allow_squash_merge",
    "allow_rebase_merge",
    "delete_branch_on_merge",
    "has_wiki",
    "has_projects",
    "has_discussions",
)
# The parts of security_and_analysis that the replay takes over, where GitHub
# reports them for the source.
SECURITY = ("secret_scanning", "secret_scanning_push_protection")
RETRIES = 5
# GitHub's guidance for a secondary rate limit without retry-after: wait at
# least a minute, longer with each retry.
RATE_LIMIT_WAIT = 60
TRANSIENT_WAIT = 5


class ReplayError(Exception):
    """Ends the run with a message; main() names the step it stopped in."""


def usage(status=2):
    print(__doc__.strip("\n"), file=sys.stderr if status else sys.stdout)
    sys.exit(status)


def run(args, stdin=None):
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    try:
        return subprocess.run(
            args,
            input=stdin,
            stdin=subprocess.DEVNULL if stdin is None else None,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
        )
    except FileNotFoundError:
        raise ReplayError(f"{args[0]} is missing") from None


def child(args, capture=False):
    """Runs one of the other scripts with the terminal's output; a Ctrl-C
    reaches it and stops it the way it stops on its own, not this one."""
    previous = signal.signal(signal.SIGINT, lambda *_: None)
    try:
        return subprocess.run(
            [str(a) for a in args],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE if capture else None,
            text=True,
        )
    except FileNotFoundError:
        raise ReplayError(f"{args[0]} is missing") from None
    finally:
        signal.signal(signal.SIGINT, previous)


def parse_response(out):
    """Status, headers and JSON body of what gh api --include printed."""
    if not out.startswith("HTTP/"):
        return None, {}, None
    end = re.search(r"\r?\n\r?\n", out)
    head, body = (out[: end.start()], out[end.end() :]) if end else (out, "")
    lines = head.splitlines()
    headers = {}
    for line in lines[1:]:
        name, _, value = line.partition(":")
        headers[name.strip().lower()] = value.strip()
    try:
        data = json.loads(body) if body.strip() else None
    except ValueError:
        data = {"message": body.strip()[:200]}
    return int(lines[0].split()[1]), headers, data


def message_of(data):
    if not isinstance(data, dict):
        return ""
    parts = [str(data.get("message", ""))]
    parts += [e.get("message") or e.get("code") or "" for e in data.get("errors") or []]
    return "; ".join(p for p in parts if p)


class Api:
    """Calls gh api, at least pace seconds after the end of the previous write,
    and waits out GitHub's rate limits as run-replay.py does."""

    def __init__(self, pace):
        self.pace, self.last_write = pace, None

    def call(self, method, endpoint, body=None):
        write = method != "GET"
        args = ["gh", "api", "--include", "--method", method, endpoint]
        payload = None
        if body is not None:
            args += ["--input", "-"]
            payload = json.dumps(body)
        for attempt in range(RETRIES + 1):
            if write and self.last_write is not None:
                time.sleep(max(0, self.last_write + self.pace - time.monotonic()))
            result = run(args, payload)
            if write:
                self.last_write = time.monotonic()
            status, headers, data = parse_response(result.stdout)
            wait = None
            if status in (403, 429):
                if headers.get("retry-after", "").isdigit():
                    wait = max(1, int(headers["retry-after"]))
                elif status == 429 or "rate limit" in message_of(data).lower():
                    wait = RATE_LIMIT_WAIT * 2**attempt
            if wait is None and not write and (status is None or status >= 500):
                wait = TRANSIENT_WAIT
            if wait is None:
                if status is None:
                    error = result.stderr.strip().splitlines()
                    raise ReplayError(f"{method} {endpoint}: no answer from GitHub: {error[-1:]}")
                return status, data
            if attempt == RETRIES:
                raise ReplayError(f"{method} {endpoint}: still refused after {RETRIES} retries")
            print(f"      HTTP {status} on {method} {endpoint}; waiting {wait} s", flush=True)
            time.sleep(wait)
        raise AssertionError("unreachable")

    def expect(self, method, endpoint, body=None, ok=(200,)):
        status, data = self.call(method, endpoint, body)
        if status not in ok:
            raise ReplayError(f"{method} {endpoint} answered HTTP {status}: {message_of(data)}")
        return data

    def pages(self, endpoint):
        joiner = "&" if "?" in endpoint else "?"
        entries, page = [], 1
        while True:
            batch = self.expect("GET", f"{endpoint}{joiner}per_page=100&page={page}")
            if not batch:
                return entries
            entries.extend(batch)
            page += 1


def read_run_file(path):
    """The fields of the run file, with their defaults, and its SHA-256."""
    try:
        raw = path.read_bytes()
        fields = json.loads(raw)
    except OSError as error:
        raise ReplayError(f"cannot read {path}: {error.strerror}") from None
    except ValueError as error:
        raise ReplayError(f"{path} holds no JSON: {error}") from None
    if not isinstance(fields, dict):
        raise ReplayError(f"{path} holds no JSON object")
    unknown = sorted(set(fields) - set(DEFAULTS) - set(REQUIRED))
    if unknown:
        raise ReplayError(f"{path} has fields replay.py does not know: {', '.join(unknown)}")
    missing = [f for f in REQUIRED if f not in fields]
    if missing:
        raise ReplayError(f"{path} lacks the fields {', '.join(missing)}")
    cfg = {**DEFAULTS, **fields}
    cfg["final_name"] = cfg["final_name"] or cfg["source"]

    def check(field, holds, what):
        if not holds(cfg[field]):
            raise ReplayError(f"{path}: {field} must be {what}")

    for field in ("source", "final_name", "target"):
        check(field, lambda v: isinstance(v, str) and SLUG.fullmatch(v), "owner/repo")
    for field in ("mailmap", "types"):
        check(
            field,
            lambda v: isinstance(v, list) and all(isinstance(x, str) and "\n" not in x for x in v),
            "a list of lines",
        )
    check("mailmap", bool, "a list of at least one line")
    for field in ("keep_merges", "with_times", "no_types"):
        check(field, lambda v: isinstance(v, bool), "true or false")
    check(
        "pace",
        lambda v: isinstance(v, int | float) and not isinstance(v, bool) and v >= 0,
        "a number of seconds",
    )
    check(
        "sign", lambda v: v is None or (isinstance(v, str) and ADDRESS.fullmatch(v)), "an address"
    )
    check("backup", lambda v: isinstance(v, str) and v, "a folder")
    check("clone_url", lambda v: v is None or (isinstance(v, str) and v), "a clone URL")

    owner, name = cfg["target"].split("/")
    final_owner, final_repo = cfg["final_name"].split("/")
    # The day-only form stays for run files written before the time was added;
    # remove it once no open run issue's target uses it.
    day = re.fullmatch(re.escape(final_repo) + r"-replay-(\d{8})(-\d{4})?", name)
    try:
        dated = day and datetime.strptime(day[1] + (day[2] or "-0000"), "%Y%m%d-%H%M")
    except ValueError:
        dated = None
    if owner.lower() != final_owner.lower() or not dated:
        raise ReplayError(
            f"{path}: target must be {final_owner}/{final_repo}-replay-<YYYYMMDD-HHMM>, the"
            " final name with the day and time of the replay, so that the rename keeps its owner"
            " and no earlier replay has used the name"
        )
    return cfg, hashlib.sha256(raw).hexdigest()


def repo_of(issue):
    return issue["repository_url"].split("/repos/", 1)[1]


class OneCommand:
    def __init__(self, run_file):
        self.run_file = run_file
        self.cfg, self.digest = read_run_file(run_file)
        self.source, self.target = self.cfg["source"], self.cfg["target"]
        self.final = self.cfg["final_name"]
        self.progress_path = run_file.with_name(
            run_file.name[: -len(".run.json")] + ".progress.json"
        )
        self.api = Api(self.cfg["pace"])
        self.progress = None
        self.step = None

    # Progress

    def load_progress(self):
        if not self.progress_path.exists():
            return False
        try:
            progress = json.loads(self.progress_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            raise ReplayError(f"cannot read {self.progress_path}: {error}") from None
        if progress.get("format") != FORMAT or progress.get("run_file") != self.digest:
            raise ReplayError(
                f"{self.run_file} changed since its run was confirmed, as {self.progress_path}"
                " records; undo the change to resume, or replay into a new target with a new"
                " run file"
            )
        self.progress = progress
        self.mirror, self.events = Path(progress["mirror"]), Path(progress["events"])
        for path in (self.mirror, self.events):
            if not path.exists():
                raise ReplayError(f"{path}, which {self.progress_path} records, is missing")
        return True

    def save_progress(self):
        partial = self.progress_path.with_name(self.progress_path.name + ".partial")
        partial.write_text(json.dumps(self.progress, indent=1) + "\n", encoding="utf-8")
        partial.replace(self.progress_path)

    def done(self, step):
        self.progress["done"].append(step)
        self.save_progress()

    def begin(self, step, what):
        self.step = step
        print(f"Step {STEPS.index(step) + 1} of {len(STEPS)}, {step}: {what}", flush=True)

    # Before the confirmation

    def check_place(self):
        inside = run(["git", "-C", str(self.run_file.parent), "rev-parse", "--is-inside-work-tree"])
        if inside.returncode == 0 and inside.stdout.strip() == "true":
            raise ReplayError(
                f"{self.run_file} lies in a git work tree; keep it outside any repository,"
                " since it holds the mailmap"
            )

    def check_target_absent(self):
        status, data = self.api.call("GET", f"repos/{self.target}")
        if status == 200:
            named = (data or {}).get("full_name", self.target)
            raise ReplayError(
                f"GitHub has {self.target} already, as {named}; replay only into a new repository,"
                " with another day in target"
            )
        if status != 404:
            raise ReplayError(f"GET repos/{self.target} answered HTTP {status}: {message_of(data)}")

    def make_mirror(self):
        self.begin("mirror", f"mirror {self.source}")
        backup = Path(self.cfg["backup"]).expanduser()
        url = self.cfg["clone_url"] or self.source
        result = child(["sh", MIRROR_SCRIPT, url, backup], capture=True)
        if result.returncode:
            raise ReplayError("backup-mirror.sh stopped; its message stands above")
        made = result.stdout.strip().splitlines()
        if not made or not made[-1].endswith(".git"):
            raise ReplayError("backup-mirror.sh named no mirror")
        self.mirror = Path(made[-1])
        print(self.mirror)
        self.events = self.mirror.with_name(self.mirror.name[: -len(".git")] + ".jsonl")

    def plan(self):
        self.begin("plan", f"plan the replay into {self.events}")
        with tempfile.TemporaryDirectory(prefix="replay-") as folder:
            mailmap, types = Path(folder) / "mailmap", Path(folder) / "types"
            mailmap.write_text("".join(f"{x}\n" for x in self.cfg["mailmap"]), encoding="utf-8")
            args = [sys.executable, HERE / "plan-replay.py"]
            if self.cfg["types"]:
                types.write_text("".join(f"{x}\n" for x in self.cfg["types"]), encoding="utf-8")
                args += ["--types", types]
            args += ["--no-types"] * self.cfg["no_types"] + ["--keep-merges"] * self.cfg[
                "keep_merges"
            ]
            result = child([*args, self.mirror, self.source, mailmap, self.events])
        if result.returncode:
            raise ReplayError("plan-replay.py stopped; its message stands above")
        guessed = 0
        for line in self.events.read_text(encoding="utf-8").splitlines()[1:]:
            e = json.loads(line)
            guessed += e.get("type_from") == "guess"
            guessed += sum(c["type_from"] == "guess" for c in e.get("commits", []))
        if guessed:
            raise ReplayError(
                f"{guessed} title{'s' if guessed > 1 else ''} would get a guessed type, marked"
                f" guessed above; give each its type in types of {self.run_file} and run again."
                f" The mirror {self.mirror} and the event file {self.events} stay; the next run"
                " makes new ones"
            )

    def survey_links(self):
        """The sub-issue links of the source's issues: those under a parent
        elsewhere, and the sub-issues of each issue that has some."""
        self.outside, self.parents = [], []
        issues = self.api.pages(f"repos/{self.source}/issues?state=all")
        for issue in sorted(issues, key=lambda i: i["number"]):
            if "pull_request" in issue:
                continue
            n = issue["number"]
            # GitHub's issue object has parent_issue_url only for a sub-issue.
            if issue.get("parent_issue_url"):
                parent = self.api.expect("GET", f"repos/{self.source}/issues/{n}/parent")
                if repo_of(parent).lower() != self.source.lower():
                    self.outside.append((n, issue["id"], repo_of(parent), parent["number"]))
            if (issue.get("sub_issues_summary") or {"total": 1})["total"]:
                children = self.api.pages(f"repos/{self.source}/issues/{n}/sub_issues")
                if children:
                    self.parents.append((n, [(repo_of(c), c["number"], c["id"]) for c in children]))
        self.check_owners()

    def check_owners(self):
        """GitHub links a sub-issue only to a parent of the same owner, so each
        repository a link of the replay reaches has to belong to the target's."""
        owner = self.target.split("/")[0]
        crossing = [
            f"#{n} under {repo}#{p}"
            for n, _, repo, p in self.outside
            if repo.split("/")[0].lower() != owner.lower()
        ]
        crossing += [
            f"{repo}#{c} under #{n}"
            for n, children in self.parents
            for repo, c, _ in children
            if repo.lower() != self.source.lower() and repo.split("/")[0].lower() != owner.lower()
        ]
        if crossing:
            raise ReplayError(
                f"GitHub links a sub-issue only to a parent of the same owner, and the target's"
                f" owner is {owner}: {'; '.join(crossing)}. GitHub refuses such a link whoever"
                " makes it, so replay.py cannot carry it. Move or remove these links in the"
                " source first, or replay with plan-replay.py and run-replay.py alone, which"
                " leave links alone, and leave these links out of the first move in the README's"
                " Taking over the source's name"
            )

    def describe_links(self):
        lines = [
            f"#{n}: in {repo}#{p}, links the replay's #{n} in the place of the source's and"
            f" unlinks the source's (writes in {repo})"
            for n, _, repo, p in self.outside
        ]
        for n, children in self.parents:
            named = [
                f"#{c}"
                if repo.lower() == self.source.lower()
                else f"{repo}#{c}, taken from the source's #{n} with replace_parent (writes in"
                f" {repo} and in the source)"
                for repo, c, _ in children
            ]
            lines.append(
                f"the replay's #{n} gets the sub-issues of the source's: {', '.join(named)}"
            )
        return lines

    def confirm(self, resumed):
        """Prints what the run does from here, and asks once for the target."""
        left = [x for x in STEPS[2:] if not resumed or x not in self.progress["done"]]
        deletes = " and the deletion of head branches on, as the source has it"
        links = self.describe_links()
        what = {
            "create": f"create {self.target}, private and empty",
            "settings": f"turn Actions off in it{deletes if self.deletes else ''}",
            "replay": f"run run-replay.py {' '.join(self.run_options())}, and make {self.default}"
            " the default branch where GitHub names another",
            "compare": "compare the replay with the source with compare-replay.py",
            "links": f"move sub-issue links: {len(links)}",
            "commands": "print the commands that archive the source and rename the replay",
        }
        if resumed:
            print(
                f"Resume the replay of {self.source} into {self.target} at step"
                f" {STEPS.index(left[0]) + 1}, {left[0]}, from {self.progress_path}:"
            )
        else:
            print(f"Replay {self.source} into {self.target}, to be renamed {self.final}:")
        for step in left:
            print(f"  {STEPS.index(step) + 1}. {what[step]}")
            if step == "links":
                for line in links:
                    print(f"       {line}")
        print(f"Type {self.target} to confirm: ", end="", flush=True)
        try:
            answer = sys.stdin.readline().strip()
        except KeyboardInterrupt:
            answer = ""
        if not sys.stdin.isatty():
            # Typed at a terminal, the answer shows as it is typed.
            print(answer)
        if answer != self.target:
            raise ReplayError("not confirmed; nothing changed on GitHub")

    # After the confirmation

    def create(self):
        self.begin("create", f"create {self.target}, private and empty")
        self.check_target_absent()
        owner, name = self.target.split("/")
        login = self.api.expect("GET", "user")["login"]
        endpoint = "user/repos" if owner.lower() == login.lower() else f"orgs/{owner}/repos"
        body = {"name": name, "private": True, "auto_init": False}
        info = self.api.expect("POST", endpoint, body, ok=(201,))
        print(f"  {info.get('html_url', self.target)}")

    def settings(self):
        self.begin("settings", "turn Actions off until the replay is checked")
        self.api.expect(
            "PUT", f"repos/{self.target}/actions/permissions", {"enabled": False}, ok=(204,)
        )
        print("  Actions off")
        if self.deletes:
            self.api.expect("PATCH", f"repos/{self.target}", {"delete_branch_on_merge": True})
            print("  deletion of head branches on, as the source has it")

    def run_options(self):
        pace = format(self.cfg["pace"], "f").rstrip("0").rstrip(".") or "0"
        options = ["--pace", pace, "--final-name", self.final]
        if self.cfg["with_times"]:
            options.append("--with-times")
        if self.cfg["sign"]:
            options += ["--sign", self.cfg["sign"]]
        return options

    def replay(self):
        self.begin("replay", f"run-replay.py into {self.target}")
        # A stopped replay may have pushed the branch already, and run-replay.py
        # checks the default branch once the target has refs.
        self.set_default(pushed=False)
        args = [sys.executable, HERE / "run-replay.py", *self.run_options()]
        result = child([*args, "--confirmed", self.target, self.events, self.mirror, self.target])
        if result.returncode:
            raise ReplayError(f"run-replay.py stopped with status {result.returncode}; see above")
        self.set_default(pushed=True)

    def set_default(self, pushed):
        """Gives the target the source's default branch where GitHub named
        another one at the creation. GitHub's documentation leaves open whether
        an empty repository takes a default branch, so this waits until the
        branch exists: after the replay, or before it where it was pushed."""
        info = self.api.expect("GET", f"repos/{self.target}")
        named = info.get("default_branch")
        if named == self.default or not (pushed or self.default in self.target_branches(info)):
            return
        self.api.expect("PATCH", f"repos/{self.target}", {"default_branch": self.default})
        print(f"  default branch {self.default}, where GitHub had named it {named}")

    def compare(self):
        self.begin("compare", f"compare {self.target} with {self.source}")
        args = [sys.executable, HERE / "compare-replay.py"]
        args += ["--with-times"] * self.cfg["with_times"]
        result = child([*args, self.events, self.mirror, self.target])
        if result.returncode:
            raise ReplayError(
                "compare-replay.py found differences or could not compare; see above. Remove"
                " their cause, or take the remaining steps by hand where a difference is meant"
            )

    def target_id(self, n):
        return self.api.expect("GET", f"repos/{self.target}/issues/{n}")["id"]

    def sub_ids(self, repo, n):
        return [c["id"] for c in self.api.pages(f"repos/{repo}/issues/{n}/sub_issues")]

    def links(self):
        self.begin("links", "move the sub-issue links of the source's issues to the replay's")
        self.survey_links()
        for n, old, repo, p in self.outside:
            new = self.target_id(n)
            listed = self.sub_ids(repo, p)
            if new not in listed:
                self.api.expect(
                    "POST", f"repos/{repo}/issues/{p}/sub_issues", {"sub_issue_id": new}, ok=(201,)
                )
            # After the sub-issue before the source's, or before the one after it
            # where the source's is first, the link takes its place once that one
            # goes; without the new link in the list, a resume finds the same one.
            others = [i for i in listed if i != new]
            at = others.index(old)
            if at:
                anchor = {"after_id": others[at - 1]}
            else:
                anchor = {"before_id": others[1]} if len(others) > 1 else None
            if anchor:
                self.api.expect(
                    "PATCH",
                    f"repos/{repo}/issues/{p}/sub_issues/priority",
                    {"sub_issue_id": new, **anchor},
                )
            self.api.expect("DELETE", f"repos/{repo}/issues/{p}/sub_issue", {"sub_issue_id": old})
            print(f"  #{n} under {repo}#{p}, in the place of the source's")
        for n, children in self.parents:
            present = self.sub_ids(self.target, n)
            for repo, c, old in children:
                inside = repo.lower() == self.source.lower()
                new = self.target_id(c) if inside else old
                if new in present:
                    continue
                # A sub-issue has one parent, so one from elsewhere leaves the source's.
                body = {"sub_issue_id": new, **({} if inside else {"replace_parent": True})}
                self.api.expect(
                    "POST", f"repos/{self.target}/issues/{n}/sub_issues", body, ok=(201,)
                )
                present.append(new)
                print(f"  {'#' if inside else repo + '#'}{c} under the replay's #{n}")

    def commands(self):
        self.begin("commands", "what is left to you")
        owner, name = self.source.split("/")
        final_repo = self.final.split("/")[1]
        lines, notes = [], []
        if self.final.lower() == self.source.lower():
            archive = f"{owner}/{name}-archive"
            if self.api.call("GET", f"repos/{archive}")[0] != 404:
                notes.append(f"{archive} exists already: give the archive another name below")
            lines += [
                f"gh api -X PATCH repos/{self.source} -f name={name}-archive",
                f"gh api -X PATCH repos/{archive} -F archived=true",
            ]
        else:
            lines.append(f"gh api -X PATCH repos/{self.source} -F archived=true")
        lines.append(f"gh api -X PATCH repos/{self.target} -f name={final_repo}")
        status, actions = self.api.call("GET", f"repos/{self.source}/actions/permissions")
        enabled = (actions or {}).get("enabled", True) if status == 200 else True
        if status != 200:
            notes.append(
                "GitHub did not say whether the source has Actions on; the command turns them on"
            )
        actions_on = str(enabled).lower()
        lines.append(
            f"gh api -X PUT repos/{self.final}/actions/permissions -F enabled={actions_on}"
        )
        fields = [
            f"-F {key}={str(self.info[key]).lower()}"
            for key in SETTINGS
            if isinstance(self.info.get(key), bool)
        ]
        fields.append("-f " + shlex.quote(f"description={self.info.get('description') or ''}"))
        lines.append(f"gh api -X PATCH repos/{self.final} {' '.join(fields)}")
        # The target is created private, so that nobody sees it before the
        # checks; a source of another visibility gets it back only here.
        private = self.info.get("private", True)
        visibility = self.info.get("visibility") or ("private" if private else "public")
        if visibility != "private":
            lines.append(f"gh api -X PATCH repos/{self.final} -f visibility={visibility}")
        # After the visibility, since a private repository on a free account has neither.
        security = self.info.get("security_and_analysis") or {}
        statuses = [
            (key, (security.get(key) or {}).get("status"))
            for key in SECURITY
            if (security.get(key) or {}).get("status") in ("enabled", "disabled")
        ]
        if statuses:
            fields = [
                "-f " + shlex.quote(f"security_and_analysis[{key}][status]={status}")
                for key, status in statuses
            ]
            lines.append(f"gh api -X PATCH repos/{self.final} {' '.join(fields)}")
        lines += [
            f"gh api -X DELETE repos/{self.final}/git/refs/heads/{branch}"
            for branch in self.extra_branches()
        ]
        stem = self.events.name[: -len(".jsonl")]
        state, work = (self.events.with_name(stem + x) for x in (".state.json", ".work.git"))
        print(
            "1. Check what compare-replay.py cannot see in the source: its secrets, variables,"
            " webhooks, deploy keys and collaborators. Where a count is not 0, or a collaborator"
            " other than you shows, carry it over to the replay by hand:"
        )
        print()
        for read in (
            "actions/secrets --jq .total_count",
            "actions/variables --jq .total_count",
            "hooks --jq length",
            "keys --jq length",
            "collaborators --jq '.[].login'",
        ):
            print(f"gh api repos/{self.source}/{read}")
        print()
        print(
            "2. Archive the source under a new name, give the replay its name, Actions,"
            " settings and, where the source is not private, visibility and secret scanning,"
            " and delete the branches the source no longer has:"
        )
        for note in notes:
            print(f"   note: {note}")
        print()
        for line in lines:
            print(line)
        print()
        clone = f"~/vc/{final_repo}"
        print(
            f"3. Replace your clone of {self.source} with a fresh clone of the replay; these"
            f" commands take it at {clone} and keep the old one, after showing what it holds"
            f" uncommitted, in {clone}-old for you to delete:"
        )
        print()
        print(f"test ! -d {clone} || {{ git -C {clone} status --short; mv {clone} {clone}-old; }}")
        print(f"gh repo clone {self.final} {clone}")
        print()
        print(f"4. Delete {self.progress_path}, {state} and {work}.")

    def target_branches(self, info):
        """The branches of the target, as git ls-remote lists them."""
        protocol = run(["gh", "config", "get", "git_protocol"]).stdout.strip()
        remote = info["ssh_url"] if protocol == "ssh" else info["clone_url"]
        listed = run(["git", "ls-remote", "--heads", remote])
        if listed.returncode:
            raise ReplayError(f"git ls-remote of {self.target} failed: {listed.stderr.strip()}")
        return {line.split("\trefs/heads/", 1)[1] for line in listed.stdout.splitlines()}

    def extra_branches(self):
        """The branches of the target that the mirror of the source lacks."""
        target = self.target_branches(self.api.expect("GET", f"repos/{self.target}"))
        source = run(
            [
                "git",
                "-C",
                str(self.mirror),
                "for-each-ref",
                "--format=%(refname:short)",
                "refs/heads/",
            ]
        )
        return sorted(target - set(source.stdout.split()))

    def main(self):
        self.step = "check"
        self.check_place()
        resumed = self.load_progress()
        self.info = self.api.expect("GET", f"repos/{self.source}")
        self.default = self.info["default_branch"]
        self.deletes = bool(self.info.get("delete_branch_on_merge"))
        if not resumed:
            self.check_target_absent()
            self.make_mirror()
            self.plan()
        self.step = "survey"
        self.survey_links()
        self.step = "confirm"
        self.confirm(resumed)
        if not resumed:
            self.progress = {
                "format": FORMAT,
                "run_file": self.digest,
                "target": self.target,
                "mirror": str(self.mirror),
                "events": str(self.events),
                "done": [],
            }
            self.save_progress()
        for step in ("create", "settings"):
            if step not in self.progress["done"]:
                getattr(self, step)()
                self.done(step)
        self.replay()
        self.compare()
        self.links()
        self.commands()
        return 0


def main(argv):
    if argv[:1] in (["-h"], ["--help"]):
        usage(0)
    sys.stdout.reconfigure(line_buffering=True)
    if len(argv) != 1 or argv[0].startswith("-") or not argv[0].endswith(".run.json"):
        usage()
    one = None
    try:
        one = OneCommand(Path(argv[0]))
        return one.main()
    except KeyboardInterrupt:
        print(file=sys.stderr)
        error = ReplayError("interrupted")
    except ReplayError as stop:
        error = stop
    step = one.step if one else "check"
    print(f"{PROG}: {error}", file=sys.stderr)
    if step not in STEPS[2:]:
        label = {
            "check": "the checks",
            "mirror": f"step 1 of {len(STEPS)}, mirror",
            "plan": f"step 2 of {len(STEPS)}, plan",
            "survey": "the survey of the sub-issue links",
            "confirm": "the confirmation",
        }[step]
        again = "to resume" if one and one.progress_path.exists() else "to start over"
        print(
            f"{PROG}: stopped in {label}, before any write to GitHub in this run; run the same"
            f" command again {again} once the cause is removed",
            file=sys.stderr,
        )
    else:
        print(
            f"{PROG}: stopped in step {STEPS.index(step) + 1} of {len(STEPS)}, {step}; run the"
            " same command again to resume there once the cause is removed",
            file=sys.stderr,
        )
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
