# replay

How to replay a GitHub repository into a new, empty one with the scripts of this folder, for the owner of both: every commit, issue, pull request, comment and label of the source, so that the target gets them under the same numbers, with mapped identities and typed titles.

Planning reads the source and writes the replay as an event file; it changes nothing on GitHub. Running applies the event file to the target, after you confirm it, and can stop and resume. Comparing reads the source and the target and names every difference between them; it changes nothing either. `replay.py` takes these three steps in turn from one run file, with the steps around them, and is the way to run a replay; the sections after it describe the steps it takes, which you can also run alone. Each script takes its inputs as arguments; run without arguments, it prints its usage.

## Replaying with one command

`replay.py` runs a whole replay from a run file: it mirrors and plans the source, asks you once to confirm, and then creates the target, replays the source into it, compares the two and moves the sub-issue links without further questions. It ends with the commands that give the replay the source's name, which stay yours to run. It runs the scripts of the sections below as processes, so it needs what [Planning a replay](#planning-a-replay) and [Running a replay](#running-a-replay) require, the git protocol and, with `sign`, the signing key among them. Its `gh` also needs the right to create a repository for the target's owner, which for [a repository of your account](https://docs.github.com/en/rest/repos/repos#create-a-repository-for-the-authenticated-user) a classic token has with the scope `repo` and a fine-grained one with the repository permission "Administration" or "Repository creation" set to write, and which for [a repository of an organisation](https://docs.github.com/en/rest/repos/repos#create-an-organization-repository) only a member of it has. It also needs the right to change the target's settings and, where the source's issues have sub-issue links, the repository permission "Issues" set to write in the repository of each parent, which [Add sub-issue](https://docs.github.com/en/rest/issues/sub-issues#add-sub-issue) asks for. Since [GitHub adds a sub-issue only to a parent of the same repository owner](https://docs.github.com/en/rest/issues/sub-issues#add-sub-issue), `replay.py` stops before the confirmation where a parent of a source's issue, or a sub-issue from elsewhere, belongs to an owner other than the target's. GitHub refuses such a link whoever makes it, so move or remove these links in the source first, or replay with the scripts of the sections below alone, which leave links alone, and leave these links out of the first move of [Taking over the source's name](#taking-over-the-sources-name).

Write the run file first, outside any repository, since it holds the mailmap; `replay.py` stops where the run file lies in a git work tree. Its name ends in `.run.json`. For `tiavelum/github-rewriter`, in `~/github-rewriter.run.json`, with an invented identity:

```json
{
  "source": "tiavelum/github-rewriter",
  "target": "tiavelum/github-rewriter-replay-20261116-1215",
  "mailmap": [
    "Ada Example <ada@example.com> <old@example.com>",
    "Ada Example <ada@example.com> GitHub <noreply@github.com>"
  ],
  "types": [
    "c1e8a97 chore",
    "10 summary Signs commits and tags with the SSH key."
  ],
  "sign": "ada@example.com"
}
```

| Field | Holds | Default |
|---|---|---|
| `source` | The source, as `owner/repo` | Required |
| `target` | The target's temporary name: the repository name of `final_name` with `-replay-` and the day and time of the replay as `YYYYMMDD-HHMM`, under the owner of `final_name`, so that the rename at the end keeps its owner and no earlier replay has used the name | Required |
| `mailmap` | The lines of the mailmap that [Planning a replay](#planning-a-replay) describes | Required |
| `final_name` | The name the replay takes over at the end, which `run-replay.py` gets as `--final-name` | `source` |
| `types` | The lines of the file of `--types`: types and `summary` lines | None |
| `sign` | The address of `--sign` | `null`, nothing signed |
| `keep_merges` | Whether the plan has `--keep-merges` | `false` |
| `no_types` | Whether the plan has `--no-types` | `false` |
| `with_times` | Whether the run and the comparison have `--with-times` | `false` |
| `pace` | The seconds of `--pace` | `1` |
| `backup` | The folder of the mirror, the event file, the state file and the work repository | `~/vc-backup` |
| `clone_url` | The URL `backup-mirror.sh` clones the source from | `git@github.com:<source>.git` |

A field it does not know stops it, as does a value of the wrong kind. Then run it:

```sh
python3 ~/vc/github-rewriter/replay/replay.py ~/github-rewriter.run.json
```

It announces each of its eight steps as `Step <n> of 8`:

1. **mirror**: makes the mirror with `backup-mirror.sh` in `backup`.
2. **plan**: plans into the event file next to the mirror, with the mailmap and the types written into a temporary folder that it deletes afterwards, and prints every changed title and the totals, as [Planning a replay](#planning-a-replay) shows. It stops where a title would get a guessed type; give that title's commit or pull request its type in `types` and run again.
3. **create**: creates the target, private and empty, for your account or for the organisation that owns it.
4. **settings**: turns Actions off in the target, and the deletion of head branches on where the source has it on.
5. **replay**: runs `run-replay.py` with `--pace`, `--final-name`, and `--sign` and `--with-times` where the run file sets them, and gives it your confirmation with `--confirmed`. Where GitHub has named the target's default branch other than the source's, it then makes the source's the default branch, once the replay has pushed it, and before `run-replay.py` where a stopped replay pushed it already.
6. **compare**: runs `compare-replay.py`, as [Comparing the replay with its source](#comparing-the-replay-with-its-source) describes, and stops at any difference.
7. **links**: moves the sub-issue links, as [Taking over the source's name](#taking-over-the-sources-name) describes. Where an issue of the source is a sub-issue of an issue elsewhere, it links the replayed issue, moves it with `after_id` after the sub-issue just before the source's, or with `before_id` before the one after it where the source's is the first, so that it takes that one's place, and unlinks the source's; where the source's is the only one, it skips the move. Where an issue of the source has sub-issues, the replayed issue gets them in the same order: the replayed ones for those of the source, and those from elsewhere moved over with `replace_parent`, the option of [Add sub-issue](https://docs.github.com/en/rest/issues/sub-issues#add-sub-issue) that replaces a sub-issue's current parent, so that they leave the source's issue.
8. **commands**: prints what is left to you, with the commands of [Taking over the source's name](#taking-over-the-sources-name) for this replay.

Before the first step it checks that the target does not exist yet. Between the plan and the creation it reads the sub-issue links, and stops where one crosses owners; then it lists what it will do, with each repository other than the target that a link is written in, and asks for the target's `owner/repo`; anything else stops it without a write to GitHub. This is the middle and the end of its output for the test's source, `ada-example/tool`, with a sub-issue link to an invented `ada-example/plans`; the answer stands after the prompt, since the test pipes it in:

```
Replay ada-example/tool into ada-example/tool-replay-20261116-1215, to be renamed ada-example/tool:
  3. create ada-example/tool-replay-20261116-1215, private and empty
  4. turn Actions off in it and the deletion of head branches on, as the source has it
  5. run run-replay.py --pace 0 --final-name ada-example/tool, and make main the default branch where GitHub names another
  6. compare the replay with the source with compare-replay.py
  7. move sub-issue links: 4
       #1: in ada-example/plans#9, links the replay's #1 in the place of the source's and unlinks the source's (writes in ada-example/plans)
       #4: in ada-example/plans#9, links the replay's #4 in the place of the source's and unlinks the source's (writes in ada-example/plans)
       the replay's #4 gets the sub-issues of the source's: #6
       the replay's #6 gets the sub-issues of the source's: ada-example/plans#11, taken from the source's #6 with replace_parent (writes in ada-example/plans and in the source)
  8. print the commands that archive the source and rename the replay
Type ada-example/tool-replay-20261116-1215 to confirm: ada-example/tool-replay-20261116-1215
Step 3 of 8, create: create ada-example/tool-replay-20261116-1215, private and empty
  https://github.com/ada-example/tool-replay-20261116-1215
Step 4 of 8, settings: turn Actions off until the replay is checked
  Actions off
  deletion of head branches on, as the source has it
Step 5 of 8, replay: run-replay.py into ada-example/tool-replay-20261116-1215
```

```
Step 7 of 8, links: move the sub-issue links of the source's issues to the replay's
  #1 under ada-example/plans#9, in the place of the source's
  #4 under ada-example/plans#9, in the place of the source's
  #6 under the replay's #4
  ada-example/plans#11 under the replay's #6
Step 8 of 8, commands: what is left to you
1. Check what compare-replay.py cannot see in the source: its secrets, variables, webhooks, deploy keys and collaborators.
2. Archive the source under a new name, give the replay its name, Actions, settings and, where the source is not private, visibility, and delete the branches the source no longer has:

gh api -X PATCH repos/ada-example/tool -f name=tool-archive
gh api -X PATCH repos/ada-example/tool-archive -F archived=true
gh api -X PATCH repos/ada-example/tool-replay-20261116-1215 -f name=tool
gh api -X PUT repos/ada-example/tool/actions/permissions -F enabled=true
gh api -X PATCH repos/ada-example/tool -F allow_merge_commit=false -F allow_squash_merge=true -F allow_rebase_merge=false -F delete_branch_on_merge=true -f 'description=A small tool'
gh api -X DELETE repos/ada-example/tool/git/refs/heads/docs/5-notes

3. Replace each local clone of ada-example/tool with a fresh clone of the replay.
4. Delete ~/tool.progress.json, ~/vc-backup/tool-2026-11-16-033713.state.json and ~/vc-backup/tool-2026-11-16-033713.work.git.
```

The paths of the last line stand for those of a run file `~/tool.run.json` and a mirror made in `~/vc-backup`. What is left to you is what these lines say: check the source's secrets, variables, webhooks, deploy keys and collaborators, which neither script reads; run the commands of step 2 in their order, which give the replay the source's Actions setting, merge methods, deletion of head branches and description and, where the source is not private, its visibility, which the replay gets only after its rename, since it is created private; replace your clones; and delete the run's files. The commands name the archive `<repository>-archive`, and a note above them says so where a repository of that name exists already: give the archive another name in the first two then. Where `final_name` is not the source, the first command only archives the source.

Where it stops, it names the step and says how to go on. A stop before the confirmation writes nothing to GitHub, and the next run starts over with a new mirror and event file; the stopped run's stay in `backup`. After the confirmation it keeps its progress in the progress file next to the run file, `~/github-rewriter.progress.json` for the run file above: the mirror, the event file and the steps done. Once you have removed the cause of the stop, run the same command again: it asks you to confirm again, skips the creation and the settings where they are done, lets `run-replay.py` resume where [Stopping and resuming](#stopping-and-resuming) says, compares again, and moves the links that are not moved yet. Ctrl-C reaches the script that runs, so in the replay step it stops `run-replay.py` after the event in progress. A run file that changed after the confirmation stops it; undo the change to resume. Where the comparison finds a difference that you accept, take the remaining steps by hand, as the sections below describe them.

## Planning a replay

Requires Python 3.10 or later, git, and the GitHub CLI `gh`, signed in with read access to the source.

The mailmap maps the author and committer of every commit, in the format that [rewrite/README.md](../rewrite/README.md#steps) describes. These two lines give an old address and GitHub, as the committer of changes made on github.com, the owner's identity, here an invented one:

```
Ada Example <ada@example.com> <old@example.com>
Ada Example <ada@example.com> GitHub <noreply@github.com>
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

Requires Python 3.10 or later, git 2.31 or later, and `gh`, signed in with the right to push to the target, to create its issues, pull requests, comments and labels, and to merge its pull requests; `git push` reaches the target over the protocol `gh config get git_protocol` names. The run asks git for no password, so that protocol has to work without one: where git reaches GitHub over SSH, set it with:

```sh
gh config set git_protocol ssh
```

Otherwise the run stops in its first check, before any write, at `could not read Username for 'https://github.com': terminal prompts disabled`.

To sign your recreated commits with `--sign`, your git configuration needs a `user.signingkey`, with `gpg.format` `ssh` or `openpgp`, the default. For an SSH key, it needs `ssh-keygen` and, since [SSH signing is available in Git 2.34 or later](https://docs.github.com/en/authentication/managing-commit-signature-verification/about-commit-signature-verification), git 2.34 or later; a key with a passphrase has to be in the agent. GitHub [verifies a signature against a public key you have added to your account](https://docs.github.com/en/authentication/managing-commit-signature-verification/about-commit-signature-verification), so the run checks that GitHub lists the key, and stops where it does not. Add an SSH key as a signing key, here `~/.ssh/id_ed25519.pub`, with:

```sh
gh ssh-key add ~/.ssh/id_ed25519.pub --type signing
```

With a classic or OAuth token, `gh` lists [SSH signing keys only with the scope `read:ssh_signing_key`](https://docs.github.com/en/rest/users/ssh-signing-keys#list-ssh-signing-keys-for-the-authenticated-user) and [GPG keys only with `read:gpg_key`](https://docs.github.com/en/rest/users/gpg-keys#list-gpg-keys-for-the-authenticated-user); a fine-grained token needs the user permission "SSH signing keys" or "GPG keys" set to read. Where it lacks the one your key needs, the run names it and stops. Add the scope with:

```sh
gh auth refresh -s read:ssh_signing_key
```

Where you run `run-replay.py` alone, not through `replay.py`, which does this itself, first create the target on GitHub, private and empty: without a README, license or ignore file, and with no ruleset or branch protection on it yet, since the direct commits are pushed to it. Turn off Actions in it until the replay is checked, since every pushed branch and every merge would otherwise start the source's workflows; and where the source has deleted the branches of its merged pull requests, turn on the deletion of head branches, so that the replay's are deleted on merge too:

```sh
gh api -X PUT repos/tiavelum/github-rewriter-trial/actions/permissions -F enabled=false
gh api -X PATCH repos/tiavelum/github-rewriter-trial -F delete_branch_on_merge=true
```

Then, with the mirror and the event file of [Planning a replay](#planning-a-replay):

```sh
python3 replay/run-replay.py "${mirror%.git}-typed.jsonl" "$mirror" tiavelum/github-rewriter-trial
```

Where GitHub names the target's default branch other than the source's, the run goes on while the target is empty. Once it is done, make the source's the default branch, here `main`; where a resumed run stops at `the default branch of tiavelum/github-rewriter-trial is master, the source's main`, do so first and run it again:

```sh
gh api -X PATCH repos/tiavelum/github-rewriter-trial -f default_branch=main
```

It checks that the mirror holds every tree of the event file, that GitHub answers for the target under the name you gave (a renamed repository stops it), and that the target is empty, prints what it will do in totals, with the labels the target already has, and asks for the target's `owner/repo`; anything else stops it without a write. It then prints one line per event, and at the end what it did and the target's URL. This is the output of a run of the test's source, `ada-example/tool`, into a fake target, as `test-replay.sh` makes it; the answer typed at the prompt does not show, since the test pipes it in:

```
Replay ada-example/tool into ada-example/tool-replay-20261116-1215: 23 events
  labels                        2
  commits                      10
  issues                        3
  pull requests                 3
  comments                      4
  merges                        2
  closes                        3
  {pr_url} in 1 squash message: https://github.com/ada-example/tool-replay-20261116-1215/pull/<number>
  labels the target has and the replay updates: bug
  labels the target has and the replay deletes: enhancement
Type ada-example/tool-replay-20261116-1215 to confirm:   label enhancement deleted
 1/23  create-label  bug updated
 2/23  create-label  docs created
 3/23  push-commits  1 commit to main, now at 16679a1
 4/23  create-issue  #1 issue
 5/23  push-branch   #2 branch feat/2-thing, 2 commits, at 6920445
 6/23  create-pull   #2 pull request feat/2-thing into main
      rate limited on POST repos/ada-example/tool-replay-20261116-1215/issues/1/comments; waiting 1 s before retry 1 of 5
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
https://github.com/ada-example/tool-replay-20261116-1215
```

Six options, given before the event file:

- `--with-times` appends the original creation time to each body and comment, as `_Originally created 2026-03-01 11:00 UTC._` after a blank line; off by default.
- `--sign <address>` signs, with the signing key of your git configuration, each recreated commit whose mapped committer has that address, as [Running a replay](#running-a-replay) requires; the others stay unsigned, since nobody running the replay holds the key of a commit someone else committed. Off by default.
- `--final-name <owner/repo>` fills `{pr_url}` with the URL of the pull request under the name the target will carry once it takes over the source's name, such as `https://github.com/tiavelum/github-rewriter/pull/3`, instead of the target's current name; off by default.
- `--state <file>` keeps the state in that file instead of the one next to the event file.
- `--confirmed <owner/repo>` takes `<owner/repo>` as the answer to the confirmation instead of asking for it, as `replay.py` gives the answer you typed; any other value stops the run as a wrong answer does.
- `--pace <seconds>` sets the least time between two writes; the default, 1, follows GitHub's advice to [pause at least one second between mutative requests](https://docs.github.com/en/rest/using-the-rest-api/best-practices-for-using-the-rest-api#pause-between-mutative-requests), and the test uses less.

For a replay into `tiavelum/github-rewriter-trial` that takes over the source's name, signing the commits you committed under an invented address:

```sh
python3 replay/run-replay.py --sign ada@example.com --final-name tiavelum/github-rewriter "${mirror%.git}-typed.jsonl" "$mirror" tiavelum/github-rewriter-trial
```

Before the confirmation, the totals then also say how many commits it signs, with which key, and what `{pr_url}` becomes; each push says how many of its commits it signed. These are the first lines of a signed run of the test, with the path of its throwaway key replaced by `~/.ssh/id_ed25519.pub`:

```
Replay ada-example/tool into ada-example/tool-replay-20261116-1215: 23 events
  labels                        2
  commits                      10
  issues                        3
  pull requests                 3
  comments                      4
  merges                        2
  closes                        3
  commits to sign               9
  signed: the commits committed by ada@example.com, with the SSH key ~/.ssh/id_ed25519.pub (ssh-ed25519)
  {pr_url} in 1 squash message: https://github.com/ada-example/tool-replay-20261116-1215/pull/<number>
  labels the target has and the replay updates: bug
  labels the target has and the replay deletes: enhancement
Type ada-example/tool-replay-20261116-1215 to confirm:   label enhancement deleted
 1/23  create-label  bug updated
 2/23  create-label  docs created
 3/23  push-commits  1 commit to main, 1 signed, now at d1d4d85
```

With a key other than an Ed25519 SSH key, the totals add `this key does not sign a commit the same way twice: a run stopped in a push of signed commits cannot resume`, as [Stopping and resuming](#stopping-and-resuming) explains.

On a rate limit, an answer 403 or 429, the run waits as [GitHub's guidance on exceeding a rate limit](https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api#exceeding-the-rate-limit) says: the seconds of `retry-after`, else up to the time of `x-ratelimit-reset` where `x-ratelimit-remaining` is 0, else a minute, doubled at each retry; it retries the same call at most 5 times and then stops. GitHub allows [no more than 500 content-generating requests per hour](https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api#about-secondary-rate-limits), and a replay makes about one per label, item, comment, merge and close, so a large one may stop on the limit; run it again after an hour.

## Stopping and resuming

Ctrl-C stops the run after the event in progress; a second Ctrl-C stops it at once. A run also stops, with a message, at the first of these:

- An issue or pull request gets a number other than the planned one, as when someone else creates an issue in the target during the run; nothing more is done.
- After a merge, the tree of the default branch differs from the source's tree after that merge.
- GitHub refuses a call, answers a write with nothing, or is still rate limited after 5 retries.
- A commit of the push in progress, rebuilt on resuming, gets another hash than the state file records for it; the run stops before the push, so the target never gets a second history.

To resume, find and remove the cause, and run the same command again, with the same `--sign` and `--final-name`; a state file that records other ones stops the run. It checks the target against the state file: its highest number and the commit its default branch is at must be those the state file records. The event that was in progress may account for one difference, and it checks what of it is done: an item with its planned number and title, a comment that is already the last of its item, a merged pull request, a label that exists and a pushed commit are taken over, not made again. Where the target differs in another way, the run stops and names the difference. Run on a finished replay, it checks the target again.

A resumed run rebuilds the commits of the push that was in progress, and takes the pushed ones over only where they get the same hashes. An Ed25519 SSH key signs the same commit the same way each time, which the test checks; an OpenPGP signature holds the time it was made, and other SSH keys may sign differently each time, so with such a key a run stopped in a push of signed commits stops again at that push. Replay into a new empty target then, or sign with an Ed25519 SSH key.

## The state file

The state file is the event file with `.state.json` for `.jsonl`, such as `~/vc-backup/github-rewriter-2026-11-15-220456-typed.state.json`, unless `--state` names one. It is written after each event, and before each push with the hashes of the commits it pushes, by replacing it, so a stop at any point leaves the last finished event. It holds JSON: the SHA-256 of the event file, `source` and `target`, `sign` and `final_name`, the values of `--sign` and `--final-name` or `null`, `done`, the number of the last finished event, `finished`, whether the target was checked after the last event, `highest`, the target's highest number, `head`, the commit the default branch is at, and the maps `numbers`, from source to target number, `hashes`, from source to target commit, `heads`, from pull request to the head of its pushed branch, and `urls`, from pull request to its URL. A state file for another event file or target stops the run.

Next to it lies the work repository, with `.work.git` for `.state.json`: a bare repository that borrows the mirror's objects and holds the recreated commits until they are pushed. Keep both until the replay is done and checked; then delete them.

## What the target ends with

- **Labels**: the source's, with their colours and descriptions. Before the first event, the run deletes each label the target has and the source lacks, such as GitHub's defaults, and updates the others.
- **Commits**: each commit of the default branch and of the pull requests' branches, recreated with `git commit-tree` from its planned tree, typed message and mapped author and committer with their original dates, on the recreated parents, so each gets a new hash. With `--sign`, those whose committer has the given address are signed with your signing key, so that GitHub can show them as verified; all others are unsigned, since `git commit-tree` does not read `commit.gpgSign`.
- **Merges**: each merged pull request is merged through GitHub, with the planned method, title and message and `{pr_url}` replaced by its URL, under the name `--final-name` gives or else under the target's, so GitHub is the committer of the squash commit, the account that runs the replay its author, and the time of the replay its date. After each merge, the tree of the default branch equals the source's.
- **Items**: each issue and pull request under its number, with its title, body, labels, assignees, draft state, and the state and state reason it ends in. Each is created open, then merged or closed. A merge closes the issues its pull request names with a closing keyword, as on GitHub; a later close leaves such an issue as it is where the state reason matches, and otherwise reopens and closes it with the planned one, since GitHub [ignores a state reason unless the state changes](https://docs.github.com/en/rest/issues/issues#update-an-issue). After the last event, the run reopens an item the source has open that a merge closed, and stops where any other item, or the labels, differ from the plan.
- **Comments**: each comment, in the planned order, after its item.
- **Hashes**: in every title, body, comment and commit message, a hash of 7 to 40 lowercase hexadecimal characters that is the prefix of exactly one source commit already recreated becomes the prefix of the same length of the new hash.
- **Branches**: each pull request's branch stays, also after its merge, unless the target deletes head branches on merge.

The target does not get the original times and authors: every item, comment and merge is by the account that runs the replay, at the time of the replay; `--with-times` keeps the creation time in the text. Nor does it get reactions, reviews, review comments, milestones or projects, which the plan does not read, or an item's history between its creation and its final state. References to items, in this repository or another, and `@` mentions act again: GitHub adds them to the timeline of the item named, and notifies the person mentioned.

## Comparing the replay with its source

Once the run has printed the target's URL, compare the target with the source, with the event file, the mirror and the state file of the run; give `--with-times` where the run had it, and `--state` where it had one:

```sh
python3 replay/compare-replay.py "${mirror%.git}-typed.jsonl" "$mirror" tiavelum/github-rewriter-trial
```

It needs `gh` signed in with read access to the source and the target, reads GitHub with GET requests only, and fetches the target's commits into a temporary repository, over the protocol `gh config get git_protocol` names, which it deletes at the end. It compares:

- **Items**: each issue and pull request under its number, with its kind, the title the event file plans, its state, its state reason where it is a closed issue, its labels and assignees, and whether it is merged; a number the source lacks has to hold a closed placeholder.
- **Labels**: each with its colour and description.
- **Texts**: every body and comment equal to the source's, with each hash of a recreated commit replaced as [What the target ends with](#what-the-target-ends-with) says, and with the original time where `--with-times` is given; where a text ends in a footer the source lacks, it says so.
- **The default branch**: as many first-parent commits as the source's and as the event file plans, each with the source's tree at the same step and the hash the state file records; each direct commit with its planned message, author and committer and their dates; each merge with its planned message, `{pr_url}` filled as the run filled it, and GitHub as committer. A `Co-authored-by` line that GitHub appends to a merge's message passes; one that stands twice does not.
- **Recreated commits**: each commit the state file records, in the target and with the tree of its source commit.
- **Branches**: the default branch and each pull request's branch, at the head the state file records, without those of merged pull requests where the target deletes head branches on merge.
- **Pull request heads**: the head of each pull request, `refs/pull/<number>/head`, at the head the state file records, also where its branch is deleted.

It prints the totals, then notes, which are no differences: who authored the merges, and each branch the target keeps that the source no longer has, which [Taking over the source's name](#taking-over-the-sources-name) deletes. This is its output for the test's replay of `ada-example/tool`:

```
Compared ada-example/tool with ada-example/tool-replay-20261116-1215:
  items                           6
  labels                          2
  comments                        4
  texts with a replaced hash      1
  commits on main                 7
  recreated commits              12
  branches                        4
  pull request heads              3
Notes:
  merges authored by Ada Example <ada@example.com>
  branch docs/5-notes stays in the target; the source no longer has it
  branch feat/2-thing stays in the target; the source no longer has it
  branch fix/3-parser stays in the target; the source no longer has it
No differences
```

It exits with 0 where it finds no difference. Otherwise it ends with `Differences:` and their number, then one line per difference, and exits with 1; these are five of the lines for a copy of that target with changed data:

```
  #4 is closed as completed, the source's not_planned
  label bug: colour ee0701, the source's d73a4a
  #6, comment 1: the body differs; it has a footer the source lacks
  branch fix/3-parser is missing in the target
  #3: the pull request head is bac0273, the state file's 8ad4614
```

Where the state file records the replay unfinished, or belongs to another event file or target, it compares nothing and exits with 2. It cannot see the source's secrets, variables, webhooks, deploy keys and collaborators; check those yourself before the source is archived.

## Taking over the source's name

Once the replay is checked, give it the source's name, so that links to the source's items reach the replayed ones under the same numbers. `replay.py` moves the sub-issue links itself and prints the other commands of this section for its replay; where you run the steps alone, take them all as follows.

First move what a replay does not carry and an archive no longer lets you change: where an item of the source is a sub-issue of an issue elsewhere, link the replayed item in its place and unlink the source's, since GitHub refuses to remove a sub-issue of an archived repository. For an item `N` of the source whose parent is `owner/other#P`, list the parent's sub-issues in their order, each with its id:

```sh
gh api --paginate repos/owner/other/issues/P/sub_issues --jq '.[] | "\(.id) \(.title)"'
```

Find the source's item in that list and note the id of the sub-issue just before it. If it is the first, note the id of the one after it; if it is the only one, skip the move. A new link lands at the end of the parent's list, so link the replayed item, move it, and unlink the source's item, with the id you noted in place of `3512345678`:

```sh
prev=3512345678
id=$(gh api repos/tiavelum/mac-config-new/issues/N --jq .id)
old=$(gh api repos/tiavelum/mac-config/issues/N --jq .id)
gh api -X POST repos/owner/other/issues/P/sub_issues -F sub_issue_id=$id
gh api -X PATCH repos/owner/other/issues/P/sub_issues/priority -F sub_issue_id=$id -F after_id=$prev
gh api -X DELETE repos/owner/other/issues/P/sub_issue -F sub_issue_id=$old
```

For a first place, put the id of the following sub-issue in `next` and replace the PATCH line with:

```sh
next=3512345678
gh api -X PATCH repos/owner/other/issues/P/sub_issues/priority -F sub_issue_id=$id -F before_id=$next
```

List the parent's sub-issues again with the first command: the replayed item stands where the source's item stood. [GitHub's REST API for sub-issues](https://docs.github.com/en/rest/issues/sub-issues) names `after_id` and `before_id` for the place and asks for the Issues repository permission with write access in the parent's repository for the three changing calls.

Then archive the source under a new name first, since its issues, pull requests and comments exist nowhere else, then rename the replay; for `tiavelum/mac-config` replayed into `tiavelum/mac-config-new`:

```sh
gh api -X PATCH repos/tiavelum/mac-config -f name=mac-config-archive
gh api -X PATCH repos/tiavelum/mac-config-archive -F archived=true
gh api -X PATCH repos/tiavelum/mac-config-new -f name=mac-config
```

[GitHub redirects a renamed repository](https://docs.github.com/en/repositories/creating-and-managing-repositories/renaming-a-repository) until another repository takes its old name, so the third command ends the redirect from `mac-config` to the archive. For the same reason, run such a replay with `--final-name tiavelum/mac-config`, so that the links its squash messages end in name the repository the replay becomes, not `mac-config-new`.

Then give the replay the settings of the source, such as its merge methods and description, and turn Actions on again. These commands show the source's settings, then turn Actions on, merge commits off and the description empty, as for `tiavelum/mac-config`, whose source allowed no merge commits and had no description:

```sh
gh api repos/tiavelum/mac-config-archive --jq '{description, allow_merge_commit, allow_squash_merge, allow_rebase_merge, delete_branch_on_merge, visibility}'
gh api -X PUT repos/tiavelum/mac-config/actions/permissions -F enabled=true
gh api -X PATCH repos/tiavelum/mac-config -F allow_merge_commit=false -f description=
```

Where the source is public and you created the replay private, so that nobody sees it before it is checked, make it public; for `tiavelum/git-alias-map`:

```sh
gh api -X PATCH repos/tiavelum/git-alias-map -f visibility=public
```

Delete each branch of the replay that the source no longer has, such as the branch of a pull request the source closed unmerged and whose branch it deleted:

```sh
gh api -X DELETE repos/tiavelum/mac-config/git/refs/heads/feat/192-log-date
```

Then replace each local clone of the source with a fresh clone of the replay at the same path, since their histories differ.

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
- Where GitHub names a new target's default branch other than the source's, the replay's first push is of a branch with another name. [Update a repository](https://docs.github.com/en/rest/repos/repos#update-a-repository) says only that `default_branch` "updates the default branch for this repository", and [Changing the default branch](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-branches-in-your-repository/changing-the-default-branch) says that "your repository must have more than one branch" to change it, so how GitHub takes such a first push into an empty repository, and whether it lets the default branch be set while the target has one branch, are open; `replay.py` therefore sets it only once the branch exists, and `run-replay.py` checks it only then. Where GitHub refuses the change, `replay.py` stops in step 5 at every run: as an administrator of the target, set the default branch on GitHub by hand where [GitHub allows it](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-branches-in-your-repository/changing-the-default-branch), which it does only for a repository with more than one branch, then run the same command again. This has not run on GitHub yet; a trial with a source whose default branch is named otherwise than GitHub names a new repository's would settle it.

## Files

| File | Step |
|---|---|
| `replay.py` | Runs a whole replay from a run file: mirrors, plans, creates and sets up the target, replays, compares, moves the sub-issue links and prints the commands that give the replay the source's name |
| `plan-replay.py` | Reads the source from a mirror and from GitHub and writes the event file |
| `run-replay.py` | Applies the event file to an empty target and keeps the state file, so that a stopped run resumes |
| `compare-replay.py` | Compares the finished target with the source, the event file and the state file, read-only, and names every difference |
| `test-replay.sh` | Tests the scripts of this folder against a source built in a temporary folder and fake GitHub targets, without contacting GitHub |
