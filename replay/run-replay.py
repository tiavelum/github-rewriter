#!/usr/bin/env python3
"""Applies an event file that plan-replay.py wrote to an empty GitHub
repository, so that the target gets the source's labels, issues, pull
requests, comments and commits under the same numbers.

  run-replay.py [--state <file>] [--with-times] [--pace <seconds>]
                [--sign <address>] [--final-name <owner/repo>]
                [--confirmed <owner/repo>] <event file> <mirror> <owner/repo>

<mirror> is the mirror the event file was planned from; <owner/repo> is the
target. The target must exist and be empty, without commits, issues or pull
requests, unless the state file records an earlier run of the same event
file into it; the run then resumes after the last finished event. The state
file is <event file> with .state.json for .jsonl unless --state names one;
the work repository that holds the recreated commits lies next to it, with
.work.git for .state.json.

Checks that the mirror holds every tree of the event file and that GitHub
answers for the target under the name given, so that a renamed target stops
it, then prints the totals and asks for <owner/repo> to be typed before the
first write; anything else stops without writing. --confirmed gives that answer
instead, for replay.py, which asked for it before it started this run.
Writes to GitHub through gh api and git push only, at least --pace seconds
apart (default 1, the pause GitHub advises between mutative requests), and
waits out GitHub's rate limits: the seconds of retry-after, else until
x-ratelimit-reset where x-ratelimit-remaining is 0, else a minute, doubled at
each of at most 5 retries of the same call; tags it creates in the
work repository and pushes. Each release it creates as a draft; its assets
it downloads from the source into the folder next to the state file, with
.downloads for .state.json, and uploads to the draft, each download removed
once uploaded; then it publishes the release where the source has it
published. --with-times appends the original creation time to each body and
comment, as "_Originally created 2026-03-01 11:00 UTC._" after a blank line,
and to a release's body the time of its publication, or for a draft its
created_at. --sign signs each recreated commit whose committer
has <address>, and each annotated tag whose tagger has it, with the signing
key of your git configuration, after checking that GitHub knows the key as
a signing key; the others stay unsigned, since only their committer or tagger
holds their key. --final-name fills {pr_url} in squash messages with the URL
under the name the target will finally carry.
"""

import bisect
import hashlib
import json
import os
import re
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

PROG = "run-replay.py"
FORMAT = 1
STATE_FORMAT = 1
KINDS = (
    "create-label",
    "push-commits",
    "push-branch",
    "create-issue",
    "create-pull",
    "add-comment",
    "merge-pull",
    "close-item",
    "create-tag",
    "create-release",
)
HASH_IN_TEXT = re.compile(r"(?<![0-9A-Za-z])[0-9a-f]{7,40}(?![0-9A-Za-z])")
SAME_REPO_CLOSING_KEYWORD = re.compile(
    r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?):?\s+#(\d+)\b", re.IGNORECASE
)
RETRIES = 5
# GitHub's guidance for a secondary rate limit without retry-after: wait at
# least a minute, longer with each retry.
RATE_LIMIT_WAIT = 60
# GitHub may answer a read with a server error, and refuse a merge or a pull request right
# after what it depends on until it has caught up; these waits have sufficed in practice.
TRANSIENT_WAIT = 5
CATCH_UP_WAIT = 3
# GitHub closes the items a merged pull request names with a closing keyword
# shortly after the merge; close-item waits this long for that.
CLOSE_WAIT = 10
SLUG = re.compile(r"[\w.-]+/[\w.-]+")
SIGNING_KEY_LISTS = {
    "ssh": ("user/ssh_signing_keys", "read:ssh_signing_key", "SSH signing keys"),
    "openpgp": ("user/gpg_keys", "read:gpg_key", "GPG keys"),
}


class ReplayError(Exception):
    pass


def usage(status=2):
    print(__doc__.strip("\n"), file=sys.stderr if status else sys.stdout)
    sys.exit(status)


def run(args, stdin=None, env=None, new_session=False):
    # A git call that needs a password fails instead of waiting for one.
    env = {**(os.environ if env is None else env), "GIT_TERMINAL_PROMPT": "0"}
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
            start_new_session=new_session,
        )
    except FileNotFoundError:
        raise ReplayError(f"{args[0]} is missing") from None


def git(repo, *args, stdin=None, env=None):
    result = run(["git", "-C", str(repo), *args], stdin, env)
    if result.returncode:
        raise ReplayError(f"git {args[0]} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def git_date(stamp):
    # Raw, so that the offset stays.
    moment = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    minutes = int(moment.utcoffset().total_seconds()) // 60
    sign = "-" if minutes < 0 else "+"
    return f"{int(moment.timestamp())} {sign}{abs(minutes) // 60:02}{abs(minutes) % 60:02}"


def now_date():
    # SOURCE_DATE_EPOCH is how reproducible builds fix the time; its specification advises
    # to stop at a value that is no whole number of seconds, an empty one included.
    fixed = os.environ.get("SOURCE_DATE_EPOCH")
    seconds = int(time.time())
    if fixed is not None:
        if not re.fullmatch(r"[0-9]+", fixed.strip()):
            raise ReplayError(f"SOURCE_DATE_EPOCH is {fixed!r}, not a whole number of seconds")
        seconds = int(fixed)
    try:
        offset = datetime.fromtimestamp(seconds).astimezone().utcoffset()
    except (OverflowError, OSError, ValueError):
        raise ReplayError(f"SOURCE_DATE_EPOCH {fixed!r} is no time this machine can date") from None
    minutes = int(offset.total_seconds()) // 60
    sign = "-" if minutes < 0 else "+"
    return seconds, f"{sign}{abs(minutes) // 60:02}{abs(minutes) % 60:02}"


def parse_response(out):
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


def git_config(name):
    result = run(["git", "config", "--get", name])
    return result.stdout.strip() if result.returncode == 0 and result.stdout.strip() else None


def scopes(header):
    return {s.strip() for s in (header or "").split(",") if s.strip()}


def lacks_scope(headers):
    # An admin: or write: scope also holds its read: scope, as gh counts them.
    held = set()
    for scope in scopes(headers.get("x-oauth-scopes")):
        level, _, name = scope.partition(":")
        held.add(scope)
        if name and level in ("admin", "write"):
            held |= {f"read:{name}", f"write:{name}"}
    return not scopes(headers.get("x-accepted-oauth-scopes")) & held


def message_of(data):
    if not isinstance(data, dict):
        return ""
    parts = [str(data.get("message", ""))]
    for error in data.get("errors") or []:
        if isinstance(error, dict):
            parts.append(error.get("message") or error.get("code") or "")
        else:
            parts.append(str(error))
    return "; ".join(p for p in parts if p)


def rate_limit_wait(status, headers, data, attempt):
    if status not in (403, 429):
        return None
    if headers.get("retry-after", "").isdigit():
        return max(1, int(headers["retry-after"]))
    if (
        headers.get("x-ratelimit-remaining") == "0"
        and headers.get("x-ratelimit-reset", "").isdigit()
    ):
        return max(1, int(headers["x-ratelimit-reset"]) - int(time.time()) + 1)
    if status == 429 or "rate limit" in message_of(data).lower():
        return RATE_LIMIT_WAIT * 2**attempt
    return None


class Api:
    def __init__(self, pace):
        self.pace = pace
        self.last_write = None
        self.headers = {}

    def before_write(self):
        if self.last_write is not None:
            wait = self.last_write + self.pace - time.monotonic()
            if wait > 0:
                time.sleep(wait)

    def after_write(self):
        self.last_write = time.monotonic()

    def call(self, method, endpoint, body=None, headers=(), upload=None):
        write = method != "GET"
        args = ["gh", "api", "--include", "--method", method, endpoint]
        for header in headers:
            args += ["-H", header]
        payload = None
        if upload is not None:
            args += ["--input", str(upload)]
        elif body is not None:
            args += ["--input", "-"]
            payload = json.dumps(body)
        for attempt in range(RETRIES + 1):
            if write:
                self.before_write()
            # A session of its own keeps a Ctrl-C from killing gh in the middle of a call.
            result = run(args, payload, new_session=True)
            if write:
                self.after_write()
            status, headers, data = parse_response(result.stdout)
            self.headers = headers
            wait, why = rate_limit_wait(status, headers, data, attempt), "rate limited"
            if wait is None and not write and (status is None or status >= 500):
                wait, why = TRANSIENT_WAIT, f"HTTP {status}" if status else "no answer"
            if wait is None:
                if status is None:
                    error = result.stderr.strip().splitlines()
                    raise ReplayError(
                        f"{method} {endpoint}: no answer from GitHub: {error[-1] if error else ''}"
                    )
                return status, data
            if attempt == RETRIES:
                raise ReplayError(f"{method} {endpoint}: still {why} after {RETRIES} retries")
            print(
                f"      {why} on {method} {endpoint}; waiting {wait} s"
                f" before retry {attempt + 1} of {RETRIES}",
                flush=True,
            )
            time.sleep(wait)
        raise AssertionError("unreachable")

    def expect(self, method, endpoint, body=None, ok=(200,)):
        status, data = self.call(method, endpoint, body)
        if status not in ok:
            raise ReplayError(f"{method} {endpoint} answered HTTP {status}: {message_of(data)}")
        return data

    def pages(self, endpoint):
        # Not --paginate, which fails through some proxies.
        joiner = "&" if "?" in endpoint else "?"
        entries, page = [], 1
        while True:
            batch = self.expect("GET", f"{endpoint}{joiner}per_page=100&page={page}")
            if not batch:
                return entries
            entries.extend(batch)
            page += 1


def default_state_path(events_path):
    name = events_path.name
    stem = name[: -len(".jsonl")] if name.endswith(".jsonl") else name
    return events_path.with_name(stem + ".state.json")


def work_path(state_path, suffix=".work.git"):
    name = state_path.name
    stem = name[: -len(".state.json")] if name.endswith(".state.json") else name
    return state_path.with_name(stem + suffix)


def load_events(path):
    raw = path.read_bytes()
    try:
        lines = [json.loads(line) for line in raw.decode("utf-8").splitlines() if line.strip()]
    except ValueError as error:
        raise ReplayError(f"{path} is no event file: {error}") from None
    if not lines or lines[0].get("kind") != "header" or lines[0].get("format") != FORMAT:
        raise ReplayError(f"{path} has no header of format {FORMAT}; plan it with plan-replay.py")
    header, events = lines[0], lines[1:]
    for seq, e in enumerate(events, 1):
        if e.get("seq") != seq or e.get("kind") not in KINDS:
            raise ReplayError(f"{path}: event {seq} is out of sequence or of an unknown kind")
    return header, events, hashlib.sha256(raw).hexdigest()


def commits(count):
    return f"{count} commit{'' if count == 1 else 's'}"


def utc_text(stamp):
    moment = datetime.fromisoformat(stamp.replace("Z", "+00:00")).astimezone(timezone.utc)
    return moment.strftime("%Y-%m-%d %H:%M UTC")


def release_label(e, planned):
    what = "draft" if e["draft"] else "pre-release" if e["prerelease"] else "published"
    shared = sum(x["tag_name"] == e["tag_name"] for x in planned) > 1
    return f"release {e['tag_name']}" + (f" ({what})" if shared else "")


class Replay:
    def __init__(self, events_path, mirror, slug, state_path, options):
        with_times, pace, sign, final_name, self.confirmed = options
        self.events_path, self.mirror, self.slug = events_path, mirror, slug
        self.state_path, self.work = state_path, work_path(state_path)
        self.downloads = work_path(state_path, ".downloads")
        self.with_times = with_times
        self.sign, self.final_name = sign, final_name
        self.sign_options, self.key_note, self.steady_key = [], "", True
        self.api = Api(pace)
        self.header, self.events, self.digest = load_events(events_path)
        # An event file planned before the rename of master names only the source's.
        self.source_default = self.header["default_branch"]
        self.default = self.header.get("target_default_branch", self.source_default)
        self.sources = sorted(set(self.header["source_commits"]))
        self.creates = {
            e["number"]: e for e in self.events if e["kind"] in ("create-issue", "create-pull")
        }
        self.done, self.highest, self.head = 0, 0, None
        self.hashes, self.numbers, self.heads, self.urls = {}, {}, {}, {}
        self.tag_shas = {}
        self.created_releases = {}
        self.refs = {}
        # None from a state file that predates committer dates at the time of the replay:
        # that run keeps the original ones, so that it resumes.
        self.committer_dates = {}
        self.finished, self.resumed_at, self.closing = False, None, (0.0, set())
        self.stopping, self.current = False, None
        self.counts = {}

    def load_state(self):
        if not self.state_path.exists():
            return False
        try:
            state = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            raise ReplayError(f"cannot read the state file {self.state_path}: {error}") from None
        if state.get("format") != STATE_FORMAT or state.get("events") != self.digest:
            raise ReplayError(
                f"{self.state_path} belongs to another event file; give another --state"
                " or remove it"
            )
        if state.get("target") != self.slug:
            raise ReplayError(f"{self.state_path} records a replay into {state.get('target')}")
        for option, value in (("--sign", self.sign), ("--final-name", self.final_name)):
            recorded = state.get(option.strip("-").replace("-", "_"))
            if recorded != value:
                was = f"{option} {recorded}" if recorded else f"no {option}"
                raise ReplayError(
                    f"{self.state_path} records a run with {was}; resume with the same options"
                )
        self.done, self.highest, self.head = state["done"], state["highest"], state["head"]
        self.hashes = state["hashes"]
        self.committer_dates = state.get("committer_dates")
        self.numbers = {int(k): v for k, v in state["numbers"].items()}
        self.heads = {int(k): v for k, v in state["heads"].items()}
        self.urls = {int(k): v for k, v in state["urls"].items()}
        # Missing in a state file written before tags were carried.
        self.tag_shas = state.get("tags", {})
        # Missing in a state file written before releases were carried.
        self.created_releases = state.get("releases", {})
        self.finished = state.get("finished", False)
        return True

    def save_state(self):
        state = {
            "format": STATE_FORMAT,
            "events": self.digest,
            "event_file": str(self.events_path),
            "source": self.header["source"],
            "target": self.slug,
            "sign": self.sign,
            "final_name": self.final_name,
            "done": self.done,
            "finished": self.finished,
            "highest": self.highest,
            "head": self.head,
            "numbers": {str(k): v for k, v in sorted(self.numbers.items())},
            "heads": {str(k): v for k, v in sorted(self.heads.items())},
            "urls": {str(k): v for k, v in sorted(self.urls.items())},
            "hashes": self.hashes,
            "tags": self.tag_shas,
            "releases": self.created_releases,
        }
        if self.committer_dates is not None:
            state["committer_dates"] = self.committer_dates
        partial = self.state_path.with_name(self.state_path.name + ".partial")
        with partial.open("w", encoding="utf-8") as file:
            json.dump(state, file, indent=1)
            file.write("\n")
            file.flush()
            os.fsync(file.fileno())
        partial.replace(self.state_path)

    def check_mirror(self):
        trees = {c["tree"] for e in self.events for c in e.get("commits", [])}
        trees |= {e["tree"] for e in self.events if e["kind"] == "merge-pull"}
        if not trees:
            return
        out = git(self.mirror, "cat-file", "--batch-check", stdin="\n".join(sorted(trees)) + "\n")
        missing = [line.split()[0] for line in out.splitlines() if line.endswith(" missing")]
        if missing:
            raise ReplayError(
                f"{self.mirror} lacks {len(missing)} trees of the event file, such as"
                f" {missing[0][:7]}; give the mirror it was planned from"
            )

    def check_signing(self):
        # The same check as rewrite/sign-commits.sh makes.
        key = git_config("user.signingkey")
        if not key:
            raise ReplayError("--sign needs a user.signingkey in your git configuration")
        form = git_config("gpg.format") or "openpgp"
        if form == "ssh":
            known = self.check_ssh_key(key)
        elif form == "openpgp":
            known = self.check_gpg_key(key)
        else:
            raise ReplayError(f"--sign signs with gpg.format ssh or openpgp, not {form}")
        endpoint, scope, what = SIGNING_KEY_LISTS[form]
        entries, page = [], 1
        while True:
            status, data = self.api.call("GET", f"{endpoint}?per_page=100&page={page}")
            if status in (403, 404) and lacks_scope(self.api.headers):
                raise ReplayError(
                    f"GitHub refused to list your {what} (HTTP {status}), which gh may read only"
                    f" with the scope {scope}; add it with: gh auth refresh -s {scope}"
                )
            if status != 200:
                raise ReplayError(f"GET {endpoint} answered HTTP {status}: {message_of(data)}")
            if not data:
                break
            entries.extend(data)
            page += 1
        known(entries)
        # The key is passed on explicitly, so that the key checked is the key that signs.
        self.sign_options = ["-c", f"gpg.format={form}", f"-S{key}"]
        self.sign_key = key

    def check_ssh_key(self, key):
        if key.startswith("key::"):
            public, private, shown = key[len("key::") :], None, "the key of user.signingkey"
        else:
            path = Path(key).expanduser()
            if not path.is_file():
                raise ReplayError(f"no signing key at {path}")
            public = path.read_text(encoding="utf-8", errors="replace").strip()
            if public.startswith("-----BEGIN"):
                # user.signingkey may name the private key; its public key lies next to it.
                private, path = path, path.with_name(path.name + ".pub")
                if not path.is_file():
                    raise ReplayError(f"no public key {path} next to the signing key {private}")
                public = path.read_text(encoding="utf-8", errors="replace").strip()
            else:
                private = (
                    path.with_name(path.name[: -len(".pub")]) if key.endswith(".pub") else None
                )
            shown = str(path)
        parts = public.split()
        if len(parts) < 2:
            raise ReplayError(f"{shown} holds no SSH public key")
        kind, blob = parts[0], parts[1]
        # A key with a passphrase has to be in the agent, or every commit asks.
        no_passphrase = (
            private is not None
            and private.is_file()
            and run(["ssh-keygen", "-y", "-P", "", "-f", str(private)]).returncode == 0
        )
        if not no_passphrase and blob not in run(["ssh-add", "-L"]).stdout.split():
            keychain = " --apple-use-keychain" if sys.platform == "darwin" else ""
            raise ReplayError(
                "the signing key is not in the agent; load it with:"
                f" ssh-add{keychain} {private or '<its private key>'}"
            )
        # Ed25519 signs the same commit with the same signature, so a resumed
        # run rebuilds a signed commit with the same hash.
        self.steady_key = kind == "ssh-ed25519"
        self.key_note = f"the SSH key {shown} ({kind})"

        def known(entries):
            if not any(blob in str(entry.get("key", "")).split() for entry in entries):
                raise ReplayError(
                    f"GitHub does not list {shown} among your SSH signing keys, so it would show"
                    " the signed commits as unverified; add it with:"
                    f" gh ssh-key add {shown if key[:5] != 'key::' else '<public key file>'}"
                    " --type signing"
                )

        return known

    def check_gpg_key(self, key):
        program = git_config("gpg.openpgp.program") or git_config("gpg.program") or "gpg"
        listed = run(
            [
                program,
                "--batch",
                "--with-colons",
                "--with-subkey-fingerprint",
                "--list-secret-keys",
                key.rstrip("!"),
            ]
        )
        if listed.returncode:
            raise ReplayError(f"{program} has no secret key {key}")
        ids = {
            line.split(":")[9][-16:].upper()
            for line in listed.stdout.splitlines()
            if line.startswith("fpr:") and len(line.split(":")) > 9
        }
        # An OpenPGP signature holds the time it was made, so a resumed run
        # rebuilds a signed commit with another hash.
        self.steady_key = False
        self.key_note = f"the GPG key {key}"

        def known(entries):
            signing = {
                str(k.get("key_id", "")).upper()
                for entry in entries
                for k in [entry, *(entry.get("subkeys") or [])]
                if k.get("can_sign")
            }
            if not ids & signing:
                raise ReplayError(
                    f"GitHub does not list the GPG key {key} among your GPG keys that sign, so it"
                    " would show the signed commits as unverified; add it with:"
                    f" gpg --armor --export {key.rstrip('!')} | gh gpg-key add -"
                )

        return known

    def read_target(self):
        status, info = self.api.call("GET", f"repos/{self.slug}")
        if status != 200:
            raise ReplayError(
                f"no repository {self.slug}, or gh has no access to it (HTTP {status})"
            )
        # GitHub answers for a renamed repository under its new name.
        if str(info.get("full_name", "")).lower() != self.slug.lower():
            raise ReplayError(
                f"GitHub answers for {self.slug} with {info.get('full_name')}; name that one"
            )
        permissions = info.get("permissions") or {}
        if not (permissions.get("push") or permissions.get("admin")):
            raise ReplayError(f"gh may not write to {self.slug}")
        self.url = info["html_url"]
        host = self.url.rsplit("/", 2)[0]
        self.pr_base = f"{host}/{self.final_name}" if self.final_name else self.url
        protocol = run(["gh", "config", "get", "git_protocol"]).stdout.strip()
        self.remote = info["ssh_url"] if protocol == "ssh" else info["clone_url"]
        newest = self.api.expect(
            "GET", f"repos/{self.slug}/issues?state=all&sort=created&direction=desc&per_page=1"
        )
        result = run(["git", "ls-remote", self.remote])
        if result.returncode:
            raise ReplayError(f"git ls-remote of {self.slug} failed: {result.stderr.strip()}")
        refs = {}
        for line in result.stdout.splitlines():
            sha, _, ref = line.partition("\t")
            refs[ref] = sha
        # GitHub's documentation leaves open whether an empty repository's default branch can
        # be set, so it is checked only once the first push has created the branch.
        if refs and info.get("default_branch") != self.default:
            raise ReplayError(
                f"the default branch of {self.slug} is {info.get('default_branch')}, the"
                f" replay's {self.default}; set it with: gh api -X PATCH repos/{self.slug}"
                f" -f default_branch={self.default}"
            )
        return (newest[0]["number"] if newest else 0), refs

    def check_target(self, resumed, highest, refs):
        head = refs.get(f"refs/heads/{self.default}")
        if not resumed:
            if refs or highest:
                raise ReplayError(
                    f"{self.slug} is not empty: it has {len(refs)} refs and items up to"
                    f" #{highest}; replay only into an empty repository"
                )
            return
        following = self.events[self.done] if self.done < len(self.events) else None
        kind = following["kind"] if following else None
        problems = []
        # The event the last run stopped in may have done part of its work, which it checks
        # itself, so it may account for one difference.
        if highest != self.highest and not (
            kind in ("create-issue", "create-pull")
            and highest == self.highest + 1 == following["number"]
        ):
            problems.append(f"its highest number is #{highest}, the state's #{self.highest}")
        if head != self.head and kind not in ("push-commits", "merge-pull"):
            problems.append(
                f"{self.default} is at {(head or 'nothing')[:7]}, the state's"
                f" {(self.head or 'nothing')[:7]}"
            )
        if problems:
            raise ReplayError(
                f"{self.slug} does not match {self.state_path}: {'; '.join(problems)}"
            )
        self.highest = highest

    def label_changes(self):
        planned = {e["name"] for e in self.events if e["kind"] == "create-label"}
        present = {label["name"] for label in self.api.pages(f"repos/{self.slug}/labels")}
        return sorted(present & planned), sorted(present - planned)

    def summary(self, resumed, updated, removed):
        left = self.events[self.done :]
        total = len(self.events)
        if self.done == total:
            print(
                f"All {total} events of the replay of {self.header['source']} into {self.slug}"
                f" are done, as {self.state_path} records; the target is checked again"
            )
        elif resumed:
            print(
                f"Resume the replay of {self.header['source']} into {self.slug}"
                f" at event {self.done + 1} of {total}, from {self.state_path}"
            )
        else:
            print(f"Replay {self.header['source']} into {self.slug}: {total} events")

        def count(kind):
            return sum(e["kind"] == kind for e in left)

        rows = [
            ("labels", count("create-label")),
            ("commits", sum(len(e.get("commits", [])) for e in left)),
            ("issues", count("create-issue")),
            ("pull requests", count("create-pull")),
            ("comments", sum(e["kind"] == "add-comment" and "review_id" not in e for e in left)),
            ("reviews as comments", sum("review_id" in e for e in left)),
            ("merges", count("merge-pull")),
            ("closes", count("close-item")),
            ("tags", count("create-tag")),
            ("releases", count("create-release")),
            ("release assets", sum(len(e.get("assets", [])) for e in left)),
            ("release asset bytes", sum(a["size"] or 0 for e in left for a in e.get("assets", []))),
        ]
        if self.sign:
            rows.append(
                (
                    "commits to sign",
                    sum(
                        c["committer"]["email"] == self.sign
                        for e in left
                        for c in e.get("commits", [])
                    ),
                )
            )
            rows.append(("tags to sign", sum(self.signs_tag(e) for e in left)))
        for name, value in rows:
            print(f"  {name:<25}{value:>6}")
        if self.default != self.source_default:
            print(
                f"  default branch: {self.source_default} in the source,"
                f" {self.default} in the target"
            )
        if self.sign:
            print(
                f"  signed: the commits committed and the tags tagged by {self.sign},"
                f" with {self.key_note}"
            )
            if not self.steady_key:
                print(
                    "  this key does not sign a commit the same way twice: a run stopped in a push"
                    " of signed commits, or in a signed tag, cannot resume"
                )
        urls = sum(e["kind"] == "merge-pull" and "{pr_url}" in e["commit_message"] for e in left)
        if urls:
            print(
                f"  {{pr_url}} in {urls} squash message{'' if urls == 1 else 's'}:"
                f" {self.pr_base}/pull/<number>"
            )
        if updated:
            print(f"  labels the target has and the replay updates: {', '.join(updated)}")
        if removed:
            print(f"  labels the target has and the replay deletes: {', '.join(removed)}")

    def prepare_work(self, resumed):
        objects = git(self.mirror, "rev-parse", "--path-format=absolute", "--git-path", "objects")
        if not self.work.is_dir():
            git(self.work.parent, "init", "-q", "--bare", self.work.name)
            git(self.work, "config", "gc.auto", "0")
        (self.work / "objects" / "info" / "alternates").write_text(objects + "\n", encoding="utf-8")
        if resumed and self.head:
            # Without --no-tags, git would fetch the target's tags into the
            # refs/tags/ of the tags this repository builds.
            git(self.work, "fetch", "-q", "--no-tags", self.remote, "+refs/heads/*:refs/target/*")

    def replace_hashes(self, value):
        if not value:
            return value or ""

        def replace(match):
            prefix = match.group(0)
            i = bisect.bisect_left(self.sources, prefix)
            found = [s for s in self.sources[i : i + 2] if s.startswith(prefix)]
            if len(found) == 1 and found[0] in self.hashes:
                return self.hashes[found[0]][: len(prefix)]
            return prefix

        return HASH_IN_TEXT.sub(replace, value)

    def stamped(self, body, created):
        if not self.with_times or not created:
            return body
        line = f"_Originally created {utc_text(created)}._"
        return f"{body}\n\n{line}" if body else line

    def recreate(self, commit):
        parents = []
        for parent in commit["parents"]:
            if parent not in self.hashes:
                raise ReplayError(
                    f"commit {commit['sha'][:7]} has the parent {parent[:7]},"
                    " which no earlier event recreated"
                )
            parents.append(self.hashes[parent])
        a, c = commit["author"], commit["committer"]
        env = dict(
            os.environ,
            GIT_AUTHOR_NAME=a["name"],
            GIT_AUTHOR_EMAIL=a["email"],
            GIT_AUTHOR_DATE=git_date(a["date"]),
            GIT_COMMITTER_NAME=c["name"],
            GIT_COMMITTER_EMAIL=c["email"],
            GIT_COMMITTER_DATE=self.committer_date(commit, parents),
        )
        signed = self.sign is not None and c["email"] == self.sign
        args = ["commit-tree", commit["tree"]]
        for parent in parents:
            args += ["-p", parent]
        if signed:
            # git takes -c before the subcommand and -S after it.
            args = [*self.sign_options[:2], *args, self.sign_options[2]]
        sha = git(self.work, *args, stdin=self.replace_hashes(commit["message"]), env=env)
        recorded = self.hashes.get(commit["sha"])
        if recorded and recorded != sha:
            why = (
                "its signature differs from the one the first run made: the signing key signs"
                " differently each time, or it is another key"
                if signed
                else "it differs from the one the first run made"
            )
            raise ReplayError(
                f"commit {commit['sha'][:7]} was rebuilt as {sha[:7]}, but {self.state_path}"
                f" records {recorded[:7]}; {why}. The run stops before it pushes a second history"
            )
        self.hashes[commit["sha"]] = sha
        return sha, signed

    def committer_date(self, commit, parents):
        if self.committer_dates is None:
            return git_date(commit["committer"]["date"])
        recorded = self.committer_dates.get(commit["sha"])
        if recorded:
            return recorded
        seconds, offset = now_date()
        # No earlier than a parent's, since GitHub's clock dates the merges.
        for parent in parents:
            seconds = max(seconds, int(git(self.work, "show", "-s", "--format=%ct", parent)))
        date = f"{seconds} {offset}"
        self.committer_dates[commit["sha"]] = date
        return date

    def recreate_all(self, e):
        sha, signed = None, 0
        for commit in e["commits"]:
            sha, was_signed = self.recreate(commit)
            signed += was_signed
        # Before the push, so that a resumed run can check it rebuilds the same hashes.
        self.save_state()
        return sha, f", {signed} signed" if self.sign else ""

    def push(self, sha, branch):
        self.api.before_write()
        git(self.work, "push", "-q", self.remote, f"{sha}:refs/heads/{branch}")
        self.api.after_write()
        git(self.work, "update-ref", f"refs/target/{branch}", sha)

    def push_commits(self, e):
        sha, signed = self.recreate_all(e)
        self.push(sha, e["branch"])
        self.head = sha
        return f"{commits(len(e['commits']))} to {e['branch']}{signed}, now at {sha[:7]}"

    def push_branch(self, e):
        if e["base_commit"] not in self.hashes:
            raise ReplayError(
                f"the branch of #{e['number']} starts on {e['base_commit'][:7]}, not yet recreated"
            )
        sha, signed = self.recreate_all(e)
        self.push(sha, e["branch"])
        self.heads[e["number"]] = sha
        return (
            f"#{e['number']} branch {e['branch']}, {commits(len(e['commits']))}{signed},"
            f" at {sha[:7]}"
        )

    def check_number(self, e, data, what):
        got = data.get("number")
        if got != e["number"]:
            raise ReplayError(
                f"the {what} planned as #{e['number']} got #{got}; the target's numbers no longer"
                " follow the source's, so the replay stops. Find out what took the number."
            )

    def create_label(self, e):
        endpoint = f"repos/{self.slug}/labels"
        fields = {"color": e.get("color") or "ededed", "description": e.get("description") or ""}
        status, data = self.api.call("POST", endpoint, {"name": e["name"], **fields})
        if status == 201:
            return f"{e['name']} created"
        errors = (data or {}).get("errors") or []
        if status == 422 and any(
            isinstance(x, dict) and x.get("code") == "already_exists" for x in errors
        ):
            self.api.expect("PATCH", f"{endpoint}/{quote(e['name'], safe='')}", fields)
            return f"{e['name']} updated"
        raise ReplayError(f"POST {endpoint} answered HTTP {status}: {message_of(data)}")

    def create_issue(self, e):
        n = e["number"]
        title = self.replace_hashes(e["title"])
        if self.highest >= n:
            data = self.api.expect("GET", f"repos/{self.slug}/issues/{n}")
            if data.get("title") != title or "pull_request" in data:
                raise ReplayError(f"#{n} exists in {self.slug}, but is not the planned issue")
            note = ", found created"
        else:
            body = {
                "title": title,
                "body": self.stamped(self.replace_hashes(e["body"]), e.get("created_at")),
                "labels": e["labels"],
                "assignees": e["assignees"],
            }
            data = self.api.expect("POST", f"repos/{self.slug}/issues", body, ok=(201,))
            self.check_number(e, data, "issue")
            note = ""
        self.highest, self.numbers[n] = n, n
        return f"#{n} issue{note}"

    def create_pull(self, e):
        n = e["number"]
        title = self.replace_hashes(e["title"])
        if self.highest >= n:
            data = self.api.expect("GET", f"repos/{self.slug}/pulls/{n}")
            if data.get("title") != title or data["head"]["ref"] != e["head"]:
                raise ReplayError(
                    f"#{n} exists in {self.slug}, but is not the planned pull request"
                )
            note = ", found created"
        else:
            body = {
                "title": title,
                "body": self.stamped(self.replace_hashes(e["body"]), e.get("created_at")),
                "head": e["head"],
                "base": e["base"],
                "draft": e["draft"],
            }
            endpoint = f"repos/{self.slug}/pulls"
            for attempt in range(RETRIES + 1):
                status, data = self.api.call("POST", endpoint, body)
                # Right after a push, GitHub may not see the branch yet; a 422 created nothing.
                if status != 422 or attempt == RETRIES:
                    break
                print(f"      HTTP 422 on POST {endpoint}; waiting {CATCH_UP_WAIT} s", flush=True)
                time.sleep(CATCH_UP_WAIT)
            if status != 201:
                raise ReplayError(f"POST {endpoint} answered HTTP {status}: {message_of(data)}")
            self.check_number(e, data, "pull request")
            note = ""
        self.highest, self.numbers[n] = n, n
        self.urls[n] = data["html_url"]
        if e["labels"] or e["assignees"]:
            fields = {"labels": e["labels"], "assignees": e["assignees"]}
            self.api.expect("PATCH", f"repos/{self.slug}/issues/{n}", fields)
        return f"#{n} pull request {e['head']} into {e['base']}{note}"

    def add_comment(self, e):
        n = e["number"]
        body = self.stamped(self.replace_hashes(e["body"]), e.get("created_at"))
        endpoint = f"repos/{self.slug}/issues/{n}/comments"
        if self.resumed_at == e["seq"]:
            comments = self.api.pages(endpoint)
            if comments and comments[-1].get("body") == body:
                return f"#{n} comment, found created"
        self.api.expect("POST", endpoint, {"body": body}, ok=(201,))
        return f"#{n} comment"

    def merge_pull(self, e):
        n = e["number"]
        if n not in self.heads or n not in self.urls:
            raise ReplayError(f"#{n} is merged before its branch was pushed or it was created")
        title = self.replace_hashes(e["commit_title"])
        url = f"{self.pr_base}/pull/{n}" if self.final_name else self.urls[n]
        message = self.replace_hashes(e["commit_message"]).replace("{pr_url}", url)
        sha, note = None, ""
        if self.resumed_at == e["seq"]:
            pull = self.api.expect("GET", f"repos/{self.slug}/pulls/{n}")
            if pull.get("merged"):
                sha, note = pull["merge_commit_sha"], ", found merged"
        endpoint = f"repos/{self.slug}/pulls/{n}/merge"
        body = {
            "merge_method": e["method"],
            "commit_title": title,
            "commit_message": message,
            "sha": self.heads[n],
        }
        for attempt in range(RETRIES + 1):
            if sha:
                break
            status, data = self.api.call("PUT", endpoint, body)
            if status == 200:
                sha = data["sha"]
            elif status in (405, 409) and attempt < RETRIES:
                # GitHub refuses a merge while it still computes whether the pull request merges.
                print(
                    f"      HTTP {status} on PUT {endpoint}; waiting {CATCH_UP_WAIT} s", flush=True
                )
                time.sleep(CATCH_UP_WAIT)
            else:
                raise ReplayError(f"PUT {endpoint} answered HTTP {status}: {message_of(data)}")
        git(
            self.work,
            "fetch",
            "-q",
            "--no-tags",
            self.remote,
            f"+refs/heads/{self.default}:refs/target/{self.default}",
        )
        fetched = git(self.work, "rev-parse", f"refs/target/{self.default}")
        if fetched != sha:
            raise ReplayError(
                f"after the merge of #{n}, {self.default} is at {fetched[:7]}, not at {sha[:7]}"
            )
        tree = git(self.work, "rev-parse", f"{sha}^{{tree}}")
        if tree != e["tree"]:
            raise ReplayError(
                f"after the merge of #{n}, the tree of {self.default} is {tree[:7]}, the source's"
                f" {e['tree'][:7]}; the replay stops at the first difference"
            )
        self.hashes[e["source_commit"]] = sha
        self.head = sha
        named = self.creates[n].get("body", "") + "\n" + message
        self.closing = (
            time.monotonic(),
            {int(x) for x in SAME_REPO_CLOSING_KEYWORD.findall(named)},
        )
        return f"#{n} {e['method']}-merged into {self.default} as {sha[:7]}{note}"

    def close_item(self, e):
        n, reason = e["number"], e.get("state_reason")
        is_pull = self.creates[n]["kind"] == "create-pull"
        item = self.api.expect("GET", f"repos/{self.slug}/issues/{n}")
        merged_at, named = self.closing
        while item["state"] == "open" and n in named and time.monotonic() - merged_at < CLOSE_WAIT:
            time.sleep(1)
            item = self.api.expect("GET", f"repos/{self.slug}/issues/{n}")
        said = f" as {reason}" if reason else ""
        note = ""
        if item["state"] == "closed":
            if reason in (None, item.get("state_reason")):
                return f"#{n} already closed{said}"
            # GitHub ignores a state reason unless the state changes.
            self.api.expect("PATCH", f"repos/{self.slug}/issues/{n}", {"state": "open"})
            note = f", reopened from {item.get('state_reason')}"
        if is_pull:
            self.api.expect("PATCH", f"repos/{self.slug}/pulls/{n}", {"state": "closed"})
        else:
            fields = {"state": "closed", **({"state_reason": reason} if reason else {})}
            self.api.expect("PATCH", f"repos/{self.slug}/issues/{n}", fields)
        return f"#{n} closed{said}{note}"

    def signs_tag(self, e):
        return (
            self.sign is not None
            and e["kind"] == "create-tag"
            and e["annotated"]
            and e["tagger"]["email"] == self.sign
        )

    def create_tag(self, e):
        name, commit = e["name"], self.hashes.get(e["commit"])
        if commit is None:
            raise ReplayError(
                f"tag {name} names {e['commit'][:7]}, which no earlier event recreated"
            )
        signed = self.signs_tag(e)
        if e["annotated"]:
            t = e["tagger"]
            env = dict(
                os.environ,
                GIT_COMMITTER_NAME=t["name"],
                GIT_COMMITTER_EMAIL=t["email"],
                GIT_COMMITTER_DATE=git_date(t["date"]),
            )
            # tag.gpgSign would sign every annotated tag, and the default
            # cleanup would change the message.
            args = ["-c", "tag.gpgSign=false", "-c", "tag.forceSignAnnotated=false"]
            if signed:
                args += [*self.sign_options[:2], "tag", "-u", self.sign_key]
            else:
                args += ["tag", "-a"]
            # Without "--", a name that starts with a dash would be an option.
            args += ["-f", "--cleanup=verbatim", "-F", "-", "--", name, commit]
            message = self.replace_hashes(e["message"])
            if signed and message and not message.endswith("\n"):
                # git appends the signature right after the message, and
                # verify-tag finds it only at the start of a line.
                message += "\n"
            git(self.work, *args, stdin=message, env=env)
            sha = git(self.work, "rev-parse", f"refs/tags/{name}")
        else:
            sha = commit
        recorded = self.tag_shas.get(name)
        if recorded and recorded != sha:
            why = (
                "its signature differs from the one the first run made: the signing key signs"
                " differently each time, or it is another key"
                if signed
                else "it differs from the one the first run made"
            )
            raise ReplayError(
                f"tag {name} was rebuilt as {sha[:7]}, but {self.state_path} records"
                f" {recorded[:7]}; {why}. The run stops before it pushes a second tag"
            )
        self.tag_shas[name] = sha
        # Before the push, so that a resumed run can check it rebuilds the same tag.
        self.save_state()
        what = "annotated, signed" if signed else "annotated" if e["annotated"] else "lightweight"
        found = self.refs.get(f"refs/tags/{name}") if self.resumed_at == e["seq"] else None
        if found == sha:
            return f"{name}, {what}, at {commit[:7]}, found pushed"
        if found:
            raise ReplayError(
                f"tag {name} is at {found[:7]} in {self.slug}, not at the rebuilt {sha[:7]}"
            )
        self.api.before_write()
        git(self.work, "push", "-q", self.remote, f"{sha}:refs/tags/{name}")
        self.api.after_write()
        return f"{name}, {what}, at {commit[:7]}"

    def create_release(self, e):
        key, tag = str(e["release_id"]), e["tag_name"]
        record, notes = self.created_releases.get(key), []
        recorded = record is not None
        if record is None and self.resumed_at == e["seq"]:
            taken = {r["id"] for r in self.created_releases.values()}
            found = [
                r
                for r in self.api.pages(f"repos/{self.slug}/releases")
                if r.get("tag_name") == tag and r.get("id") not in taken
            ]
            if found:
                record = {
                    "id": found[0]["id"],
                    "upload_url": found[0]["upload_url"],
                    "assets": {},
                    "published": False,
                }
                notes.append("found created")
        if record is None:
            if e["commit"] and e["commit"] not in self.hashes:
                raise ReplayError(
                    f"release {tag} names {e['commit'][:7]}, which no earlier event recreated"
                )
            body = {
                "tag_name": tag,
                # GitHub reads it only where the tag is missing, as for a draft.
                "target_commitish": self.hashes[e["commit"]] if e["commit"] else self.default,
                "name": e["name"],
                "body": self.stamped(
                    self.replace_hashes(e["body"]), e["published_at"] or e["created_at"]
                ),
                # GitHub refuses an asset for a published release that is immutable.
                "draft": True,
                "prerelease": e["prerelease"],
            }
            data = self.api.expect("POST", f"repos/{self.slug}/releases", body, ok=(201,))
            record = {
                "id": data["id"],
                "upload_url": data["upload_url"],
                "assets": {},
                "published": False,
            }
        # Saved before the first asset, after each one and after the publication, so that a
        # resumed run takes over what is done.
        self.created_releases[key] = record
        self.save_state()
        existing, taken, removed = None, 0, 0
        for asset in e["assets"]:
            if str(asset["id"]) in record["assets"]:
                # A stop between the record of an upload and the removal of
                # its download leaves the download behind.
                (self.downloads / str(asset["id"])).unlink(missing_ok=True)
                continue
            if self.resumed_at == e["seq"]:
                if existing is None:
                    listed = self.api.pages(f"repos/{self.slug}/releases/{record['id']}/assets")
                    existing = {x["name"]: x for x in listed}
                found = existing.get(asset["name"])
                if found and self.uploaded_whole(found, asset):
                    record["assets"][str(asset["id"])] = found["id"]
                    self.save_state()
                    # The download of an upload whose answer was lost.
                    (self.downloads / str(asset["id"])).unlink(missing_ok=True)
                    taken += 1
                    continue
                if found:
                    # GitHub refuses a second asset of the same name.
                    self.api.expect(
                        "DELETE", f"repos/{self.slug}/releases/assets/{found['id']}", ok=(204,)
                    )
                    removed += 1
            path = self.download(tag, asset)
            record["assets"][str(asset["id"])] = self.upload(record, asset, path)["id"]
            self.save_state()
            path.unlink()
        if self.downloads.is_dir() and not any(self.downloads.iterdir()):
            self.downloads.rmdir()
        if not e["draft"] and not record.get("published"):
            # The answer of a publication may have been lost. GitHub documents
            # the list, not Get a release, as giving drafts to those who push.
            listed = {}
            if recorded:
                listed = {r["id"]: r for r in self.api.pages(f"repos/{self.slug}/releases")}
            if listed.get(record["id"], {}).get("draft") is False:
                notes.append("found published")
            else:
                # GitHub makes each newly published release the latest unless told otherwise.
                body = {"draft": False, "make_latest": "true" if e["latest"] else "false"}
                self.api.expect("PATCH", f"repos/{self.slug}/releases/{record['id']}", body)
            record["published"] = True
            self.save_state()
        if taken:
            notes.append(f"{taken} found uploaded")
        if removed:
            notes.append(f"{removed} found half uploaded, removed and uploaded again")
        what = "draft" if e["draft"] else "pre-release" if e["prerelease"] else "published"
        count, size = len(e["assets"]), sum(a["size"] or 0 for a in e["assets"])
        files = f"{count} asset{'' if count == 1 else 's'}, {size} bytes" if count else "no assets"
        latest = ", latest" if e["latest"] else ""
        return f"{tag}, {what}{latest}, {files}" + "".join(f", {note}" for note in notes)

    @staticmethod
    def uploaded_whole(found, asset):
        digests = (found.get("digest"), asset.get("digest"))
        return (
            found.get("state") == "uploaded"
            and found.get("size") == asset["size"]
            and (None in digests or digests[0] == digests[1])
        )

    @staticmethod
    def how_download_differs(path, asset):
        size = path.stat().st_size
        if asset["size"] is not None and size != asset["size"]:
            return f"has {size} bytes, GitHub lists {asset['size']}"
        algorithm, _, expected = (asset.get("digest") or "").partition(":")
        if algorithm == "sha256":
            digest = hashlib.sha256()
            with path.open("rb") as file:
                for chunk in iter(lambda: file.read(1 << 20), b""):
                    digest.update(chunk)
            if digest.hexdigest() != expected:
                return f"has the SHA-256 digest {digest.hexdigest()}, GitHub lists {expected}"
        return None

    def download(self, tag, asset):
        self.downloads.mkdir(exist_ok=True)
        path = self.downloads / str(asset["id"])
        if path.is_file() and self.how_download_differs(path, asset) is None:
            return path
        partial = path.with_name(path.name + ".partial")
        endpoint = f"repos/{self.header['source']}/releases/assets/{asset['id']}"
        # GitHub answers with the content or a redirect to it, which gh follows.
        args = ["gh", "api", "-H", "Accept: application/octet-stream", endpoint]
        try:
            with partial.open("wb") as out:
                result = subprocess.run(
                    args,
                    stdin=subprocess.DEVNULL,
                    stdout=out,
                    stderr=subprocess.PIPE,
                    env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
                    start_new_session=True,
                )
        except FileNotFoundError:
            raise ReplayError("gh is missing") from None
        if result.returncode:
            error = result.stderr.decode("utf-8", errors="replace").strip().splitlines()
            raise ReplayError(f"GET {endpoint} failed: {error[-1] if error else ''}")
        problem = self.how_download_differs(partial, asset)
        if problem:
            raise ReplayError(
                f"the asset {asset['name']} of release {tag}, downloaded from {endpoint},"
                f" {problem}; run the same command again to download it again"
            )
        partial.replace(path)
        return path

    def upload(self, record, asset, path):
        endpoint = record["upload_url"].split("{", 1)[0] + "?name=" + quote(asset["name"], safe="")
        if asset["label"]:
            endpoint += "&label=" + quote(asset["label"], safe="")
        status, data = self.api.call(
            "POST", endpoint, headers=[f"Content-Type: {asset['content_type']}"], upload=path
        )
        if status != 201:
            raise ReplayError(
                f"POST {endpoint} answered HTTP {status}: {message_of(data)}; run the same command"
                " again, which removes an asset GitHub left half uploaded and uploads it again"
            )
        return data

    def apply(self, e):
        handler = {
            "create-label": self.create_label,
            "push-commits": self.push_commits,
            "push-branch": self.push_branch,
            "create-issue": self.create_issue,
            "create-pull": self.create_pull,
            "add-comment": self.add_comment,
            "merge-pull": self.merge_pull,
            "close-item": self.close_item,
            "create-tag": self.create_tag,
            "create-release": self.create_release,
        }[e["kind"]]
        return handler(e)

    def reconcile(self):
        found = {i["number"]: i for i in self.api.pages(f"repos/{self.slug}/issues?state=all")}
        problems, reopened = [], []
        for n, e in sorted(self.creates.items()):
            item, status = found.get(n), None
            if item is None:
                # GitHub's list can lag behind an item created a moment ago.
                status, data = self.api.call("GET", f"repos/{self.slug}/issues/{n}")
                item = data if status == 200 else None
            if item is None:
                problems.append(
                    f"#{n} is missing" + ("" if status == 404 else f", GET answered HTTP {status}")
                )
                continue
            merged = (item.get("pull_request") or {}).get("merged_at")
            state = "merged" if merged else item["state"]
            if e["state"] == "open" and state == "closed":
                kind = "pulls" if e["kind"] == "create-pull" else "issues"
                self.api.expect("PATCH", f"repos/{self.slug}/{kind}/{n}", {"state": "open"})
                reopened.append(n)
            elif state != e["state"]:
                problems.append(f"#{n} is {state}, planned {e['state']}")
            elif e["kind"] == "create-issue" and state == "closed" and e.get("state_reason"):
                if item.get("state_reason") != e["state_reason"]:
                    problems.append(
                        f"#{n} is closed as {item.get('state_reason')}, planned {e['state_reason']}"
                    )
        problems += [f"#{n} is not in the plan" for n in sorted(set(found) - set(self.creates))]
        planned = {e["name"] for e in self.events if e["kind"] == "create-label"}
        labels = {label["name"] for label in self.api.pages(f"repos/{self.slug}/labels")}
        if labels != planned:
            problems.append(f"the labels differ: {', '.join(sorted(labels ^ planned))}")
        problems += self.tag_problems()
        problems += self.release_problems()
        for n in reopened:
            print(f"  #{n} reopened: a closing keyword closed it, the source has it open")
        if problems:
            raise ReplayError(f"{self.slug} differs from the plan: {'; '.join(problems)}")

    def tag_problems(self):
        result = run(["git", "ls-remote", "--refs", "--tags", self.remote])
        if result.returncode:
            raise ReplayError(f"git ls-remote of {self.slug} failed: {result.stderr.strip()}")
        found = {}
        # Only a tab ends the hash: git allows other Unicode blanks in a name.
        for line in result.stdout.split("\n"):
            sha, _, ref = line.partition("\t")
            if ref.startswith("refs/tags/"):
                found[ref[len("refs/tags/") :]] = sha
        planned = [e["name"] for e in self.events if e["kind"] == "create-tag"]
        problems = []
        for name in planned:
            sha, recorded = found.get(name), self.tag_shas.get(name)
            if sha is None:
                problems.append(f"tag {name} is missing")
            elif sha != recorded:
                problems.append(
                    f"tag {name} is at {sha[:7]}, the state file's {(recorded or 'nothing')[:7]}"
                )
        problems += [f"tag {name} is not in the plan" for name in sorted(set(found) - set(planned))]
        return problems

    def release_problems(self):
        found = {r["id"]: r for r in self.api.pages(f"repos/{self.slug}/releases")}
        planned = [e for e in self.events if e["kind"] == "create-release"]
        latest = None
        if any(e["latest"] for e in planned):
            status, data = self.api.call("GET", f"repos/{self.slug}/releases/latest")
            latest = data if status == 200 else None
        problems, recorded = [], set()
        for e in planned:
            tag, at = e["tag_name"], release_label(e, planned)
            # By id, so that a draft and a published release of one tag are both checked.
            record = self.created_releases.get(str(e["release_id"]))
            r = found.get(record["id"]) if record else None
            if r is None:
                problems.append(f"{at} is missing")
                continue
            recorded.add(r["id"])
            kind = (bool(r.get("draft")), bool(r.get("prerelease")))
            if r.get("tag_name") != tag or kind != (e["draft"], e["prerelease"]):
                problems.append(
                    f"{at} is on {r.get('tag_name')}, draft {kind[0]} and pre-release"
                    f" {kind[1]}, planned draft {e['draft']} and pre-release {e['prerelease']}"
                )
            names = sorted(
                a["name"]
                for a in self.api.pages(f"repos/{self.slug}/releases/{r['id']}/assets")
                if a.get("state") == "uploaded"
            )
            assets = sorted(a["name"] for a in e["assets"])
            if names != assets:
                problems.append(f"{at} has the assets {names}, planned {assets}")
            if e["latest"] and (latest or {}).get("id") != r["id"]:
                named = (latest or {}).get("tag_name") or "none"
                problems.append(f"the latest release is {named}, planned {tag}")
        problems += [
            f"release {r.get('tag_name')} is not in the plan"
            for i, r in sorted(found.items())
            if i not in recorded
        ]
        return problems

    def interrupt(self, signum, frame):
        if self.stopping:
            raise KeyboardInterrupt
        self.stopping = True
        print(f"{PROG}: interrupted; stopping after this event", file=sys.stderr, flush=True)

    def main(self):
        self.check_mirror()
        resumed = self.load_state()
        if self.sign:
            self.check_signing()
        if self.committer_dates is not None:
            # A SOURCE_DATE_EPOCH the run cannot use stops it here, before the
            # confirmation, not in the middle of an event.
            now_date()
        highest, refs = self.read_target()
        self.check_target(resumed, highest, refs)
        self.refs = refs
        # Only before the first event, so that a resumed run does not change them again.
        updated, removed = self.label_changes() if self.done == 0 else ([], [])
        self.summary(resumed, updated, removed)
        print(f"Type {self.slug} to confirm: ", end="", flush=True)
        if self.confirmed is not None:
            answer = self.confirmed
            print(f"{answer}, as --confirmed gives it", flush=True)
        else:
            try:
                answer = sys.stdin.readline().strip()
            except KeyboardInterrupt:
                answer = ""
        if answer != self.slug:
            raise ReplayError("not confirmed; nothing changed")

        signal.signal(signal.SIGINT, self.interrupt)
        if resumed:
            self.resumed_at = self.done + 1
        else:
            self.save_state()
        self.prepare_work(resumed)
        for name in removed:
            self.api.expect("DELETE", f"repos/{self.slug}/labels/{quote(name, safe='')}", ok=(204,))
            print(f"  label {name} deleted")

        total = len(self.events)
        width = len(str(total))
        for e in self.events[self.done :]:
            self.current = e["seq"]
            detail = self.apply(e)
            self.done = e["seq"]
            self.save_state()
            self.counts[e["kind"]] = self.counts.get(e["kind"], 0) + 1
            print(f"{e['seq']:>{width}}/{total}  {e['kind']:<12}  {detail}", flush=True)
            if self.stopping:
                print(
                    f"{PROG}: stopped after event {e['seq']} of {total};"
                    " run the same command again to resume"
                )
                return 130
        self.current = None
        self.reconcile()
        self.finished = True
        self.save_state()
        print("Done in this run:")
        for kind in KINDS:
            print(f"  {kind:<25}{self.counts.get(kind, 0):>6}")
        print(self.url)
        return 0


def main(argv):
    if argv[:1] in (["-h"], ["--help"]):
        usage(0)
    state, with_times, pace, sign, final_name, confirmed = None, False, 1.0, None, None, None
    while argv[:1] and argv[0].startswith("--"):
        option, argv = argv[0], argv[1:]
        if option == "--state" and argv:
            state, argv = Path(argv[0]), argv[1:]
        elif option == "--with-times":
            with_times = True
        elif option == "--pace" and argv and re.fullmatch(r"\d+(\.\d+)?", argv[0]):
            pace, argv = float(argv[0]), argv[1:]
        elif option == "--sign" and argv and re.fullmatch(r"[^@\s]+@[^@\s]+", argv[0]):
            sign, argv = argv[0], argv[1:]
        elif option == "--final-name" and argv and SLUG.fullmatch(argv[0]):
            final_name, argv = argv[0], argv[1:]
        elif option == "--confirmed" and argv:
            confirmed, argv = argv[0], argv[1:]
        else:
            usage()
    if len(argv) != 3 or argv[0].startswith("-"):
        usage()
    events_path, mirror, slug = Path(argv[0]), Path(argv[1]), argv[2]
    if not SLUG.fullmatch(slug):
        usage()
    replay = None
    try:
        if not events_path.is_file():
            raise ReplayError(f"no event file at {events_path}")
        if not mirror.is_dir():
            raise ReplayError(f"no mirror at {mirror}")
        state = state or default_state_path(events_path)
        if not state.parent.is_dir():
            raise ReplayError(f"no folder {state.parent} for the state file")
        options = (with_times, pace, sign, final_name, confirmed)
        replay = Replay(events_path, mirror, slug, state, options)
        return replay.main()
    except ReplayError as stop:
        print(f"{PROG}: {stop}", file=sys.stderr)
        if replay and replay.current:
            print(
                f"{PROG}: stopped in event {replay.current} of {len(replay.events)};"
                f" {replay.state_path} holds the events up to {replay.done}",
                file=sys.stderr,
            )
        return 1
    except KeyboardInterrupt:
        print(file=sys.stderr)
        if replay and replay.current:
            print(
                f"{PROG}: stopped in event {replay.current}; run the same command again,"
                " and that event checks what of it is done",
                file=sys.stderr,
            )
        return 130


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
