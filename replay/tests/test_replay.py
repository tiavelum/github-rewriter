"""The checks of replay.py, run from a run file into a target that does not
exist yet; and of a source whose default branch is master: its plans, its
replays by run-replay.py and by replay.py, and the uninterrupted replay's
event file as one planned before the rename."""

import hashlib
import json
import re
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from conftest import (
    API_BASE,
    REPLAY,
    TOOL,
    TOOL_NEW,
    Git,
    Plan,
    copy_target,
    has_match,
    has_search,
    lines,
    run,
    shell_status,
)

# replay.py, from a run file, into a target that does not exist yet, with
# sub-issue links: #1 and #4 of the source under ada-example/plans#9, #6 under
# #4, and ada-example/plans#11 under #6.
SLUG = "ada-example/tool-replay-20261116"
LINKS_ALL = (
    '{"ada-example/plans#9": [9001, 8010, 9004], "ada-example/tool#4": [9006],'
    ' "ada-example/tool#6": [8011]}'
)
# The links as the replay leaves them, each replayed item in the place of
# the source's.
LINKS_MOVED = {
    "ada-example/plans#9": [7001, 8010, 7004],
    "ada-example/tool#4": [9006],
    "ada-example/tool-replay-20261116#4": [7006],
    "ada-example/tool-replay-20261116#6": [8011],
}


def bre(text):
    """A grep pattern whose only special character is the dot, as a Python
    pattern: each dot any character, as grep reads it, every other character
    itself."""
    return re.escape(text).replace(r"\.", ".")


def without_time(call):
    """A logged call without its time, as cut -d" " -f2- prints it."""
    return call.partition(" ")[2] if " " in call else call


def first_write(writes):
    """The first write without its time, as head -n 1 | cut -d" " -f2-
    prints it; empty where there is none."""
    return without_time(writes[0]) if writes else ""


def mapped(out_lines, patterns, substitutions):
    """The lines that match one of the patterns, each changed by the
    substitutions in their order and followed by a space, as grep -e ... |
    sed -e ... | tr "\\n" " " prints them."""
    picked = [line for line in out_lines if any(re.search(p, line) for p in patterns)]
    result = ""
    for line in picked:
        for pattern, replacement in substitutions:
            line = re.sub(pattern, replacement, line, count=1)
        result += line + " "
    return result


def count_search(pattern, out_lines):
    """The number of lines the pattern matches in, as grep -c counts them."""
    return sum(bool(re.search(pattern, line)) for line in out_lines)


def read_json(path):
    """The JSON of a file; a missing file fails, as open() does."""
    return json.loads(Path(path).read_text(encoding="utf-8"))


def held_links(target):
    """The target's sub-issue links whose list is not empty; a missing file
    fails."""
    return {k: v for k, v in read_json(target.folder / "links.json").items() if v}


def heads(target):
    """The target's branches, each followed by a space, as for-each-ref
    --format="%(refname:short)" refs/heads/ | tr "\\n" " " prints them."""
    listed = target.git("for-each-ref", "--format=%(refname:short)", "refs/heads/")
    return "".join(f"{line} " for line in listed.split("\n")) if listed else ""


@pytest.fixture(scope="module")
def replay_setup(root, run_plan, make_target):
    """Makes a target that does not exist yet, ada-example/tool-replay-20261116
    by default, with the links given as JSON or those of LINKS_ALL, and next to
    it <folder>-api, the source's API of the run's plan with issue ids,
    settings, Actions and the issues of ada-example/plans."""

    def setup(name, slug=SLUG, links=LINKS_ALL):
        target = make_target(name, slug)
        (target.folder / "absent").touch()
        (target.folder / "links.json").write_text(links + "\n", encoding="utf-8")
        api = root / f"{name}-api"
        shutil.copytree(run_plan.api, api)
        for page in api.glob(f"{API_BASE}_issues-*.json"):
            issues = json.loads(page.read_text(encoding="utf-8"))
            for it in issues:
                it["id"] = 9000 + it["number"]
            page.write_text(json.dumps(issues), encoding="utf-8")
        info = {
            "default_branch": "main",
            "delete_branch_on_merge": True,
            "allow_merge_commit": False,
            "allow_squash_merge": True,
            "allow_rebase_merge": False,
            "description": "A small tool",
        }
        (api / f"{API_BASE}.json").write_text(json.dumps(info), encoding="utf-8")
        (api / f"{API_BASE}_actions_permissions.json").write_text(
            '{"enabled": true}', encoding="utf-8"
        )
        plans = [
            {"id": 8000 + n, "number": n, "title": f"Plan {n}", "state": "open"}
            for n in (9, 10, 11)
        ]
        (api / "repos_ada-example_plans_issues-1.json").write_text(
            json.dumps(plans), encoding="utf-8"
        )
        return target

    return setup


@pytest.fixture(scope="module")
def run_file(root, hashes):
    """Writes a run file for the replay of ada-example/tool that sets every
    type the plan would guess, with the backup folder given and the fields
    given set to those values."""

    def write(path, backup, **changes):
        h = hashes
        fields = {
            "source": TOOL,
            "target": SLUG,
            "mailmap": [
                "Ada Example <ada@example.com> <ada.old@example.com>",
                "Ada Example <ada@example.com> GitHub <noreply@github.com>",
            ],
            "types": [
                f"{h['C1'][:7]} docs",
                f"{h['C3'][:7]} test",
                f"{h['C4'][:9]} chore",
                f"{h['C5'][:7]} feat",
            ],
            "pace": 0,
            "backup": str(backup),
            "clone_url": f"{root}/source.git",
            **changes,
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(fields, indent=1), encoding="utf-8")
        return path

    return write


@pytest.fixture(scope="module")
def one(root, target_env):
    """Runs replay.py against the target with the answer typed at the
    confirmation, the source's API in <folder>-api and the variables given
    set, from the session's folder, with the interpreter that runs pytest;
    its output and error in one unless merged is false."""

    def one(target, answer, path, merged=True, **variables):
        env = {
            **target_env,
            "FAKE_GITHUB": str(target.folder),
            "FAKE_GH_API": f"{target.folder}-api",
            **{k: str(v) for k, v in variables.items()},
        }
        script = [sys.executable, REPLAY / "replay.py", path]
        return run(script, env, root, stdin=f"{answer}\n", merged=merged)

    return one


def ran(target, runs, progress=None):
    """What runs of replay.py into a target left, read right after them,
    before a later run changes the target: their statuses, their output
    appended in one, the target's writes, whether it is still absent, and
    whether the progress file given exists."""
    out = "".join(r.out for r in runs)
    return SimpleNamespace(
        target=target,
        runs=runs,
        statuses=[shell_status(r) for r in runs],
        out=out,
        out_lines=lines(out),
        writes=target.writes(),
        absent=(target.folder / "absent").exists(),
        progress=None if progress is None else progress.exists(),
    )


# One uninterrupted run.


@pytest.fixture(scope="module")
def replay_py_uninterrupted(root, replay_setup, run_file, one):
    """The uninterrupted run, its standard output and error apart."""
    name = "replay-py-uninterrupted"
    target = replay_setup(name)
    path = run_file(root / f"{name}-runs" / "tool.run.json", root / f"{name}-backup")
    result = one(target, SLUG, path, merged=False)
    return SimpleNamespace(target=target, result=result, writes=target.writes())


STEPS = (
    "1 of 8, mirror",
    "2 of 8, plan",
    "3 of 8, create",
    "4 of 8, settings",
    "5 of 8, replay",
    "6 of 8, compare",
    "7 of 8, links",
    "8 of 8, commands",
)


def test_runs_every_step_after_one_confirmation_and_the_comparison_finds_no_difference(
    replay_py_uninterrupted,
):
    """replay.py runs every step from a run file after one confirmation, and the comparison finds no difference"""  # noqa: E501 # the description word for word
    r = replay_py_uninterrupted.result
    out = r.out_lines
    assert shell_status(r) == 0, r.err + r.out
    assert r.err == "", r.err
    for n in STEPS:
        assert has_search(f"^Step {n}: ", out), f"no step {n}\n{r.out}"
    assert count_search("to confirm: ", out) == 2, r.out
    confirmed = f"Type {SLUG} to confirm: {SLUG}, as --confirmed gives it"
    assert has_match(bre(confirmed), out), r.out
    assert has_match("No differences", out), r.out
    assert has_match("  guessed types +0", out), r.out
    assert not (replay_py_uninterrupted.target.folder / "refused").exists()


def test_creates_the_target_private_with_actions_off_and_head_branches_deleted_on_merge(
    replay_py_uninterrupted,
):
    """replay.py creates the target private after the confirmation, with Actions off and head branches deleted on merge as in the source"""  # noqa: E501 # the description word for word
    t = replay_py_uninterrupted.target
    assert first_write(replay_py_uninterrupted.writes) == "POST user/repos", (
        replay_py_uninterrupted.writes
    )
    assert not (t.folder / "absent").exists()
    s, a = read_json(t.folder / "settings.json"), read_json(t.folder / "actions.json")
    assert s["private"] and s["delete_branch_on_merge"] and a == {"enabled": False}, (s, a)
    assert heads(t) == "docs/5-notes main "


def test_moves_each_link_into_the_place_of_the_sources_item_and_links_its_sub_issues(
    replay_py_uninterrupted,
):
    """replay.py moves each sub-issue link into the place of the source's item, and links the sub-issues of the source's items"""  # noqa: E501 # the description word for word
    out = replay_py_uninterrupted.result.out_lines
    assert held_links(replay_py_uninterrupted.target) == LINKS_MOVED
    assert has_match(bre("  #1 under ada-example/plans#9, in the place of the source's"), out)
    assert has_match(bre("  ada-example/plans#11 under the replay's #6"), out), (
        replay_py_uninterrupted.result.out
    )


def test_moves_a_link_after_the_sub_issue_before_the_sources_or_before_the_one_after_it(
    replay_py_uninterrupted,
):
    """replay.py moves a link after the sub-issue before the source's, or before the one after it where the source's is first"""  # noqa: E501 # the description word for word
    text = (replay_py_uninterrupted.target.folder / "priorities").read_text(encoding="utf-8")
    assert text.replace("\n", " ") == (
        '{"before_id": 8010, "sub_issue_id": 7001} {"after_id": 8010, "sub_issue_id": 7004} '
    ), text


COMMANDS = (
    "gh api -X PATCH repos/ada-example/tool -f name=tool-archive",
    "gh api -X PATCH repos/ada-example/tool-archive -F archived=true",
    "gh api -X PATCH repos/ada-example/tool-replay-20261116 -f name=tool",
    "gh api -X PUT repos/ada-example/tool/actions/permissions -F enabled=true",
    "gh api -X PATCH repos/ada-example/tool -F allow_merge_commit=false"
    " -F allow_squash_merge=true -F allow_rebase_merge=false -F delete_branch_on_merge=true"
    " -f 'description=A small tool'",
    "gh api -X DELETE repos/ada-example/tool/git/refs/heads/docs/5-notes",
)


def test_prints_without_running_them_the_commands_that_archive_rename_and_restore(
    replay_py_uninterrupted,
):
    """replay.py prints, without running them, the commands that archive the source, rename the replay and restore its settings"""  # noqa: E501 # the description word for word
    out = replay_py_uninterrupted.result.out_lines
    for line in COMMANDS:
        assert line in out, f"no line: {line}\n{replay_py_uninterrupted.result.out}"
    calls = replay_py_uninterrupted.target.calls()
    assert not has_search("archived|name=tool", calls), calls


READS = (
    "gh api repos/ada-example/tool/actions/secrets --jq .total_count",
    "gh api repos/ada-example/tool/actions/variables --jq .total_count",
    "gh api repos/ada-example/tool/hooks --jq length",
    "gh api repos/ada-example/tool/keys --jq length",
    "gh api repos/ada-example/tool/collaborators --jq '.[].login'",
    "test ! -d ~/vc/tool || { git -C ~/vc/tool status --short; mv ~/vc/tool ~/vc/tool-old; }",
    "gh repo clone ada-example/tool ~/vc/tool",
)


def test_prints_the_reads_before_the_archive_and_after_it_the_commands_that_replace_the_clone(
    replay_py_uninterrupted,
):
    """replay.py prints the reads of what the comparison cannot see in the source before the archive, and after it the commands that replace the local clone"""  # noqa: E501 # the description word for word
    out = replay_py_uninterrupted.result.out_lines
    for line in READS:
        assert line in out, f"no line: {line}\n{replay_py_uninterrupted.result.out}"
    assert not has_search("secret_scanning|has_wiki", out), replay_py_uninterrupted.result.out
    order = mapped(
        out,
        ("/actions/secrets --jq", "archived=true$", "^gh repo clone "),
        ((".*secrets.*", "reads"), (".*archived.*", "archive"), ("^gh repo clone.*", "clone")),
    )
    assert order == "reads archive clone ", replay_py_uninterrupted.result.out


# A run file that leaves a type to guess; a wrong confirmation; and run
# files that replay.py refuses, run against the target of the wrong
# confirmation after it.


@pytest.fixture(scope="module")
def replay_py_guessed_type(root, hashes, replay_setup, run_file, one):
    name = "replay-py-guessed-type"
    target = replay_setup(name)
    h = hashes
    types = [f"{h['C4'][:9]} chore", f"{h['C1'][:7]} docs", f"{h['C3'][:7]} test"]
    path = run_file(root / f"{name}-runs" / "tool.run.json", root / f"{name}-backup", types=types)
    return ran(target, [one(target, SLUG, path)], root / f"{name}-runs" / "tool.progress.json")


def test_stops_after_the_plan_before_any_write_and_the_confirmation_where_a_type_is_guessed(
    replay_py_guessed_type, hashes
):
    """replay.py stops after the plan, before any write and before the confirmation, where a type would be guessed"""  # noqa: E501 # the description word for word
    out = replay_py_guessed_type.out_lines
    assert replay_py_guessed_type.statuses == [1], replay_py_guessed_type.out
    guessed = bre(
        "replay.py: 1 title would get a guessed type, marked guessed above;"
        " give each its type in types of "
    )
    assert has_search(f"^{guessed}", out), replay_py_guessed_type.out
    assert has_search(f"^  {hashes['C5'][:7]}  guessed  ", out), replay_py_guessed_type.out
    stopped = bre("replay.py: stopped in step 2 of 8, plan, before any write to GitHub in this run")
    assert has_search(f"^{stopped}", out), replay_py_guessed_type.out
    assert not has_search("to confirm", out), replay_py_guessed_type.out
    assert not replay_py_guessed_type.writes, replay_py_guessed_type.writes
    assert replay_py_guessed_type.absent
    assert replay_py_guessed_type.progress is False


@pytest.fixture(scope="module")
def replay_py_wrong_confirmation(root, replay_setup, run_file, one):
    name = "replay-py-wrong-confirmation"
    target = replay_setup(name)
    path = run_file(root / f"{name}-runs" / "tool.run.json", root / f"{name}-backup")
    return ran(
        target, [one(target, "tool-replay-20261116", path)], path.with_name("tool.progress.json")
    )


WRONG_CONFIRMATION_LINES = (
    "  7. move sub-issue links: 4",
    "       #1: in ada-example/plans#9, links the replay's #1 in the place of the source's and"
    " unlinks the source's (writes in ada-example/plans)",
    "       the replay's #6 gets the sub-issues of the source's: ada-example/plans#11, taken"
    " from the source's #6 with replace_parent (writes in ada-example/plans and in the source)",
    "  3. create ada-example/tool-replay-20261116, private and empty",
    "  5. run run-replay.py --pace 0 --final-name ada-example/tool, and make main the default"
    " branch where GitHub names another",
)


def test_lists_what_it_will_do_links_included_and_writes_nothing_on_a_wrong_confirmation(
    replay_py_wrong_confirmation,
):
    """replay.py lists what it will do, sub-issue links included, and writes nothing on a wrong confirmation"""  # noqa: E501 # the description word for word
    out = replay_py_wrong_confirmation.out_lines
    assert replay_py_wrong_confirmation.statuses == [1], replay_py_wrong_confirmation.out
    assert has_search(bre("replay.py: not confirmed; nothing changed on GitHub") + "$", out)
    for line in WRONG_CONFIRMATION_LINES:
        assert has_match(bre(line), out), f"no line: {line}\n{replay_py_wrong_confirmation.out}"
    assert not replay_py_wrong_confirmation.writes, replay_py_wrong_confirmation.writes
    assert replay_py_wrong_confirmation.absent
    assert replay_py_wrong_confirmation.progress is False


@pytest.fixture(scope="module")
def replay_py_refused_run_files(root, source, replay_py_wrong_confirmation, run_file, one):
    """The three refused run files, each run against the target of the wrong
    confirmation after it; their statuses, their output appended in one, and
    that target's writes after them."""
    name = "replay-py-refused-run-files"
    backup = root / f"{name}-backup"
    runs = root / f"{name}-runs"
    runs.mkdir()
    paths = [
        run_file(source.work / "tool.run.json", backup),
        run_file(runs / "colour.run.json", backup, colour="blue"),
        run_file(runs / "name.run.json", backup, target="ada-example/tool-new"),
    ]
    target = replay_py_wrong_confirmation.target
    return ran(target, [one(target, SLUG, p) for p in paths])


def test_refuses_a_run_file_in_a_work_tree_with_an_unknown_field_or_a_target_not_named_for_the_day(
    replay_py_refused_run_files,
):
    """replay.py refuses a run file in a git work tree, with an unknown field, or with a target not named for the day of the replay"""  # noqa: E501 # the description word for word
    out = replay_py_refused_run_files.out_lines
    assert replay_py_refused_run_files.statuses == [1, 1, 1], replay_py_refused_run_files.out
    work_tree = bre(
        "tool.run.json lies in a git work tree; keep it outside any repository,"
        " since it holds the mailmap"
    )
    assert has_search(work_tree + "$", out), replay_py_refused_run_files.out
    unknown = bre("colour.run.json has fields replay.py does not know: colour")
    assert has_search(unknown + "$", out), replay_py_refused_run_files.out
    named = bre("name.run.json: target must be ada-example/tool-replay-<YYYYMMDD-HHMM>")
    assert has_search(named, out), replay_py_refused_run_files.out
    assert not replay_py_refused_run_files.writes, replay_py_refused_run_files.writes


# A run stopped by a Ctrl-C in the replay, resumed into a difference the
# comparison finds, since the source's label changed meanwhile, and resumed
# once more after the label is back.


@pytest.fixture(scope="module")
def replay_py_interrupted(root, replay_setup, run_file, one):
    name = "replay-py-interrupted"
    target = replay_setup(name)
    path = run_file(root / f"{name}-runs" / "tool.run.json", root / f"{name}-backup")
    labels = root / f"{name}-api" / f"{API_BASE}_labels-1.json"
    first = one(target, SLUG, path, FAKE_GH_INTERRUPT=f"POST repos/{SLUG}/issues")
    kept = labels.read_bytes()
    # sed 's/0075ca/123456/': the first on each line.
    changed = [re.sub("0075ca", "123456", line, count=1) for line in kept.decode().split("\n")]
    labels.write_text("\n".join(changed), encoding="utf-8")
    second = one(target, SLUG, path)
    labels.write_bytes(kept)
    third = one(target, SLUG, path)
    return ran(target, [first, second, third])


def test_stops_where_run_replay_stops_and_the_same_command_resumes_after_a_new_confirmation(
    replay_py_interrupted,
):
    """replay.py stops where run-replay.py stops, and the same command resumes there after a new confirmation"""  # noqa: E501 # the description word for word
    out = replay_py_interrupted.out_lines
    assert replay_py_interrupted.statuses == [1, 1, 0], replay_py_interrupted.out
    stopped = "^" + bre("run-replay.py: stopped after event ") + "[0-9]*"
    stopped += bre(" of 23; run the same command again to resume") + "$"
    assert has_search(stopped, out), replay_py_interrupted.out
    step = bre(
        "replay.py: stopped in step 5 of 8, replay; run the same command again to resume there"
        " once the cause is removed"
    )
    assert has_search(f"^{step}$", out), replay_py_interrupted.out
    resume = bre(f"Resume the replay of ada-example/tool into {SLUG} at step 5, replay, from ")
    assert has_search(f"^{resume}.*" + bre("tool.progress.json:") + "$", out), (
        replay_py_interrupted.out
    )
    event = bre(f"Resume the replay of ada-example/tool into {SLUG} at event ") + "[0-9]*"
    assert has_search(f"^{event}" + bre(" of 23"), out), replay_py_interrupted.out
    assert count_search(" POST user/repos$", replay_py_interrupted.target.calls()) == 1, (
        replay_py_interrupted.target.calls()
    )


def test_stops_at_a_difference_the_comparison_finds_before_it_moves_a_sub_issue_link(
    replay_py_interrupted,
):
    """replay.py stops at a difference the comparison finds, before it moves a sub-issue link"""
    out = replay_py_interrupted.out_lines
    assert "  label docs: colour 0075ca, the source's 123456" in out, replay_py_interrupted.out
    step = bre(
        "replay.py: stopped in step 6 of 8, compare; run the same command again to resume there"
    )
    assert has_search(f"^{step}", out), replay_py_interrupted.out
    assert count_search("^Step 7 of 8, links", out) == 1, replay_py_interrupted.out


def test_ends_a_stopped_and_resumed_run_with_the_links_and_the_target_of_an_uninterrupted_one(
    replay_py_uninterrupted, replay_py_interrupted
):
    """replay.py ends a stopped and resumed run with the links and the target of an uninterrupted one"""  # noqa: E501 # the description word for word
    assert held_links(replay_py_interrupted.target) == LINKS_MOVED
    assert has_match("No differences", replay_py_interrupted.out_lines), replay_py_interrupted.out
    uninterrupted, interrupted = replay_py_uninterrupted.target, replay_py_interrupted.target
    assert uninterrupted.dump().decode("utf-8") == interrupted.dump().decode("utf-8")


# A target that GitHub creates with the default branch master, and lets no
# one change while it lacks the branch, with #1 the only sub-issue of
# ada-example/plans#9 and no other link; stopped by a Ctrl-C in the replay
# after the first push, and resumed; signed in as bob-example, a member of the
# organisation ada-example.


@pytest.fixture(scope="module")
def replay_py_master_target(root, replay_setup, run_file, one):
    name = "replay-py-master-target"
    target = replay_setup(name, SLUG, '{"ada-example/plans#9": [9001]}')
    path = run_file(root / f"{name}-runs" / "tool.run.json", root / f"{name}-backup")
    first = one(
        target,
        SLUG,
        path,
        FAKE_GH_DEFAULT="master",
        FAKE_GH_LOGIN="bob-example",
        FAKE_GH_INTERRUPT=f"POST repos/{SLUG}/issues",
    )
    return ran(target, [first, one(target, SLUG, path)])


RENAMED = "  default branch main, where GitHub had named it master"


def test_gives_the_target_the_sources_default_branch_once_it_has_it_where_github_names_another(
    replay_py_master_target,
):
    """replay.py gives the target the source's default branch once it has it, where GitHub names another at the creation"""  # noqa: E501 # the description word for word
    out, t = replay_py_master_target.out_lines, replay_py_master_target.target
    assert replay_py_master_target.statuses == [1, 0], replay_py_master_target.out
    step = bre("replay.py: stopped in step 5 of 8, replay; run the same command again")
    assert has_search(f"^{step}", out), replay_py_master_target.out
    assert has_match(bre(RENAMED), out), replay_py_master_target.out
    assert not (t.folder / "rejected").exists(), (t.folder / "rejected").read_text()
    assert has_match("No differences", out), replay_py_master_target.out
    assert read_json(t.folder / "settings.json")["default_branch"] == "main"
    assert held_links(t) == {"ada-example/plans#9": [7001]}


# The same target named master, replayed without a stop, from a public
# source.


@pytest.fixture(scope="module")
def replay_py_public_source(root, replay_setup, run_file, one):
    name = "replay-py-public-source"
    target = replay_setup(name)
    info_path = root / f"{name}-api" / f"{API_BASE}.json"
    info = read_json(info_path)
    info.update(
        private=False,
        visibility="public",
        has_wiki=True,
        has_projects=True,
        has_discussions=False,
        security_and_analysis={
            "secret_scanning": {"status": "enabled"},
            "secret_scanning_push_protection": {"status": "enabled"},
            "dependabot_security_updates": {"status": "disabled"},
        },
    )
    info_path.write_text(json.dumps(info), encoding="utf-8")
    path = run_file(root / f"{name}-runs" / "tool.run.json", root / f"{name}-backup")
    return ran(target, [one(target, SLUG, path, FAKE_GH_DEFAULT="master")])


def test_gives_the_sources_default_branch_after_an_uninterrupted_replay_into_a_master_target(
    replay_py_public_source,
):
    """replay.py gives the target the source's default branch after an uninterrupted replay into a target named master"""  # noqa: E501 # the description word for word
    assert has_match(bre(RENAMED), replay_py_public_source.out_lines), replay_py_public_source.out
    rejected = replay_py_public_source.target.folder / "rejected"
    assert not rejected.exists(), replay_py_public_source.out + rejected.read_text()


def test_creates_a_public_sources_target_private_and_prints_the_command_that_makes_it_public(
    replay_py_uninterrupted, replay_py_public_source
):
    """replay.py creates the target of a public source private, and prints the command that makes the renamed replay public, after the rename, only for such a source"""  # noqa: E501 # the description word for word
    out = replay_py_public_source.out_lines
    s = read_json(replay_py_public_source.target.folder / "settings.json")
    assert s["private"] and "visibility" not in s, s
    assert "gh api -X PATCH repos/ada-example/tool -f visibility=public" in out, (
        replay_py_public_source.out
    )
    order = mapped(
        out,
        ("-f name=tool$", "visibility=public$"),
        ((".*-f name=tool$", "rename"), (".*visibility=public$", "visibility")),
    )
    assert order == "rename visibility ", replay_py_public_source.out
    assert not has_search("visibility=", replay_py_uninterrupted.result.out_lines), (
        replay_py_uninterrupted.result.out
    )


def test_prints_the_wiki_projects_and_discussions_with_the_settings_and_secret_scanning_after(
    replay_py_public_source,
):
    """replay.py prints the source's wiki, projects and discussions with its settings, and its secret scanning after the visibility"""  # noqa: E501 # the description word for word
    out = replay_py_public_source.out_lines
    settings = (
        "gh api -X PATCH repos/ada-example/tool -F allow_merge_commit=false"
        " -F allow_squash_merge=true -F allow_rebase_merge=false -F delete_branch_on_merge=true"
        " -F has_wiki=true -F has_projects=true -F has_discussions=false"
        " -f 'description=A small tool'"
    )
    assert settings in out, replay_py_public_source.out
    order = mapped(
        out,
        ("visibility=public$", "security_and_analysis"),
        ((".*visibility=public$", "visibility"), (".*security_and_analysis.*", "security")),
    )
    assert order == "visibility security ", replay_py_public_source.out
    security = (
        "gh api -X PATCH repos/ada-example/tool"
        " -f 'security_and_analysis[secret_scanning][status]=enabled'"
        " -f 'security_and_analysis[secret_scanning_push_protection][status]=enabled'"
    )
    assert security in out, replay_py_public_source.out
    assert not has_search("dependabot", out), replay_py_public_source.out


def test_reads_the_parent_only_of_an_issue_that_names_one_and_skips_the_move_of_an_only_sub_issue(
    replay_py_master_target,
):
    """replay.py reads the parent only of an issue whose parent_issue_url names one, and skips the move of an only sub-issue"""  # noqa: E501 # the description word for word
    calls = replay_py_master_target.target.calls()
    assert has_search(" GET repos/ada-example/tool/issues/1/parent$", calls), calls
    assert not has_search(" GET repos/ada-example/tool/issues/[46]/parent$", calls), calls
    assert not (replay_py_master_target.target.folder / "priorities").exists()


def test_creates_the_target_with_orgs_owner_repos_where_its_owner_is_not_the_signed_in_account(
    replay_py_master_target,
):
    """replay.py creates the target with orgs/<owner>/repos where its owner is not the account gh is signed in with"""  # noqa: E501 # the description word for word
    assert first_write(replay_py_master_target.target.writes()) == "POST orgs/ada-example/repos", (
        replay_py_master_target.target.writes()
    )
    assert not has_search(" POST user/repos$", replay_py_master_target.target.calls()), (
        replay_py_master_target.target.calls()
    )


# GitHub refuses the creation once, then the change of Actions once; each
# run stops in that step, and the next resumes there, the last one only up to
# a wrong confirmation.


@pytest.fixture(scope="module")
def replay_py_github_refuses(root, replay_setup, run_file, one):
    name = "replay-py-github-refuses"
    target = replay_setup(name)
    path = run_file(root / f"{name}-runs" / "tool.run.json", root / f"{name}-backup")
    denied = [
        one(target, SLUG, path, FAKE_GH_DENY=deny)
        for deny in ("POST user/repos", f"PUT repos/{SLUG}/actions/permissions")
    ]
    result = ran(target, [*denied, one(target, "no", path)])
    progress = root / f"{name}-runs" / "tool.progress.json"
    result.progress = progress.read_text(encoding="utf-8") if progress.exists() else None
    result.actions = (target.folder / "actions.json").exists()
    return result


DENIED = " answered HTTP 403: Resource not accessible by personal access token"


def test_stops_in_step_3_where_github_refuses_the_creation_and_creates_the_target_on_the_next_run(
    replay_py_github_refuses,
):
    """replay.py stops in step 3 where GitHub refuses the creation, and creates the target when the same command runs again"""  # noqa: E501 # the description word for word
    out = replay_py_github_refuses.out_lines
    assert replay_py_github_refuses.statuses == [1, 1, 1], replay_py_github_refuses.out
    assert has_match(bre(f"replay.py: POST user/repos{DENIED}"), out), replay_py_github_refuses.out
    step = bre(
        "replay.py: stopped in step 3 of 8, create; run the same command again to resume there"
    )
    assert has_search(f"^{step}", out), replay_py_github_refuses.out
    resume = bre(f"Resume the replay of ada-example/tool into {SLUG} at step 3, create, from ")
    assert has_search(f"^{resume}", out), replay_py_github_refuses.out
    assert count_search(" POST user/repos$", replay_py_github_refuses.writes) == 2, (
        replay_py_github_refuses.writes
    )
    assert not replay_py_github_refuses.absent


def test_stops_in_step_4_where_github_refuses_a_setting_and_resumes_there_without_creating_again(
    replay_py_github_refuses,
):
    """replay.py stops in step 4 where GitHub refuses a setting, and resumes there without creating the target again"""  # noqa: E501 # the description word for word
    out = replay_py_github_refuses.out_lines
    assert has_match(bre(f"replay.py: PUT repos/{SLUG}/actions/permissions{DENIED}"), out), (
        replay_py_github_refuses.out
    )
    step = bre(
        "replay.py: stopped in step 4 of 8, settings; run the same command again to resume there"
    )
    assert has_search(f"^{step}", out), replay_py_github_refuses.out
    resume = bre(f"Resume the replay of ada-example/tool into {SLUG} at step 4, settings, from ")
    assert has_search(f"^{resume}", out), replay_py_github_refuses.out
    assert (out or [""])[-1] == (
        "replay.py: stopped in the confirmation, before any write to GitHub in this run;"
        " run the same command again to resume once the cause is removed"
    ), replay_py_github_refuses.out
    assert not replay_py_github_refuses.actions
    assert replay_py_github_refuses.progress is not None
    assert json.loads(replay_py_github_refuses.progress)["done"] == ["create"], (
        replay_py_github_refuses.progress
    )
    assert "".join(f"{without_time(w)}|" for w in replay_py_github_refuses.writes) == (
        f"POST user/repos|POST user/repos|PUT repos/{SLUG}/actions/permissions|"
    ), replay_py_github_refuses.writes


# A replay under another owner than that of the repository of a parent and
# of a sub-issue from elsewhere.


@pytest.fixture(scope="module")
def replay_py_crossing_owners(root, replay_setup, run_file, one):
    slug = "bob-example/tool-replay-20261116-1215"
    name = "replay-py-crossing-owners"
    target = replay_setup(name, slug)
    path = run_file(
        root / f"{name}-runs" / "tool.run.json",
        root / f"{name}-backup",
        target=slug,
        final_name="bob-example/tool",
    )
    return ran(target, [one(target, slug, path)], path.with_name("tool.progress.json"))


def test_stops_before_the_confirmation_without_a_write_where_a_sub_issue_link_would_cross_owners(
    replay_py_crossing_owners,
):
    """replay.py stops before the confirmation, without a write, where a sub-issue link would cross owners"""  # noqa: E501 # the description word for word
    out = replay_py_crossing_owners.out_lines
    assert replay_py_crossing_owners.statuses == [1], replay_py_crossing_owners.out
    crossing = (
        "replay.py: GitHub links a sub-issue only to a parent of the same owner, and the"
        " target's owner is bob-example: #1 under ada-example/plans#9; #4 under"
        " ada-example/plans#9; ada-example/plans#11 under #6. GitHub refuses such a link"
        " whoever makes it, so replay.py cannot carry it. Move or remove these links in the"
        " source first, or replay with plan-replay.py and run-replay.py alone, which leave"
        " links alone, and leave these links out of the first move in the README's Taking"
        " over the source's name"
    )
    assert crossing in out, replay_py_crossing_owners.out
    survey = bre(
        "replay.py: stopped in the survey of the sub-issue links, before any write to GitHub"
        " in this run"
    )
    assert has_search(f"^{survey}", out), replay_py_crossing_owners.out
    assert not has_search("to confirm", out), replay_py_crossing_owners.out
    assert not replay_py_crossing_owners.writes, replay_py_crossing_owners.writes
    assert replay_py_crossing_owners.absent
    assert replay_py_crossing_owners.progress is False


# A source with a tag, a release on it, a draft for the branch wip/idea and
# that branch, of no pull request; a run file that does not accept the
# branch and the draft stops in the plan, one that does replays. The replays
# with all kinds off and with the releases off below take the release alone.

RELEASE_V01 = (
    '[{"id": 1, "tag_name": "v0.1", "name": "First", "draft": false, "prerelease": false}]\n'
)


@pytest.fixture(scope="module")
def source_extra(root, base_env, source):
    """source-extra.git: a mirror of the source with a tag v0.1 at the
    squash merge of #2 and a branch wip/idea at the last direct commit."""
    mirror = root / "source-extra.git"
    git = Git(base_env, root)
    git("clone", "-q", "--mirror", source.bare, mirror)
    git("--git-dir", mirror, "tag", "v0.1", source.hashes["M2"])
    git("--git-dir", mirror, "update-ref", "refs/heads/wip/idea", source.hashes["C5"])
    return mirror


@pytest.fixture(scope="module")
def replay_py_left_behind(root, source_extra, replay_setup, run_file, one):
    """The run that stops, with the target's writes and absent right after
    it, and the run that replays."""
    name = "replay-py-left-behind"
    target = replay_setup(name)
    (root / f"{name}-api" / f"{API_BASE}_releases-1.json").write_text(
        '[{"id": 1, "tag_name": "v0.1", "name": "First", "draft": false, "prerelease": false},\n'
        '  {"id": 2, "tag_name": "v0.2-rc", "name": "Idea", "draft": true, "prerelease": false,'
        ' "target_commitish": "wip/idea"}]\n',
        encoding="utf-8",
    )
    clone_url = str(source_extra)
    runs = root / f"{name}-runs"
    stop_file = run_file(runs / "stop.run.json", root / f"{name}-backup", clone_url=clone_url)
    stop = ran(target, [one(target, SLUG, stop_file)])
    path = run_file(
        runs / "tool.run.json",
        root / f"{name}-backup-2",
        clone_url=clone_url,
        leave_behind=["tag v0.1", "release v0.2-rc", "branch wip/idea"],
    )
    return SimpleNamespace(stop=stop, done=ran(target, [one(target, SLUG, path)]))


def test_stops_in_the_plan_before_any_write_where_the_plan_leaves_behind_what_is_not_accepted(
    replay_py_left_behind,
):
    """replay.py stops in the plan, before any write, where the plan leaves behind what leave_behind does not accept"""  # noqa: E501 # the description word for word
    r = replay_py_left_behind.stop
    out = r.out_lines
    assert r.statuses == [1], r.out
    left = bre(
        "plan-replay.py: the replay leaves behind 2 of the source's tags, releases and branches"
        " that --leave-behind does not accept (leave_behind, in a run file of replay.py)"
    )
    assert has_search(f"^{left}", out), r.out
    assert has_match(bre("replay.py: plan-replay.py stopped; its message stands above"), out)
    step = bre("replay.py: stopped in step 2 of 8, plan, before any write to GitHub in this run")
    assert has_search(f"^{step}", out), r.out
    assert not r.writes, r.writes
    assert r.absent


def test_passes_leave_behind_carries_the_tag_and_its_release_and_names_what_the_archive_keeps(
    replay_py_left_behind,
):
    """replay.py passes leave_behind to the plan, carries the tag and the release on it, and names in its last step what only the archive keeps"""  # noqa: E501 # the description word for word
    r = replay_py_left_behind.done
    out = r.out_lines
    assert r.statuses == [0], r.out
    assert has_match("No differences", out), r.out
    assert "  release v0.2-rc of the source is left behind, as planned" in out, r.out
    assert not has_search("^" + bre("  tag v0.1 ") + "|^" + bre("  release v0.1 "), out), r.out
    assert has_match("  tags +1", out), r.out
    assert has_match("  releases +1", out), r.out
    releases = read_json(r.target.folder / "releases.json")
    assert " ".join(x["tag_name"] for x in releases) == "v0.1", releases
    warning = (
        bre("plan-replay.py: warning: ")
        + ".*"
        + bre("/leave-behind accepts tag v0.1, which the replay does not leave behind")
    )
    assert has_match(warning, out), r.out
    note = "   note: only the archive keeps what the plan left behind: branch wip/idea,"
    assert f"{note} release v0.2-rc" in out, r.out
    patterns = (
        r"^2\. Archive",
        "note: only the archive",
        "^gh api -X PATCH repos/ada-example/tool -f name=tool-archive$",
    )
    picked = [line for line in out if any(re.search(p, line) for p in patterns)]
    assert "".join(f"{line[:12]}|" for line in picked) == (
        "2. Archive t|   note: onl|gh api -X PA|"
    ), r.out


# Run files whose switches are no true or false, and one with no_tags
# without no_releases, each of which stops before anything is read or written.

SWITCHES = ({"no_tags": "yes"}, {"no_releases": 1}, {"no_reviews": None}, {"no_tags": True})


@pytest.fixture(scope="module")
def replay_py_bad_switches(root, replay_setup, run_file, one):
    name = "replay-py-bad-switches"
    target = replay_setup(name)
    runs = []
    for change in SWITCHES:
        path = run_file(root / f"{name}-runs" / "tool.run.json", root / f"{name}-backup", **change)
        runs.append(one(target, SLUG, path))
    result = ran(target, runs, root / f"{name}-runs" / "tool.progress.json")
    result.calls = (target.folder / "calls").exists()
    result.backup = (root / f"{name}-backup").exists()
    return result


def test_refuses_a_switch_that_is_not_true_or_false_and_no_tags_without_no_releases(
    replay_py_bad_switches,
):
    """replay.py refuses a switch of the run file that is not true or false, and no_tags without no_releases, before anything is read or written"""  # noqa: E501 # the description word for word
    out = replay_py_bad_switches.out_lines
    assert replay_py_bad_switches.statuses == [1, 1, 1, 1], replay_py_bad_switches.out
    for field in ("no_tags", "no_releases", "no_reviews"):
        must = bre(f"tool.run.json: {field} must be true or false") + "$"
        assert has_search(must, out), f"no stop for {field}\n{replay_py_bad_switches.out}"
    needs = bre(
        "tool.run.json: no_tags needs no_releases: GitHub creates the missing tag of a release it"
        " creates, at the commit the release's target_commitish names, so a replay with releases"
        " would still carry tags. Set no_releases to true too, or no_tags to false"
    )
    assert has_search(needs + "$", out), replay_py_bad_switches.out
    checks = bre("replay.py: stopped in the checks, before any write to GitHub in this run")
    assert count_search(f"^{checks}", out) == 4, replay_py_bad_switches.out
    assert not replay_py_bad_switches.calls
    assert not replay_py_bad_switches.backup
    assert replay_py_bad_switches.progress is False


# The same source with a tag, a release and a branch of no pull request,
# with a run file that turns tags, releases and reviews off and accepts only
# the branch it leaves behind.


@pytest.fixture(scope="module")
def replay_py_all_off(root, source_extra, replay_setup, run_file, one):
    name = "replay-py-all-off"
    target = replay_setup(name)
    (root / f"{name}-api" / f"{API_BASE}_releases-1.json").write_text(RELEASE_V01, encoding="utf-8")
    path = run_file(
        root / f"{name}-runs" / "tool.run.json",
        root / f"{name}-backup",
        clone_url=str(source_extra),
        leave_behind=["branch wip/idea"],
        no_tags=True,
        no_releases=True,
        no_reviews=True,
    )
    return ran(target, [one(target, SLUG, path)])


def line_after_last(text, out_lines):
    """The last line grep -A 1 -x prints for the text: the line after its
    last match, or that match where it is the last line; empty where none
    matches, as grep -A 1 -x ... | tail -n 1 prints it."""
    found = [i for i, line in enumerate(out_lines) if line == text]
    return out_lines[min(found[-1] + 1, len(out_lines) - 1)] if found else ""


ALL_OFF_NOTES = (
    "tag v0.1 of the source is left behind: tags are turned off",
    "release v0.1 of the source is left behind: releases are turned off",
    "reviews are turned off: the event file plans no review as a comment",
    "branch wip/idea of the source is left behind, as planned",
)


def test_passes_the_switches_to_the_plan_names_them_and_the_comparison_notes_them_turned_off(
    replay_py_left_behind, replay_py_all_off
):
    """replay.py passes the switches to the plan, names them before the confirmation, and the comparison notes them as turned off"""  # noqa: E501 # the description word for word
    out = replay_py_all_off.out_lines
    assert replay_py_all_off.statuses == [0], replay_py_all_off.out
    assert has_match("No differences", out), replay_py_all_off.out
    turned_off = (
        "  turned off in the run file: tags, releases and reviews; the replay carries none of"
        " them, and only the archive keeps them"
    )
    assert line_after_last(turned_off, out)[:5] == "Type ", replay_py_all_off.out
    for line in ALL_OFF_NOTES:
        assert f"  {line}" in out, f"no note: {line}\n{replay_py_all_off.out}"
    assert not has_search("/reviews", replay_py_all_off.target.calls()), (
        replay_py_all_off.target.calls()
    )
    assert not has_search("turned off", replay_py_left_behind.done.out_lines), (
        replay_py_left_behind.done.out
    )


def test_names_in_its_last_step_what_only_the_archive_keeps_of_the_kinds_turned_off(
    replay_py_left_behind, replay_py_all_off
):
    """replay.py names in its last step what only the archive keeps of the kinds the run file turns off"""  # noqa: E501 # the description word for word
    out, left_behind_out = replay_py_all_off.out_lines, replay_py_left_behind.done.out_lines
    left = "   note: only the archive keeps what the plan left behind: branch wip/idea, tag v0.1,"
    assert f"{left} release v0.1" in out, replay_py_all_off.out
    tags = "   note: only the archive keeps the tags of the source, since the plan turned tags off"
    assert tags in out, replay_py_all_off.out
    releases = (
        "   note: only the archive keeps the releases of the source, since the plan turned"
        " releases off"
    )
    assert releases in out, replay_py_all_off.out
    assert not has_search("since the plan turned tags off", left_behind_out), (
        replay_py_left_behind.done.out
    )
    assert not has_search("since the plan turned releases off", left_behind_out), (
        replay_py_left_behind.done.out
    )
    reviews = (
        "   note: only the archive keeps the reviews of the pull requests, since the plan turned"
        " reviews off"
    )
    assert reviews in out, replay_py_all_off.out
    assert not has_search("keeps the reviews", left_behind_out), replay_py_left_behind.done.out


# The same source, with a run file that turns only the releases off; and
# that source without its release, with a run file that turns tags and
# releases off. Each accepts the branch it leaves behind.


@pytest.fixture(scope="module")
def replay_py_releases_off(root, source_extra, replay_setup, run_file, one):
    name = "replay-py-releases-off"
    target = replay_setup(name)
    (root / f"{name}-api" / f"{API_BASE}_releases-1.json").write_text(RELEASE_V01, encoding="utf-8")
    path = run_file(
        root / f"{name}-runs" / "tool.run.json",
        root / f"{name}-backup",
        clone_url=str(source_extra),
        leave_behind=["branch wip/idea"],
        no_releases=True,
    )
    return ran(target, [one(target, SLUG, path)])


@pytest.fixture(scope="module")
def replay_py_tags_releases_off(
    root, source_extra, replay_py_releases_off, replay_setup, run_file, one
):
    name = "replay-py-tags-releases-off"
    target = replay_setup(name)
    path = run_file(
        root / f"{name}-runs" / "tool.run.json",
        root / f"{name}-backup",
        clone_url=str(source_extra),
        leave_behind=["branch wip/idea"],
        no_tags=True,
        no_releases=True,
    )
    return ran(target, [one(target, SLUG, path)])


def test_no_releases_alone_carries_the_tags_and_names_the_releases_turned_off_not_the_tags(
    replay_py_releases_off, replay_py_tags_releases_off
):
    """replay.py with no_releases alone carries the tags, notes the releases as turned off, and names in its last step the releases and not the tags"""  # noqa: E501 # the description word for word
    out = replay_py_releases_off.out_lines
    assert replay_py_releases_off.statuses == [0], replay_py_releases_off.out
    assert has_match("No differences", out), replay_py_releases_off.out
    tags = replay_py_releases_off.target.git("for-each-ref", "--format=%(refname)", "refs/tags/")
    assert tags == "refs/tags/v0.1", tags
    assert "  release v0.1 of the source is left behind: releases are turned off" in out, (
        replay_py_releases_off.out
    )
    left = (
        "   note: only the archive keeps what the plan left behind: branch wip/idea, release v0.1"
    )
    assert left in out, replay_py_releases_off.out
    releases = (
        "   note: only the archive keeps the releases of the source, since the plan turned"
        " releases off"
    )
    assert releases in out, replay_py_releases_off.out
    assert not has_search("turned tags off|^" + bre("  tag v0.1 ") + "|keeps the tags", out)
    turned_off = bre(
        "  turned off in the run file: releases; the replay carries none of them, and only the"
        " archive keeps them"
    )
    assert has_match(turned_off, out), replay_py_releases_off.out


def test_no_tags_and_no_releases_without_a_release_names_the_tags_turned_off_not_the_releases(
    run_process, replay_py_tags_releases_off
):
    """replay.py with no_tags and no_releases, on a source without a release, names in its last step the tags turned off and not the releases"""  # noqa: E501 # the description word for word
    out = replay_py_tags_releases_off.out_lines
    assert replay_py_tags_releases_off.statuses == [0], replay_py_tags_releases_off.out
    assert has_match("No differences", out), replay_py_tags_releases_off.out
    tags = run_process(
        "git", "--git-dir", replay_py_tags_releases_off.target.repo, "for-each-ref", "refs/tags/"
    )
    assert tags.out.rstrip("\n") == "", tags.out
    left = "   note: only the archive keeps what the plan left behind: branch wip/idea, tag v0.1"
    assert left in out, replay_py_tags_releases_off.out
    tags_off = (
        "   note: only the archive keeps the tags of the source, since the plan turned tags off"
    )
    assert tags_off in out, replay_py_tags_releases_off.out
    assert not has_search("turned releases off|keeps the releases", out), (
        replay_py_tags_releases_off.out
    )


# The default branch master: the test's source with main renamed to master,
# whose pull requests are based on master, whose #6 names master in its body
# and which has a draft for master, planned, replayed into a target and
# compared; a copy of that target whose default branch is master; the same
# source with a branch main beside master; that source replayed by replay.py
# into a target that GitHub names master; and the uninterrupted replay's
# event file without target_default_branch, as one planned before the
# rename, checked again and compared.


def to_master(git, bare):
    """Renames the branch main of a bare repository to master."""
    git("--git-dir", bare, "update-ref", "refs/heads/master", "refs/heads/main")
    git("--git-dir", bare, "update-ref", "-d", "refs/heads/main")
    git("--git-dir", bare, "symbolic-ref", "HEAD", "refs/heads/master")


def master_api(api):
    """Makes master the default branch of that copy of the source's API and
    the base of its pull requests."""
    info_path = api / f"{API_BASE}.json"
    info = read_json(info_path)
    info["default_branch"] = "master"
    info_path.write_text(json.dumps(info), encoding="utf-8")
    pulls_path = api / f"{API_BASE}_pulls-1.json"
    pulls = read_json(pulls_path)
    for p in pulls:
        p["base"]["ref"] = "master"
    pulls_path.write_text(json.dumps(pulls), encoding="utf-8")


@pytest.fixture(scope="module")
def mirror_master(root, base_env, source):
    """mirror-master.git: a copy of the mirror with main renamed to master."""
    mirror = root / "mirror-master.git"
    shutil.copytree(source.mirror, mirror, symlinks=True)
    to_master(Git(base_env, root), mirror)
    return mirror


@pytest.fixture(scope="module")
def api_master(root, run_plan):
    """api-master: the API of the run's plan with master as the default
    branch and the base of the pull requests, #6 naming master in its body,
    and a draft for master."""
    api = root / "api-master"
    shutil.copytree(run_plan.api, api)
    master_api(api)
    page = api / f"{API_BASE}_issues-1.json"
    issues = read_json(page)
    for it in issues:
        if it["number"] == 6:
            it["body"] = "Seen twice since Merge branch 'master'."
    page.write_text(json.dumps(issues), encoding="utf-8")
    draft = {
        "id": 21,
        "tag_name": "v0.9-rc",
        "name": "Candidate",
        "draft": True,
        "prerelease": False,
        "target_commitish": "master",
        "body": "",
        "author": {"login": "ada-example"},
        "created_at": "2026-03-08T13:00:00Z",
        "published_at": None,
    }
    (api / f"{API_BASE}_releases-1.json").write_text(json.dumps([draft]), encoding="utf-8")
    return api


@pytest.fixture(scope="module")
def master_plans(root, mirror_master, api_master, plan_extra):
    """The plan of mirror-master.git, master.jsonl, its standard output and
    error apart; and that of the same source with #3's head branch named
    main, as a fork may name it, and its draft for refs/heads/master,
    master-head.jsonl."""
    master = root / "master.jsonl"
    planned = plan_extra(api_master, master, mirror=mirror_master)
    api_head = root / "api-master-head"
    shutil.copytree(api_master, api_head)
    pulls_path = api_head / f"{API_BASE}_pulls-1.json"
    pulls = read_json(pulls_path)
    for p in pulls:
        if p["number"] == 3:
            p["head"]["ref"] = "main"
    pulls_path.write_text(json.dumps(pulls), encoding="utf-8")
    releases_path = api_head / f"{API_BASE}_releases-1.json"
    releases = read_json(releases_path)
    releases[0]["target_commitish"] = "refs/heads/master"
    releases_path.write_text(json.dumps(releases), encoding="utf-8")
    head = root / "master-head.jsonl"
    plan_extra(api_head, head, mirror=mirror_master, merged=True)
    return SimpleNamespace(master=master, result=planned, head=head)


def test_plans_a_master_source_without_warnings_and_says_that_the_target_names_it_main(
    planned, master_plans
):
    """plan-replay.py plans a source whose default branch is master without warnings, and says that the target names it main"""  # noqa: E501 # the description word for word
    r = master_plans.result
    assert r.status == 0, r.err + r.out
    assert r.err == "", r.err
    first = r.out_lines[0] if r.out_lines else ""
    assert first == "Default branch: master in the source, main in the target", r.out
    assert not has_search("^Default branch", planned.main.out_lines), planned.main.out


def test_records_master_and_main_in_the_header_and_plans_each_push_and_pull_request_for_main(
    run_plan, master_plans
):
    """plan-replay.py records the source's default branch master and the target's main in the header, and plans each push to main and each pull request against main"""  # noqa: E501 # the description word for word
    p = Plan(master_plans.master)
    assert p.header["default_branch"] == "master"
    assert p.header["target_default_branch"] == "main"
    assert {e["branch"] for e in p.of("push-commits")} == {"main"}
    assert {e["base"] for e in p.of("create-pull")} == {"main"}
    assert len(p.of("push-commits")) == 3
    assert len(p.of("create-pull")) == 3
    with run_plan.file.open(encoding="utf-8") as f:
        h = json.loads(f.readline())
    assert h["default_branch"] == h["target_default_branch"] == "main", h


def without_seq(event):
    return {k: v for k, v in event.items() if k != "seq"}


def test_plans_a_draft_for_master_for_the_default_branch_and_all_else_as_for_a_main_source(
    run_plan, master_plans
):
    """plan-replay.py plans a draft for master as one for the default branch, keeps a text that names master, and plans every other event and the header as for the source with main"""  # noqa: E501 # the description word for word
    p = Plan(master_plans.master)
    releases = [
        (e["tag_name"], e["draft"], e["commit"], e["on_tag"]) for e in p.of("create-release")
    ]
    assert releases == [("v0.9-rc", True, None, False)]
    assert p.of("create-issue", 6)[0]["body"] == "Seen twice since Merge branch 'master'."
    run_lines = run_plan.file.read_text(encoding="utf-8").splitlines()
    assert run_lines
    six = ("create-issue", 6)
    planned = [
        without_seq(e) | ({"body": "Seen twice."} if (e["kind"], e.get("number")) == six else {})
        for e in p.events
        if e["kind"] != "create-release"
    ]
    assert planned == [without_seq(json.loads(line)) for line in run_lines[1:]]

    def others(header):
        return {k: v for k, v in header.items() if "default_branch" not in k}

    assert others(p.header) == others(json.loads(run_lines[0]))


def test_renames_a_head_branch_named_main_in_a_master_source_and_plans_a_draft_for_refs_heads(
    master_plans,
):
    """plan-replay.py gives a pull request whose head branch is named main another name in a source whose default branch is master, and plans a draft for refs/heads/master for the default branch"""  # noqa: E501 # the description word for word
    p = Plan(master_plans.head)
    pushed = sorted(e["branch"] for e in p.of("push-branch"))
    assert pushed == ["docs/5-notes", "feat/2-thing", "main-3"]
    assert {e["branch"] for e in p.of("push-commits")} == {"main"}
    releases = [(e["tag_name"], e["draft"], e["commit"]) for e in p.of("create-release")]
    assert releases == [("v0.9-rc", True, None)]


@pytest.fixture(scope="module")
def master_replay(
    root, base_env, mirror_master, api_master, master_plans, make_target, replay, compare
):
    """master.jsonl replayed into a target and compared; and a copy of its
    target whose default branch is master, compared after it."""
    slug = "ada-example/tool-master-replay"
    target = make_target("gh-master-replay", slug)
    state = root / "master-replay.state.json"
    tail = (master_plans.master, mirror_master, slug)
    result = replay(
        target,
        slug,
        *("--pace", "0", "--state", state, *tail),
        merged=True,
        FAKE_GH_API=api_master,
    )
    compared = compare(target, "--state", state, *tail, api=api_master)
    master_default = copy_target(root, target, "gh-master-default")
    Git(base_env, root)(
        "--git-dir", master_default.repo, "update-ref", "refs/heads/master", "refs/heads/main"
    )
    (master_default.folder / "settings.json").write_text(
        '{"default_branch": "master"}\n', encoding="utf-8"
    )
    compared_master_default = compare(master_default, "--state", state, *tail, api=api_master)
    return SimpleNamespace(
        target=target,
        state=state,
        result=result,
        compared=compared,
        compared_master_default=compared_master_default,
    )


def test_run_replay_replays_a_master_source_into_main_and_says_so_in_its_totals(
    master_replay, replay_uninterrupted
):
    """run-replay.py replays a source whose default branch is master into main, and says so in its totals"""  # noqa: E501 # the description word for word
    r = master_replay.result
    out = r.out_lines
    assert r.status == 0, r.out
    assert "  default branch: master in the source, main in the target" in out, r.out
    assert has_search(" 3 commits to main, now at ", out), r.out
    assert has_search("#2 pull request feat/2-thing into main$", out), r.out
    assert not has_search("default branch:", replay_uninterrupted.result.out_lines), (
        replay_uninterrupted.result.out
    )


def test_run_replay_pushes_master_to_main_and_creates_the_pulls_and_the_draft_for_main(
    master_replay, view, hashes
):
    """run-replay.py pushes the source's master to main, creates each pull request against main and the draft for master for main, keeps a text that names master, and creates no branch master"""  # noqa: E501 # the description word for word
    v = view(master_replay.target, master_replay.state)
    assert v.git("for-each-ref", "--format=%(refname)", "refs/heads/") == (
        "refs/heads/docs/5-notes\nrefs/heads/feat/2-thing\nrefs/heads/fix/3-parser\nrefs/heads/main"
    )
    assert v.git("rev-parse", "main") == v.recreated[hashes["C5"]]
    assert {it["base"] for it in v.items.values() if it["kind"] == "pull"} == {"main"}
    releases = [
        (r["tag_name"], r["draft"], r["target_commitish"])
        for r in master_replay.target.load("releases", [])
    ]
    assert releases == [("v0.9-rc", True, "main")]
    assert v.items[6]["body"] == "Seen twice since Merge branch 'master'."


def test_compare_replay_compares_master_with_main_notes_it_and_finds_no_difference(
    master_replay, compare_finished
):
    """compare-replay.py compares the source's master with the target's main, notes it, and finds no difference"""  # noqa: E501 # the description word for word
    c = master_replay.compared
    out = c.out_lines
    assert c.status == 0, c.out
    assert has_match("No differences", out), c.out
    assert "  default branch master of the source is main in the target, as planned" in out, c.out
    assert has_match("  commits on main +7", out), c.out
    assert has_match("  branches +4", out), c.out
    assert not has_search("^  branch main ", out), c.out
    plain = compare_finished.uninterrupted
    assert not has_search("default branch", plain.out_lines), plain.out


def test_compare_replay_names_a_target_whose_default_branch_is_master_where_the_plan_names_main(
    master_replay,
):
    """compare-replay.py names a target whose default branch is master where the plan names main"""
    c = master_replay.compared_master_default
    out = c.out_lines
    assert c.status == 1, c.out
    assert "  the default branch is master, planned main" in out, c.out
    assert "  branch master is in the target, but in no event" in out, c.out
    assert has_match("Differences: 2", out), c.out
    assert not has_search("as planned", out), c.out


@pytest.fixture(scope="module")
def main_beside_master(root, base_env, source, source_gh, plan, mirror_master, api_master):
    """The source with a branch main beside master, planned without
    --types; its output and error in one."""
    mirror = root / "mirror-both.git"
    shutil.copytree(mirror_master, mirror, symlinks=True)
    git = Git(base_env, root)
    git("--git-dir", mirror, "update-ref", "refs/heads/main", source.hashes["C1"])
    events = root / "both.jsonl"
    env = source_gh("master-gh").using(FAKE_GH_API=api_master)
    result = plan(mirror, TOOL, source.mailmap, events, env=env, merged=True)
    return SimpleNamespace(events=events, result=result)


def test_plan_replay_stops_without_an_event_file_at_a_branch_main_beside_master_and_names_both(
    main_beside_master,
):
    """plan-replay.py stops, and writes no event file, at a source with a branch main beside its default branch master, and names both"""  # noqa: E501 # the description word for word
    r = main_beside_master.result
    assert r.status == 1, r.out
    assert not main_beside_master.events.exists()
    both = (
        "plan-replay.py: the source has a branch main beside its default branch master, which"
        " the replay names main; it cannot give two branches one name. Rename or delete the"
        " branch main in the source, then mirror and plan again"
    )
    assert both in r.out_lines, r.out
    assert r.out.count("\n") == 1, r.out


@pytest.fixture(scope="module")
def replay_py_master_source(root, base_env, source, replay_setup, run_file, one):
    """A mirror of the source with main renamed to master, replayed by
    replay.py into a target that GitHub names master."""
    mirror = root / "source-master.git"
    git = Git(base_env, root)
    git("clone", "-q", "--mirror", source.bare, mirror)
    to_master(git, mirror)
    name = "replay-py-master-source"
    target = replay_setup(name)
    master_api(root / f"{name}-api")
    path = run_file(
        root / f"{name}-runs" / "tool.run.json", root / f"{name}-backup", clone_url=str(mirror)
    )
    return ran(target, [one(target, SLUG, path, FAKE_GH_DEFAULT="master")])


def test_replays_a_master_source_into_main_says_so_and_makes_main_the_default_branch(
    replay_py_master_source, replay_py_wrong_confirmation
):
    """replay.py replays a source whose default branch is master into main, says so before the confirmation, makes main the default branch where GitHub names master, and the comparison finds no difference"""  # noqa: E501 # the description word for word
    out, t = replay_py_master_source.out_lines, replay_py_master_source.target
    assert replay_py_master_source.statuses == [0], replay_py_master_source.out
    step = (
        "  5. run run-replay.py --pace 0 --final-name ada-example/tool, and make main the default"
        " branch where GitHub names another; the source's master becomes main"
    )
    assert step in out, replay_py_master_source.out
    assert RENAMED in out, replay_py_master_source.out
    rejected = t.folder / "rejected"
    assert not rejected.exists(), replay_py_master_source.out + rejected.read_text()
    assert has_match("No differences", out), replay_py_master_source.out
    assert read_json(t.folder / "settings.json")["default_branch"] == "main"
    assert heads(t) == "docs/5-notes main "
    assert not has_search("becomes main", replay_py_wrong_confirmation.out_lines), (
        replay_py_wrong_confirmation.out
    )


def test_names_the_replays_main_beside_the_sources_master_and_prints_no_command_deleting_main(
    replay_py_uninterrupted, replay_py_master_source
):
    """replay.py names in its last step the replay's main beside the source's master, and prints no command that deletes main"""  # noqa: E501 # the description word for word
    out = replay_py_master_source.out_lines
    note = "   note: the replay's default branch is main, where the source's is master"
    assert note in out, replay_py_master_source.out
    assert "gh api -X DELETE repos/ada-example/tool/git/refs/heads/docs/5-notes" in out, (
        replay_py_master_source.out
    )
    assert not has_search("refs/heads/main$", out), replay_py_master_source.out
    assert not has_search("default branch is main", replay_py_uninterrupted.result.out_lines), (
        replay_py_uninterrupted.result.out
    )


@pytest.fixture(scope="module")
def old_default(root, source, run_plan, replay_uninterrupted, compare_finished, replay, compare):
    """The uninterrupted replay's event file without target_default_branch,
    as one planned before the rename, with a copy of its state file that
    records its hash; run into its target and compared after the comparisons
    of the finished replay; the target's writes right before the run and
    after both."""
    run_lines = run_plan.file.read_text(encoding="utf-8").splitlines()
    header = json.loads(run_lines[0])
    del header["target_default_branch"]
    text = "\n".join([json.dumps(header, ensure_ascii=False), *run_lines[1:]]) + "\n"
    events = root / "old-default.jsonl"
    events.write_text(text, encoding="utf-8")
    state = read_json(replay_uninterrupted.state)
    state["events"] = hashlib.sha256(text.encode()).hexdigest()
    state_file = root / "old-default.state.json"
    state_file.write_text(json.dumps(state), encoding="utf-8")
    target = replay_uninterrupted.target
    writes_before = len(target.writes())
    tail = ("--state", state_file, events, source.mirror, TOOL_NEW)
    result = replay(target, TOOL_NEW, "--pace", "0", *tail, merged=True)
    compared = compare(target, *tail, api=run_plan.api)
    return SimpleNamespace(
        result=result,
        compared=compared,
        writes_before=writes_before,
        writes_after=len(target.writes()),
    )


def test_run_and_compare_take_an_event_file_without_target_default_branch_as_before(
    old_default, compare_finished
):
    """run-replay.py and compare-replay.py take an event file planned before the rename, without target_default_branch, as before, with the source's default branch as the target's"""  # noqa: E501 # the description word for word
    r, c = old_default.result, old_default.compared
    assert (r.status, c.status) == (0, 0), r.out + c.out
    assert has_search("^All 23 events of the replay .* are done", r.out_lines), r.out
    assert old_default.writes_after == old_default.writes_before
    assert c.out == compare_finished.uninterrupted.out
