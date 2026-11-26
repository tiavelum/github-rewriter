# Running the steps of a replay alone

How to plan a replay, run it and compare its result with the scripts of [`replay/`](../../replay/README.md) one at a time, without `replay.py`, for the owner of the source and the target.

## Planning a replay

Requires Python 3.10 or later, git, and the GitHub CLI `gh`, signed in with read access to the source and, where the source has draft releases, push access to it, since GitHub [lists draft releases only to users with push access](https://docs.github.com/en/rest/releases/releases#list-releases); a classic token has that access with the scope [`repo`](https://docs.github.com/en/apps/oauth-apps/building-oauth-apps/scopes-for-oauth-apps), which "grants full access to public and private repositories", where your account can push to the source. Without it, the plan sees no draft, and the comparison names each draft the event file carries as one the source lacks. Running and comparing read the source's releases and their assets the same way.

The mailmap maps the author and committer of every commit, in the format that [rewrite/README.md](../../rewrite/README.md#steps) describes. These two lines give an old address and GitHub, as the committer of changes made on github.com, the owner's identity, here an invented one:

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

It prints every title it changed, with `guessed` where it guessed the type, every squash message it wrote for a pull request merged with a merge commit, what it leaves behind, as [What a replay leaves behind](what-a-replay-carries.md#what-a-replay-leaves-behind) describes, then the totals and the event file; for a source whose default branch is `master`, it prints `Default branch: master in the source, main in the target` before them, as [What the target ends with](what-a-replay-carries.md#what-the-target-ends-with) describes. The counts are those of the repository on the day the step was run; yours differ. This output is shortened where `…` stands:

```
Changed titles: 7
  c1e8a97           Set up the repository: README, license, ignore list and project instructions  ->  feat: set up the repository: README, license, ignore list and project instructions
  c420a3b           Merge pull request #32 from tiavelum/feat/24-skill-run-file  ->  feat: adapt the skill replay-repository to the run file of replay.py (#32)
  …
Squash messages written for merge commits: 5
  #32  feat: adapt the skill replay-repository to the run file of replay.py (#32)
      Adapts the skill `replay-repository` to the run file of `replay/replay.py`, merged with #30 (feat: replay a repository with one command from a run file): it asks the owner every question of the run file in one round, has the owner run `replay.py`, and checks the comparison's output before its own check and a checker's.

      {pr_url}
  …
Left behind: 0
Totals:
  items                        66
  issues                       39
  pull requests                27
  comments                    119
  reviews                      22
  labels                       13
  tags                          0
  releases                      0
  release assets                0
  commits                      72
  squash merges                27
  merge commits                 0
  events                      311
  guessed types                 0
  events out of time order      3
  left behind                   0
~/vc-backup/github-rewriter-2026-11-17-015317.jsonl
```

Check every changed title, the guessed ones above all, and every squash message. To set a type yourself, write it into a file, one line per pull request number or commit hash of at least 7 characters, and plan again into a new event file:

```sh
printf '%s\n' 'c1e8a97 chore' >~/replay-types
python3 replay/plan-replay.py --types ~/replay-types "$mirror" tiavelum/github-rewriter ~/rewrite-mailmap "${mirror%.git}-typed.jsonl"
```

It prints the same as before, with the type set, and the new event file:

```
Changed titles: 7
  c1e8a97           Set up the repository: README, license, ignore list and project instructions  ->  chore: set up the repository: README, license, ignore list and project instructions
  …
~/vc-backup/github-rewriter-2026-11-17-015317-typed.jsonl
```

In the same file, a line of a pull request number, `summary` and a text sets the summary of the squash message that [How pull requests are merged](what-a-replay-carries.md#how-pull-requests-are-merged) describes, such as `10 summary Signs commits and tags with the SSH key.`

Two options, given before the mirror, turn off what the replay changes; without them, every title gets a type and every merge commit becomes a squash merge:

- `--no-types` keeps every title as it is, instead of giving it a type as [How a title gets its type](what-a-replay-carries.md#how-a-title-gets-its-type) describes.
- `--keep-merges` keeps the merge commits, as [How pull requests are merged](what-a-replay-carries.md#how-pull-requests-are-merged) describes.

Three options, given before the mirror, turn off what the replay carries; without them, it carries every review as a comment and every tag and release it can place, and stops at each other tag and release it leaves behind, as [What a replay leaves behind](what-a-replay-carries.md#what-a-replay-leaves-behind) describes:

- `--no-tags` plans no tag and accepts every tag as left behind, without a line of `--leave-behind`.
- `--no-releases` plans no release and accepts every release as left behind, the same way.
- `--no-reviews` plans no review as a comment, and reads no review from GitHub.

`--no-tags` needs `--no-releases`, since GitHub [creates the missing tag of a release it creates](https://docs.github.com/en/rest/releases/releases#create-a-release), from the branch or commit its `target_commitish` names, by default the repository's default branch, so a replay that creates releases would still carry tags. `plan-replay.py` stops at `--no-tags` without `--no-releases` before it reads the mirror or GitHub, and `replay.py` at `no_tags` without `no_releases` before its first step, whether or not the source has releases. The event file's header lists the kinds turned off, as [The event file](file-formats.md#the-event-file) describes, so that the comparison notes them as turned off.

`plan-replay.py` stops, and writes no event file, when `--no-tags` stands without `--no-releases`, when the source has a branch `main` beside its default branch `master`, as [What the target ends with](what-a-replay-carries.md#what-the-target-ends-with) describes, when it leaves behind a tag, release or branch that `--leave-behind` does not accept and no option turns off, as [What a replay leaves behind](what-a-replay-carries.md#what-a-replay-leaves-behind) describes, when a merged pull request was merged into a branch other than the default branch, when the mirror lacks a pull request's head, when a pull request's branch merges a commit that is neither on the first-parent line of the default branch nor on the branch of a pull request, or when the number order and the order of the default branch cannot both hold, as when a pull request's branch starts on a commit that only a later item brings.

## Running a replay

Requires Python 3.10 or later, git 2.31 or later, and `gh`, signed in with the right to push to the target, to create its issues, pull requests, comments, labels and releases and upload their assets, and to merge its pull requests, and with the access to the source that [Planning a replay](#planning-a-replay) names, since the run downloads the assets of the source's releases; `git push` reaches the target over the protocol `gh config get git_protocol` names. GitHub asks for the scope `workflow` to [create a release](https://docs.github.com/en/rest/releases/releases#create-a-release) whose commit adds or modifies a file under `.github/workflows/`; where a release of the source stands on such a commit, add it with:

```sh
gh auth refresh -s workflow
```

The run asks git for no password, so the protocol `git push` takes has to work without one: where git reaches GitHub over SSH, set it with:

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

Where GitHub names the target's default branch other than the plan names it, the source's or `main` for a source's `master`, as [What the target ends with](what-a-replay-carries.md#what-the-target-ends-with) describes, the run goes on while the target is empty. Once it is done, make the plan's the default branch, here `main`; where a resumed run stops at `the default branch of tiavelum/github-rewriter-trial is master, the replay's main`, do so first and run it again:

```sh
gh api -X PATCH repos/tiavelum/github-rewriter-trial -f default_branch=main
```

It checks that the mirror holds every tree of the event file, that GitHub answers for the target under the name you gave (a renamed repository stops it), and that the target is empty, prints what it will do in totals, with the labels the target already has, and asks for the target's `owner/repo`; anything else stops it without a write. It then prints one line per event, and at the end what it did and the target's URL. This is the output of a run of the test's source, `ada-example/tool`, into a fake target, as the fixture `replay_uninterrupted` of [`tests/conftest.py`](../../replay/tests/conftest.py) makes it, with its target `ada-example/tool-new` given a name of the form a run file asks for; the answer typed at the prompt does not show, since the test pipes it in:

```
Replay ada-example/tool into ada-example/tool-replay-20261116-1215: 23 events
  labels                        2
  commits                      10
  issues                        3
  pull requests                 3
  comments                      4
  reviews as comments           0
  merges                        2
  closes                        3
  tags                          0
  releases                      0
  release assets                0
  release asset bytes           0
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
  create-tag                    0
  create-release                0
https://github.com/ada-example/tool-replay-20261116-1215
```

For a source with tags and releases, each tag gets a line such as `25/29  create-tag    v0.2, annotated, at 9d94f69`, with `lightweight` for a lightweight tag, and each release one such as `26/29  create-release  v0.2, published, latest, 2 assets, 26 bytes`, with `pre-release` or `draft` for those, as [What the target ends with](what-a-replay-carries.md#what-the-target-ends-with) describes; the totals count the releases, their assets and the bytes of the assets, which the run downloads from the source and uploads to the target. For a source whose default branch is `master`, the totals add `default branch: master in the source, main in the target`, and each push and pull request names `main`.

Six options, given before the event file:

- `--with-times` appends the original creation time to each body and comment, as `_Originally created 2026-03-01 11:00 UTC._` after a blank line, and to a release's body the time of its publication, or for a draft its `created_at`, which [GitHub documents](https://docs.github.com/en/rest/releases/releases#get-the-latest-release) as "the date of the commit used for the release", not the date the draft was made; off by default.
- `--sign <address>` signs, with the signing key of your git configuration, each recreated commit whose mapped committer has that address, and each annotated tag whose mapped tagger has it, as [Running a replay](#running-a-replay) requires; the others stay unsigned, since nobody running the replay holds the key of a commit someone else committed or a tag someone else tagged. Off by default.
- `--final-name <owner/repo>` fills `{pr_url}` with the URL of the pull request under the name the target will carry once it takes over the source's name, such as `https://github.com/tiavelum/github-rewriter/pull/3`, instead of the target's current name; off by default.
- `--state <file>` keeps the state in that file instead of the one next to the event file.
- `--confirmed <owner/repo>` takes `<owner/repo>` as the answer to the confirmation instead of asking for it, as `replay.py` gives the answer you typed; any other value stops the run as a wrong answer does.
- `--pace <seconds>` sets the least time between two writes; the default, 1, follows GitHub's advice to [pause at least one second between mutative requests](https://docs.github.com/en/rest/using-the-rest-api/best-practices-for-using-the-rest-api#pause-between-mutative-requests), and the test uses less.

For a replay into `tiavelum/github-rewriter-trial` that takes over the source's name, signing the commits you committed under an invented address:

```sh
python3 replay/run-replay.py --sign ada@example.com --final-name tiavelum/github-rewriter "${mirror%.git}-typed.jsonl" "$mirror" tiavelum/github-rewriter-trial
```

Before the confirmation, the totals then also say how many commits and tags it signs, with which key, and what `{pr_url}` becomes; each push says how many of its commits it signed, and each signed tag's line says `signed`. These are the first lines of a signed run of the test, with the path of its throwaway key replaced by `~/.ssh/id_ed25519.pub`:

```
Replay ada-example/tool into ada-example/tool-replay-20261116-1215: 23 events
  labels                        2
  commits                      10
  issues                        3
  pull requests                 3
  comments                      4
  reviews as comments           0
  merges                        2
  closes                        3
  tags                          0
  releases                      0
  release assets                0
  release asset bytes           0
  commits to sign               9
  tags to sign                  0
  signed: the commits committed and the tags tagged by ada@example.com, with the SSH key ~/.ssh/id_ed25519.pub (ssh-ed25519)
  {pr_url} in 1 squash message: https://github.com/ada-example/tool-replay-20261116-1215/pull/<number>
  labels the target has and the replay updates: bug
  labels the target has and the replay deletes: enhancement
Type ada-example/tool-replay-20261116-1215 to confirm:   label enhancement deleted
 1/23  create-label  bug updated
 2/23  create-label  docs created
 3/23  push-commits  1 commit to main, 1 signed, now at d1d4d85
```

With a key other than an Ed25519 SSH key, the totals add `this key does not sign a commit the same way twice: a run stopped in a push of signed commits, or in a signed tag, cannot resume`, as [Stopping and resuming](stopping-and-resuming.md#stopping-and-resuming) explains.

On a rate limit, an answer 403 or 429, the run waits as [GitHub's guidance on exceeding a rate limit](https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api#exceeding-the-rate-limit) says: the seconds of `retry-after`, else up to the time of `x-ratelimit-reset` where `x-ratelimit-remaining` is 0, else a minute, doubled at each retry; it retries the same call at most 5 times and then stops. GitHub allows [no more than 500 content-generating requests per hour](https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api#about-secondary-rate-limits), and a replay makes about one per label, item, comment, merge, close, release and asset, so a large one may stop on the limit; run it again after an hour.

## Comparing the replay with its source

Once the run has printed the target's URL, compare the target with the source, with the event file, the mirror and the state file of the run; give `--with-times` where the run had it, and `--state` where it had one:

```sh
python3 replay/compare-replay.py "${mirror%.git}-typed.jsonl" "$mirror" tiavelum/github-rewriter-trial
```

It needs `gh` signed in with read access to the target and the access to the source that [Planning a replay](#planning-a-replay) names, reads GitHub with GET requests only, and fetches the target's commits into a temporary repository, over the protocol `gh config get git_protocol` names, which it deletes at the end. It compares:

- **Items**: each issue and pull request under its number, with its kind, the title the event file plans, its state, its state reason where it is a closed issue, its labels and assignees, and whether it is merged; a number the source lacks has to hold a closed placeholder.
- **Labels**: each with its colour and description.
- **Comments and reviews**: each item's comments in the order the event file plans them; each comment of the source and each review of a source pull request but pending ones in the event file, and each planned review still in the source, its body in the text the plan wrote of it. An event file planned before reviews were carried plans none, and the comparison notes it; so does one planned with `--no-reviews`, whose note says that reviews are turned off, and the comparison then reads no review of the source and expects none in the target.
- **Texts**: every body and comment equal to the source's, each review's comment equal to the text the plan wrote, with each hash of a recreated commit replaced as [What the target ends with](what-a-replay-carries.md#what-the-target-ends-with) says, and with the original time where `--with-times` is given; where a text ends in a footer the source lacks, it says so.
- **The default branch**: the target's default branch is the one the event file's header names, `main` for a source's `master`, as [What the target ends with](what-a-replay-carries.md#what-the-target-ends-with) describes, else a difference such as `the default branch is master, planned main`; and the source's compared with the target's under that name: as many first-parent commits as the source's and as the event file plans, each with the source's tree at the same step and the hash the state file records; each direct commit with its planned message, author and committer, the author's original date and the committer date the state file records; each merge with its planned message, `{pr_url}` filled as the run filled it, and GitHub as committer. A `Co-authored-by` line that GitHub appends to a merge's message passes; one that stands twice does not.
- **Recreated commits**: each commit the state file records, in the target and with the tree of its source commit, and none of those the run built itself committed before one of its parents.
- **Branches**: the default branch, under the name the header gives it, and each pull request's branch, at the head the state file records, without those of merged pull requests where the target deletes head branches on merge.
- **Pull request heads**: the head of each pull request, `refs/pull/<number>/head`, at the head the state file records, also where its branch is deleted.
- **Tags the replay carries**: each tag the event file plans, at the commit recreated from the one it names, lightweight or annotated as planned, an annotated one naming that commit with the planned message, each hash replaced as for texts, and the planned tagger and date; a signature at the end of the message does not count, and neither does the line break the run puts before it, as [What the target ends with](what-a-replay-carries.md#what-the-target-ends-with) describes.
- **Releases the replay carries**: each release the event file plans, in the target as the state file maps it, so that a draft and a published release of one tag are each compared, with a line such as `release v0.2 (draft): …` where they share the tag, under its tag name, with the planned name and body, the body's hashes replaced as for texts and with the original time where `--with-times` is given, draft and pre-release as planned, the latest where the plan's is, and the assets of the source's release that GitHub lists as uploaded, by name, each uploaded in the target and with the source's size, content type and digest where both report one.
- **Tags, releases and branches of the source**: each branch and each other tag of the mirror in the target at the commit recreated from the one it names, and each other release of the source in the target, read from the mirror and from GitHub rather than from the plan; one the target lacks, or holds at another commit, is a note where the event file's header lists it as left behind, as [What a replay leaves behind](what-a-replay-carries.md#what-a-replay-leaves-behind) describes, and a difference otherwise. Where the header lists tags or releases as turned off, one of that kind the target lacks is a note that says so, and one the target holds is a difference. A tag or release of the target that the source lacks is a difference.

It prints the totals, then notes, which are no differences: `default branch master of the source is main in the target, as planned` where the plan renames it, who authored the merges, each branch the target keeps that the source no longer has, which [Taking over the source's name](../../replay/README.md#taking-over-the-sources-name) deletes, each tag, release and branch the plan left behind, as `tag v0.1 of the source is left behind, as planned`, or, of a kind the plan turned off, as `tag v0.1 of the source is left behind: tags are turned off`, `reviews are turned off: the event file plans no review as a comment` where the plan turned them off, and, for an event file planned before the header recorded what a plan leaves behind, that it accepts nothing as left behind. This is its output for the test's replay of `ada-example/tool`:

```
Compared ada-example/tool with ada-example/tool-replay-20261116-1215:
  items                           6
  labels                          2
  comments                        4
  reviews as comments             0
  texts with a replaced hash      1
  commits on main                 7
  recreated commits              12
  branches                        4
  pull request heads              3
  tags                            0
  releases                        0
  release assets                  0
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

And this is one of the lines for the same target compared with a source that also has a tag `v0.1`, which the plan did not leave behind:

```
  tag v0.1 of the source is missing in the target
```

And these are the lines for a replay of the test's source with three tags, whose target then got `v0.1` moved to another commit, `v0.2` made anew with another message, and `v0.1.1` made lightweight:

```
  tag v0.1 of the source is at 9d94f69 in the target, not at the recreated dbf44bc
  tag v0.1.1 is lightweight in the target, annotated as planned
  tag v0.2: the message differs; they part at character 1: 'Another message\n', the source's 'Second, after 7dd6d6e\n'
```

And these are three of the lines for the same replay, whose target then got, among other changes, another body for the release `v0.1.1`, lost the asset `notes.txt` of `v0.2`, and no longer has `v0.2` as its latest release:

```
  release v0.1.1: the body differs; they part at character 1: 'Changed.', the source's ''
  release v0.2: latest false, planned true
  release v0.2: asset notes.txt is missing in the target
```

Where the state file records the replay unfinished, or belongs to another event file or target, it compares nothing and exits with 2. It cannot see the source's secrets, variables, webhooks, deploy keys and collaborators; check those yourself before the source is archived.
