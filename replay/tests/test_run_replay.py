"""The checks of run-replay.py against fake targets, replaying run.jsonl."""

import json
import re
from itertools import pairwise
from types import SimpleNamespace

import pytest
from conftest import TOOL_NEW, TOOL_SOMEONE_ELSES_ISSUE, has_match, has_search, has_text, lines


def first_parent_trees(run_process, git_dir):
    """The trees of the first-parent line of main, oldest first, as
    git rev-list --format=%T | grep -v "^commit" gives them; the pipe drops
    git's exit status, so a failing git gives no trees."""
    listed = run_process(
        "git",
        "--git-dir",
        git_dir,
        "rev-list",
        "--first-parent",
        "--reverse",
        "--format=%T",
        "main",
    )
    return [line for line in listed.out_lines if not line.startswith("commit")]


def test_plan_has_the_fourth_comment(run_plan):
    """run-replay.py's plan has the fourth comment"""
    r = run_plan.result
    assert r.status == 0, r.out
    assert has_match("  comments +4", r.out_lines), r.out
    assert has_match("  events +23", r.out_lines), r.out


def test_writes_nothing_when_the_confirmation_is_not_the_targets_owner_repo(
    root, source, run_plan, make_target, replay
):
    """run-replay.py writes nothing when the confirmation is not the target's owner/repo"""
    target = make_target("gh-refused")
    state = root / "refused.state.json"
    r = replay(
        target, "tool-new", "--state", state, run_plan.file, source.mirror, TOOL_NEW, merged=True
    )
    assert r.status == 1, r.out
    assert has_search("run-replay.py: not confirmed; nothing changed$", r.out_lines), r.out
    assert has_match("  issues +3", r.out_lines), r.out
    assert has_search("labels the target has and the replay deletes: enhancement", r.out_lines)
    assert not target.writes(), target.writes()
    assert target.git("for-each-ref") == ""
    assert not state.exists()
    assert not (root / "refused.work.git").exists()


def test_replays_the_plan_with_a_line_per_event_the_totals_and_the_targets_url(
    replay_uninterrupted,
):
    """run-replay.py replays the plan, with a line per event, the totals and the target's URL"""
    r = replay_uninterrupted.result
    assert r.status == 0, r.err + r.out
    assert r.err == ""
    assert sum(bool(re.match(" *[0-9]+/23  ", line)) for line in r.out_lines) == 23, r.out
    assert has_match("  merge-pull +2", r.out_lines), r.out
    assert r.last_out_line == "https://github.com/ada-example/tool-new"
    refused = replay_uninterrupted.target.folder / "refused"
    assert not refused.exists(), refused.read_text(encoding="utf-8")


def test_gives_every_issue_and_pull_request_the_number_and_title_of_the_plan(
    replay_uninterrupted, view
):
    """run-replay.py gives every issue and pull request the number and title of the plan"""
    v = view(replay_uninterrupted.target, replay_uninterrupted.state)
    assert [(n, it["kind"], it["title"]) for n, it in sorted(v.items.items())] == [
        (e["number"], "pull" if e["kind"] == "create-pull" else "issue", e["title"])
        for e in v.events
        if e["kind"] in ("create-issue", "create-pull")
    ]
    assert sorted(v.items) == [1, 2, 3, 4, 5, 6]


def test_leaves_the_default_branch_with_the_sources_tree_after_each_push_and_merge(
    replay_uninterrupted, source, run_process
):
    """run-replay.py leaves the target's default branch with the source's tree after each push and merge"""  # noqa: E501 # the description word for word
    trees_source = first_parent_trees(run_process, source.mirror)
    trees_target = first_parent_trees(run_process, replay_uninterrupted.target.repo)
    assert len(trees_source) == 7, trees_source
    assert trees_source == trees_target


def test_pushes_commits_with_mapped_identities_author_dates_replay_time_and_typed_messages(
    replay_uninterrupted, view, hashes
):
    """run-replay.py pushes commits with the mapped identities, the original author dates, the time of the replay as committer date and the typed messages"""  # noqa: E501 # the description word for word
    v = view(replay_uninterrupted.target, replay_uninterrupted.state)
    m, git = v.recreated, v.git
    raw = "--format=%an|%ae|%ad|%cn|%ce|%cd|%s"
    assert (
        git("log", "-1", raw, "--date=raw", m[hashes["C3"]])
        == "Ada Example|ada@example.com|1772712000 +0200|Ada Example|ada@example.com"
        "|1794000000 +0000|test: update the tests"
    )
    assert v.state["committer_dates"][hashes["C3"]] == "1794000000 +0000"
    assert (
        git("log", "-1", "--format=%an|%ae|%cn|%ce|%s", m[hashes["F1"]])
        == "Bob Example|bob@example.com|Bob Example|bob@example.com|fix: repair the parser"
    )
    assert git("rev-parse", "fix/3-parser") == m[hashes["F1"]]
    assert git("rev-parse", "docs/5-notes^2") == m[hashes["C5"]]
    assert (
        git("log", "-1", "--format=%B", m[hashes["C4"]])
        == "chore: tidy the scripts\n\nNo change in behaviour."
    )


def test_squash_merges_with_the_planned_message_and_fills_in_pr_url(
    replay_uninterrupted, view, hashes
):
    """run-replay.py squash-merges with the planned message and fills in {pr_url}"""
    v = view(replay_uninterrupted.target, replay_uninterrupted.state)
    m, git = v.recreated, v.git
    assert git("log", "-1", "--format=%B", m[hashes["M3"]]) == (
        "fix: repair the parser (#3)\n\nThe parser failed on empty input.\n\n"
        "https://github.com/ada-example/tool-new/pull/3"
    )
    assert git("log", "-1", "--format=%s|%cn", m[hashes["M2"]]) == "feat: add thing (#2)|GitHub"


def test_replaces_a_hash_of_a_recreated_commit_in_a_later_comment_and_nothing_else(
    replay_uninterrupted, view, hashes
):
    """run-replay.py replaces a hash of a recreated commit in a later comment, and nothing else"""
    v = view(replay_uninterrupted.target, replay_uninterrupted.state)
    m = v.recreated
    assert v.comments[-1] == (
        6,
        "Tidied in "
        + m[hashes["C4"]][:7]
        + ", after "
        + m[hashes["M2"]][:10]
        + "; abcdef0 is no commit.",
    )
    assert m[hashes["C4"]][:7] != hashes["C4"][:7]
    assert v.comments[0] == (1, "Seen in the readme.")


def test_leaves_an_issue_closed_by_a_merge_as_it_is_and_sets_a_different_state_reason(
    replay_uninterrupted, view
):
    """run-replay.py leaves an issue closed by a merge as it is and sets a different state reason"""
    v = view(replay_uninterrupted.target, replay_uninterrupted.state)
    items = sorted(v.items.items())
    assert [c for c in v.closes if c[0] == 1] == [[1, "completed"]]
    assert [c for c in v.closes if c[0] == 4] == [[4, "completed"], [4, "not_planned"]]
    assert [(n, it["state"], it["state_reason"]) for n, it in items if it["kind"] == "issue"] == [
        (1, "closed", "completed"),
        (4, "closed", "not_planned"),
        (6, "open", None),
    ]
    assert [(n, it["state"], bool(it["merged_at"])) for n, it in items if it["kind"] == "pull"] == [
        (2, "closed", True),
        (3, "closed", True),
        (5, "closed", False),
    ]


def test_creates_and_updates_the_planned_labels_deletes_the_others_and_labels_the_items(
    replay_uninterrupted, view
):
    """run-replay.py creates and updates the planned labels, deletes the others and labels the items"""  # noqa: E501 # the description word for word
    v = view(replay_uninterrupted.target, replay_uninterrupted.state)
    assert sorted((x["name"], x["color"], x["description"]) for x in v.labels) == [
        ("bug", "d73a4a", "Something isn't working"),
        ("docs", "0075ca", "Documentation"),
    ]
    assert (v.items[6]["labels"], v.items[6]["assignees"]) == (["bug", "docs"], ["ada-example"])


def test_waits_out_a_rate_limit_as_retry_after_tells_and_retries_the_same_call(
    replay_uninterrupted,
):
    """run-replay.py waits out a rate limit as Retry-After tells and retries the same call"""
    r = replay_uninterrupted.result
    waited = (
        "rate limited on POST repos/ada-example/tool-new/issues/1/comments;"
        " waiting 1 s before retry 1 of 5"
    )
    assert has_text(waited, r.out_lines), r.out
    call = " POST repos/ada-example/tool-new/issues/1/comments"
    assert sum(c.endswith(call) for c in replay_uninterrupted.calls) == 2, (
        replay_uninterrupted.calls
    )


def test_paces_its_writes_by_pace(replay_uninterrupted):
    """run-replay.py paces its writes by --pace"""
    # The time of each write against that of the write before it.
    timed = [(float(w.split()[0]), w) for w in replay_uninterrupted.writes]
    gaps = [f"gap {b - a} before {w}" for (a, _), (b, w) in pairwise(timed) if b - a < 0.1]
    assert not gaps, gaps


@pytest.fixture(scope="module")
def replay_resumed(root, source, run_plan, make_target, replay):
    """The same replay, stopped by a Ctrl-C and by three answers lost after
    GitHub did the call, and resumed each time; the output of the five runs
    in one, in the order they ran."""
    target = make_target("gh-resumed")
    state = root / "resumed.state.json"

    def resume(interrupted, lost):
        return replay(
            target,
            TOOL_NEW,
            *("--pace", "0", "--state", state, run_plan.file, source.mirror, TOOL_NEW),
            merged=True,
            FAKE_GH_INTERRUPT=interrupted,
            FAKE_GH_LOSE=lost,
        )

    runs = [
        resume("PATCH repos/ada-example/tool-new/labels/bug", ""),
        resume("", "POST repos/ada-example/tool-new/pulls"),
        resume("", "POST repos/ada-example/tool-new/issues/3/comments"),
        resume("", "PUT repos/ada-example/tool-new/pulls/3/merge"),
        resume("", ""),
    ]
    out = "".join(r.out for r in runs)
    return SimpleNamespace(
        target=target,
        statuses=[r.status for r in runs],
        out=out,
        out_lines=lines(out),
        dump=target.dump(),
    )


def test_stops_after_the_event_a_ctrl_c_interrupts_and_resumes_there(replay_resumed):
    """run-replay.py stops after the event a Ctrl-C interrupts, and resumes there"""
    r = replay_resumed
    stopped = "run-replay.py: stopped after event 1 of 23; run the same command again to resume"
    assert has_match(stopped, r.out_lines), r.out
    resumed = "Resume the replay of ada-example/tool into ada-example/tool-new at event 2 of 23"
    assert has_text(resumed, r.out_lines), r.out


def test_takes_over_what_a_call_whose_answer_was_lost_did_when_it_resumes(replay_resumed):
    """run-replay.py takes over what a call whose answer was lost did, when it resumes"""
    r = replay_resumed
    assert r.statuses == [130, 1, 1, 1, 0], r.out
    assert has_text("#2 pull request feat/2-thing into main, found created", r.out_lines), r.out
    assert has_text("#3 comment, found created", r.out_lines), r.out
    assert has_search("#3 squash-merged into main as .*, found merged", r.out_lines), r.out


def test_ends_a_stopped_and_resumed_replay_in_the_same_target_as_an_uninterrupted_one(
    replay_uninterrupted, replay_resumed
):
    """run-replay.py ends a stopped and resumed replay in the same target as an uninterrupted one"""
    assert replay_uninterrupted.dump.decode("utf-8") == replay_resumed.dump.decode("utf-8")


def test_checks_a_finished_replay_again_without_writing_and_refuses_a_non_empty_target(again):
    """run-replay.py checks a finished replay again without writing, and refuses a target that is not empty"""  # noqa: E501 # the description word for word
    same, other = again.same, again.other
    assert (same.status, other.status) == (0, 1), same.out + other.out
    assert has_search("^All 23 events of the replay .* are done", same.out_lines), same.out
    not_empty = "ada-example/tool-new is not empty: it has 8 refs and items up to #6"
    assert has_text(not_empty, other.out_lines), other.out
    assert again.writes_after == again.writes_before


def test_reads_by_its_number_an_item_the_targets_list_lacks_before_it_calls_it_missing(lag, again):
    """run-replay.py reads by its number an issue or pull request the target's list lacks, before it calls the item missing"""  # noqa: E501 # the description word for word
    assert lag.result.status == 0, lag.result.out
    assert lag.after[2] > lag.before[2]
    assert lag.after[6] > lag.before[6]
    assert lag.writes == again.writes_before


def test_stops_at_a_number_other_than_the_planned_one_before_anything_more(
    root, replay_someone_elses_issue
):
    """run-replay.py stops at a number other than the planned one, before anything more"""
    r = replay_someone_elses_issue.result
    assert r.status == 1, r.out
    assert has_search("^run-replay.py: the issue planned as #4 got #5", r.out_lines), r.out
    writes = replay_someone_elses_issue.writes
    last = writes[-1] if writes else ""
    # The last write without its time.
    assert (
        last.partition(" ")[2] if " " in last else last
    ) == f"POST repos/{TOOL_SOMEONE_ELSES_ISSUE}/issues"
    assert (root / "run.state.json").is_file()
    assert (root / "run.work.git").is_dir()


def test_with_times_appends_the_original_creation_time_to_bodies_and_comments(
    replay_someone_elses_issue, view
):
    """run-replay.py --with-times appends the original creation time to bodies and comments"""
    v = view(replay_someone_elses_issue.target, replay_someone_elses_issue.state)
    assert (
        v.items[1]["body"] == "The readme is empty.\n\n_Originally created 2026-03-01 11:00 UTC._"
    )
    assert v.comments[0] == (1, "Seen in the readme.\n\n_Originally created 2026-03-02 12:00 UTC._")
    assert v.items[2]["title"] == "feat: add thing"


def test_runs_gh_with_git_terminal_prompt_0_so_no_call_through_run_waits_for_a_password(
    replay_uninterrupted, lag
):
    """run-replay.py runs gh with GIT_TERMINAL_PROMPT=0, so no call through run() waits for a password"""  # noqa: E501 # the description word for word
    # Read right after the last run of run-replay.py into the target of the
    # uninterrupted replay, since its comparison that follows writes the file
    # again; compared without its final line breaks, and a missing file fails.
    prompt = lag.prompt
    assert prompt is not None
    assert prompt.rstrip("\n") == "0"


def test_stops_when_the_tree_after_a_merge_differs_from_the_plans_and_names_both(
    root, source, run_plan, make_target, replay
):
    """run-replay.py stops when the tree after a merge differs from the plan's, and names both"""
    # A plan whose second merge expects the tree of the first; the mirror
    # holds it, so only the check after the merge can see the difference.
    lines = run_plan.file.read_text(encoding="utf-8").splitlines()
    merges = [i for i, line in enumerate(lines) if json.loads(line).get("kind") == "merge-pull"]
    event = json.loads(lines[merges[1]])
    event["tree"] = json.loads(lines[merges[0]])["tree"]
    lines[merges[1]] = json.dumps(event)
    bad_tree = root / "bad-tree.jsonl"
    bad_tree.write_text("\n".join(lines) + "\n", encoding="utf-8")
    target = make_target("gh-bad-tree", "ada-example/tool-bad-tree")
    slug = "ada-example/tool-bad-tree"
    state = root / "bad-tree.state.json"
    r = replay(
        target, slug, "--pace", "0", "--state", state, bad_tree, source.mirror, slug, merged=True
    )
    assert r.status == 1, r.out
    stopped = (
        "^run-replay.py: after the merge of #[0-9]*, the tree of main is [0-9a-f]{7}, the"
        " source's [0-9a-f]{7}; the replay stops at the first difference"
    )
    assert has_search(stopped, r.out_lines), r.out


def test_final_name_puts_the_given_name_in_the_url_of_a_squash_message(
    replay_final_name, view, hashes
):
    """run-replay.py --final-name puts the given name in the URL of a squash message"""
    v = view(replay_final_name.target, replay_final_name.state)
    assert v.git("log", "-1", "--format=%B", v.recreated[hashes["M3"]]) == (
        "fix: repair the parser (#3)\n\nThe parser failed on empty input.\n\n"
        "https://github.com/ada-example/tool/pull/3"
    )
    assert v.items[3]["title"] == "fix: repair the parser"


def test_names_in_the_totals_the_url_pr_url_gets_with_final_name_and_without(
    replay_final_name, replay_uninterrupted
):
    """run-replay.py names in the totals the URL {pr_url} gets, with --final-name and without"""
    named, plain = replay_final_name.result, replay_uninterrupted.result
    assert named.status == 0, named.out
    final = "  {pr_url} in 1 squash message: https://github.com/ada-example/tool/pull/<number>"
    assert final in named.out_lines, named.out
    target = "  {pr_url} in 1 squash message: https://github.com/ada-example/tool-new/pull/<number>"
    assert target in plain.out_lines, plain.out


def test_refuses_a_bad_final_name_a_sign_that_is_no_address_and_a_resume_with_other_options(
    final_name_again,
):
    """run-replay.py refuses a --final-name not of the form owner/repo, a --sign that is no address, and a resume with other options"""  # noqa: E501 # the description word for word
    again = final_name_again
    assert (again.bad_name.status, again.bad_sign.status, again.resumed.status) == (2, 2, 1), (
        again.resumed.out
    )
    recorded = (
        "run-replay.py: .*final-name.state.json records a run with --final-name ada-example/tool;"
        " resume with the same options"
    )
    assert has_match(recorded, again.resumed.out_lines), again.resumed.out
