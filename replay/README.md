# replay

How to plan the replay of a GitHub repository into a new, empty one with the scripts of this folder, for the owner of both: every commit, issue, pull request, comment and label of the source, so that the target gets them under the same numbers, with mapped identities and typed titles.

Planning reads the source and writes the replay as an event file; it changes nothing on GitHub. Each script takes its inputs as arguments; run without arguments, it prints its usage.

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

It prints every title it changed, with `guessed` where it guessed the type, then the totals and the event file:

```
Changed titles: 1
  c1e8a97           Set up the repository: README, license, ignore list and project instructions  ->  feat: set up the repository: README, license, ignore list and project instructions
Totals:
  items                        11
  issues                       10
  pull requests                 1
  comments                     10
  labels                       13
  commits                       4
  squash merges                 1
  events                       38
  guessed types                 0
  events out of time order      0
/root/vc-backup/github-rewriter-2026-11-15-213525.jsonl
```

Check every changed title, the guessed ones above all. To set a type yourself, write it into a file, one line per pull request number or commit hash of at least 7 characters, and plan again into a new event file:

```sh
printf '%s\n' 'c1e8a97 chore' >~/replay-types
python3 replay/plan-replay.py --types ~/replay-types "$mirror" tiavelum/github-rewriter ~/rewrite-mailmap "${mirror%.git}-typed.jsonl"
```

```
Changed titles: 1
  c1e8a97           Set up the repository: README, license, ignore list and project instructions  ->  chore: set up the repository: README, license, ignore list and project instructions
Totals:
  items                        11
  issues                       10
  pull requests                 1
  comments                     10
  labels                       13
  commits                       4
  squash merges                 1
  events                       38
  guessed types                 0
  events out of time order      0
/root/vc-backup/github-rewriter-2026-11-15-213525-typed.jsonl
```

`plan-replay.py` stops, and writes no event file, when a merged pull request was merged into a branch other than the default branch, when the mirror lacks a pull request's head, or when the number order and the order of the default branch cannot both hold, as when a pull request's branch starts on a commit that only a later item brings.

## How a title gets its type

The first line of each commit message and each pull request title takes the form `<type>: <summary>`, with one of the types `feat`, `fix`, `docs`, `chore`, `refactor`, `test`, `build`, `ci` and `revert`. A title that starts with one of them and a colon keeps it, in lowercase. Every other title gets the first type of this list that applies:

1. The type the override file sets for the commit's hash or the pull request's number.
2. For a pull request, its squash commit and its branch's commits: the prefix of its head branch, such as `fix/` in `fix/12-broken-links`, where the prefix is a type or one of `feature/` for `feat`, `bugfix/` and `hotfix/` for `fix`, and `doc/` for `docs`; else the type the pull request's own title carries.
3. A guess from the files the commit or the whole pull request changes: `docs` where they are all Markdown files, `ci` where they all lie in `.github/workflows/`, `test` where they are all test files, and `feat` for anything else. A test file lies outside `.github` and in a `test`, `tests` or `spec` folder, or its name starts with `test` or `tests` and a `-`, `_` or `.`, or ends in `-test`, `_test`, `.test` or `_spec` before its extension.

The first word of the summary is lowercased where it is an uppercase letter followed only by lowercase letters, so `Add the readme` becomes `docs: add the readme`, while `README` and `POSIX` keep their case. Bodies stay as they are.

## How pull requests are merged

Every merged pull request is replayed as a squash merge, so the default branch of the target is linear:

- One that the source merged with a squash gets the typed first line and the body of the source's squash commit.
- One that the source merged with a merge commit gets the typed pull request title with ` (#N)` as its first line, and as its body the first paragraph of the description that is not a heading or HTML, followed by `{pr_url}`, which stands for the URL of the target's pull request.

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
| `merge-pull` | Squash-merge pull request `number` | `number`, `method` (`squash`), `source_method` (`squash` or `merge`), `source_commit`, `tree`, `original_title`, `commit_title`, `commit_message`, `type`, `type_from` |
| `close-item` | Close item `number` | `number`, `state_reason` |

Each commit in `commits` holds `sha`, `tree`, `parents`, `message`, `original_title`, `type`, `type_from` and `author` and `committer`, each with its mapped `name` and `email` and its original `date`. `parents` are source hashes; a commit pushed directly to the default branch keeps only its first parent. `type_from` says where the type came from: `present`, `override`, `branch` or `guess`.

Events follow the original times, with these constraints: items are created strictly in number order; a branch is pushed before its pull request is created and after the commit it starts on; the default branch gets its commits in their original order. Where a constraint moves an event before an earlier one, the totals count it under events out of time order. Direct commits with no other event between them form one push. A number that the source lacks gets a placeholder issue, closed as not planned.

## Known limits

- Review comments, reviews, reactions, milestones and projects are not read.
- An item is replayed in its final state: one reopened and closed again is closed once, with its labels and assignees as they are now.
- A pull request without commits of its own, or one whose base is not the default branch, is planned with a warning, since GitHub may refuse to create it.

## Files

| File | Step |
|---|---|
| `plan-replay.py` | Reads the source from a mirror and from GitHub and writes the event file |
| `test-replay.sh` | Tests the scripts of this folder against a source built in a temporary folder, without contacting GitHub |
