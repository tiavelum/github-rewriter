# replay

How to replay a GitHub repository into a new, empty one with the scripts of this folder, for the owner of both: every commit, issue, pull request, comment and label of the source, so that the target gets them under the same numbers, with mapped identities and typed titles.

Planning reads the source and writes the replay as an event file; it changes nothing on GitHub. Running applies the event file to the target, after you confirm it, and can stop and resume. Each script takes its inputs as arguments; run without arguments, it prints its usage.

## Planning a replay

Requires Python 3.10 or later, git, and the GitHub CLI `gh`, signed in with read access to the source.

The mailmap maps the author and committer of every commit, in the format that [rewrite/README.md](../rewrite/README.md#steps) describes. These two lines give an old address and GitHub, as the committer of changes made on github.com, the owner's identity:

```
Andreas Tiefenauer <tiavelum@gmail.com> <old@example.com>
Andreas Tiefenauer <tiavelum@gmail.com> GitHub <noreply@github.com>
```

The steps, for `tiavelum/github-rewriter` with that mailmap in `~/rewrite-mailmap`:

```sh
cd ~/vc/github-rewriter
mirror=$(rewrite/backup-mirror.sh tiavelum/github-rewriter)   # mirror in ~/vc-backup
python3 replay/plan-replay.py "$mirror" tiavelum/github-rewriter ~/rewrite-mailmap "${mirror%.git}.jsonl"
```

It prints every title it changed, with `guessed` where it guessed the type, every squash message it wrote for a pull request merged with a merge commit, then the totals and the event file. The counts are those of the repository on the day the step was run; yours differ.

```
Changed titles: 1
  c1e8a97           Set up the repository: README, license, ignore list and project instructions  ->  feat: set up the repository: README, license, ignore list and project instructions
Squash messages written for merge commits: 0
Totals:
  items                        13
  issues                       11
  pull requests                 2
  comments                     12
  labels                       13
  commits                      11
  squash merges                 1
  merge commits                 0
  events                       43
  guessed types                 0
  events out of time order      0
~/vc-backup/github-rewriter-2026-11-15-220456.jsonl
```

Check every changed title, the guessed ones above all, and every squash message. To set a type yourself, write it into a file, one line per pull request number or commit hash of at least 7 characters, and plan again into a new event file:

```sh
printf '%s\n' 'c1e8a97 chore' >~/replay-types
python3 replay/plan-replay.py --types ~/replay-types "$mirror" tiavelum/github-rewriter ~/rewrite-mailmap "${mirror%.git}-typed.jsonl"
```

```
Changed titles: 1
  c1e8a97           Set up the repository: README, license, ignore list and project instructions  ->  chore: set up the repository: README, license, ignore list and project instructions
Squash messages written for merge commits: 0
Totals:
  items                        13
  issues                       11
  pull requests                 2
  comments                     12
  labels                       13
  commits                      11
  squash merges                 1
  merge commits                 0
  events                       43
  guessed types                 0
  events out of time order      0
~/vc-backup/github-rewriter-2026-11-15-220456-typed.jsonl
```

In the same file, a line of a pull request number, `summary` and a text sets the summary of the squash message that [How pull requests are merged](#how-pull-requests-are-merged) describes, such as `10 summary Signs commits and tags with the SSH key.`

Two options, given before the mirror, turn off what the replay changes; without them, every title gets a type and every merge commit becomes a squash merge:

- `--no-types` keeps every title as it is, instead of giving it a type as [How a title gets its type](#how-a-title-gets-its-type) describes.
- `--keep-merges` keeps the merge commits, as [How pull requests are merged](#how-pull-requests-are-merged) describes.

`plan-replay.py` stops, and writes no event file, when a merged pull request was merged into a branch other than the default branch, when the mirror lacks a pull request's head, when a pull request's branch merges a commit that is neither on the first-parent line of the default branch nor on the branch of a pull request, or when the number order and the order of the default branch cannot both hold, as when a pull request's branch starts on a commit that only a later item brings.

## Running a replay

Requires Python 3.10 or later, git 2.31 or later, and `gh`, signed in with the right to push to the target, to create its issues, pull requests, comments and labels, and to merge its pull requests; `git push` reaches the target over the protocol `gh config get git_protocol` names.

First create the target on GitHub, empty: without a README, license or ignore file, with the default branch named as the source's, and with no ruleset or branch protection on it yet, since the direct commits are pushed to it. Then, with the mirror and the event file of [Planning a replay](#planning-a-replay):

```sh
python3 replay/run-replay.py "${mirror%.git}-typed.jsonl" "$mirror" tiavelum/github-rewriter-trial
```

It checks that the mirror holds every tree of the event file and that the target is empty, prints what it will do in totals, with the labels the target already has, and asks for the target's `owner/repo`; anything else stops it without a write. It then prints one line per event, and at the end what it did and the target's URL. This is the output of a run of the test's source, `ada-example/tool`, into a fake target, as `test-replay.sh` makes it; the answer typed at the prompt does not show, since the test pipes it in:

```
Replay ada-example/tool into ada-example/tool-new: 23 events
  labels                        2
  commits                      10
  issues                        3
  pull requests                 3
  comments                      4
  merges                        2
  closes                        3
  labels the target has and the replay updates: bug
  labels the target has and the replay deletes: enhancement
Type ada-example/tool-new to confirm:   label enhancement deleted
 1/23  create-label  bug updated
 2/23  create-label  docs created
 3/23  push-commits  1 commit to main, now at 16679a1
 4/23  create-issue  #1 issue
 5/23  push-branch   #2 branch feat/2-thing, 2 commits, at 6920445
 6/23  create-pull   #2 pull request feat/2-thing into main
      rate limited on POST repos/ada-example/tool-new/issues/1/comments; waiting 1 s before retry 1 of 5
 7/23  add-comment   #1 comment
 8/23  merge-pull    #2 squash-merged into main as c0c4c38
 9/23  close-item    #1 already closed as completed
10/23  push-branch   #3 branch fix/3-parser, 1 commit, at 8ad4614
11/23  create-pull   #3 pull request fix/3-parser into main
12/23  create-issue  #4 issue
13/23  add-comment   #3 comment
14/23  merge-pull    #3 squash-merged into main as ab5d006
15/23  push-commits  3 commits to main, now at bac0273
16/23  close-item    #4 closed as not_planned, reopened from completed
17/23  add-comment   #4 comment
18/23  push-commits  1 commit to main, now at ad8a46b
19/23  push-branch   #5 branch docs/5-notes, 2 commits, at e9844ce
20/23  create-pull   #5 pull request docs/5-notes into main
21/23  create-issue  #6 issue
22/23  close-item    #5 closed
23/23  add-comment   #6 comment
Done in this run:
  create-label                  2
  push-commits                  3
  push-branch                   3
  create-issue                  3
  create-pull                   3
  add-comment                   4
  merge-pull                    2
  close-item                    3
https://github.com/ada-example/tool-new
```

Three options, given before the event file:

- `--with-times` appends the original creation time to each body and comment, as `_Originally created 2026-03-01 11:00 UTC._` after a blank line; off by default.
- `--state <file>` keeps the state in that file instead of the one next to the event file.
- `--pace <seconds>` sets the least time between two writes; the default, 1, follows GitHub's advice to [pause at least one second between mutative requests](https://docs.github.com/en/rest/using-the-rest-api/best-practices-for-using-the-rest-api#pause-between-mutative-requests), and the test uses less.

On a rate limit, an answer 403 or 429, the run waits as [GitHub's guidance on exceeding a rate limit](https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api#exceeding-the-rate-limit) says: the seconds of `retry-after`, else up to the time of `x-ratelimit-reset` where `x-ratelimit-remaining` is 0, else a minute, doubled at each retry; it retries the same call at most 5 times and then stops. GitHub allows [no more than 500 content-generating requests per hour](https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api#about-secondary-rate-limits), and a replay makes about one per label, item, comment, merge and close, so a large one may stop on the limit; run it again after an hour.

## Stopping and resuming

Ctrl-C stops the run after the event in progress; a second Ctrl-C stops it at once. A run also stops, with a message, at the first of these:

- An issue or pull request gets a number other than the planned one, as when someone else creates an issue in the target during the run; nothing more is done.
- After a merge, the tree of the default branch differs from the source's tree after that merge.
- GitHub refuses a call, answers a write with nothing, or is still rate limited after 5 retries.

To resume, find and remove the cause, and run the same command again. It checks the target against the state file: its highest number and the commit its default branch is at must be those the state file records. The event that was in progress may account for one difference, and it checks what of it is done: an item with its planned number and title, a comment that is already the last of its item, a merged pull request, a label that exists and a pushed commit are taken over, not made again. Where the target differs in another way, the run stops and names the difference. Run on a finished replay, it checks the target again.

## The state file

The state file is the event file with `.state.json` for `.jsonl`, such as `~/vc-backup/github-rewriter-2026-11-15-220456-typed.state.json`, unless `--state` names one. It is written after each event, by replacing it, so a stop at any point leaves the last finished event. It holds JSON: the SHA-256 of the event file, `source` and `target`, `done`, the number of the last finished event, `finished`, whether the target was checked after the last event, `highest`, the target's highest number, `head`, the commit the default branch is at, and the maps `numbers`, from source to target number, `hashes`, from source to target commit, `heads`, from pull request to the head of its pushed branch, and `urls`, from pull request to its URL. A state file for another event file or target stops the run.

Next to it lies the work repository, with `.work.git` for `.state.json`: a bare repository that borrows the mirror's objects and holds the recreated commits until they are pushed. Keep both until the replay is done and checked; then delete them.

## What the target ends with

- **Labels**: the source's, with their colours and descriptions. Before the first event, the run deletes each label the target has and the source lacks, such as GitHub's defaults, and updates the others.
- **Commits**: each commit of the default branch and of the pull requests' branches, recreated with `git commit-tree` from its planned tree, typed message and mapped author and committer with their original dates, on the recreated parents, so each gets a new hash. The recreated commits are never signed: `git commit-tree` does not read `commit.gpgSign`, so a resumed run builds each commit with the same hash again.
- **Merges**: each merged pull request is merged through GitHub, with the planned method, title and message and `{pr_url}` replaced by its URL, so GitHub is the committer of the squash commit, the account that runs the replay its author, and the time of the replay its date. After each merge, the tree of the default branch equals the source's.
- **Items**: each issue and pull request under its number, with its title, body, labels, assignees, draft state, and the state and state reason it ends in. Each is created open, then merged or closed. A merge closes the issues its pull request names with a closing keyword, as on GitHub; a later close leaves such an issue as it is where the state reason matches, and otherwise reopens and closes it with the planned one, since GitHub [ignores a state reason unless the state changes](https://docs.github.com/en/rest/issues/issues#update-an-issue). After the last event, the run reopens an item the source has open that a merge closed, and stops where any other item, or the labels, differ from the plan.
- **Comments**: each comment, in the planned order, after its item.
- **Hashes**: in every title, body, comment and commit message, a hash of 7 to 40 lowercase hexadecimal characters that is the prefix of exactly one source commit already recreated becomes the prefix of the same length of the new hash.
- **Branches**: each pull request's branch stays, also after its merge, unless the target deletes head branches on merge.

The target does not get the original times and authors: every item, comment and merge is by the account that runs the replay, at the time of the replay; `--with-times` keeps the creation time in the text. Nor does it get reactions, reviews, review comments, milestones or projects, which the plan does not read, or an item's history between its creation and its final state. References to items, in this repository or another, and `@` mentions act again: GitHub adds them to the timeline of the item named, and notifies the person mentioned.

## Taking over the source's name

Once the replay is checked, give it the source's name, so that links to the source's items reach the replayed ones under the same numbers. Archive the source under a new name first, since its issues, pull requests and comments exist nowhere else, then rename the replay; for `tiavelum/mac-config` replayed into `tiavelum/mac-config-new`:

```sh
gh api -X PATCH repos/tiavelum/mac-config -f name=mac-config-archive
gh api -X PATCH repos/tiavelum/mac-config-archive -F archived=true
gh api -X PATCH repos/tiavelum/mac-config-new -f name=mac-config
```

[GitHub redirects a renamed repository](https://docs.github.com/en/repositories/creating-and-managing-repositories/renaming-a-repository) until another repository takes its old name, so the third command ends the redirect from `mac-config` to the archive. Then replace each local clone of the source with a fresh clone of the replay at the same path, since their histories differ.

## How a title gets its type

The first line of each commit message and each pull request title takes the form `<type>: <summary>`, with one of the types `feat`, `fix`, `docs`, `chore`, `refactor`, `test`, `build`, `ci` and `revert`. A title that starts with one of them and a colon keeps it, in lowercase. Every other title gets the first type of this list that applies:

1. The type the override file sets for the commit's hash or the pull request's number.
2. For a pull request, its squash commit and its branch's commits: the prefix of its head branch, such as `fix/` in `fix/12-broken-links`, where the prefix is a type or one of `feature/` for `feat`, `bugfix/` and `hotfix/` for `fix`, and `doc/` for `docs`; else the type the pull request's own title carries.
3. A guess from the files the commit or the whole pull request changes: `docs` where they are all Markdown files, `ci` where they all lie in `.github/workflows/`, `test` where they are all test files, and `feat` for anything else. A test file lies outside `.github` and in a `test`, `tests` or `spec` folder, or its name starts with `test` or `tests` and a `-`, `_` or `.`, or ends in `-test`, `_test`, `.test` (or the plural) or `_spec` before its extension.

The first word of the summary is lowercased where it is an uppercase letter followed only by lowercase letters, so `Add the readme` becomes `docs: add the readme`, while `README` and `POSIX` keep their case. Bodies stay as they are.

## How pull requests are merged

By default, every merged pull request is replayed as a squash merge, so the default branch of the target is linear:

- One that the source merged with a squash gets the typed first line and the body of the source's squash commit.
- One that the source merged with a merge commit gets the typed pull request title with ` (#N)` as its first line, and as its body a summary of the description followed by `{pr_url}`, which stands for the URL of the target's pull request. The summary is the first paragraph that is not a heading, HTML, closing keywords alone such as `Closes #5`, or a lead-in that ends in a colon, cut to its first sentence where it is longer than 300 characters; a `summary` line of the override file replaces it.

With `--keep-merges`, a pull request that the source merged with a merge commit is merged with a merge commit instead, with that commit's message unchanged; the tree of the source's merge commit is the expected tree either way.

A pull request that the source closed unmerged gets its branch, is created, and is closed.

## The event file

The event file holds JSON Lines: the header on the first line, then one event per line in the order they apply. Each event holds what it needs besides the git objects of the mirror: `seq`, counting from 1, `kind`, `time`, the original time in UTC, which labels lack, and the fields of its kind.

| `kind` | Means | Fields |
|---|---|---|
| `header` | The first line, no event | `format` (1), `source`, `default_branch`, and `source_commits`: the hash of every source commit the replay recreates, so that later text can be pointed at the new hashes |
| `create-label` | Create a label | `name`, `color`, `description` |
| `push-commits` | Push commits directly to the default branch | `branch`, `commits` |
| `push-branch` | Push the branch of pull request `number` | `number`, `branch`, `source_branch`, `base_commit`, the source commit it starts on, `commits` |
| `create-issue` | Create issue `number` | `number`, `title`, `body`, `labels`, `assignees`, `state`, `state_reason`, `author`, `created_at`; `placeholder` where it keeps the number of an item the source no longer has |
| `create-pull` | Create pull request `number` | `number`, `title`, `original_title`, `type`, `type_from`, `body`, `head`, `base`, `draft`, `labels`, `assignees`, `state` (`open`, `closed` or `merged`), `author`, `created_at` |
| `add-comment` | Comment on item `number` | `number`, `body`, `author`, `created_at`, `source_id` |
| `merge-pull` | Merge pull request `number` | `number`, `method` (`squash` or `merge`), `source_method` (`squash` or `merge`), `source_commit`, `tree`, `original_title`, `commit_title`, `commit_message`, `type`, `type_from` |
| `close-item` | Close item `number` | `number`, `state_reason` |

Each commit in `commits` holds `sha`, `tree`, `parents`, `message`, `original_title`, `type`, `type_from` and `author` and `committer`, each with its mapped `name` and `email` and its original `date`. `parents` are source hashes; a commit pushed directly to the default branch keeps only its first parent. `type_from` says where the type came from: `present`, `override`, `branch` or `guess`. `type` and `type_from` are `null` where no type is given: with `--no-types`, and in a `merge-pull` of method `merge`.

Events follow the original times, with these constraints: items are created strictly in number order; a branch is pushed before its pull request is created and after the commit it starts on; the default branch gets its commits in their original order. Where a constraint moves an event before an earlier one, the totals count it under events out of time order: a pull request whose final head merges a commit that the default branch got after the pull request was opened comes after that commit, with the items numbered after it. `state` is the state the item ends in; create every item open and let `close-item` or `merge-pull` change it. Direct commits with no other event between them form one push. A number that the source lacks gets a placeholder issue, closed as not planned.

## Known limits

- Review comments, reviews, reactions, milestones and projects are not read.
- An item is replayed in its final state: one reopened and closed again is closed once, with its labels and assignees as they are now.
- A pull request without commits of its own, or one whose base is not the default branch, is planned with a warning, since GitHub may refuse to create it; the run then stops at it.
- A Ctrl-C reaches a running `git` too; the run then stops in the middle of the event, which the next run checks and finishes.

## Files

| File | Step |
|---|---|
| `plan-replay.py` | Reads the source from a mirror and from GitHub and writes the event file |
| `run-replay.py` | Applies the event file to an empty target and keeps the state file, so that a stopped run resumes |
| `test-replay.sh` | Tests the scripts of this folder against a source built in a temporary folder and fake GitHub targets, without contacting GitHub |
