import hashlib
import json
import shutil
import time
from types import SimpleNamespace

import pytest
from conftest import (
    API_BASE,
    TOOL,
    TOOL_TAGS_RELEASES,
    Git,
    Planned,
    as_committer,
    copy_target,
    has_match,
    has_search,
    has_text,
    kill_hook,
    lines,
    past_header,
    refuse_hook,
    shell_status,
    write_hook,
)

ADA = ("Ada Example", "ada@example.com")


def with_universal_newlines(text):
    return text.replace("\r\n", "\n").replace("\r", "\n")


def tag_refs(run_process, target):
    return run_process("git", "--git-dir", target.repo, "for-each-ref", "refs/tags/")


def same_tags(run_process, uninterrupted, resumed):
    first, other = tag_refs(run_process, uninterrupted), tag_refs(run_process, resumed)
    assert (first.status, other.status) == (0, 0), first.err + other.err
    assert first.out.count("\n") == 3, first.out
    assert first.out == other.out


@pytest.fixture(scope="module")
def changed_tags(
    root, base_env, extra_plan, mirror_extra, api_extra, replay_tags_releases, compare, replay
):
    target = copy_target(root, replay_tags_releases.target, "gh-changed-tags")
    state = root / "changed-tags.state.json"
    shutil.copyfile(replay_tags_releases.state, state)
    git, repo = Git(base_env, root), ("--git-dir", target.repo)
    git(*repo, "tag", "-f", "v0.1", "main")
    git(
        *(*repo, "tag", "-f", "-a", "-m", "Another message", "v0.2", "v0.2^{commit}"),
        env=as_committer(ADA, "1772888400 +0200"),
    )
    git(*repo, "tag", "-f", "v0.1.1", "v0.1.1^{commit}")
    tail = (extra_plan.file, mirror_extra, TOOL_TAGS_RELEASES)
    compared = compare(target, "--state", state, *tail, api=api_extra)
    again = replay(target, TOOL_TAGS_RELEASES, "--pace", "0", "--state", state, *tail, merged=True)
    return SimpleNamespace(target=target, state=state, compared=compared, again=again)


@pytest.fixture(scope="module")
def killed_tag(root, run_process, extra_plan, mirror_extra, make_target, replay):
    target = make_target("gh-killed-tag", TOOL_TAGS_RELEASES)
    write_hook(target, "post-receive", kill_hook("refs/tags/v0.2"))
    state = root / "killed-tag.state.json"
    tail = (extra_plan.file, mirror_extra, TOOL_TAGS_RELEASES)

    def resume(target, state):
        return replay(
            target, TOOL_TAGS_RELEASES, "--pace", "0", "--state", state, *tail, merged=True
        )

    first = resume(target, state)
    # The killed run's push goes on without it: time to end before the copy.
    time.sleep(1)
    copy = copy_target(root, target, "gh-other-tag-object")
    copy_state = root / "other-tag-object.state.json"
    recorded = json.loads(state.read_text(encoding="utf-8")) if state.exists() else {"tags": {}}
    # Where the killed run saved no tag, no state file of the copy is
    # written, so that only the check of the copy fails for it.
    if "v0.2" in recorded["tags"]:
        # As a rebuild that differs would leave it.
        recorded["tags"]["v0.2"] = "0123456789abcdef0123456789abcdef01234567"
        copy_state.write_text(json.dumps(recorded), encoding="utf-8")
    other_object_refs = run_process("git", "--git-dir", copy.repo, "for-each-ref").out
    second = resume(target, state)
    other_object = resume(copy, copy_state)
    # One text, since a line the killed run left unended runs on into the second run's first.
    out = first.out + second.out
    return SimpleNamespace(
        target=target,
        statuses=[shell_status(r) for r in (first, second)],
        out_lines=lines(out),
        out=out,
        copy=copy,
        other_object_refs=other_object_refs,
        other_object=other_object,
    )


def test_names_a_tag_elsewhere_a_tag_with_another_message_and_one_lightweight_planned_annotated(
    hashes, changed_tags
):
    changed = changed_tags
    main = changed.target.git("rev-parse", "main")[:7]
    m2 = json.loads(changed.state.read_text(encoding="utf-8"))["hashes"][hashes["M2"]][:7]
    r = changed.compared
    out = r.out_lines
    assert r.status == 1, r.out
    elsewhere = f"  tag v0.1 of the source is at {main} in the target, not at the recreated {m2}"
    assert elsewhere in out, r.out
    message = "  tag v0.2: the message differs; they part at character 1: 'Another message"
    assert has_text(message, out), r.out
    assert "  tag v0.1.1 is lightweight in the target, annotated as planned" in out, r.out
    assert has_match("Differences: 3", out), r.out


def test_checks_the_targets_tags_after_the_last_event_and_stops_at_each_that_differs(
    changed_tags,
):
    r = changed_tags.again
    differs = (
        "run-replay.py: ada-example/tool-tags-releases differs from the plan: tag v0\\.1 is at"
        " [0-9a-f]{7}, the state file's [0-9a-f]{7}; tag v0\\.1\\.1 is at [0-9a-f]{7}, the state"
        " file's [0-9a-f]{7}; tag v0\\.2 is at [0-9a-f]{7}, the state file's [0-9a-f]{7}$"
    )
    assert r.status == 1, r.out
    assert has_search(differs, r.out_lines), r.out


def test_resumes_a_run_killed_after_a_tags_push_takes_it_over_and_ends_with_the_same_tags(
    run_process, replay_tags_releases, killed_tag
):
    killed = killed_tag
    assert killed.statuses == [137, 0], killed.out
    found = r"[0-9]+/[0-9]+  create-tag    v0\.2, annotated, at [0-9a-f]{7}, found pushed$"
    assert has_search(found, killed.out_lines), killed.out
    same_tags(run_process, replay_tags_releases.target, killed.target)


def test_stops_before_pushing_where_a_rebuilt_tag_differs_from_the_one_the_state_file_records(
    run_process, killed_tag
):
    killed = killed_tag
    r = killed.other_object
    out = r.out_lines
    assert r.status == 1, r.out
    rebuilt = (
        "run-replay.py: tag v0\\.2 was rebuilt as [0-9a-f]{7}, but .*/other-tag-object.state.json"
        " records 0123456; it differs from the one the first run made. The run stops before it"
        " pushes a second tag$"
    )
    assert has_search(rebuilt, out), r.out
    assert has_search("^run-replay.py: stopped in event [0-9]* of [0-9]*", out), r.out
    refs = run_process("git", "--git-dir", killed.copy.repo, "for-each-ref").out
    assert refs.rstrip("\n") == killed.other_object_refs.rstrip("\n")


@pytest.fixture(scope="module")
def pushed_tags(root, extra_plan, mirror_extra, make_target, replay):
    target = make_target("gh-pushed-tags", TOOL_TAGS_RELEASES)
    write_hook(target, "post-receive", kill_hook("refs/tags/v0.1"))
    write_hook(target, "pre-receive", refuse_hook("refs/tags/v0.2"))
    state = root / "pushed-tags.state.json"
    tail = (extra_plan.file, mirror_extra, TOOL_TAGS_RELEASES)

    def replay_once():
        return replay(
            target, TOOL_TAGS_RELEASES, "--pace", "0", "--state", state, *tail, merged=True
        )

    first = replay_once()
    # The killed run's push goes on without it: time to end before the resume.
    time.sleep(1)
    second = replay_once()
    # Empty where the state file is missing, so that the check of v0.2 fails on it.
    v02 = (
        json.loads(state.read_text(encoding="utf-8"))["tags"].get("v0.2", "")
        if state.exists()
        else ""
    )
    third = replay_once()
    runs = [first, second, third]
    return SimpleNamespace(
        target=target, runs=runs, statuses=[shell_status(r) for r in runs], v02=v02
    )


def test_resumes_a_run_killed_after_it_pushed_a_lightweight_tag_and_takes_the_tag_over(
    pushed_tags,
):
    pushed = pushed_tags
    second = pushed.runs[1]
    assert pushed.statuses == [137, 1, 0], pushed.runs[0].out + second.out
    found = r"[0-9]+/[0-9]+  create-tag    v0\.1, lightweight, at [0-9a-f]{7}, found pushed$"
    assert has_search(found, second.out_lines), second.out


def test_resumes_a_run_stopped_before_a_tags_push_rebuilds_the_recorded_tag_and_pushes_it(
    run_process, replay_tags_releases, pushed_tags
):
    tags = pushed_tags
    second, third = tags.runs[1], tags.runs[2]
    assert has_search("^run-replay.py: stopped in event [0-9]* of [0-9]*", second.out_lines)
    assert has_search("refused once", second.out_lines), second.out
    assert tags.v02
    v02 = run_process("git", "--git-dir", tags.target.repo, "rev-parse", "refs/tags/v0.2")
    assert v02.out.rstrip("\n") == tags.v02
    pushed = r"[0-9]+/[0-9]+  create-tag    v0\.2, annotated, at [0-9a-f]{7}$"
    assert has_search(pushed, third.out_lines), third.out
    same_tags(run_process, replay_tags_releases.target, tags.target)


@pytest.fixture(scope="module")
def missing_tag(root, extra_plan, mirror_extra, replay_tags_releases, replay):
    target = copy_target(root, replay_tags_releases.target, "gh-missing-tag")
    state = root / "missing-tag.state.json"
    shutil.copyfile(replay_tags_releases.state, state)
    target.git("update-ref", "-d", "refs/tags/v0.1.1")
    target.git("tag", "v9", "main")
    tail = (extra_plan.file, mirror_extra, TOOL_TAGS_RELEASES)
    return replay(target, TOOL_TAGS_RELEASES, "--pace", "0", "--state", state, *tail, merged=True)


def test_names_after_the_last_event_a_planned_tag_it_lacks_and_a_tag_the_plan_lacks(missing_tag):
    r = missing_tag
    differs = (
        "run-replay.py: ada-example/tool-tags-releases differs from the plan: tag v0\\.1\\.1 is"
        " missing; tag v9 is not in the plan$"
    )
    assert r.status == 1, r.out
    assert has_search(differs, r.out_lines), r.out


@pytest.fixture(scope="module")
def message_tags(msg_plans, mirror_msg, api_extra, make_target, replay, compare):
    target = make_target("gh-message-tags", TOOL_TAGS_RELEASES)
    tail = (msg_plans.planned.file, mirror_msg, TOOL_TAGS_RELEASES)
    result = replay(target, TOOL_TAGS_RELEASES, "--pace", "0", *tail, merged=True)
    compared = compare(target, *tail, api=api_extra)
    return SimpleNamespace(target=target, result=result, compared=compared)


def test_keep_whole_a_tag_message_with_the_lines_of_a_signature_and_leave_refused_names_alone(
    root, run_process, message_tags
):
    tags = message_tags
    notes = run_process("git", "--git-dir", tags.target.repo, "cat-file", "tag", "notes")
    r, c = tags.result, tags.compared
    out = c.out_lines
    assert (r.status, c.status) == (0, 0), r.out + c.out
    assert past_header(notes.out) == (root / "notes-message").read_text(encoding="utf-8")
    assert has_match("No differences", out), c.out
    assert "  tag HEAD of the source is left behind, as planned" in out, c.out
    assert "  tag -x of the source is left behind, as planned" in out, c.out
    odd = ("for-each-ref", "refs/tags/HEAD", "refs/tags/-x")
    assert run_process("git", "--git-dir", tags.target.repo, *odd).out.rstrip("\n") == ""


def review(review_id, login, body, state, submitted_at, commit_id):
    entry = {"id": review_id, "user": {"login": login}, "body": body, "state": state}
    # GitHub lists a pending review without submitted_at.
    if submitted_at:
        entry["submitted_at"] = submitted_at
    entry["commit_id"] = commit_id
    return entry


def write_api(folder, name, data):
    (folder / f"{API_BASE}{name}").write_text(json.dumps(data), encoding="utf-8")


def read_api(folder, name):
    return json.loads((folder / f"{API_BASE}{name}").read_text(encoding="utf-8"))


REVIEW_COMMENTS = [
    {
        "id": 601,
        "pull_request_review_id": 502,
        "user": {"login": "ada-example"},
        "path": "thing.sh",
        "line": 3,
        "start_line": 1,
        "original_line": 3,
        "side": "LEFT",
        "subject_type": "line",
        "in_reply_to_id": None,
        "body": "This breaks on an empty line.",
        "created_at": "2026-03-04T13:00:00Z",
    },
    {
        "id": 602,
        "pull_request_review_id": 503,
        "user": {"login": "bob-example"},
        "path": "thing.sh",
        "line": None,
        "original_line": 3,
        "subject_type": "line",
        "in_reply_to_id": 601,
        "body": "Agreed.",
        "created_at": "2026-03-04T14:00:00Z",
    },
    {
        "id": 603,
        "pull_request_review_id": 503,
        "user": {"login": "bob-example"},
        "path": "README.md",
        "line": None,
        "original_line": None,
        "side": "LEFT",
        "subject_type": "file",
        "in_reply_to_id": None,
        "body": "Mention the parser.",
        "created_at": "2026-03-04T14:00:01Z",
    },
    {
        "id": 604,
        "pull_request_review_id": 504,
        "user": {"login": "bob-example"},
        "path": "thing.sh",
        "line": 2,
        "original_line": 2,
        "subject_type": "line",
        "in_reply_to_id": None,
        "body": "Still a draft.",
        "created_at": "2026-03-04T15:00:00Z",
    },
]


@pytest.fixture(scope="module")
def api_reviews(root, run_plan, hashes):
    folder = root / "api-reviews"
    shutil.copytree(run_plan.api, folder)
    b2, f1, n1 = hashes["B2"], hashes["F1"], hashes["N1"]
    write_api(
        folder,
        "_pulls_2_reviews-1.json",
        [review(501, "bob-example", "", "APPROVED", "2026-03-02T15:00:00Z", b2)],
    )
    write_api(
        folder,
        "_pulls_3_reviews-1.json",
        [
            review(
                *(502, "ada-example", "Handle empty input.", "CHANGES_REQUESTED"),
                *("2026-03-04T13:00:00Z", f1),
            ),
            review(503, "bob-example", "", "COMMENTED", "2026-03-04T14:00:00Z", f1),
            review(504, "bob-example", "Draft.", "PENDING", None, f1),
        ],
    )
    write_api(
        folder,
        "_pulls_5_reviews-1.json",
        [review(505, "ada-example", "Superseded.", "DISMISSED", "2026-03-07T09:00:00Z", n1)],
    )
    write_api(folder, "_pulls_comments-1.json", REVIEW_COMMENTS)
    return folder


@pytest.fixture(scope="module")
def api_reviews_long(root, api_reviews, hashes):
    folder = root / "api-reviews-long"
    shutil.copytree(api_reviews, folder)
    # One character more than the 65536 a comment takes.
    long_review = review(
        507, "ada-example", "x" * 65537, "COMMENTED", "2026-03-07T09:00:00Z", hashes["N1"]
    )
    write_api(folder, "_pulls_5_reviews-1.json", [long_review])
    listed = read_api(folder, "_pulls_comments-1.json")
    listed.append(
        {
            "id": 605,
            "pull_request_review_id": None,
            "user": {"login": "bob-example"},
            "path": "thing.sh",
            "line": 1,
            "original_line": 1,
            "subject_type": "line",
            "in_reply_to_id": None,
            "body": "Older than reviews.",
            "created_at": "2026-03-04T16:00:00Z",
        }
    )
    write_api(folder, "_pulls_comments-1.json", listed)
    return folder


@pytest.fixture(scope="module")
def api_reviews_changed(root, api_reviews, hashes):
    folder = root / "api-reviews-changed"
    shutil.copytree(api_reviews, folder)
    b2 = hashes["B2"]
    (folder / f"{API_BASE}_pulls_5_reviews-1.json").write_text("[]\n", encoding="utf-8")
    write_api(
        folder,
        "_pulls_2_reviews-1.json",
        [
            review(501, "bob-example", "approved", "APPROVED", "2026-03-02T15:00:00Z", b2),
            review(506, "ada-example", "Late.", "COMMENTED", "2026-03-09T09:00:00Z", b2),
        ],
    )
    changed = read_api(folder, "_pulls_3_reviews-1.json")
    changed[0]["body"] = "Reject empty input."
    # The text of its own review comment 602, which the plan holds below the place of a body.
    changed[1]["body"] = "Agreed."
    write_api(folder, "_pulls_3_reviews-1.json", changed)
    kept = [c for c in read_api(folder, "_issues_comments-1.json") if c["id"] != 104]
    kept.append(
        {
            "id": 199,
            "issue_url": "https://api.github.com/repos/ada-example/tool/issues/1",
            "body": "Added later.",
            "user": {"login": "bob-example"},
            "created_at": "2026-03-10T12:00:00Z",
        }
    )
    write_api(folder, "_issues_comments-1.json", kept)
    return folder


@pytest.fixture(scope="module")
def review_plans(root, source, plan, source_gh, api_reviews, api_reviews_long):
    s, gh = source, source_gh("reviews-gh")

    def plan_reviews(api, name):
        events = root / name
        env = gh.using(FAKE_GH_API=api)
        result = plan("--types", s.types, s.mirror, TOOL, s.mailmap, events, env=env, merged=True)
        return Planned(events, api, result)

    return SimpleNamespace(
        reviews=plan_reviews(api_reviews, "reviews.jsonl"),
        long=plan_reviews(api_reviews_long, "reviews-long.jsonl"),
    )


def without_header_keys(path, keys):
    head, *rest = path.read_text(encoding="utf-8").splitlines()
    header = json.loads(head)
    for key in keys:
        del header[key]
    return "\n".join([json.dumps(header), *rest]) + "\n"


@pytest.fixture(scope="module")
def reviewed(
    root,
    source,
    run_plan,
    review_plans,
    api_reviews,
    api_reviews_changed,
    make_target,
    replay,
    compare,
):
    events, mirror = review_plans.reviews.file, source.mirror
    slug = "ada-example/tool-reviews"
    target = make_target("gh-reviews", slug)
    state = root / "reviews-replay.state.json"
    run = replay(
        *(target, slug, "--pace", "0", "--state", state, events, mirror, slug),
        merged=True,
        FAKE_GH_API=api_reviews,
    )
    tail = ("--state", state, events, mirror, slug)
    compared = compare(target, *tail, api=api_reviews)
    compared_changed = compare(target, *tail, api=api_reviews_changed)

    old = root / "old-reviews.jsonl"
    old.write_text(without_header_keys(run_plan.file, ("reviews", "turned_off")), encoding="utf-8")
    old_slug = "ada-example/tool-before-reviews"
    old_target = make_target("gh-before-reviews", old_slug)
    old_tail = ("--state", root / "before-reviews.state.json", old, mirror, old_slug)
    before_reviews_run = replay(old_target, old_slug, "--pace", "0", *old_tail, merged=True)
    before_reviews_compared = compare(old_target, *old_tail, api=api_reviews)

    timed_slug = "ada-example/tool-reviews-with-times"
    timed = make_target("gh-reviews-with-times", timed_slug)
    timed_state = root / "reviews-with-times.state.json"
    timed_tail = ("--with-times", "--state", timed_state, events, mirror, timed_slug)
    with_times_run = replay(
        timed, timed_slug, "--pace", "0", *timed_tail, merged=True, FAKE_GH_API=api_reviews
    )
    with_times_compared = compare(timed, *timed_tail, api=api_reviews)

    text = without_header_keys(events, ("turned_off",))
    before = root / "reviews-before.jsonl"
    before.write_text(text, encoding="utf-8")
    recorded = json.loads(state.read_text(encoding="utf-8"))
    recorded["events"] = hashlib.sha256(text.encode()).hexdigest()
    before_state = root / "reviews-before-switches.state.json"
    before_state.write_text(json.dumps(recorded), encoding="utf-8")
    compared_before_switches = compare(
        target, "--state", before_state, before, mirror, slug, api=api_reviews
    )
    return SimpleNamespace(
        target=target,
        state=state,
        run=run,
        compared=compared,
        compared_changed=compared_changed,
        before_reviews_run=before_reviews_run,
        before_reviews_compared=before_reviews_compared,
        with_times_run=with_times_run,
        with_times_compared=with_times_compared,
        compared_before_switches=compared_before_switches,
    )


@pytest.fixture(scope="module")
def no_reviews(root, source, plan, source_gh, api_reviews, make_target, replay, compare):
    s, gh = source, source_gh("noreviews-gh")
    events = root / "noreviews.jsonl"
    planned = plan(
        *("--types", s.types, "--no-reviews", s.mirror, TOOL, s.mailmap, events),
        env=gh.using(FAKE_GH_API=api_reviews),
        merged=True,
    )
    slug = "ada-example/tool-no-reviews"
    target = make_target("gh-no-reviews", slug)
    tail = (events, s.mirror, slug)
    result = replay(target, slug, "--pace", "0", *tail, merged=True)
    compared = compare(target, *tail, api=api_reviews)
    return SimpleNamespace(
        gh=gh,
        plan=Planned(events, api_reviews, planned),
        target=target,
        result=result,
        compared=compared,
    )


def test_plans_each_submitted_review_as_a_comment_at_its_time_and_leaves_a_pending_one_out(
    review_plans, read_plan
):
    p = read_plan(review_plans.reviews.file)
    assert [
        (e["number"], e["review_id"], e["created_at"])
        for e in p.of("add-comment")
        if "review_id" in e
    ] == [
        (2, 501, "2026-03-02T15:00:00Z"),
        (3, 502, "2026-03-04T13:00:00Z"),
        (3, 503, "2026-03-04T14:00:00Z"),
        (5, 505, "2026-03-07T09:00:00Z"),
    ]
    assert [e.get("review_id", e.get("source_id")) for e in p.of("add-comment", 3)] == [
        102,
        502,
        503,
    ]
    assert p.header["reviews"] is True
    assert len(p.events) == 27


def test_writes_a_review_as_its_reviewer_state_commit_body_and_each_comment_under_its_place(
    review_plans, read_plan, hashes
):
    p = read_plan(review_plans.reviews.file)
    b2, f1, n1 = hashes["B2"][:7], hashes["F1"][:7], hashes["N1"][:7]
    assert [e["body"] for e in p.of("add-comment") if "review_id" in e] == [
        "_Review by bob-example: approved, on " + b2 + "._",
        "_Review by ada-example: changes requested, on " + f1 + "._\n\nHandle empty input.\n\n"
        "**`thing.sh`, lines 1 to 3, before the change**\n\nThis breaks on an empty line.",
        "_Review by bob-example: commented, on " + f1 + "._\n\n**`thing.sh`, line 3, a reply**"
        "\n\nAgreed.\n\n**`README.md`, file**\n\nMention the parser.",
        "_Review by ada-example: dismissed, on " + n1 + "._\n\nSuperseded.",
    ]


def test_warns_of_a_review_longer_than_a_comment_takes_and_of_a_comment_without_a_review_id(
    review_plans,
):
    r = review_plans.long.result
    out = r.out_lines
    assert r.status == 0, r.out[:3000]
    too_long = (
        "plan-replay.py: warning: review 507 of #5 has 655[0-9]{2} characters, more than the"
        " 65536 a comment takes; the run stops at it"
    )
    assert has_match(too_long, out), r.out[:3000]
    without_id = "plan-replay.py: warning: 1 review comment without a review id left out"
    assert without_id in out, r.out[:3000]


def test_counts_the_reviews_apart_from_the_comments_and_warns_of_comments_of_an_uncarried_one(
    review_plans, planned
):
    r = review_plans.reviews.result
    out = r.out_lines
    assert r.status == 0, r.out
    warning = (
        "plan-replay.py: warning: 1 review comment of review 504, which no submitted review of a"
        " listed pull request has, left out"
    )
    assert warning in out, r.out
    assert has_match("  comments +4", out), r.out
    assert has_match("  reviews +4", out), r.out
    assert has_match("  reviews +0", planned.main.out_lines), planned.main.out


def test_posts_each_review_as_a_comment_with_the_recreated_hash_of_the_commit_it_names(
    reviewed, view, hashes
):
    v = view(reviewed.target, reviewed.state)
    comments, m = v.comments, v.recreated
    out = with_universal_newlines(reviewed.run.out)
    assert out.count("reviews as comments           4") == 1, out
    changes = next(c for c in comments if c[1].startswith("_Review by ada-example: changes"))
    assert comments[comments.index(changes)][0] == 3
    body = (
        "_Review by ada-example: changes requested, on " + m[hashes["F1"]][:7] + "._\n\n"
        "Handle empty input.\n\n**`thing.sh`, lines 1 to 3, before the change**\n\n"
        "This breaks on an empty line."
    )
    assert any(c == (3, body) for c in comments), comments
    assert len(comments) == 8
    assert out.count("  comments                      4\n") == 1, out


def test_finds_no_difference_in_a_replay_that_carries_the_reviews_as_comments(reviewed):
    r, c = reviewed.run, reviewed.compared
    out = c.out_lines
    assert (r.status, c.status) == (0, 0), r.out + c.out
    assert has_match("No differences", out), c.out
    assert has_match("  comments +8", out), c.out
    assert has_match("  reviews as comments +4", out), c.out


CHANGED_REVIEW_LINES = (
    "#5, comment 1: the source has no review 505",
    "#2: review 506 of the source is not in the event file",
    "#3, comment 2: the event file lacks the body of the review",
    "#1: comment 199 of the source is not in the event file",
    "#6, comment 1: the source has no comment 104",
    "#2, comment 1: the event file lacks the body of the review",
    "#3, comment 3: the event file lacks the body of the review",
)


def test_names_a_review_or_comment_gone_one_the_plan_lacks_and_a_review_body_the_plan_lacks(
    reviewed,
):
    r = reviewed.compared_changed
    out = r.out_lines
    assert r.status == 1, r.out
    for line in CHANGED_REVIEW_LINES:
        assert f"  {line}" in out, f"no line: {line}\n{r.out}"
    assert has_match("Differences: 7", out), r.out


def test_finds_no_difference_in_a_replay_with_with_times_that_carries_the_reviews(reviewed):
    r, c = reviewed.with_times_run, reviewed.with_times_compared
    assert (r.status, c.status) == (0, 0), r.out + c.out
    assert has_match("No differences", c.out_lines), c.out


def test_notes_an_event_file_that_predates_reviews_and_expects_none(reviewed):
    r, c = reviewed.before_reviews_run, reviewed.before_reviews_compared
    out = c.out_lines
    assert (r.status, c.status) == (0, 0), r.out + c.out
    assert "  the event file predates reviews: it plans no review as a comment" in out, c.out
    assert has_match("No differences", out), c.out


def test_without_a_switch_turns_nothing_off_and_carries_the_reviews(review_plans, read_plan):
    p = read_plan(review_plans.reviews.file)
    assert p.header["turned_off"] == []
    assert p.header["reviews"] is True
    assert len([e for e in p.events if "review_id" in e]) == 4


def test_no_reviews_plans_no_review_records_them_turned_off_and_plans_nothing_else_differently(
    no_reviews, run_plan, read_plan
):
    p = read_plan(no_reviews.plan.file)
    assert not [e for e in p.events if "review_id" in e]
    assert p.header["reviews"] is False
    assert p.header["turned_off"] == ["reviews"]
    run_lines = run_plan.file.read_text(encoding="utf-8").splitlines()
    assert p.events == [json.loads(line) for line in run_lines[1:]]


def test_no_reviews_reads_no_review_and_no_review_comment_from_github_and_warns_of_none(
    no_reviews,
):
    r = no_reviews.plan.result
    out = r.out_lines
    calls = no_reviews.gh.calls()
    assert r.status == 0, r.out
    assert not has_search("warning", out), r.out
    assert has_match("  reviews +0", out), r.out
    assert has_search("^api repos/ada-example/tool/issues/comments", calls), calls
    assert not has_search("/reviews|pulls/comments", calls), calls


def test_notes_reviews_as_turned_off_where_the_plan_turns_them_off_and_reads_none(no_reviews):
    r, c = no_reviews.result, no_reviews.compared
    out = c.out_lines
    assert (r.status, c.status) == (0, 0), r.out + c.out
    assert has_match("No differences", out), c.out
    note = "  reviews are turned off: the event file plans no review as a comment"
    assert note in out, c.out
    assert not has_search("predates reviews", out), c.out
    assert has_match("  reviews as comments +0", out), c.out
    assert has_match("  comments +4", out), c.out
    calls = no_reviews.target.calls()
    assert not has_search("/reviews", calls), calls


def test_compares_an_event_file_whose_header_was_written_before_the_switches_as_before(reviewed):
    r = reviewed.compared_before_switches
    out = r.out_lines
    assert r.status == 0, r.out
    assert has_match("No differences", out), r.out
    assert has_match("  reviews as comments +4", out), r.out
    assert not has_search("turned off|predates", out), r.out
