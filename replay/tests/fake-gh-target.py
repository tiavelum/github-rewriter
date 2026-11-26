"""A fake gh that plays GitHub's API for the target in $FAKE_GITHUB, as GitHub's REST pages
describe it; the FAKE_GH_* variables set up a rate limit, a lost answer, a lag and other cases.

DENY, HALF, INTERRUPT, LAG, LOSE, NOT_MERGEABLE, PRIMARY_LIMIT, RATE_LIMIT, TOO_MANY and UNSEEN
name a call "<method> <endpoint>" and act once, on the first occurrence of it that reaches them,
in that target only:

FAKE_GH_API         the source's API folder: it answers a GET of another repository from it, and
                    takes from it the ids of other repositories' issues for the sub-issue calls
FAKE_GH_DEFAULT     the default branch of the target that a POST creates; main where unset
FAKE_GH_DENY        a call it answers 403 without a rate limit, doing nothing
FAKE_GH_HALF        an upload that leaves an empty asset in the state starter and answers 502
FAKE_GH_INTERRUPT   a call before which it sends the script that ran gh a SIGINT, as Ctrl-C does
FAKE_GH_LAG         a list whose first non-empty answer lacks its highest-numbered item and
                    every pull request
FAKE_GH_LOGIN       the login of the account, the owner of user/repos; ada-example where unset
FAKE_GH_LOSE        a call it does and then answers 502, as when the answer is lost
FAKE_GH_NOT_MERGEABLE  a merge it answers 405, doing nothing, as while GitHub computes whether
                    the pull request merges
FAKE_GH_NO_SCOPE    where set, a call of user/... answers 404, as to a token without the scope
FAKE_GH_PRIMARY_LIMIT  a call it answers 403 with x-ratelimit-remaining 0 and a reset a second
                    later, doing nothing
FAKE_GH_RATE_LIMIT  a call it answers 403 with Retry-After: 1, doing nothing
FAKE_GH_SKIP        the number an issue someone else creates takes, just before the next item
FAKE_GH_TOO_MANY    a call it answers 429 with Retry-After: 1, doing nothing; a 429 without it,
                    which run-replay.py waits a minute for, runs in no test
FAKE_GH_UNSEEN      a call it answers 422, doing nothing, as when GitHub does not see a branch
                    pushed just before

The files and folders of $FAKE_GITHUB:

name                the target's owner/repo
repo.git            the target's bare repository, which its clone_url and ssh_url name
absent              while it exists, no target; a POST user/repos or orgs/<org>/repos creates it
immutable           where it exists, an upload to a published release answers 422
calls               each gh api call, as its time and "<method> <endpoint>"
refused             each call it refuses, such as a command other than gh api
rejected            each PATCH of the repository refused for a default branch the target lacks
prompt              the GIT_TERMINAL_PROMPT of the last gh config get git_protocol, or unset
items.json          the issues and pull requests, by number
comments.json       the comments, each with the number of its item
labels.json         the labels
closes.json         each closing, as the number and the state reason
settings.json       the repository's settings, such as private and delete_branch_on_merge, as
                    POST and PATCH set them
actions.json        whether Actions is on, as the last PUT actions/permissions set it
releases.json       the releases, with their assets
assets/             the content of each uploaded asset, under its id
links.json          sub-issue ids by parent, for every repository; the target's are 7000 + number
priorities          the body of each move of a sub-issue
ssh_signing_keys.json, gpg_keys.json  the account's signing keys; none where a file is missing
once-*              a marker for each call a variable above has acted on
"""

import hashlib
import json
import os
import re
import signal
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import parse_qs, unquote

root = Path(os.environ["FAKE_GITHUB"])
slug = (root / "name").read_text().strip()
repo = root / "repo.git"
request_headers, upload_data = {}, None
REASONS = {
    200: "OK",
    201: "Created",
    204: "No Content",
    403: "Forbidden",
    404: "Not Found",
    405: "Method Not Allowed",
    409: "Conflict",
    422: "Unprocessable Entity",
    429: "Too Many Requests",
    502: "Bad Gateway",
}
CLOSING = re.compile(r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?):?\s+#(\d+)\b", re.I)


def load(name, default):
    path = root / f"{name}.json"
    return json.loads(path.read_text()) if path.exists() else default


def save(name, value):
    (root / f"{name}.json").write_text(json.dumps(value, indent=1, sort_keys=True) + "\n")


def refuse(why):
    with (root / "refused").open("a") as f:
        f.write(why + "\n")
    sys.exit(f"fake gh: refused: {why}")


def once(knob, call):
    marker = root / ("once-" + knob + re.sub(r"\W", "_", call))
    if os.environ.get(knob) != call or marker.exists():
        return False
    marker.touch()
    return True


def git(*args, env=None, stdin=None):
    return subprocess.run(
        ["git", "--git-dir", str(repo), *args], capture_output=True, text=True, env=env, input=stdin
    )


def rev(ref):
    found = git("rev-parse", "-q", "--verify", f"{ref}^{{commit}}")
    return found.stdout.strip() if found.returncode == 0 else None


def invalid(text):
    return 422, {"message": "Validation Failed", "errors": [{"message": text}]}


def issue_view(it):
    view = {k: it[k] for k in ("number", "title", "body", "state", "state_reason")}
    view["id"] = 7000 + it["number"]
    view.update(
        labels=[{"name": x} for x in it["labels"]],
        assignees=[{"login": x} for x in it["assignees"]],
        html_url=f"https://github.com/{slug}/"
        f"{'pull' if it['kind'] == 'pull' else 'issues'}/{it['number']}",
    )
    if it["kind"] == "pull":
        view["pull_request"] = {"merged_at": it["merged_at"]}
    return view


def pull_view(it):
    view = {k: it[k] for k in ("number", "title", "body", "state", "draft", "merge_commit_sha")}
    view.update(
        merged=bool(it["merged_at"]),
        html_url=f"https://github.com/{slug}/pull/{it['number']}",
        head={"ref": it["head"], "sha": rev(f"refs/heads/{it['head']}")},
        base={"ref": it["base"]},
    )
    return view


def set_state(it, state, reason, closes):
    if state == it["state"]:
        return
    it["state"] = state
    if state == "closed":
        it["state_reason"] = (reason or "completed") if it["kind"] == "issue" else None
        closes.append([it["number"], it["state_reason"]])
    else:
        it["state_reason"] = "reopened" if it["kind"] == "issue" else None


def new_number(items):
    n = max(map(int, items), default=0) + 1
    if os.environ.get("FAKE_GH_SKIP") == str(n):
        items[str(n)] = {
            "number": n,
            "kind": "issue",
            "title": "Someone else's issue",
            "body": "",
            "state": "open",
            "state_reason": None,
            "labels": [],
            "assignees": [],
        }
        n += 1
    return n


def merge(it, body, items, closes):
    if it["kind"] != "pull" or it["state"] != "open":
        return 405, {"message": "Pull Request is not mergeable"}
    head, base = rev(f"refs/heads/{it['head']}"), rev(f"refs/heads/{it['base']}")
    if body.get("sha") and body["sha"] != head:
        return 409, {"message": "Head branch was modified. Review and try the merge again."}
    merged = git("merge-tree", "--write-tree", base, head)
    if merged.returncode:
        return 405, {"message": "Merge conflict"}
    tree = merged.stdout.split()[0]
    parents = ["-p", base] + (["-p", head] if body["merge_method"] == "merge" else [])
    title = body.get("commit_title") or it["title"]
    message = title + (f"\n\n{body['commit_message']}" if body.get("commit_message") else "")
    date = f"{1772900000 + it['number'] * 3600} +0000"
    env = dict(
        os.environ,
        GIT_AUTHOR_NAME="Ada Example",
        GIT_AUTHOR_EMAIL="ada@example.com",
        GIT_AUTHOR_DATE=date,
        GIT_COMMITTER_NAME="GitHub",
        GIT_COMMITTER_EMAIL="noreply@github.com",
        GIT_COMMITTER_DATE=date,
    )
    sha = git("commit-tree", tree, *parents, env=env, stdin=message).stdout.strip()
    git("update-ref", f"refs/heads/{it['base']}", sha, base)
    if load("settings", {}).get("delete_branch_on_merge"):
        git("update-ref", "-d", f"refs/heads/{it['head']}")
    it.update(state="closed", merged_at="2026-11-01T00:00:00Z", merge_commit_sha=sha)
    closes.append([it["number"], None])
    # GitHub interprets closing keywords only in a pull request into the default branch; the
    # fake closes for any base, since plan-replay.py stops at a merge into another branch, so
    # no replay merges one.
    for n in CLOSING.findall(it["body"] + "\n" + message):
        named = items.get(n)
        if named and named["kind"] == "issue":
            set_state(named, "closed", "completed", closes)
    return 200, {"sha": sha, "merged": True, "message": "Pull Request successfully merged"}


def from_files(path, q):
    name = Path(os.environ["FAKE_GH_API"]) / path.replace("/", "_")
    if request_headers.get("accept") == "application/octet-stream":
        found = name.with_name(name.name + ".bin")
        if re.fullmatch(r"repos/[^/]+/[^/]+/releases/assets/\d+", path) and found.exists():
            return 200, found.read_bytes()
        return 404, {"message": "Not Found"}
    if "page" in q:
        page = name.with_name(f"{name.name}-{q['page']}.json")
        entries = json.loads(page.read_text()) if page.exists() else []
        if path.endswith("/issues"):
            links, repo = load("links", {}), path[len("repos/") : -len("/issues")]
            for it in entries:
                it["sub_issues_summary"] = {"total": len(links.get(f"{repo}#{it['number']}", []))}
                parent = next((k for k, ids in links.items() if it.get("id") in ids), None)
                # GitHub leaves the field out of an issue that is no sub-issue.
                if parent:
                    it["parent_issue_url"] = "https://api.github.com/repos/{}/issues/{}".format(
                        *parent.split("#")
                    )
        return 200, entries
    found = name.with_name(name.name + ".json")
    return (
        (200, json.loads(found.read_text())) if found.exists() else (404, {"message": "Not Found"})
    )


def known_issues():
    found = {}
    for f in Path(os.environ.get("FAKE_GH_API", "/nonexistent")).glob("repos_*_issues-*.json"):
        owner, repo = re.fullmatch(r"repos_(.+?)_(.+)_issues-\d+\.json", f.name).groups()
        for it in json.loads(f.read_text()):
            found[(f"{owner}/{repo}", it["number"])] = it
    if not (root / "absent").exists():
        for it in load("items", {}).values():
            found[(slug, it["number"])] = issue_view(it)
    for (repo, _), it in found.items():
        it["repository_url"] = f"https://api.github.com/repos/{repo}"
    return found


def sub_issues(method, repo, n, what, body, q):
    issues = known_issues()
    by_id = {it["id"]: it for it in issues.values() if "id" in it}
    links, key = load("links", {}), f"{repo}#{n}"
    if (repo, n) not in issues:
        return 404, {"message": "Not Found"}
    children = links.setdefault(key, [])
    result = 404, {"message": "Not Found"}
    if method == "GET" and what == "parent":
        me = issues[(repo, n)].get("id")
        parent = next((k for k, ids in links.items() if me in ids), None)
        if parent:
            prepo, pn = parent.split("#")
            result = 200, issues[(prepo, int(pn))]
    elif method == "GET" and what == "sub_issues":
        per, number = int(q.get("per_page", 30)), int(q.get("page", 1))
        result = 200, [by_id[i] for i in children][(number - 1) * per : number * per]
    elif method == "POST" and what == "sub_issues":
        child = body["sub_issue_id"]
        held = next((k for k, ids in links.items() if child in ids), None)
        # GitHub's Add sub-issue: "The sub-issue must belong to the same repository owner as
        # the parent issue".
        owner = repo.split("/")[0].lower()
        if child not in by_id or held == key or (held and not body.get("replace_parent")):
            result = invalid("the issue cannot be added as a sub-issue")
        elif by_id[child]["repository_url"].split("/")[-2].lower() != owner:
            result = invalid("the sub-issue must belong to the same repository owner as the parent")
        else:
            if held:
                links[held].remove(child)
            children.append(child)
            result = 201, issues[(repo, n)]
    elif method == "PATCH" and what == "sub_issues/priority":
        child, other = body["sub_issue_id"], body.get("before_id") or body.get("after_id")
        if child not in children or other not in children or child == other:
            result = invalid("sub_issue_id, before_id or after_id is not a sub-issue")
        else:
            children.remove(child)
            children.insert(children.index(other) + ("after_id" in body), child)
            with (root / "priorities").open("a") as f:
                f.write(json.dumps(body, sort_keys=True) + "\n")
            result = 200, issues[(repo, n)]
    elif method == "DELETE" and what == "sub_issue" and body.get("sub_issue_id") in children:
        children.remove(body["sub_issue_id"])
        result = 200, issues[(repo, n)]
    save("links", links)
    return result


def create_repo(owner, body):
    if not (root / "absent").exists() or f"{owner}/{body['name']}" != slug:
        return invalid("name already exists on this account")
    (root / "absent").unlink()
    default = os.environ.get("FAKE_GH_DEFAULT", "main")
    save("settings", {"private": bool(body.get("private")), "default_branch": default})
    return 201, {
        "full_name": slug,
        "html_url": f"https://github.com/{slug}",
        "default_branch": default,
        "private": bool(body.get("private")),
    }


def release_view(r):
    return {k: v for k, v in r.items() if k != "latest"}


def create_release(body, releases):
    tag, draft, prerelease = (
        body.get("tag_name"),
        bool(body.get("draft")),
        bool(body.get("prerelease")),
    )
    latest = body.get("make_latest", "true")
    if not tag or latest not in ("true", "false", "legacy"):
        return invalid("tag_name is missing or make_latest is not true, false or legacy")
    if not draft and any(r["tag_name"] == tag and not r["draft"] for r in releases):
        return 422, {
            "message": "Validation Failed",
            "errors": [{"resource": "Release", "code": "already_exists", "field": "tag_name"}],
        }
    commitish = body.get("target_commitish") or load("settings", {}).get("default_branch", "main")
    # GitHub creates the tag of a published release that lacks one, and a
    # draft's only once it is published.
    if not draft and not rev(f"refs/tags/{tag}"):
        if not rev(commitish):
            return invalid("target_commitish is not a branch or commit")
        git("update-ref", f"refs/tags/{tag}", rev(commitish))
    made_latest = latest == "true" and not draft and not prerelease
    if made_latest:
        for r in releases:
            r["latest"] = False
    rid = max((r["id"] for r in releases), default=0) + 1
    releases.append(
        {
            "id": rid,
            "tag_name": tag,
            "target_commitish": commitish,
            "name": body.get("name"),
            "body": body.get("body"),
            "draft": draft,
            "prerelease": prerelease,
            "latest": made_latest,
            "assets": [],
            "html_url": f"https://github.com/{slug}/releases/tag/{tag}",
            "upload_url": f"https://uploads.github.com/repos/{slug}/releases/{rid}/assets{{?name,label}}",
        }
    )
    return 201, release_view(releases[-1])


def update_release(release, body, releases):
    latest = body.get("make_latest", "true")
    if latest not in ("true", "false", "legacy"):
        return invalid("make_latest is not true, false or legacy")
    tag = body.get("tag_name", release["tag_name"])
    publish = release["draft"] and body.get("draft") is False
    if publish and any(r["tag_name"] == tag and not r["draft"] for r in releases):
        return 422, {
            "message": "Validation Failed",
            "errors": [{"resource": "Release", "code": "already_exists", "field": "tag_name"}],
        }
    release.update(
        {k: body[k] for k in ("tag_name", "name", "body", "draft", "prerelease") if k in body}
    )
    if publish and not rev(f"refs/tags/{tag}"):
        git("update-ref", f"refs/tags/{tag}", rev(release["target_commitish"]))
    if publish and latest == "true" and not release["prerelease"]:
        for r in releases:
            r["latest"] = r is release
    return 200, release_view(release)


def upload_asset(path, q, call):
    releases = load("releases", [])
    up = re.fullmatch(
        r"https://uploads\.github\.com/repos/([^/]+/[^/]+)/releases/(\d+)/assets", path
    )
    release = next((r for r in releases if up and r["id"] == int(up[2])), None)
    if (root / "absent").exists() or not up or up[1] != slug or release is None:
        return 404, {"message": "Not Found"}
    if upload_data is None or not request_headers.get("content-type") or not q.get("name"):
        return invalid("an upload needs the name, a Content-Type and the asset's data")
    if (root / "immutable").exists() and not release["draft"]:
        # The message reports of immutable releases quote, since GitHub's pages name none.
        return 422, {"message": "Cannot upload assets to an immutable release."}
    if any(a["name"] == q["name"] for a in release.get("assets", [])):
        return 422, {
            "message": "Validation Failed",
            "errors": [{"resource": "ReleaseAsset", "code": "already_exists", "field": "name"}],
        }
    # GitHub renames some names on upload without saying to what, so the fake keeps each name
    # until a trial on GitHub (#129) shows what a renamed one becomes.
    # An empty asset in the state starter, as GitHub's page says an upstream failure may leave.
    half = once("FAKE_GH_HALF", call)
    data = b"" if half else upload_data
    # Each asset ever uploaded keeps its file, so that no id comes twice.
    (root / "assets").mkdir(exist_ok=True)
    aid = 501 + len(list((root / "assets").iterdir()))
    (root / "assets" / str(aid)).write_bytes(data)
    asset = {
        "id": aid,
        "name": q["name"],
        "label": q.get("label", ""),
        "content_type": request_headers["content-type"],
        "size": len(data),
        "state": "starter" if half else "uploaded",
        "digest": None if half else "sha256:" + hashlib.sha256(data).hexdigest(),
    }
    release.setdefault("assets", []).append(asset)
    save("releases", releases)
    return (502, {"message": "Server Error"}) if half else (201, asset)


def handle(method, endpoint, body):
    path, _, query = endpoint.partition("?")
    q = {k: v[-1] for k, v in parse_qs(query).items()}
    if method == "POST" and path.startswith("https://uploads.github.com/"):
        return upload_asset(path, q, f"{method} {endpoint}")
    login = os.environ.get("FAKE_GH_LOGIN", "ada-example")
    if method == "GET" and path == "user":
        return 200, {"login": login}
    if method == "POST" and path == "user/repos":
        return create_repo(login, body)
    if method == "POST" and re.fullmatch(r"orgs/[^/]+/repos", path):
        return create_repo(path.split("/")[1], body)
    sub = re.fullmatch(
        r"repos/([^/]+/[^/]+)/issues/(\d+)/(parent|sub_issues|sub_issues/priority|sub_issue)", path
    )
    if sub:
        return sub_issues(method, sub[1], int(sub[2]), sub[3], body, q)
    if method == "GET" and path in ("user/ssh_signing_keys", "user/gpg_keys"):
        per, number = int(q.get("per_page", 30)), int(q.get("page", 1))
        return 200, load(path[len("user/") :], [])[(number - 1) * per : number * per]
    prefix = f"repos/{slug}"
    if (root / "absent").exists() and (path == prefix or path.startswith(prefix + "/")):
        return 404, {"message": "Not Found"}
    if path != prefix and not path.startswith(prefix + "/"):
        if method == "GET" and path.startswith("repos/") and os.environ.get("FAKE_GH_API"):
            return from_files(path, q)
        return 404, {"message": "Not Found"}
    parts = [unquote(p) for p in path[len(prefix) :].split("/") if p]
    items, comments = load("items", {}), load("comments", [])
    labels, closes = load("labels", []), load("closes", [])
    names = [x["name"] for x in labels]
    route = (method, *[p if not p.isdigit() else "N" for p in parts])

    def page(entries):
        per, number = int(q.get("per_page", 30)), int(q.get("page", 1))
        return 200, entries[(number - 1) * per : number * per]

    def item(kind=None):
        it = items.get(parts[1])
        return it if it and kind in (None, it["kind"]) else None

    result = 404, {"message": "Not Found"}
    if route == ("GET",):
        result = (
            200,
            {
                "full_name": slug,
                "default_branch": "main",
                "clone_url": str(repo),
                "ssh_url": str(repo),
                "html_url": f"https://github.com/{slug}",
                "permissions": {"admin": True, "push": True},
                **load("settings", {}),
            },
        )
    elif (
        route == ("PATCH",)
        and "default_branch" in body
        and not rev(f"refs/heads/{body['default_branch']}")
    ):
        with (root / "rejected").open("a") as f:
            f.write(f"{method} {endpoint}: no branch {body['default_branch']}\n")
        result = invalid("the default branch must exist")
    elif route == ("PATCH",):
        save("settings", {**load("settings", {}), **body})
        result = 200, {"full_name": slug, **load("settings", {})}
    elif route == ("PUT", "actions", "permissions"):
        save("actions", {"enabled": body["enabled"]})
        result = 204, None
    elif route == ("GET", "labels"):
        result = page(labels)
    elif route == ("GET", "releases"):
        result = page([release_view(r) for r in load("releases", [])])
    elif route == ("POST", "releases"):
        releases = load("releases", [])
        result = create_release(body, releases)
        save("releases", releases)
    elif route == ("GET", "releases", "latest"):
        latest = next((r for r in load("releases", []) if r.get("latest")), None)
        result = (200, release_view(latest)) if latest else (404, {"message": "Not Found"})
    elif route == ("PATCH", "releases", "N"):
        releases = load("releases", [])
        release = next((r for r in releases if r["id"] == int(parts[1])), None)
        if release:
            result = update_release(release, body, releases)
            save("releases", releases)
    elif route == ("GET", "releases", "N", "assets"):
        release = next((r for r in load("releases", []) if r["id"] == int(parts[1])), None)
        result = page(release.get("assets", [])) if release else (404, {"message": "Not Found"})
    elif route == ("DELETE", "releases", "assets", "N"):
        releases = load("releases", [])
        for r in releases:
            kept = [a for a in r.get("assets", []) if a["id"] != int(parts[2])]
            if len(kept) < len(r.get("assets", [])):
                r["assets"] = kept
                result = 204, None
        save("releases", releases)
    elif route == ("POST", "labels"):
        if body["name"] in names:
            result = (
                422,
                {
                    "message": "Validation Failed",
                    "errors": [{"resource": "Label", "code": "already_exists", "field": "name"}],
                },
            )
        else:
            labels.append({k: body.get(k) for k in ("name", "color", "description")})
            result = 201, labels[-1]
    elif route[:2] in (("PATCH", "labels"), ("DELETE", "labels")) and parts[1] in names:
        label = labels[names.index(parts[1])]
        if method == "DELETE":
            labels.remove(label)
            result = 204, None
        else:
            label.update({k: body[k] for k in ("color", "description") if k in body})
            result = 200, label
    elif route == ("GET", "issues"):
        wanted = q.get("state", "open")
        found = [issue_view(it) for it in items.values() if wanted in ("all", it["state"])]
        result = page(
            sorted(found, key=lambda v: v["number"], reverse=q.get("direction", "desc") == "desc")
        )
    elif route in (("POST", "issues"), ("POST", "pulls")):
        # GitHub's pulls endpoints take no labels or assignees; the issues endpoints set them.
        if route[1] == "pulls":
            body = {k: v for k, v in body.items() if k not in ("labels", "assignees")}
        if any(x not in names for x in body.get("labels", [])):
            result = invalid("label does not exist")
        elif route[1] == "pulls" and not (
            rev(f"refs/heads/{body['head']}") and rev(f"refs/heads/{body['base']}")
        ):
            result = invalid("head or base is not a branch")
        elif (
            route[1] == "pulls"
            and git("rev-list", "--count", f"{body['base']}..{body['head']}").stdout.strip() == "0"
        ):
            result = invalid(f"No commits between {body['base']} and {body['head']}")
        else:
            n = new_number(items)
            it = {
                "number": n,
                "title": body["title"],
                "body": body.get("body") or "",
                "state": "open",
                "state_reason": None,
                "labels": body.get("labels", []),
                "assignees": body.get("assignees", []),
            }
            if route[1] == "pulls":
                it.update(
                    kind="pull",
                    head=body["head"],
                    base=body["base"],
                    draft=body.get("draft", False),
                    merged_at=None,
                    merge_commit_sha=None,
                )
                git("update-ref", f"refs/pull/{n}/head", rev(f"refs/heads/{body['head']}"))
            else:
                it["kind"] = "issue"
            items[str(n)] = it
            result = 201, (pull_view(it) if it["kind"] == "pull" else issue_view(it))
    elif route == ("GET", "issues", "N") and item():
        result = 200, issue_view(item())
    elif route == ("GET", "pulls", "N") and item("pull"):
        result = 200, pull_view(item("pull"))
    elif route in (("PATCH", "issues", "N"), ("PATCH", "pulls", "N")) and item(
        None if parts[0] == "issues" else "pull"
    ):
        it = item()
        if parts[0] == "pulls":
            body = {k: v for k, v in body.items() if k not in ("labels", "assignees")}
        if any(x not in names for x in body.get("labels", [])):
            result = invalid("label does not exist")
        else:
            it.update({k: body[k] for k in ("title", "body", "labels", "assignees") if k in body})
            if "state" in body:
                set_state(it, body["state"], body.get("state_reason"), closes)
            result = 200, (issue_view(it) if parts[0] == "issues" else pull_view(it))
    elif route == ("GET", "issues", "comments"):
        result = page(
            [
                {**c, "issue_url": f"https://api.github.com/{prefix}/issues/{c['number']}"}
                for c in comments
            ]
        )
    elif route == ("GET", "issues", "N", "comments") and item():
        result = page([c for c in comments if c["number"] == int(parts[1])])
    elif route == ("POST", "issues", "N", "comments") and item():
        comments.append({"id": 1000 + len(comments), "number": int(parts[1]), "body": body["body"]})
        result = 201, comments[-1]
    elif route == ("PUT", "pulls", "N", "merge") and item():
        result = merge(item(), body, items, closes)
    save("items", items)
    save("comments", comments)
    save("labels", labels)
    save("closes", closes)
    return result


args = sys.argv[1:]
if args == ["config", "get", "git_protocol"]:
    (root / "prompt").write_text(os.environ.get("GIT_TERMINAL_PROMPT", "unset"))
    print("https")
    sys.exit(0)
if args[:1] != ["api"]:
    refuse(" ".join(args))
method, endpoint, include, has_input, rest = "GET", None, False, False, args[1:]
while rest:
    arg = rest.pop(0)
    if arg in ("-i", "--include"):
        include = True
    elif arg in ("-X", "--method") and rest:
        method = rest.pop(0)
    elif arg in ("-H", "--header") and rest:
        key, _, value = rest.pop(0).partition(":")
        request_headers[key.strip().lower()] = value.strip()
    elif arg == "--input" and rest[:1] == ["-"]:
        has_input = bool(rest.pop(0))
    elif arg == "--input" and rest:
        upload_data = Path(rest.pop(0)).read_bytes()
    elif arg.startswith("-") or endpoint:
        refuse(f"argument {arg}")
    else:
        endpoint = arg
if not endpoint:
    refuse("a call without an endpoint")
body = json.loads(sys.stdin.read()) if has_input else {}
call = f"{method} {endpoint}"
with (root / "calls").open("a") as f:
    f.write(f"{time.time():.3f} {call}\n")
headers = []
if once("FAKE_GH_RATE_LIMIT", call):
    status, data = 403, {"message": "You have exceeded a secondary rate limit."}
    headers = [("Retry-After", "1")]
elif once("FAKE_GH_PRIMARY_LIMIT", call):
    status, data = 403, {"message": "API rate limit exceeded for user ID 1."}
    headers = [("x-ratelimit-remaining", "0"), ("x-ratelimit-reset", str(int(time.time()) + 1))]
elif once("FAKE_GH_TOO_MANY", call):
    status, data = 429, {"message": "Too many requests"}
    headers = [("Retry-After", "1")]
elif once("FAKE_GH_NOT_MERGEABLE", call):
    status, data = 405, {"message": "Pull Request is not mergeable"}
elif once("FAKE_GH_UNSEEN", call):
    status, data = invalid("head is not a branch yet")
elif once("FAKE_GH_DENY", call):
    status, data = 403, {"message": "Resource not accessible by personal access token"}
# GitHub answers 404 with these headers to a token without the scope.
elif endpoint.startswith("user/") and os.environ.get("FAKE_GH_NO_SCOPE"):
    status, data = 404, {"message": "Not Found"}
    kind = endpoint.split("?")[0].split("/")[1][:-1]
    headers = [
        ("X-OAuth-Scopes", "repo, read:org"),
        ("X-Accepted-OAuth-Scopes", f"admin:{kind}, read:{kind}, write:{kind}"),
    ]
else:
    if once("FAKE_GH_INTERRUPT", call):
        # The suite's gh execs this script, so its parent is the script that ran gh.
        os.kill(os.getppid(), signal.SIGINT)
    status, data = handle(method, endpoint, body)
    # GitHub's list of issues lags behind an item just created.
    if status == 200 and isinstance(data, list) and data and once("FAKE_GH_LAG", call):
        top = max(x["number"] for x in data)
        data = [d for d in data if d["number"] != top and "pull_request" not in d]
    if once("FAKE_GH_LOSE", call):
        status, data = 502, {"message": "Server Error"}
kind = "application/octet-stream" if isinstance(data, bytes) else "application/json; charset=utf-8"
lines = [("Content-Type", kind), *headers]
if include:
    sys.stdout.write(
        f"HTTP/1.1 {status} {REASONS[status]}\n"
        + "".join(f"{k}: {v}\r\n" for k, v in lines)
        + "\r\n"
    )
if isinstance(data, bytes):
    sys.stdout.flush()
    sys.stdout.buffer.write(data)
elif data is not None:
    sys.stdout.write(json.dumps(data))
if status >= 400:
    sys.exit(f"gh: {data.get('message', '')} (HTTP {status})")
