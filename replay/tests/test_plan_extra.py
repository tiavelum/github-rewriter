"""The checks of plan-replay.py against copies of the source with tags and
releases: odd tags, tag messages and drafts, and the switches for tags and
releases."""

import json
import re
import shutil

import pytest

TOOL = "ada-example/tool"
# The tag of mirror-odd.git whose name holds a no-break space.
NBSP_TAG = "sp\N{NO-BREAK SPACE}ace"
RELEASES = "repos_ada-example_tool_releases"


def has_match(pattern, lines):
    """Whether a line matches the extended pattern whole, as grep -Ex finds it."""
    return any(re.fullmatch(pattern, line) for line in lines)


def has_search(pattern, lines):
    """Whether the pattern matches in a line, as grep finds it without -x."""
    return any(re.search(pattern, line) for line in lines)


def has_text(text, lines):
    """Whether a line holds the text, as grep -F finds it without -x."""
    return any(text in line for line in lines)


def count_starting(prefix, lines):
    """The number of lines that start with the prefix, as grep -c "^prefix" counts them."""
    return sum(line.startswith(prefix) for line in lines)


def events_of(path):
    """The events of an event file without its header, as the shell test's
    conditions read them: its text split with str.splitlines()."""
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()[1:]]


def without_seq(event):
    return {k: v for k, v in event.items() if k != "seq"}


@pytest.fixture(scope="module")
def pasted_extra(api_extra, mirror_extra, plan_pasted):
    """extra-stop.jsonl, the plan of mirror-extra.git without --leave-behind,
    which stops; and extra-pasted.jsonl, planned with the lines it printed."""
    return plan_pasted(
        api_extra, mirror_extra, "extra-stop.jsonl", "leave-pasted", "extra-pasted.jsonl"
    )


@pytest.fixture(scope="module")
def extra_del(root, api_extra_del, plan_extra):
    """extra-del.jsonl: the plan of mirror-extra.git whose source deletes head
    branches on merge, without --leave-behind; its output and error apart."""
    events = root / "extra-del.jsonl"
    return plan_extra(api_extra_del, events)


@pytest.fixture(scope="module")
def latest_left(root, api_extra, leave, plan_extra):
    """latest-left.jsonl: the same source whose latest release, v9.9, is on a
    tag the mirror lacks, and with a published release v0.1 older than v0.2:
    v0.2, the newest one the replay carries, takes the place of the latest.
    Its --leave-behind, leave-latest, is $T/leave with a line for v9.9."""
    folder = root / "api-latest-left"
    shutil.copytree(api_extra, folder)
    page = folder / f"{RELEASES}-1.json"
    releases = json.loads(page.read_text(encoding="utf-8"))

    def release(release_id, tag, created):
        return {
            "id": release_id,
            "tag_name": tag,
            "name": tag,
            "draft": False,
            "prerelease": False,
            "target_commitish": "main",
            "body": "",
            "author": {"login": "ada-example"},
            "created_at": created,
            "published_at": created,
        }

    latest = release(9, "v9.9", "2026-03-09T12:00:00Z")
    releases = [latest, *releases, release(4, "v0.1", "2026-03-01T12:00:00Z")]
    page.write_text(json.dumps(releases), encoding="utf-8")
    (folder / f"{RELEASES}_latest.json").write_text(json.dumps(latest), encoding="utf-8")
    leave_latest = root / "leave-latest"
    leave_latest.write_text(leave.read_text(encoding="utf-8") + "release v9.9\n", encoding="utf-8")
    events = root / "latest-left.jsonl"
    return events, plan_extra(folder, events, "--leave-behind", leave_latest)


@pytest.fixture(scope="module")
def odd_plans(api_extra, mirror_odd, plan_pasted):
    """odd-stop.jsonl, the plan of mirror-odd.git that stops; and odd.jsonl,
    planned with the lines it printed."""
    return plan_pasted(api_extra, mirror_odd, "odd-stop.jsonl", "leave-odd", "odd.jsonl")


@pytest.fixture(scope="module")
def off_stop(root, api_extra, plan_extra):
    """off-stop.jsonl: --no-releases --no-tags without --leave-behind."""
    events = root / "off-stop.jsonl"
    return events, plan_extra(api_extra, events, "--no-releases", "--no-tags")


@pytest.fixture(scope="module")
def norel(root, api_extra, leave_branches, plan_extra):
    """norel.jsonl: --no-releases alone, with the branches in --leave-behind."""
    events = root / "norel.jsonl"
    return events, plan_extra(api_extra, events, "--no-releases", "--leave-behind", leave_branches)


@pytest.fixture(scope="module")
def off_all(root, api_extra, leave, plan_extra):
    """off-all.jsonl: --no-tags --no-releases with $T/leave as --leave-behind."""
    events = root / "off-all.jsonl"
    options = ("--no-tags", "--no-releases", "--leave-behind", leave)
    return events, plan_extra(api_extra, events, *options)


def test_stops_and_writes_no_event_file_at_each_branch_left_behind_unaccepted(pasted_extra, hashes):
    """plan-replay.py stops, and writes no event file, at each branch it leaves behind that --leave-behind does not accept, and carries the tags and releases"""  # noqa: E501 # the description word for word
    stop = pasted_extra.stop
    err = stop.result.err_lines
    n1, n2, c5 = hashes["N1"][:7], hashes["N2"][:7], hashes["C5"][:7]
    assert stop.result.status == 1, stop.result.err
    assert not stop.file.exists()
    assert has_search(
        "^plan-replay.py: the replay leaves behind 2 of the source's tags, releases and branches"
        " that --leave-behind does not accept",
        err,
    ), stop.result.err
    for line in (
        f"  branch   docs/5-notes  # at {n1}; the replay pushes the head of #5, {n2}, under its"
        " name",
        f"  branch   wip/idea      # at {c5}, the head of no pull request",
    ):
        assert line in err, f"no line: {line}\n{stop.result.err}"
    assert not has_search(r"feat/2-thing|fix/3-parser|^  tag |^  release |Traceback", err), (
        stop.result.err
    )


def test_records_what_leave_behind_accepts_in_the_header_and_plans_nothing_else_differently(
    extra_plan, run_plan, read_plan, hashes
):
    """plan-replay.py records what --leave-behind accepts in the header, and plans nothing else differently but the tags and releases"""  # noqa: E501 # the description word for word
    p = read_plan(extra_plan.file)
    left = p.header["left_behind"]
    assert [(x["kind"], x["name"]) for x in left] == [
        ("branch", "docs/5-notes"),
        ("branch", "wip/idea"),
    ]
    assert [x["sha"] for x in left] == [hashes["N1"], hashes["C5"]]
    assert [
        without_seq(e) for e in p.events if e["kind"] not in ("create-tag", "create-release")
    ] == [without_seq(e) for e in events_of(run_plan.file)]


def test_plans_each_release_on_a_tag_it_carries_with_its_assets_and_the_latest(
    extra_plan, read_plan, hashes
):
    """plan-replay.py plans each release on a tag it carries, a pre-release and a draft whose tag the source lacks included, with its assets, and the source's latest release as the latest"""  # noqa: E501 # the description word for word
    p = read_plan(extra_plan.file)
    r = {e["tag_name"]: e for e in p.of("create-release")}
    assert r
    assert sorted(r) == ["v0.1.1", "v0.2", "v0.3"]
    assert [
        (r[t]["draft"], r[t]["prerelease"], r[t]["latest"], r[t]["on_tag"], r[t]["commit"])
        for t in ("v0.2", "v0.1.1", "v0.3")
    ] == [
        (False, False, True, True, hashes["C5"]),
        (False, True, False, True, hashes["F1"]),
        (True, False, False, False, None),
    ]
    v02 = r["v0.2"]
    assert (v02["name"], v02["body"], v02["published_at"], v02["time"]) == (
        "Second",
        "Built from " + hashes["C4"][:7] + ".",
        "2026-03-07T15:00:00Z",
        "2026-03-07T15:00:00Z",
    )
    assert [
        (
            a["id"],
            a["name"],
            a["label"],
            a["content_type"],
            a["size"],
            a["digest"][:7] if a["digest"] else None,
        )
        for a in v02["assets"]
    ] == [
        (11, "tool.tar.gz", "", "application/gzip", 11, "sha256:"),
        (12, "notes.txt", "Release notes", "text/plain", 15, None),
    ]
    assert r["v0.3"]["time"] == "2026-03-08T13:00:00Z"
    assert not r["v0.1.1"]["assets"]


def test_plans_each_release_after_its_tag_and_a_draft_for_main_after_its_first_push(
    extra_plan, read_plan
):
    """plan-replay.py plans each release after the event of its tag, and a draft for the default branch after its first push"""  # noqa: E501 # the description word for word
    p = read_plan(extra_plan.file)
    events, of = p.events, p.of
    r = {e["tag_name"]: events.index(e) for e in of("create-release")}
    assert r
    t = {e["name"]: events.index(e) for e in of("create-tag")}
    assert t
    assert r["v0.2"] > t["v0.2"]
    assert r["v0.1.1"] > t["v0.1.1"]
    assert r["v0.3"] > events.index(of("push-commits")[0])
    assert events[r["v0.2"] - 1]["time"] <= events[r["v0.2"]]["time"]


def test_plans_each_tag_at_a_recreated_commit_with_mapped_message_tagger_and_date(
    extra_plan, read_plan, hashes
):
    """plan-replay.py plans each tag at a recreated commit, lightweight or annotated, with the message and the tagger mapped through the mailmap and the original date"""  # noqa: E501 # the description word for word
    p = read_plan(extra_plan.file)
    t = {e["name"]: e for e in p.of("create-tag")}
    assert t
    assert [(e["name"], e["commit"], e["annotated"]) for e in p.of("create-tag")] == [
        ("v0.1", hashes["M2"], False),
        ("v0.1.1", hashes["F1"], True),
        ("v0.2", hashes["C5"], True),
    ]
    assert (t["v0.1"]["message"], t["v0.1"]["tagger"], t["v0.1"]["time"]) == (None, None, None)
    assert (t["v0.2"]["message"], t["v0.2"]["tagger"], t["v0.2"]["time"]) == (
        "Second, after " + hashes["C4"][:7] + "\n",
        {"name": "Ada Example", "email": "ada@example.com", "date": "2026-03-07T15:00:00+02:00"},
        "2026-03-07T13:00:00Z",
    )
    assert (t["v0.1.1"]["message"], t["v0.1.1"]["tagger"]) == (
        "Parser fix\n",
        {"name": "Bob Example", "email": "bob@example.com", "date": "2026-03-04T10:30:00+00:00"},
    )


def test_plans_a_lightweight_tag_right_after_its_commit_and_an_annotated_one_at_its_date(
    extra_plan, read_plan, hashes
):
    """plan-replay.py plans a lightweight tag right after the event that recreates its commit, and an annotated one at its date after that event"""  # noqa: E501 # the description word for word
    p = read_plan(extra_plan.file)
    events, of = p.events, p.of
    t = {e["name"]: events.index(e) for e in of("create-tag")}
    assert t
    assert t["v0.1"] == events.index(of("merge-pull", 2)[0]) + 1
    c5_push = next(
        e for e in of("push-commits") if hashes["C5"] in [c["sha"] for c in e["commits"]]
    )
    assert t["v0.2"] > events.index(c5_push)
    assert t["v0.1.1"] > events.index(of("push-branch", 3)[0])
    v011 = t["v0.1.1"]
    assert events[v011 - 1]["time"] <= events[v011]["time"] <= events[v011 + 1]["time"]


def test_makes_the_newest_carried_release_the_latest_where_the_latest_is_left_behind(
    latest_left, read_plan
):
    """plan-replay.py makes the newest published release it carries the latest where the source's latest release is left behind, and warns of it"""  # noqa: E501 # the description word for word
    events, result = latest_left
    p = read_plan(events)
    assert [
        (e["tag_name"], e["latest"])
        for e in p.of("create-release")
        if not e["draft"] and not e["prerelease"]
    ] == [("v0.1", False), ("v0.2", True)]
    assert "v9.9" in [x["name"] for x in p.header["left_behind"] if x["kind"] == "release"]
    # Split as the shell test's condition reads the file, with str.splitlines().
    assert (
        "plan-replay.py: warning: the source's latest release is left behind; v0.2, the newest"
        " one the replay carries, becomes the target's latest"
    ) in result.err.splitlines(), result.err


EXTRA_WARNINGS = ("tag v0.1", "tag v0.2", "tag v9", "release v0.2", "release v0.3")


def test_prints_what_it_leaves_behind_and_warns_of_an_accepted_line_that_names_nothing_left(
    extra_plan, planned
):
    """plan-replay.py prints what it leaves behind, counts it, the tags, the releases and their assets, and warns of an accepted line that names nothing it leaves behind, a tag or release it carries included"""  # noqa: E501 # the description word for word
    r = extra_plan.result
    out = r.out_lines
    assert r.status == 0, r.err + r.out
    assert "Left behind: 2" in out, r.out
    for total in ("left behind +2", "tags +3", "releases +3", "release assets +2"):
        assert has_match(f"  {total}", out), f"no line {total!r} in:\n{r.out}"
    assert not has_search("^  release  ", out), r.out
    for line in EXTRA_WARNINGS:
        pattern = f"plan-replay.py: warning: .*/leave accepts {line}, which the replay does not leave behind"  # noqa: E501 # one line of the output
        assert has_match(pattern, r.err_lines), f"no warning for {line}:\n{r.err}"
    assert r.err.count("\n") == 5, r.err
    main = planned.main.out_lines
    assert "Left behind: 0" in main, planned.main.out
    for total in ("left behind +0", "tags +0", "releases +0"):
        assert has_match(f"  {total}", main), f"no line {total!r} in:\n{planned.main.out}"


def test_leaves_behind_the_branch_of_a_merged_pull_request_where_the_source_deletes_it(
    extra_del,
):
    """plan-replay.py leaves behind the branch of a merged pull request where the source deletes head branches on merge"""  # noqa: E501 # the description word for word
    err = extra_del.err_lines
    assert extra_del.status == 1, extra_del.err
    assert has_search("^plan-replay.py: the replay leaves behind 4 of", err), extra_del.err
    deleted = "which the replay deletes on its merge, as the source deletes head branches"
    assert f"  branch   feat/2-thing  # the head of #2, {deleted}" in err, extra_del.err
    assert f"  branch   fix/3-parser  # the head of #3, {deleted}" in err, extra_del.err


def test_takes_the_lines_it_prints_where_it_stops_as_lines_of_leave_behind(pasted_extra):
    """plan-replay.py takes the lines it prints where it stops, with their comments, as lines of --leave-behind"""  # noqa: E501 # the description word for word
    again = pasted_extra.planned.result
    leave = pasted_extra.leave.read_text(encoding="utf-8")
    assert again.status == 0, leave + again.out
    assert leave.count("\n") == 2, leave
    assert "Left behind: 2" in again.out_lines, again.out


def test_stops_at_a_release_whose_tag_it_leaves_behind_and_plans_it_on_no_other_tag(
    odd_plans, read_plan
):
    """plan-replay.py stops at a release whose tag it leaves behind, without a line of --leave-behind, and plans it on no other tag"""  # noqa: E501 # the description word for word
    stop = odd_plans.stop.result
    err = stop.err_lines
    pattern = r"  release  v0\.3 +# draft, named 'Next'; its tag is left behind"
    assert has_match(pattern, err), stop.err
    assert count_starting("  release ", err) == 1, stop.err
    p = read_plan(odd_plans.planned.file)
    assert [e["tag_name"] for e in p.of("create-release")] == ["v0.1.1", "v0.2"]


def test_stops_at_a_tag_of_a_tag_a_tree_and_an_unrecreated_commit_and_takes_back_a_nbsp_name(
    odd_plans, mirror_odd, hashes, run_process
):
    """plan-replay.py stops at a tag of a tag, peeled to its commit, a tag of a tree and a tag of a commit it does not recreate, and takes back a name with a no-break space"""  # noqa: E501 # the description word for word
    c5, s1 = hashes["C5"][:7], hashes["S1"][:7]
    tree = run_process("git", "--git-dir", mirror_odd, "rev-parse", f"{hashes['C5']}^{{tree}}")
    tree = tree.out.strip()[:7]
    stop, again = odd_plans.stop.result, odd_plans.planned.result
    err = stop.err_lines
    assert has_search("^plan-replay.py: the replay leaves behind 6 of", err), stop.err
    of_a_tag = "the replay carries no tag of a tag"
    assert has_match(
        rf"  tag      v0\.3 +# annotated, at {c5} through another tag; {of_a_tag}", err
    )
    of_a_tree = "the replay carries only tags of commits"
    assert has_match(rf"  tag      tree-tag +# lightweight, at the tree {tree}; {of_a_tree}", err)
    assert has_text(f"  tag      {NBSP_TAG} ", err), stop.err
    unrecreated = f" # lightweight, at {s1}, a commit the replay does not recreate$"
    assert has_search(f"^  tag      .*{unrecreated}", err), stop.err
    assert not has_search(r"^  tag      v0\.[12]", err), stop.err
    assert again.status == 0, again.out
    assert "Left behind: 6" in again.out_lines, again.out
    assert has_match("  tags +3", again.out_lines), again.out


def test_records_the_commit_a_tag_of_a_tag_peels_to_in_the_header(odd_plans, read_plan, hashes):
    """plan-replay.py records the commit a tag of a tag peels to in the header"""
    header = read_plan(odd_plans.planned.file).header
    assert [
        x["sha"] for x in header["left_behind"] if (x["kind"], x["name"]) == ("tag", "v0.3")
    ] == [hashes["C5"]]


def test_stops_at_an_annotated_and_a_lightweight_tag_whose_name_git_tag_refuses(msg_plans, hashes):
    """plan-replay.py stops at an annotated and a lightweight tag whose name git tag refuses, and carries the others"""  # noqa: E501 # the description word for word
    c5 = hashes["C5"][:7]
    stop, again = msg_plans.stop, msg_plans.planned.result
    err = stop.result.err_lines
    assert (stop.result.status, again.status) == (1, 0), stop.result.err + again.out
    assert not stop.file.exists()
    assert has_search("^plan-replay.py: the replay leaves behind 4 of", err), stop.result.err
    assert has_match(f"  tag      HEAD +# annotated, at {c5}; git tag refuses the name", err)
    assert has_match(f"  tag      -x +# lightweight, at {c5}; git tag refuses the name", err)
    assert not has_search("^  tag      notes", err), stop.result.err
    assert has_match("  tags +4", again.out_lines), again.out


def test_keeps_whole_a_tag_message_that_holds_the_lines_of_a_signature(root, msg_plans, read_plan):
    """plan-replay.py keeps whole a tag message that holds the lines of a signature in its text"""
    p = read_plan(msg_plans.planned.file)
    message = (root / "notes-message").read_text(encoding="utf-8")
    assert [e["message"] for e in p.of("create-tag") if e["name"] == "notes"] == [message]
    assert not [e for e in p.of("create-tag") if e["name"] in ("HEAD", "-x")]


def test_refuses_a_line_of_leave_behind_other_than_a_kind_and_a_name(root, api_extra, plan_extra):
    """plan-replay.py refuses a line of --leave-behind other than a kind and a name"""
    bad_leave = root / "bad-leave"
    bad_leave.write_text("tags v0.1\n", encoding="utf-8")
    events = root / "bad-leave.jsonl"
    result = plan_extra(api_extra, events, "--leave-behind", bad_leave)
    assert result.status != 0
    pattern = "plan-replay.py: .*/bad-leave:1: expected one of tag, release, branch and a name"
    assert has_match(pattern, result.err_lines), result.err
    assert not events.exists()


def test_stops_at_no_tags_without_no_releases_before_it_reads_the_mirror_or_github(
    root, source, plan, source_gh
):
    """plan-replay.py stops at --no-tags without --no-releases, before it reads the mirror or GitHub"""  # noqa: E501 # the description word for word
    gh = source_gh("notags-gh")
    events = root / "notags.jsonl"
    nothing = root / "nothing.git"
    result = plan("--no-tags", nothing, TOOL, source.mailmap, events, env=gh.env, merged=True)
    message = (
        "plan-replay.py: --no-tags needs --no-releases (no_tags needs no_releases, in a run file"
        " of replay.py): GitHub creates the missing tag of a release it creates, at the commit"
        " the release's target_commitish names, so a replay with releases would still carry"
        " tags. Give --no-releases too, or leave out --no-tags"
    )
    assert result.status == 1, result.out
    assert message in result.out_lines, result.out
    assert result.out.count("\n") == 1, result.out
    assert not gh.log.exists(), gh.log.read_text(encoding="utf-8")
    assert not events.exists()


def test_no_tags_no_releases_accepts_every_tag_and_release_and_still_stops_at_each_branch(
    off_plan, off_stop, hashes
):
    """plan-replay.py --no-tags --no-releases accepts every tag and release without a line of --leave-behind, lists each as turned off, and still stops at each branch"""  # noqa: E501 # the description word for word
    off = off_plan.result
    stop_file, stop = off_stop
    m2 = hashes["M2"][:7]
    assert (off.status, stop.status) == (0, 1), off.err + off.out + stop.err
    assert off.err == ""
    assert "Left behind: 8" in off.out_lines, off.out
    assert has_match("  tags +0", off.out_lines), off.out
    assert has_match("  releases +0", off.out_lines), off.out
    tag = f"  tag      v0.1          lightweight, at {m2}; tags are turned off"
    assert tag in off.out_lines, off.out
    release = "  release  v0.3          draft, named 'Next'; releases are turned off"
    assert release in off.out_lines, off.out
    assert not stop_file.exists()
    stopped = (
        "^plan-replay.py: the replay leaves behind 2 of the source's tags, releases and branches"
    )
    assert has_search(stopped, stop.err_lines), stop.err
    assert count_starting("  branch ", stop.err_lines) == 2, stop.err
    assert not has_search("^  tag |^  release ", stop.err_lines), stop.err


def test_no_tags_no_releases_plans_no_tag_lists_both_as_turned_off_and_nothing_else_differently(
    off_plan, run_plan, read_plan
):
    """plan-replay.py --no-tags --no-releases plans no tag, lists tags and releases as turned off in the header, and plans nothing else differently"""  # noqa: E501 # the description word for word
    p = read_plan(off_plan.file)
    header = p.header
    assert header["turned_off"] == ["tags", "releases"]
    assert header["reviews"] is True
    assert not p.of("create-tag")
    assert [(x["kind"], x["name"]) for x in header["left_behind"]] == [
        ("branch", "docs/5-notes"),
        ("branch", "wip/idea"),
        ("tag", "v0.1"),
        ("tag", "v0.1.1"),
        ("tag", "v0.2"),
        ("release", "v0.1.1"),
        ("release", "v0.2"),
        ("release", "v0.3"),
    ]
    assert [x["reason"].rsplit("; ", 1)[1] for x in header["left_behind"][2:]] == [
        "tags are turned off"
    ] * 3 + ["releases are turned off"] * 3
    assert p.events == events_of(run_plan.file)


def test_no_releases_alone_accepts_the_releases_plans_none_and_carries_the_tags(norel):
    """plan-replay.py --no-releases alone accepts the releases, plans none of them, and carries the tags"""  # noqa: E501 # the description word for word
    _, r = norel
    out = r.out_lines
    assert r.status == 0, r.err + r.out
    assert r.err == ""
    assert "Left behind: 5" in out, r.out
    for total in ("tags +3", "releases +0", "release assets +0"):
        assert has_match(f"  {total}", out), f"no line {total!r} in:\n{r.out}"
    pattern = r"  release  v0\.2 +published, named 'Second'; releases are turned off"
    assert has_match(pattern, out), r.out
    assert not has_search("^  tag ", out), r.out


def test_no_releases_alone_plans_the_tags_as_without_a_switch_and_no_release(
    norel, extra_plan, read_plan
):
    """plan-replay.py --no-releases alone plans the tags as without a switch and no release, and lists only releases as turned off"""  # noqa: E501 # the description word for word
    events, _ = norel
    p = read_plan(events)
    assert p.header["turned_off"] == ["releases"]
    assert [(x["kind"], x["name"]) for x in p.header["left_behind"]] == [
        ("branch", "docs/5-notes"),
        ("branch", "wip/idea"),
        ("release", "v0.1.1"),
        ("release", "v0.2"),
        ("release", "v0.3"),
    ]
    assert not p.of("create-release")
    assert [without_seq(e) for e in p.events] == [
        without_seq(e) for e in events_of(extra_plan.file) if e["kind"] != "create-release"
    ]


def test_no_releases_alone_still_stops_at_each_tag_it_cannot_place_unaccepted(
    root, api_extra, mirror_odd, leave_branches, plan_extra
):
    """plan-replay.py --no-releases alone still stops at each tag it cannot place that --leave-behind does not accept"""  # noqa: E501 # the description word for word
    events = root / "norel-odd.jsonl"
    options = ("--no-releases", "--leave-behind", leave_branches)
    r = plan_extra(api_extra, events, *options, mirror=mirror_odd)
    err = r.err_lines
    assert r.status == 1, r.err
    assert not events.exists()
    assert has_search("^plan-replay.py: the replay leaves behind 3 of", err), r.err
    for name in ("v0.3", "tree-tag", NBSP_TAG):
        assert has_text(f"  tag      {name} ", err), f"no line for {name}:\n{r.err}"
    assert not has_search("^  release |^  branch ", err), r.err


OFF_ALL_WARNINGS = (
    "tag v0.1, which --no-tags",
    "tag v0.2, which --no-tags",
    "release v0.2, which --no-releases",
    "release v0.3, which --no-releases",
)


def test_warns_of_a_line_of_leave_behind_for_what_a_switch_accepts_already(off_all):
    """plan-replay.py warns of a line of --leave-behind for a tag or release a switch accepts already, and does not stop at it"""  # noqa: E501 # the description word for word
    _, r = off_all
    err = r.err_lines
    assert r.status == 0, r.err
    for line in OFF_ALL_WARNINGS:
        pattern = f"plan-replay.py: warning: .*/leave accepts {line} leaves behind already"
        assert has_match(pattern, err), f"no warning: {line}\n{r.err}"
    pattern = (
        "plan-replay.py: warning: .*/leave accepts tag v9, which the replay does not leave behind"
    )
    assert has_match(pattern, err), r.err
    assert r.err.count("\n") == 5, r.err


def test_stops_at_a_draft_it_cannot_place_and_warns_of_an_asset_an_upload_left_half_done(
    root, api_drafts, leave_branches, drafts_plan, plan_extra
):
    """plan-replay.py stops at a draft whose target_commitish names neither the default branch nor a commit it recreates, and warns of an asset an upload left half done"""  # noqa: E501 # the description word for word
    stop_file = root / "drafts-stop.jsonl"
    stop = plan_extra(api_drafts, stop_file, "--leave-behind", leave_branches)
    drafts = drafts_plan.result
    assert (stop.status, drafts.status) == (1, 0), stop.err + drafts.err + drafts.out
    assert not stop_file.exists()
    assert has_search("^plan-replay.py: the replay leaves behind 1 of", stop.err_lines), stop.err
    pattern = (
        r"  release  v1\.0-rc +# draft, named 'Candidate'; its target_commitish 'wip/idea' is"
        " neither the default branch nor a commit the replay recreates"
    )
    assert has_match(pattern, stop.err_lines), stop.err
    warning = "plan-replay.py: warning: asset broken.zip of release v0.2 is starter, not uploaded; left out"  # noqa: E501 # one line of the output
    assert warning in drafts.err_lines, drafts.err
    assert has_match("  releases +6", drafts.out_lines), drafts.out
    assert has_match("  release assets +3", drafts.out_lines), drafts.out


def test_plans_a_draft_for_a_commit_named_by_a_prefix_of_its_hash_after_it_is_recreated(
    drafts_plan, read_plan, hashes
):
    """plan-replay.py plans a draft for a commit it recreates, named by a prefix of its hash, after the event that recreates it"""  # noqa: E501 # the description word for word
    p = read_plan(drafts_plan.file)
    events, of = p.events, p.of
    r = next(e for e in of("create-release") if e["tag_name"] == "v0.9")
    assert r
    assert (r["commit"], r["on_tag"], r["draft"]) == (hashes["C4"], False, True)
    c4_push = next(
        e for e in of("push-commits") if hashes["C4"] in [c["sha"] for c in e["commits"]]
    )
    assert events.index(r) > events.index(c4_push)
    assert [x["name"] for x in p.header["left_behind"] if x["kind"] == "release"] == ["v1.0-rc"]


def test_plans_a_draft_and_a_published_release_of_one_tag_as_two_and_a_later_one_not_latest(
    drafts_plan, read_plan, hashes
):
    """plan-replay.py plans a draft and a published release of one tag as two releases, and a release published after the latest one as not the latest"""  # noqa: E501 # the description word for word
    p = read_plan(drafts_plan.file)
    events, releases = p.events, p.of("create-release")
    assert sorted(
        (e["release_id"], e["draft"], e["latest"], e["on_tag"])
        for e in releases
        if e["tag_name"] == "v0.2"
    ) == [(1, False, True, True), (6, True, False, True)]
    v = next(e for e in releases if e["tag_name"] == "v0.1")
    assert v
    assert (v["latest"], v["on_tag"], v["commit"]) == (False, True, hashes["M2"])
    assert events.index(v) > max(events.index(e) for e in releases if e["tag_name"] == "v0.2")
