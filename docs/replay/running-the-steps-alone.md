# Running the steps of a replay alone

How to plan a replay, run it and compare its result with the scripts of [`replay/`](../../replay/README.md) one at a time, without `replay.py`, for the owner of the source and the target. Each script needs what [What a replay needs](../../replay/README.md#what-a-replay-needs) gives, and prints its options, the files it reads and writes, where it stops and, for `compare-replay.py`, its exit codes when run without arguments; this page gives one command per step, the steps that `replay.py` would take for you, and what to check in the output.

## Planning a replay

The mailmap maps the author and committer of every commit, in the format that [rewrite/README.md](../../rewrite/README.md#getting-started) describes. These two lines give an old address and GitHub, as the committer of changes made on github.com, the owner's identity, here an invented one:

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

Check every changed title it prints, those marked `guessed` above all, and every squash message; for a source whose default branch is `master`, it also prints `Default branch: master in the source, main in the target`, as [What the target ends with](what-a-replay-carries.md#what-the-target-ends-with) describes. A changed title stands on a line such as:

```
  c1e8a97           Set up the repository: README, license, ignore list and project instructions  ->  feat: set up the repository: README, license, ignore list and project instructions
```

To set a type or a summary yourself, write its line into a file, as the usage text of `plan-replay.py` shows, and plan again into a new event file:

```sh
printf '%s\n' 'c1e8a97 chore' >~/replay-types
python3 replay/plan-replay.py --types ~/replay-types "$mirror" tiavelum/github-rewriter ~/rewrite-mailmap "${mirror%.git}-typed.jsonl"
```

Where the plan stops at what it leaves behind, accept each line as [What a replay leaves behind](what-a-replay-carries.md#what-a-replay-leaves-behind) shows.

## Running a replay

The run needs what [What a replay needs](../../replay/README.md#what-a-replay-needs) gives, for `--sign` the signing key and the scope that lets `gh` list it among them. First create the target on GitHub, private and empty: without a README, license or ignore file, and with no ruleset or branch protection on it yet, since the direct commits are pushed to it. Turn off Actions in it until the replay is checked, since every pushed branch and every merge would otherwise start the source's workflows; and where the source has deleted the branches of its merged pull requests, turn on the deletion of head branches, so that the replay's are deleted on merge too:

```sh
gh api -X PUT repos/tiavelum/github-rewriter-trial/actions/permissions -F enabled=false
gh api -X PATCH repos/tiavelum/github-rewriter-trial -F delete_branch_on_merge=true
```

Then, with the mirror and the event file of [Planning a replay](#planning-a-replay), here signing the commits you committed under an invented address, and filling `{pr_url}` with the name the replay takes over at the end:

```sh
python3 replay/run-replay.py --sign ada@example.com --final-name tiavelum/github-rewriter "${mirror%.git}-typed.jsonl" "$mirror" tiavelum/github-rewriter-trial
```

Before the confirmation, check the labels it updates and deletes in the target, what `{pr_url}` becomes and, with `--sign`, which key signs; for a signed replay of the test's source `ada-example/tool`, without `--final-name` and with the path of its throwaway key replaced by `~/.ssh/id_ed25519.pub`, these lines read:

```
  signed: the commits committed and the tags tagged by ada@example.com, with the SSH key ~/.ssh/id_ed25519.pub (ssh-ed25519)
  {pr_url} in 1 squash message: https://github.com/ada-example/tool-replay-20261116-1215/pull/<number>
  labels the target has and the replay updates: bug
  labels the target has and the replay deletes: enhancement
Type ada-example/tool-replay-20261116-1215 to confirm:
```

With a key other than an Ed25519 SSH key, it adds `this key does not sign a commit the same way twice: a run stopped in a push of signed commits, or in a signed tag, cannot resume`, as [Stopping and resuming](stopping-and-resuming.md#stopping-and-resuming) explains. It ends with the target's URL.

Where GitHub names the target's default branch other than the plan names it, as [What the target ends with](what-a-replay-carries.md#what-the-target-ends-with) describes, the run goes on while the target is empty. Once it is done, make the plan's the default branch, here `main`; where a resumed run stops at `the default branch of tiavelum/github-rewriter-trial is master, the replay's main`, do so first and run it again:

```sh
gh api -X PATCH repos/tiavelum/github-rewriter-trial -f default_branch=main
```

GitHub allows [no more than 500 content-generating requests per hour](https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api#about-secondary-rate-limits), and a replay makes about one per label, item, comment, merge, close, release and asset, so a large one may stop on the limit after its retries; run it again after an hour.

## Comparing the replay with its source

Once the run has printed the target's URL, compare the target with the source, with the options of the run that the usage text of `compare-replay.py` names:

```sh
python3 replay/compare-replay.py "${mirror%.git}-typed.jsonl" "$mirror" tiavelum/github-rewriter-trial
```

It compares:

- **Items**: each issue and pull request under its number, with its kind, the title the event file plans, its state, its state reason where it is a closed issue, its labels and assignees, and whether it is merged; a number the source lacks has to hold a closed placeholder.
- **Labels**: each with its colour and description.
- **Comments and reviews**: each item's comments in the order the event file plans them; each comment of the source and each review of a source pull request but pending ones in the event file, and each planned review still in the source, its body in the text the plan wrote of it. An event file planned before reviews were carried plans none, and the comparison notes it; so does one planned with `--no-reviews`, whose note says that reviews are turned off, and the comparison then reads no review of the source and expects none in the target.
- **Texts**: every body and comment equal to the source's, each review's comment equal to the text the plan wrote, with each hash of a recreated commit replaced as [What the target ends with](what-a-replay-carries.md#what-the-target-ends-with) says, and with the original time where `--with-times` is given; where a text ends in a footer the source lacks, it says so.
- **The default branch**: the target's default branch is the one the event file's header names, else a difference such as `the default branch is master, planned main`; and the source's compared with the target's under that name: as many first-parent commits as the source's and as the event file plans, each with the source's tree at the same step and the hash the state file records; each direct commit with its planned message, author and committer, the author's original date and the committer date the state file records; each merge with its planned message, `{pr_url}` filled as the run filled it, and GitHub as committer. A `Co-authored-by` line that GitHub appends to a merge's message passes; one that stands twice does not.
- **Recreated commits**: each commit the state file records, in the target and with the tree of its source commit, and none of those the run built itself committed before one of its parents.
- **Branches**: the default branch, under the name the header gives it, and each pull request's branch, at the head the state file records, without those of merged pull requests where the target deletes head branches on merge.
- **Pull request heads**: the head of each pull request, `refs/pull/<number>/head`, at the head the state file records, also where its branch is deleted.
- **Tags the replay carries**: each tag the event file plans, at the commit recreated from the one it names, lightweight or annotated as planned, an annotated one naming that commit with the planned message, each hash replaced as for texts, and the planned tagger and date; a signature at the end of the message does not count, and neither does the line break the run puts before it, as [What the target ends with](what-a-replay-carries.md#what-the-target-ends-with) describes.
- **Releases the replay carries**: each release the event file plans, in the target as the state file maps it, so that a draft and a published release of one tag are each compared, with a line such as `release v0.2 (draft): …` where they share the tag, under its tag name, with the planned name and body, the body's hashes replaced as for texts and with the original time where `--with-times` is given, draft and pre-release as planned, the latest where the plan's is, and the assets of the source's release that GitHub lists as uploaded, by name, each uploaded in the target and with the source's size, content type and digest where both report one.
- **Tags, releases and branches of the source**: each branch and each other tag of the mirror in the target at the commit recreated from the one it names, and each other release of the source in the target, read from the mirror and from GitHub rather than from the plan; one the target lacks, or holds at another commit, is a note where the event file's header lists it as left behind, as [What a replay leaves behind](what-a-replay-carries.md#what-a-replay-leaves-behind) describes, and a difference otherwise. Where the header lists tags or releases as turned off, one of that kind the target lacks is a note that says so, and one the target holds is a difference. A tag or release of the target that the source lacks is a difference.

After the totals, it prints notes, which are no differences, such as each branch the target keeps that the source no longer has, which [Taking over the source's name](../../replay/README.md#taking-over-the-sources-name) deletes, and each tag, release and branch the plan left behind. For the test's replay of `ada-example/tool`, it ends with:

```
Notes:
  merges authored by Ada Example <ada@example.com>
  branch docs/5-notes stays in the target; the source no longer has it
  branch feat/2-thing stays in the target; the source no longer has it
  branch fix/3-parser stays in the target; the source no longer has it
No differences
```

Otherwise it ends with `Differences:` and their number, then one line per difference, such as these for copies of that target with changed data:

```
  #4 is closed as completed, the source's not_planned
  #6, comment 1: the body differs; it has a footer the source lacks
  tag v0.1 of the source is at 9d94f69 in the target, not at the recreated dbf44bc
  release v0.2: asset notes.txt is missing in the target
```
