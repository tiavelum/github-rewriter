import datetime
import json
import os
import re
import shutil
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from conftest import (
    ADA_OLD,
    BOB,
    TOOL_NEW,
    Git,
    Plan,
    as_committer,
    copy_target,
    has_match,
    has_search,
    kill_hook,
    lines,
    past_header,
    recreated,
    refuse_hook,
    run,
    shell_status,
    write_hook,
)

ADA = "ada@example.com"
TOOL_KILLED_DATES = "ada-example/tool-killed-dates"
TOOL_ON_CLOCK = "ada-example/tool-on-clock"
TOOL_EARLY_EPOCH = "ada-example/tool-early-epoch"
TOOL_BAD_EPOCHS = "ada-example/tool-bad-epochs"
TOOL_LATE_START = "ada-example/tool-late-start"

needs_ssh_keygen = pytest.mark.skipif(
    shutil.which("ssh-keygen") is None,
    reason="ssh-keygen is missing; run-replay.py --sign with an SSH key not tested",
)


def date_replay(replay, source, run_plan, target, slug, state, **variables):
    tail = ("--pace", "0", "--state", state, run_plan.file, source.mirror, slug)
    return replay(target, slug, *tail, merged=True, **variables)


@pytest.fixture(scope="module")
def killed_dates(root, source, run_plan, make_target, replay):
    target = make_target("gh-killed-dates", TOOL_KILLED_DATES)
    write_hook(target, "post-receive", kill_hook("refs/heads/feat/2-thing"))
    state = root / "killed-dates.state.json"
    first = date_replay(replay, source, run_plan, target, TOOL_KILLED_DATES, state)
    # The killed run's push goes on without it: time to end before the resume.
    time.sleep(1)
    second = date_replay(
        *(replay, source, run_plan, target, TOOL_KILLED_DATES, state),
        SOURCE_DATE_EPOCH="1794009999",
    )
    runs = [first, second]
    return SimpleNamespace(
        target=target, state=state, runs=runs, statuses=[shell_status(r) for r in runs]
    )


@pytest.fixture(scope="module")
def on_clock(root, source, run_plan, make_target, replay):
    target = make_target("gh-on-clock", TOOL_ON_CLOCK)
    state = root / "on-clock.state.json"
    clock_from = int(time.time())
    result = date_replay(
        *(replay, source, run_plan, target, TOOL_ON_CLOCK, state), unset=("SOURCE_DATE_EPOCH",)
    )
    clock_to = int(time.time())
    return SimpleNamespace(
        target=target, state=state, result=result, clock_from=clock_from, clock_to=clock_to
    )


@pytest.fixture(scope="module")
def early_epoch(root, source, run_plan, make_target, replay):
    target = make_target("gh-early-epoch", TOOL_EARLY_EPOCH)
    state = root / "early-epoch.state.json"
    result = date_replay(
        replay,
        *(source, run_plan, target, TOOL_EARLY_EPOCH, state),
        # Before the dates the fake gives its merges.
        SOURCE_DATE_EPOCH="1000000000",
        # POSIX TZ counts west of UTC as positive: this zone is 5:30 east of UTC.
        TZ="XXX-5:30",
    )
    return SimpleNamespace(target=target, state=state, result=result)


# The third, the superscript two, U+00B2, is a digit but no ASCII digit.
BAD_EPOCHS = ("", "1.5", os.fsdecode(b"\302\262"), "99999999999999999999")


@pytest.fixture(scope="module")
def bad_epochs(root, source, run_plan, make_target, replay):
    target = make_target("gh-bad-epochs", TOOL_BAD_EPOCHS)
    state = root / "bad-epochs.state.json"
    runs = [
        date_replay(
            *(replay, source, run_plan, target, TOOL_BAD_EPOCHS, state), SOURCE_DATE_EPOCH=epoch
        )
        for epoch in BAD_EPOCHS
    ]
    out = "".join(r.out for r in runs)
    return SimpleNamespace(
        target=target, statuses=[shell_status(r) for r in runs], out=out, out_lines=lines(out)
    )


@pytest.fixture(scope="module")
def late_start(root, source, run_plan, make_target, replay):
    target = make_target("gh-late-start", TOOL_LATE_START)
    write_hook(target, "pre-receive", refuse_hook("refs/heads/main"))
    state = root / "late-start.state.json"
    first = date_replay(replay, source, run_plan, target, TOOL_LATE_START, state)
    # As a run started before committer dates were the time of the replay leaves its state file.
    recorded = json.loads(state.read_text(encoding="utf-8"))
    for sha in recorded.pop("committer_dates"):
        recorded["hashes"].pop(sha, None)
    state.write_text(json.dumps(recorded), encoding="utf-8")
    second = date_replay(replay, source, run_plan, target, TOOL_LATE_START, state)
    runs = [first, second]
    return SimpleNamespace(
        target=target, state=state, runs=runs, statuses=[shell_status(r) for r in runs]
    )


@pytest.fixture(scope="module")
def old_dates(root, source, run_plan, replay_uninterrupted, compare_finished, compare):
    state = json.loads(replay_uninterrupted.state.read_text(encoding="utf-8"))
    del state["committer_dates"]
    path = root / "old-dates.state.json"
    path.write_text(json.dumps(state), encoding="utf-8")
    tail = ("--state", path, run_plan.file, source.mirror, TOOL_NEW)
    return compare(replay_uninterrupted.target, *tail, api=run_plan.api)


@pytest.fixture(scope="module")
def early_commit(
    root, base_env, hashes, source, run_plan, replay_uninterrupted, old_dates, compare
):
    target = copy_target(root, replay_uninterrupted.target, "gh-order")
    f1, m2 = hashes["F1"], hashes["M2"]
    stamp = "1000000000 +0000"
    env = {
        **base_env,
        "GIT_AUTHOR_NAME": BOB[0],
        "GIT_AUTHOR_EMAIL": BOB[1],
        "GIT_AUTHOR_DATE": stamp,
        **as_committer(BOB, stamp),
    }
    tree = f"{recreated(replay_uninterrupted.state, f1)}^{{tree}}"
    parent = recreated(replay_uninterrupted.state, m2)
    made = run(
        ["git", "--git-dir", target.repo, "commit-tree", tree, "-p", parent],
        env,
        root,
        stdin="Repair the parser\n",
    )
    assert made.status == 0, made.err
    early = made.out.strip()
    target.git("update-ref", "refs/heads/fix/3-parser", early)
    state = json.loads(replay_uninterrupted.state.read_text(encoding="utf-8"))
    state["hashes"][f1] = early
    state["committer_dates"][f1] = stamp
    path = root / "order.state.json"
    path.write_text(json.dumps(state), encoding="utf-8")
    tail = ("--state", path, run_plan.file, source.mirror, TOOL_NEW)
    return SimpleNamespace(early=early, result=compare(target, *tail, api=run_plan.api))


def test_resumes_a_push_its_kill_interrupted_with_the_recorded_dates_and_dates_later_ones_anew(
    killed_dates, view, hashes
):
    killed = killed_dates
    assert killed.statuses == [137, 0], "".join(r.out for r in killed.runs)
    v = view(killed.target, killed.state)
    m, git = v.recreated, v.git
    assert git("log", "-1", "--format=%ct", m[hashes["B2"]]) == "1794000000"
    assert git("rev-parse", "feat/2-thing") == m[hashes["B2"]]
    assert git("log", "-1", "--format=%ct", m[hashes["C5"]]) == "1794009999"


def test_gives_each_recreated_commit_the_machines_time_where_source_date_epoch_is_not_set(
    on_clock, view, hashes
):
    clocked = on_clock
    v = view(clocked.target, clocked.state)
    m, git = v.recreated, v.git
    committed = int(git("log", "-1", "--format=%ct", m[hashes["C3"]]))
    assert clocked.clock_from <= committed <= clocked.clock_to
    assert git("log", "-1", "--format=%ad", "--date=raw", m[hashes["C3"]]) == "1772712000 +0200"


def test_replay_on_the_machines_clock_passes_the_comparison(source, run_plan, on_clock, compare):
    clocked = on_clock
    assert clocked.result.status == 0, clocked.result.out
    tail = ("--state", clocked.state, run_plan.file, source.mirror, TOOL_ON_CLOCK)
    c = compare(clocked.target, *tail, api=run_plan.api)
    assert c.status == 0, clocked.result.out + c.out
    assert has_match("No differences", c.out_lines), clocked.result.out + c.out


def test_commits_no_recreated_commit_before_its_parent_which_githubs_clock_may_date_later(
    early_epoch, view, hashes
):
    early = early_epoch
    v = view(early.target, early.state)
    m, git = v.recreated, v.git
    f1 = git("log", "-1", "--format=%ct", m[hashes["F1"]])
    m2 = git("log", "-1", "--format=%ct", m[hashes["M2"]])
    assert f1 == m2
    assert m2 != "1000000000"
    assert git("log", "-1", "--format=%cd", "--date=raw", m[hashes["C1"]]) == "1000000000 +0530"


def test_stops_before_the_confirmation_without_a_write_at_an_epoch_that_is_no_whole_number(
    bad_epochs,
):
    bad = bad_epochs
    out = bad.out_lines
    assert bad.statuses == [1, 1, 1, 1], bad.out
    not_whole = "run-replay.py: SOURCE_DATE_EPOCH is .*, not a whole number of seconds"
    assert sum(bool(re.fullmatch(not_whole, line)) for line in out) == 3, bad.out
    no_time = "run-replay.py: SOURCE_DATE_EPOCH .* is no time this machine can date"
    assert has_match(no_time, out), bad.out
    assert not has_search("Traceback|to confirm", out), bad.out
    assert not bad.target.writes(), bad.target.writes()


def test_resumes_a_run_started_before_committer_dates_with_the_original_ones_and_records_none(
    late_start, view, hashes
):
    late = late_start
    assert late.statuses == [1, 0], "".join(r.out for r in late.runs)
    v = view(late.target, late.state)
    m, git = v.recreated, v.git
    assert "committer_dates" not in v.state

    def planned(sha):
        commit = next(c for e in v.events for c in e.get("commits", []) if c["sha"] == sha)
        return int(datetime.datetime.fromisoformat(commit["committer"]["date"]).timestamp())

    assert all(
        int(git("log", "-1", "--format=%ct", m[hashes[k]])) == planned(hashes[k])
        for k in ("C1", "C3", "F1", "N2")
    )


def test_expects_the_original_committer_dates_from_a_state_file_that_predates_them(old_dates):
    r = old_dates
    out = r.out_lines
    assert r.status == 1, r.out
    step = (
        r"  main, step 1 \([0-9a-f]{7}\): committer Ada Example <ada@example.com> 1794000000"
        r" \+0000, planned Ada Example <ada@example.com> 1772359200 \+0000"
    )
    assert has_match(step, out), r.out
    assert not has_search("committed before its", out), r.out


def test_names_a_recreated_commit_that_is_committed_before_its_parent(
    hashes, replay_uninterrupted, early_commit
):
    r, early = early_commit.result, early_commit.early
    parent = recreated(replay_uninterrupted.state, hashes["M2"])
    assert r.status == 1, r.out
    named = (
        f"  the recreated commit {early[:7]} of {hashes['F1'][:7]} is committed before its"
        f" parent {parent[:7]}"
    )
    assert named in r.out_lines, r.out


def nothing_written(target, state):
    assert not target.writes(), target.writes()
    assert target.git("for-each-ref") == ""
    assert not state.exists()
    assert not state.with_name(state.name.removesuffix(".state.json") + ".work.git").exists()


def config_with(base_env, root, name, text):
    path = root / name
    own = Path(base_env["GIT_CONFIG_GLOBAL"]).read_text(encoding="utf-8")
    path.write_text(own + text, encoding="utf-8")
    return path


def sign_args(state, plan_file, mirror):
    return ("--sign", ADA, "--state", state, plan_file, mirror, TOOL_NEW)


@pytest.fixture(scope="module")
def no_key(root, source, run_plan, make_target, replay):
    target = make_target("gh-nokey")
    state = root / "nokey.state.json"
    args = sign_args(state, run_plan.file, source.mirror)
    return SimpleNamespace(
        target=target, state=state, result=replay(target, TOOL_NEW, *args, merged=True)
    )


FAKE_GPG = """\
#!/bin/sh
for last; do :; done
[ "$last" = 0123456789ABCDEF ] || { echo "gpg: error reading key: No secret key" >&2; exit 2; }
printf '%s\\n' 'sec:u:255:22:0123456789ABCDEF:1772000000:::u:::scESC:::+:::ed25519:::0:' \\
  'fpr:::::::::FEDCBA98765432100123456789ABCDEF:' \\
  'ssb:u:255:22:1111222233334444:1772000000::::::s:::+:::ed25519::' \\
  'fpr:::::::::AAAABBBBCCCCDDDD1111222233334444:'
"""

GPG_KEYS = (
    '[{"id": 3, "key_id": "FEDCBA9876543210", "can_sign": false, "subkeys":'
    ' [{"id": 4, "key_id": "1111222233334444", "can_sign": true}]}]\n'
)


@pytest.fixture(scope="module")
def gpg_key(root, base_env, source, run_plan, make_target, replay):
    bin_gpg = root / "bin-gpg"
    bin_gpg.mkdir()
    gpg = bin_gpg / "gpg"
    gpg.write_text(FAKE_GPG, encoding="utf-8")
    gpg.chmod(0o755)
    config = config_with(
        base_env,
        root,
        "global-gpg",
        f"[user]\n\tsigningkey = 0123456789ABCDEF\n[gpg]\n\tprogram = {gpg}\n",
    )
    target = make_target("gh-gpg")
    state = root / "gpg.state.json"
    args = sign_args(state, run_plan.file, source.mirror)
    unknown = replay(target, TOOL_NEW, *args, merged=True, GIT_CONFIG_GLOBAL=config)
    (target.folder / "gpg_keys.json").write_text(GPG_KEYS, encoding="utf-8")
    known = replay(target, "no", *args, merged=True, GIT_CONFIG_GLOBAL=config)
    return SimpleNamespace(target=target, state=state, unknown=unknown, known=known)


def test_sign_stops_without_a_user_signingkey_before_writing(no_key):
    r = no_key.result
    assert r.status == 1, r.out
    missing = "run-replay.py: --sign needs a user.signingkey in your git configuration"
    assert has_match(missing, r.out_lines), r.out
    nothing_written(no_key.target, no_key.state)


def test_sign_stops_before_writing_where_github_does_not_list_the_gpg_key_as_one_that_signs(
    gpg_key,
):
    r = gpg_key.unknown
    assert r.status == 1, r.out
    unlisted = (
        "^run-replay.py: GitHub does not list the GPG key 0123456789ABCDEF among your GPG keys"
        " that sign"
    )
    assert has_search(unlisted, r.out_lines), r.out
    calls = gpg_key.target.calls()
    assert has_search(r" GET user/gpg_keys\?per_page=100&page=1$", calls), calls
    nothing_written(gpg_key.target, gpg_key.state)


def test_sign_takes_a_gpg_key_whose_signing_subkey_github_lists_and_says_it_cannot_resume(
    gpg_key,
):
    r = gpg_key.known
    out = r.out_lines
    assert r.status == 1, r.out
    assert has_search("run-replay.py: not confirmed; nothing changed$", out), r.out
    assert has_match("  commits to sign +9", out), r.out
    assert has_match("  tags to sign +0", out), r.out
    signed = (
        "  signed: the commits committed and the tags tagged by ada@example.com, with the GPG"
        " key 0123456789ABCDEF"
    )
    assert signed in out, r.out
    twice = (
        "  this key does not sign a commit the same way twice: a run stopped in a push of signed"
        " commits, or in a signed tag, cannot resume"
    )
    assert twice in out, r.out
    nothing_written(gpg_key.target, gpg_key.state)


@pytest.fixture(scope="module")
def ssh_key(root, base_env):
    keygen = ("ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", "test", "-f")
    made = run([*keygen, root / "sign-key"], base_env, root)
    assert made.status == 0, made.err
    pub = root / "sign-key.pub"
    listed = public_key(pub)
    signers = root / "allowed-signers"
    signers.write_text(f"{ADA} {listed}\n", encoding="utf-8")
    config = config_with(
        base_env, root, "global-sign", f"[gpg]\n\tformat = ssh\n[user]\n\tsigningkey = {pub}\n"
    )
    # As Python prints the path, without the double slash a TMPDIR ending in a slash leaves.
    shown = re.sub("/+", "/", str(root))
    return SimpleNamespace(
        keygen=keygen, pub=pub, listed=listed, signers=signers, config=config, shown=shown
    )


def public_key(pub):
    return " ".join(pub.read_text(encoding="utf-8").split(" ")[:2]).rstrip("\n")


@pytest.fixture(scope="module")
def sign_target(make_target, ssh_key):
    def sign_target(name):
        target = make_target(name)
        listed = (
            f'[{{"id": 1, "key": "{ssh_key.listed}", "title": "test",'
            ' "created_at": "2026-11-01T00:00:00Z"}]\n'
        )
        (target.folder / "ssh_signing_keys.json").write_text(listed, encoding="utf-8")
        return target

    return sign_target


@pytest.fixture(scope="module")
def sign_replay(source, run_plan, ssh_key, replay):
    def sign_replay(target, answer, state, **variables):
        args = ("--pace", "0", *sign_args(state, run_plan.file, source.mirror))
        return replay(
            target, answer, *args, merged=True, GIT_CONFIG_GLOBAL=ssh_key.config, **variables
        )

    return sign_replay


@pytest.fixture(scope="module")
def pass_key(root, base_env, source, run_plan, ssh_key, sign_target, replay):
    # The passphrase x in place of the empty one after -N; no agent holds the key.
    made = run([*ssh_key.keygen[:5], "x", *ssh_key.keygen[6:], root / "pass-key"], base_env, root)
    assert made.status == 0, made.err
    text = ssh_key.config.read_text(encoding="utf-8")
    changed = "".join(
        re.sub("sign-key.pub", "pass-key.pub", line, count=1)
        for line in text.splitlines(keepends=True)
    )
    config = root / "global-pass"
    config.write_text(changed, encoding="utf-8")
    target = sign_target("gh-pass")
    state = root / "pass.state.json"
    args = ("--pace", "0", *sign_args(state, run_plan.file, source.mirror))
    result = replay(
        *(target, TOOL_NEW, *args),
        merged=True,
        unset=("SSH_AUTH_SOCK",),
        GIT_CONFIG_GLOBAL=config,
    )
    return SimpleNamespace(target=target, state=state, result=result)


@needs_ssh_keygen
def test_sign_stops_before_writing_when_the_key_has_a_passphrase_and_no_agent_holds_it(pass_key):
    r = pass_key.result
    assert r.status == 1, r.out
    assert has_search("the signing key is not in the agent", r.out_lines), r.out
    nothing_written(pass_key.target, pass_key.state)


@needs_ssh_keygen
def test_sign_stops_before_writing_where_github_does_not_list_the_ssh_key_as_a_signing_key(
    root, ssh_key, make_target, sign_replay
):
    target = make_target("gh-unknown")
    state = root / "unknown.state.json"
    r = sign_replay(target, TOOL_NEW, state)
    p = ssh_key.shown
    assert r.status == 1, r.out
    unlisted = (
        f"run-replay.py: GitHub does not list {p}/sign-key.pub among your SSH signing keys, so it"
        " would show the signed commits as unverified; add it with:"
        f" gh ssh-key add {p}/sign-key.pub --type signing"
    )
    assert unlisted in r.out_lines, r.out
    calls = target.calls()
    assert has_search(r" GET user/ssh_signing_keys\?per_page=100&page=1$", calls), calls
    nothing_written(target, state)


@needs_ssh_keygen
def test_sign_names_the_scope_gh_lacks_to_list_the_signing_keys_and_stops_before_writing(
    root, sign_target, sign_replay
):
    target = sign_target("gh-scope")
    state = root / "scope.state.json"
    r = sign_replay(target, TOOL_NEW, state, FAKE_GH_NO_SCOPE="1")
    assert r.status == 1, r.out
    refused = (
        "run-replay.py: GitHub refused to list your SSH signing keys (HTTP 404), which gh may"
        " read only with the scope read:ssh_signing_key; add it with:"
        " gh auth refresh -s read:ssh_signing_key"
    )
    assert refused in r.out_lines, r.out
    nothing_written(target, state)


@pytest.fixture(scope="module")
def signed_run(root, sign_target, sign_replay):
    target = sign_target("gh-signed-run")
    state = root / "signed-run.state.json"
    return SimpleNamespace(target=target, state=state, result=sign_replay(target, TOOL_NEW, state))


@needs_ssh_keygen
def test_sign_says_in_the_totals_how_many_commits_it_signs_and_with_which_key_and_in_each_push(
    ssh_key, signed_run
):
    r = signed_run.result
    out = r.out_lines
    assert r.status == 0, r.out
    assert has_match("  commits to sign +9", out), r.out
    signed = (
        "  signed: the commits committed and the tags tagged by ada@example.com, with the SSH"
        f" key {ssh_key.shown}/sign-key.pub (ssh-ed25519)"
    )
    assert signed in out, r.out
    assert not has_search("same way twice", out), r.out
    assert has_search("#3 branch fix/3-parser, 1 commit, 0 signed, at ", out), r.out
    assert has_search(" 3 commits to main, 3 signed, now at ", out), r.out
    assert has_search("#2 branch feat/2-thing, 2 commits, 2 signed, at ", out), r.out


@needs_ssh_keygen
def test_sign_signs_exactly_the_recreated_commits_whose_committer_has_the_address(
    ssh_key, signed_run, view, hashes
):
    v = view(signed_run.target, signed_run.state)
    m, git = v.recreated, v.git
    allowed = f"gpg.ssh.allowedSignersFile={ssh_key.signers}"
    marks = {
        c["sha"]: (
            c["committer"]["email"],
            git("-c", allowed, "log", "-1", "--format=%G?", m[c["sha"]]),
        )
        for e in v.events
        for c in e.get("commits", [])
    }
    assert marks
    assert all(mark == ("G" if email == ADA else "N") for email, mark in marks.values()), marks
    assert sorted(mark for _, mark in marks.values()) == ["G"] * 9 + ["N"]
    assert marks[hashes["F1"]] == ("bob@example.com", "N")
    merges = [git("log", "-1", "--format=%G?", m[hashes[k]]) for k in ("M2", "M3")]
    assert merges == ["N", "N"]


def commits_without_hashes(run_process, target):
    # Empty where git fails, which the check of their count then reports.
    listed = run_process(
        *("git", "--git-dir", target.repo, "log", "--all"),
        *("--format=%T %an %ae %ad %cn %ce %cd %s", "--date=raw"),
    )
    return sorted(listed.out_lines)


@needs_ssh_keygen
def test_sign_changes_no_tree_identity_date_or_subject(
    run_process, replay_uninterrupted, signed_run
):
    unsigned = commits_without_hashes(run_process, replay_uninterrupted.target)
    signed = commits_without_hashes(run_process, signed_run.target)
    assert len(unsigned) == 12, unsigned
    assert unsigned == signed


@pytest.fixture(scope="module")
def killed_signed(root, run_process, hashes, sign_target, sign_replay):
    target = sign_target("gh-killed-signed")
    write_hook(target, "post-receive", kill_hook("refs/heads/feat/2-thing"))
    state = root / "killed-signed.state.json"
    first = sign_replay(target, TOOL_NEW, state)
    # The push the kill left running ends on its own; then the copy.
    time.sleep(1)
    copy = copy_target(root, target, "gh-other-commit-hash")
    copy_state = root / "other-commit-hash.state.json"
    recorded = json.loads(state.read_text(encoding="utf-8")) if state.exists() else {"hashes": {}}
    # Where the killed run saved no hash, no state file of the copy is
    # written, so that only the check of the copy fails for it.
    if hashes["B2"] in recorded["hashes"]:
        # As a key that signs differently each time would leave it.
        recorded["hashes"][hashes["B2"]] = "0123456789abcdef0123456789abcdef01234567"
        copy_state.write_text(json.dumps(recorded), encoding="utf-8")
    other_hash_refs = run_process("git", "--git-dir", copy.repo, "for-each-ref").out
    other_hash_writes = len(copy.writes())
    second = sign_replay(target, TOOL_NEW, state)
    other_hash = sign_replay(copy, TOOL_NEW, copy_state)
    out = first.out + second.out
    return SimpleNamespace(
        target=target,
        state=state,
        statuses=[shell_status(r) for r in (first, second)],
        out=out,
        out_lines=lines(out),
        copy=copy,
        other_hash_refs=other_hash_refs,
        other_hash_writes=other_hash_writes,
        other_hash=other_hash,
    )


@needs_ssh_keygen
def test_sign_ends_a_run_killed_after_a_push_and_resumed_with_the_hashes_of_an_uninterrupted_one(
    run_process, signed_run, killed_signed
):
    killed, signed = killed_signed, signed_run
    assert killed.statuses == [137, 0], killed.out
    resumed = "Resume the replay of ada-example/tool into ada-example/tool-new at event 5 of 23"
    assert has_search(resumed, killed.out_lines), killed.out
    branch = run_process(
        "git", "--git-dir", killed.copy.repo, "for-each-ref", "refs/heads/feat/2-thing"
    )
    assert branch.out.rstrip("\n") != ""
    assert signed.target.dump() == killed.target.dump()
    signed_hashes, killed_hashes = (
        json.loads(f.read_text(encoding="utf-8"))["hashes"] for f in (signed.state, killed.state)
    )
    assert signed_hashes == killed_hashes


@needs_ssh_keygen
def test_stops_before_pushing_where_a_rebuilt_commit_gets_another_hash_than_the_state_file_records(
    run_process, hashes, ssh_key, killed_signed
):
    killed = killed_signed
    r = killed.other_hash
    out = r.out_lines
    b2 = hashes["B2"][:7]
    assert r.status == 1, r.out
    rebuilt = (
        f"run-replay.py: commit {b2} was rebuilt as [0-9a-f]{{7}}, but"
        f" {re.escape(ssh_key.shown)}/other-commit-hash.state.json records 0123456; its signature"
        " differs from the one the first run made: the signing key signs differently each time,"
        " or it is another key. The run stops before it pushes a second history$"
    )
    assert has_search(rebuilt, out), r.out
    assert has_search("^run-replay.py: stopped in event 5 of 23", out), r.out
    refs = run_process("git", "--git-dir", killed.copy.repo, "for-each-ref").out
    assert refs.rstrip("\n") == killed.other_hash_refs.rstrip("\n")
    assert len(killed.copy.writes()) == killed.other_hash_writes


def verified(run_process, ssh_key, target, tag):
    allowed = f"gpg.ssh.allowedSignersFile={ssh_key.signers}"
    return (
        run_process("git", "-c", allowed, "--git-dir", target.repo, "verify-tag", tag).status == 0
    )


@pytest.fixture(scope="module")
def signed_tags(root, ssh_key, extra_plan, mirror_extra, api_extra, sign_target, replay, compare):
    target = sign_target("gh-signed-tags")
    state = root / "signed-tags.state.json"
    args = ("--pace", "0", *sign_args(state, extra_plan.file, mirror_extra))
    result = replay(target, TOOL_NEW, *args, merged=True, GIT_CONFIG_GLOBAL=ssh_key.config)
    tail = ("--state", state, extra_plan.file, mirror_extra, TOOL_NEW)
    return SimpleNamespace(
        target=target, result=result, compared=compare(target, *tail, api=api_extra)
    )


@needs_ssh_keygen
def test_sign_signs_each_annotated_tag_whose_tagger_has_the_address_and_no_other_and_counts_them(
    run_process, ssh_key, signed_run, signed_tags
):
    tags = signed_tags
    r, c = tags.result, tags.compared
    out = r.out_lines
    assert (r.status, c.status) == (0, 0), r.out + c.out
    assert has_match("  tags to sign +1", out), r.out
    v02 = r"^ *[0-9]+/[0-9]+  create-tag    v0\.2, annotated, signed, at [0-9a-f]{7}$"
    assert has_search(v02, out), r.out
    v011 = r"^ *[0-9]+/[0-9]+  create-tag    v0\.1\.1, annotated, at [0-9a-f]{7}$"
    assert has_search(v011, out), r.out
    assert verified(run_process, ssh_key, tags.target, "v0.2")
    assert not verified(run_process, ssh_key, tags.target, "v0.1.1")
    # Its status goes unchecked: a failing cat-file finds no signature either.
    unsigned = run_process("git", "--git-dir", tags.target.repo, "cat-file", "tag", "v0.1.1")
    assert not has_search("BEGIN SSH SIGNATURE", unsigned.out_lines), unsigned.out
    assert has_match("  tags to sign +0", signed_run.result.out_lines), signed_run.result.out
    assert has_match("No differences", c.out_lines), r.out + c.out


@pytest.fixture(scope="module")
def mirror_sig(root, base_env, hashes, ssh_key, mirror_extra):
    mirror = root / "mirror-sig.git"
    shutil.copytree(mirror_extra, mirror, symlinks=True)
    sign = ("-c", "gpg.format=ssh", "-c", f"user.signingkey={ssh_key.pub}")
    Git(base_env, root)(
        *(*sign, "--git-dir", mirror, "tag", "-s", "-m", "Signed in the source", "v0.4"),
        hashes["C5"],
        env=as_committer(ADA_OLD, "2026-03-07T16:00:00+00:00"),
    )
    made = run(
        [
            "git",
            "--git-dir",
            mirror,
            "tag",
            "-a",
            # Keeps the message without a final line break.
            "--cleanup=verbatim",
            "-F",
            "-",
            "v0.5",
            hashes["C5"],
        ],
        {**base_env, **as_committer(ADA_OLD, "2026-03-07T17:00:00+00:00")},
        root,
        stdin="No line break",
    )
    assert made.status == 0, made.err
    return mirror


@pytest.fixture(scope="module")
def sig_plan(root, api_extra, leave, mirror_sig, plan_extra):
    events = root / "sig.jsonl"
    options = ("--leave-behind", leave)
    return SimpleNamespace(
        file=events, result=plan_extra(api_extra, events, *options, mirror=mirror_sig, merged=True)
    )


@pytest.fixture(scope="module")
def sig_replays(
    root, ssh_key, mirror_sig, sig_plan, api_extra, sign_target, make_target, replay, compare
):
    tail = (sig_plan.file, mirror_sig, TOOL_NEW)

    def replay_and_compare(target, state, *options, **variables):
        args = ("--pace", "0", *options, "--state", state, *tail)
        result = replay(target, TOOL_NEW, *args, merged=True, **variables)
        compared = compare(target, "--state", state, *tail, api=api_extra)
        return SimpleNamespace(target=target, result=result, compared=compared)

    signed = replay_and_compare(
        sign_target("gh-sig-signed"),
        root / "sig-signed.state.json",
        *("--sign", ADA),
        GIT_CONFIG_GLOBAL=ssh_key.config,
    )
    unsigned = replay_and_compare(make_target("gh-sig-unsigned"), root / "sig-unsigned.state.json")
    return SimpleNamespace(signed=signed, unsigned=unsigned)


@needs_ssh_keygen
def test_plans_a_signed_tags_message_without_its_signature_and_one_without_a_final_break_as_is(
    run_process, mirror_sig, sig_plan
):
    r = sig_plan.result
    assert r.status == 0, r.out
    tag = run_process("git", "--git-dir", mirror_sig, "cat-file", "tag", "v0.4")
    assert "-----BEGIN SSH SIGNATURE-----" in tag.out_lines, tag.out
    p = Plan(sig_plan.file)
    messages = {
        e["name"]: e["message"] for e in p.of("create-tag") if e["name"] in ("v0.4", "v0.5")
    }
    assert messages == {"v0.4": "Signed in the source\n", "v0.5": "No line break"}


def tag_message(run_process, target, tag):
    return past_header(run_process("git", "--git-dir", target.repo, "cat-file", "tag", tag).out)


def first_lines(text, count):
    return "".join(re.findall(r"[^\n]*\n|[^\n]+$", text)[:count]).rstrip("\n")


@needs_ssh_keygen
def test_sign_signs_a_tag_signed_in_the_source_anew_and_ends_an_unended_message_so_both_verify(
    run_process, ssh_key, sig_replays
):
    signed = sig_replays.signed
    r, c = signed.result, signed.compared
    assert (r.status, c.status) == (0, 0), r.out + c.out
    assert has_match("  tags to sign +3", r.out_lines), r.out
    assert verified(run_process, ssh_key, signed.target, "v0.4")
    assert verified(run_process, ssh_key, signed.target, "v0.5")
    v04 = tag_message(run_process, signed.target, "v0.4")
    assert first_lines(v04, 2) == "Signed in the source\n-----BEGIN SSH SIGNATURE-----"
    assert sum(line.startswith("-----BEGIN") for line in lines(v04)) == 1, v04
    v05 = tag_message(run_process, signed.target, "v0.5")
    assert first_lines(v05, 2) == "No line break\n-----BEGIN SSH SIGNATURE-----"
    assert has_match("No differences", c.out_lines), r.out + c.out


@needs_ssh_keygen
def test_without_sign_gives_a_tag_signed_in_the_source_no_signature_and_keeps_an_unended_message(
    run_process, sig_replays
):
    unsigned = sig_replays.unsigned
    r, c = unsigned.result, unsigned.compared
    assert (r.status, c.status) == (0, 0), r.out + c.out
    assert tag_message(run_process, unsigned.target, "v0.4").rstrip("\n") == "Signed in the source"
    v05 = run_process("git", "--git-dir", unsigned.target.repo, "cat-file", "tag", "v0.5").out
    assert v05.encode("utf-8")[-14:].decode("utf-8").rstrip("\n") == "\nNo line break"
    assert has_match("No differences", c.out_lines), r.out + c.out
