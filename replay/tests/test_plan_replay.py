import pytest
from conftest import TOOL, has_match


@pytest.fixture(scope="module")
def gh(plan_gh):
    return plan_gh


@pytest.fixture(scope="module")
def main_plan(planned, read_plan):
    return read_plan(planned.files.events)


@pytest.fixture(scope="module")
def plain_plan(planned, read_plan):
    return read_plan(planned.files.plain)


@pytest.fixture(scope="module")
def merges_plan(planned, read_plan):
    return read_plan(planned.files.merges)


TOTALS = [
    "items +6",
    "issues +3",
    "pull requests +3",
    "comments +3",
    "labels +2",
    "commits +10",
    "squash merges +2",
    "merge commits +0",
    "events +22",
    "events out of time order +3",
]


def test_writes_the_plan_and_prints_the_totals_without_warnings(planned):
    main = planned.main
    assert main.status == 0, main.err
    assert main.err == ""
    assert main.last_out_line == str(planned.files.events)
    for total in TOTALS:
        assert has_match(f"  {total}", main.out_lines), f"no line {total!r} in:\n{main.out}"


def test_creates_the_items_in_number_order_issues_and_pull_requests_interleaved(main_plan):
    items = [
        (e["number"], e["kind"])
        for e in main_plan.events
        if e["kind"] in ("create-issue", "create-pull")
    ]
    assert items == [
        (1, "create-issue"),
        (2, "create-pull"),
        (3, "create-pull"),
        (4, "create-issue"),
        (5, "create-pull"),
        (6, "create-issue"),
    ]


def test_orders_the_events_by_time_after_the_labels(main_plan):
    events = main_plan.events
    assert [e["seq"] for e in events] == list(range(1, len(events) + 1))
    assert [e["kind"] for e in events[:2]] == ["create-label"] * 2
    assert all(e["time"] for e in events[2:])
    late = [("push-branch", 5), ("create-pull", 5), ("create-issue", 6)]
    rest = [e["time"] for e in events[2:] if (e["kind"], e.get("number")) not in late]
    assert rest == sorted(rest)


def test_places_a_branch_that_merges_a_later_commit_of_the_default_branch_after_it(
    main_plan, hashes
):
    events, of = main_plan.events, main_plan.of
    assert events.index(of("push-branch", 5)[0]) == events.index(of("push-commits")[-1]) + 1
    assert main_plan.commit(hashes["N2"])["parents"] == [hashes["N1"], hashes["C5"]]
    assert [
        (events[i]["kind"], events[i].get("number"))
        for i in range(3, len(events))
        if events[i]["time"] < max(e["time"] for e in events[2:i])
    ] == [("push-branch", 5), ("create-pull", 5), ("create-issue", 6)]


def test_pushes_a_branch_right_before_its_pull_request_and_comments_after_the_item(main_plan):
    events, of = main_plan.events, main_plan.of
    assert all(
        events.index(of("push-branch", n)[0]) + 1 == events.index(of("create-pull", n)[0])
        for n in (2, 3, 5)
    )
    assert all(
        events.index(e)
        > events.index((of("create-issue", e["number"]) + of("create-pull", e["number"]))[0])
        for e in of("add-comment")
    )


def test_applies_the_mailmap_to_author_and_committer_not_the_committed_mailmap(main_plan, hashes):
    assert {
        (p["name"], p["email"])
        for e in main_plan.events
        for c in e.get("commits", [])
        for p in (c["author"], c["committer"])
    } == {("Ada Example", "ada@example.com"), ("Bob Example", "bob@example.com")}
    assert main_plan.commit(hashes["F1"])["committer"]["email"] == "bob@example.com"


def test_keeps_the_original_dates_trees_and_parents(main_plan, hashes):
    commit, of = main_plan.commit, main_plan.of
    assert commit(hashes["C1"])["author"]["date"] == "2026-03-01T10:00:00+00:00"
    assert commit(hashes["C3"])["committer"]["date"] == "2026-03-05T14:00:00+02:00"
    assert commit(hashes["B1"])["tree"] == hashes["TREEB1"]
    assert commit(hashes["F1"])["parents"] == [hashes["M2"]]
    assert of("push-branch", 3)[0]["base_commit"] == hashes["M2"]
    assert of("merge-pull", 3)[0]["tree"] == hashes["TREE3"]


def test_takes_the_type_from_the_branch_prefix(main_plan, hashes):
    assert main_plan.title(hashes["B1"]) == "feat: add thing"
    assert main_plan.of("create-pull", 3)[0]["title"] == "fix: repair the parser"
    assert main_plan.title(hashes["N1"]) == "docs: add notes"
    assert main_plan.commit(hashes["B1"])["type_from"] == "branch"


def test_keeps_a_type_that_is_present(main_plan, hashes):
    assert main_plan.title(hashes["C2"]) == "ci: add the test workflow"
    assert main_plan.commit(hashes["C2"])["type_from"] == "present"


def test_guesses_and_marks_the_type_of_a_direct_commit(main_plan, hashes):
    marked = [
        (main_plan.title(hashes[k]), main_plan.commit(hashes[k])["type_from"])
        for k in ("C1", "C3", "C5")
    ]
    assert marked == [
        ("docs: add the readme", "guess"),
        ("test: update the tests", "guess"),
        ("feat: rewrite thing in POSIX sh", "guess"),
    ]


def test_respects_the_override_file(main_plan, hashes):
    assert main_plan.title(hashes["C4"]) == "chore: tidy the scripts"
    assert main_plan.commit(hashes["C4"])["type_from"] == "override"


def test_lowercases_only_a_capitalised_ordinary_first_word(main_plan, hashes):
    assert main_plan.title(hashes["B2"]) == "feat: README: mention thing"
    assert main_plan.title(hashes["C5"]).endswith("POSIX sh")
    assert main_plan.of("create-pull", 2)[0]["title"] == "feat: add thing"


def test_keeps_bodies_as_they_are(main_plan, hashes):
    of, commit = main_plan.of, main_plan.commit
    assert of("create-pull", 2)[0]["body"] == "Adds thing.\n\nCloses #1"
    assert of("create-pull", 3)[0]["body"].count("\r\n") == 8
    assert of("create-issue", 4)[0]["body"] == "Tabs would help."
    assert [e["body"] for e in of("add-comment", 3)] == ["Looks right."]
    assert commit(hashes["B1"])["message"] == "feat: add thing\n"
    assert commit(hashes["C4"])["message"] == "chore: tidy the scripts\n\nNo change in behaviour.\n"


def test_squash_merges_a_squashed_pull_request_with_its_typed_title_and_body(main_plan, hashes):
    merge = main_plan.of("merge-pull", 2)[0]
    assert merge["commit_title"] == "feat: add thing (#2)"
    assert merge["commit_message"] == "* Add thing\n\n* README: mention thing"
    assert merge["source_commit"] == hashes["M2"]


def test_turns_a_merge_commit_into_a_squash_merge_summing_up_the_description(main_plan):
    m = main_plan.of("merge-pull", 3)[0]
    assert m
    assert (m["method"], m["source_method"], m["commit_title"], m["commit_message"]) == (
        "squash",
        "merge",
        "fix: repair the parser (#3)",
        "The parser failed on empty input.\n\n{pr_url}",
    )


def test_gives_a_closed_unmerged_pull_request_a_branch_create_and_close_but_no_merge(
    main_plan, hashes
):
    of = main_plan.of
    assert [c["sha"] for c in of("push-branch", 5)[0]["commits"]] == [hashes["N1"], hashes["N2"]]
    assert of("create-pull", 5)[0]["state"] == "closed"
    assert len(of("close-item", 5)) == 1
    assert not of("merge-pull", 5)


def test_closes_issues_with_their_state_reason_and_keeps_labels_and_assignees(main_plan):
    of = main_plan.of
    assert [(e["number"], e["state_reason"]) for e in of("close-item")] == [
        (1, "completed"),
        (4, "not_planned"),
        (5, None),
    ]
    six = of("create-issue", 6)[0]
    assert (six["labels"], six["assignees"]) == (["bug", "docs"], ["ada-example"])


def test_pushes_direct_commits_in_a_row_as_one_push(main_plan, hashes):
    assert [[c["sha"] for c in e["commits"]] for e in main_plan.of("push-commits")] == [
        [hashes["C1"]],
        [hashes["C2"], hashes["C3"], hashes["C4"]],
        [hashes["C5"]],
    ]


def test_lists_every_recreated_source_commit_in_the_header(main_plan, hashes):
    header = main_plan.header
    assert header["kind"] == "header"
    assert header["source"] == "ada-example/tool"
    recreated = ("C1", "B1", "B2", "M2", "F1", "M3", "C2", "C3", "C4", "N1", "C5", "N2")
    assert sorted(header["source_commits"]) == sorted(hashes[k] for k in recreated)


def test_prints_every_changed_title_marking_guessed_types(planned, hashes):
    main = planned.main
    c1 = hashes["C1"][:7]
    assert f"  {c1}  guessed  Add the readme  ->  docs: add the readme" in main.out_lines, main.out
    assert "  #3                Repair the parser  ->  fix: repair the parser" in main.out_lines
    assert "ci: add the test workflow" not in main.out
    assert "Changed titles: 14" in main.out_lines


def test_prints_every_squash_message_it_writes_for_a_merge_commit(planned):
    main = planned.main
    assert "Squash messages written for merge commits: 1" in main.out_lines, main.out
    assert "  #3  fix: repair the parser (#3)" in main.out_lines
    assert "      The parser failed on empty input." in main.out_lines
    assert "      {pr_url}" in main.out_lines


def test_plans_with_no_types_and_with_keep_merges_without_warnings(planned):
    plain, merges = planned.plain, planned.merges
    assert (plain.status, merges.status) == (0, 0), plain.err + merges.err
    assert plain.err == ""
    assert merges.err == ""
    assert "Changed titles: 1" in plain.out_lines, plain.out
    assert has_match("  squash merges +1", merges.out_lines), merges.out
    assert has_match("  merge commits +1", merges.out_lines)
    assert "Squash messages written for merge commits: 0" in merges.out_lines


def test_no_types_ignores_the_type_lines_of_the_override_file_without_a_warning(planned):
    plain_typed = planned.plain_typed
    assert plain_typed.status == 0, plain_typed.err
    assert plain_typed.err == ""


def test_no_types_keeps_every_title_as_it_is(plain_plan, hashes):
    assert plain_plan.title(hashes["B1"]) == "Add thing"
    assert plain_plan.title(hashes["C2"]) == "ci: add the test workflow"
    assert plain_plan.of("create-pull", 3)[0]["title"] == "Repair the parser"
    assert plain_plan.of("merge-pull", 2)[0]["commit_title"] == "Add thing (#2)"
    types = {(c["type"], c["type_from"]) for e in plain_plan.events for c in e.get("commits", [])}
    assert types == {(None, None)}


def test_takes_the_summary_of_a_squash_message_from_the_override_file(plain_plan):
    m = plain_plan.of("merge-pull", 3)[0]
    assert m
    assert (m["commit_title"], m["commit_message"]) == (
        "Repair the parser (#3)",
        "Repairs the parser on empty input.\n\n{pr_url}",
    )


def test_keep_merges_merges_a_merge_commit_with_its_message_and_tree(merges_plan, hashes):
    m = merges_plan.of("merge-pull", 3)[0]
    assert m
    assert (
        m["method"],
        m["source_method"],
        m["commit_title"],
        m["commit_message"],
        m["tree"],
        m["type"],
    ) == (
        "merge",
        "merge",
        "Merge pull request #3 from bob-example/fix/3-parser",
        "Repair the parser",
        hashes["TREE3"],
        None,
    )
    assert merges_plan.of("merge-pull", 2)[0]["method"] == "squash"
    assert merges_plan.of("create-pull", 3)[0]["title"] == "fix: repair the parser"


# After planned, whose four plans write the calls to gh that this test reads in its log.
def test_reads_every_page_and_calls_gh_only_with_get_requests(planned, gh):
    assert not gh.refused.exists(), gh.refused.read_text(encoding="utf-8")
    calls = gh.calls()
    assert any("issues?state=all&per_page=100&page=3" in call for call in calls), calls
    assert all(call.startswith("api repos/ada-example/tool") for call in calls), calls


def test_the_fake_gh_refuses_writing_requests(source_gh):
    guard = source_gh("guard")
    assert guard.run("gh", "api", "-X", "POST", "repos/a/b/issues").status != 0
    assert guard.run("gh", "api", "repos/a/b/issues", "-f", "title=x").status != 0
    assert guard.run("gh", "api", "--method", "PATCH", "repos/a/b/issues/1").status != 0
    assert guard.refused.read_text(encoding="utf-8").count("\n") == 3


def test_stops_with_a_message_at_a_branch_that_merges_a_commit_no_pull_request_holds(
    root, source, plan, gh, api_stray, hashes
):
    stray = root / "stray.jsonl"
    result = plan(source.mirror, TOOL, source.mailmap, stray, env=gh.using(FAKE_GH_API=api_stray))
    assert result.status != 0
    s1 = hashes["S1"][:7]
    assert f"the branch of pull request #7 merges {s1}, which is neither" in result.err, result.err
    assert "Traceback" not in result.err
    assert not stray.exists()


def test_refuses_an_existing_event_file_and_a_missing_folder(root, source, plan, gh, planned):
    s, events = source, planned.files.events
    assert plan(s.mirror, TOOL, s.mailmap, events, env=gh.env).status != 0
    assert events.read_text(encoding="utf-8").count("\n") == 23
    nodir = plan(s.mirror, TOOL, s.mailmap, root / "nodir" / "out.jsonl", env=gh.env)
    assert nodir.status != 0
    pattern = "plan-replay.py: no folder .*/nodir for the event file"
    assert has_match(pattern, nodir.err_lines), nodir.err
    assert "Traceback" not in nodir.err


def test_refuses_a_missing_mailmap_and_a_wrong_line_in_the_override_file(root, source, plan, gh):
    s, other = source, root / "other.jsonl"
    assert plan(s.mirror, TOOL, root / "nothing", other, env=gh.env).status != 0
    bad_types = root / "bad-types"
    bad_types.write_text("1 feature\n", encoding="utf-8")
    assert plan("--types", bad_types, s.mirror, TOOL, s.mailmap, other, env=gh.env).status != 0
    bad_summary = root / "bad-summary"
    bad_summary.write_text("abc1234 summary Text\n", encoding="utf-8")
    assert plan("--types", bad_summary, s.mirror, TOOL, s.mailmap, other, env=gh.env).status != 0
    assert not other.exists()
