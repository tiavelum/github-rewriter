# replay

How to replay a GitHub repository into a new, empty one with the scripts of this folder, for the owner of both: every commit, issue, pull request, comment, review and label of the source, reviews as comments, and its tags and releases, with their assets, so that the target gets them under the same numbers, with mapped identities and typed titles. A repository is replayed into a new one, rather than rewritten in place, replayed into the same one or forked, since a rewrite in place leaves the pull requests showing the old commits with the old identities and needs a force push of the default branch, a replay into the same one leaves each replayed pull request beside its original under a new number, and a fork can have [its own issues and pull requests](https://docs.github.com/en/pull-requests/reference/forks), and the source's, which that page does not say a fork copies, stay in the source ([#3](https://github.com/tiavelum/github-rewriter/issues/3#issuecomment-7170929265)).

Planning reads the source and writes the replay as an event file; it changes nothing on GitHub. Running applies the event file to the target, after you confirm it, and can stop and resume. Comparing reads the source and the target and names every difference between them; it changes nothing either. `replay.py` takes these three steps in turn from one run file, with the steps around them, and is the way to run a replay; [Running the steps of a replay alone](../docs/replay/running-the-steps-alone.md) describes the steps it takes, which you can also run alone, and [Documents](#documents) lists what else is written about a replay. Each script takes its inputs as arguments; run without arguments, it prints its usage.

## What a replay needs

Python 3.10 or later, git 2.31 or later, and the GitHub CLI `gh`, signed in with:

- read access to the source and, where the source has draft releases, push access to it, since GitHub [lists draft releases only to users with push access](https://docs.github.com/en/rest/releases/releases#list-releases); a classic token has that access with the scope [`repo`](https://docs.github.com/en/apps/oauth-apps/building-oauth-apps/scopes-for-oauth-apps), which "grants full access to public and private repositories", where your account can push to the source. Without it, the plan sees no draft, and the comparison names each draft the event file carries as one the source lacks; the run reads the source's releases and their assets the same way.
- the right to push to the target, to create its issues, pull requests, comments, labels and releases and upload their assets, to merge its pull requests, and to change its settings where you or `replay.py` set them up.
- for `replay.py`, which creates the target, the right to create a repository for the target's owner, which for [a repository of your account](https://docs.github.com/en/rest/repos/repos#create-a-repository-for-the-authenticated-user) a classic token has with the scope `repo` and a fine-grained one with the repository permission "Administration" or "Repository creation" set to write, and which for [a repository of an organisation](https://docs.github.com/en/rest/repos/repos#create-an-organization-repository) only a member of it has; and, where the source's issues have sub-issue links, the repository permission "Issues" set to write in the repository of each parent, which [Add sub-issue](https://docs.github.com/en/rest/issues/sub-issues#add-sub-issue) asks for.
- the scope `workflow`, which GitHub asks for to [create a release](https://docs.github.com/en/rest/releases/releases#create-a-release) whose commit adds or modifies a file under `.github/workflows/`, where a release of the source stands on such a commit.

Add the scope `workflow` with:

```sh
gh auth refresh -s workflow
```

The run and the comparison reach the target with `git push` and `git fetch` over the protocol `gh config get git_protocol` names, and ask git for no password, so that protocol has to work without one: where git reaches GitHub over SSH, set it with:

```sh
gh config set git_protocol ssh
```

Otherwise the run stops in its first check, before any write, at `could not read Username for 'https://github.com': terminal prompts disabled`.

To sign your recreated commits, with `sign` in a run file or `--sign` of `run-replay.py`, your git configuration needs a `user.signingkey`, with `gpg.format` `ssh` or `openpgp`, the default. For an SSH key, it needs `ssh-keygen` and, since [SSH signing is available in Git 2.34 or later](https://docs.github.com/en/authentication/managing-commit-signature-verification/about-commit-signature-verification), git 2.34 or later; a key with a passphrase has to be in the agent. GitHub [verifies a signature against a public key you have added to your account](https://docs.github.com/en/authentication/managing-commit-signature-verification/about-commit-signature-verification), so the run checks that GitHub lists the key, and stops where it does not. Add an SSH key as a signing key, here `~/.ssh/id_ed25519.pub`, with:

```sh
gh ssh-key add ~/.ssh/id_ed25519.pub --type signing
```

With a classic or OAuth token, `gh` lists [SSH signing keys only with the scope `read:ssh_signing_key`](https://docs.github.com/en/rest/users/ssh-signing-keys#list-ssh-signing-keys-for-the-authenticated-user) and [GPG keys only with `read:gpg_key`](https://docs.github.com/en/rest/users/gpg-keys#list-gpg-keys-for-the-authenticated-user); a fine-grained token needs the user permission "SSH signing keys" or "GPG keys" set to read. Where it lacks the one your key needs, the run names it and stops. Add the scope with:

```sh
gh auth refresh -s read:ssh_signing_key
```

## Replaying with one command

`replay.py` runs a whole replay from a run file: it mirrors and plans the source, asks you once to confirm, and then creates the target, replays the source into it, compares the two and moves the sub-issue links without further questions. It ends with the commands that give the replay the source's name, which stay yours to run. It runs the scripts of those steps as processes and needs what [What a replay needs](#what-a-replay-needs) gives. Since [GitHub adds a sub-issue only to a parent of the same repository owner](https://docs.github.com/en/rest/issues/sub-issues#add-sub-issue), `replay.py` stops before the confirmation where a parent of a source's issue, or a sub-issue from elsewhere, belongs to an owner other than the target's. GitHub refuses such a link whoever makes it, so move or remove these links in the source first, or replay with the scripts of those steps alone, which leave links alone, and leave these links out of the first move of [Taking over the source's name](#taking-over-the-sources-name).

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
| `mailmap` | The lines of the mailmap that [Planning a replay](../docs/replay/running-the-steps-alone.md#planning-a-replay) describes | Required |
| `final_name` | The name the replay takes over at the end, which `run-replay.py` gets as `--final-name` | `source` |
| `types` | The lines of the file of `--types`: types and `summary` lines | None |
| `leave_behind` | The lines of the file of `--leave-behind`: the tags, releases and branches the replay may leave behind, as [What a replay leaves behind](../docs/replay/what-a-replay-carries.md#what-a-replay-leaves-behind) describes | None |
| `sign` | The address of `--sign` | `null`, nothing signed |
| `keep_merges` | Whether the plan has `--keep-merges` | `false` |
| `no_types` | Whether the plan has `--no-types` | `false` |
| `no_tags` | Whether the plan has `--no-tags`, which needs `no_releases`, as the usage text of `plan-replay.py` explains | `false` |
| `no_releases` | Whether the plan has `--no-releases` | `false` |
| `no_reviews` | Whether the plan has `--no-reviews` | `false` |
| `with_times` | Whether the run and the comparison have `--with-times` | `false` |
| `pace` | The seconds of `--pace` | `1` |
| `backup` | The folder of the mirror, the event file, the state file and the work repository | `~/vc-backup` |
| `clone_url` | The URL `backup-mirror.sh` clones the source from | `git@github.com:<source>.git` |

A field it does not know, or a value of the wrong kind, stops it before it reads or writes anything. Before the run, bring your clone of this repository up to date with [`git pull --ff-only`](https://git-scm.com/docs/git-pull), and show with [`gh config get`](https://cli.github.com/manual/gh_config_get) the protocol `gh` is set to, which [What a replay needs](#what-a-replay-needs) says has to work without a password:

```sh
git -C ~/vc/github-rewriter pull --ff-only && gh config get git_protocol
```

Then run `replay.py`. On macOS, put `caffeinate -i` in front, which keeps the Mac from sleeping while idle until the command ends, as `man caffeinate` describes; a replay of many items takes a while:

```sh
caffeinate -i python3 ~/vc/github-rewriter/replay/replay.py ~/github-rewriter.run.json
```

It announces each of its eight steps as `Step <n> of 8`:

1. **mirror**: makes the mirror with `backup-mirror.sh` in `backup`.
2. **plan**: plans into the event file next to the mirror, with the mailmap and the types written into a temporary folder that it deletes afterwards, and prints every changed title and the totals, as [Planning a replay](../docs/replay/running-the-steps-alone.md#planning-a-replay) shows. Where it stops at a guessed type, give that title's commit or pull request its type in `types`; where it stops at what the plan leaves behind, add the line of each you accept to `leave_behind`; then run again.
3. **create**: creates the target, private and empty, for your account or for the organisation that owns it.
4. **settings**: turns Actions off in the target, and the deletion of head branches on where the source has it on.
5. **replay**: runs `run-replay.py` with `--pace`, `--final-name`, and `--sign` and `--with-times` where the run file sets them, and gives it your confirmation with `--confirmed`. Where GitHub has named the target's default branch other than the plan names it, as [What the target ends with](../docs/replay/what-a-replay-carries.md#what-the-target-ends-with) describes, it then makes the plan's the default branch, once the replay has pushed it, and before `run-replay.py` where a stopped replay pushed it already.
6. **compare**: runs `compare-replay.py`, as [Comparing the replay with its source](../docs/replay/running-the-steps-alone.md#comparing-the-replay-with-its-source) describes, and stops at any difference.
7. **links**: moves the sub-issue links, as [Taking over the source's name](#taking-over-the-sources-name) describes for a parent elsewhere. Where an issue of the source has sub-issues, the replayed issue gets them in the same order: the replayed ones for those of the source, and those from elsewhere moved over with `replace_parent`, the option of [Add sub-issue](https://docs.github.com/en/rest/issues/sub-issues#add-sub-issue) that replaces a sub-issue's current parent, so that they leave the source's issue.
8. **commands**: prints what is left to you, with the commands of [Taking over the source's name](#taking-over-the-sources-name) for this replay.

Before the first step it checks that the target does not exist yet. Between the plan and the creation it reads the sub-issue links, and stops where one crosses owners; then it lists what it will do and asks for the target's `owner/repo`; anything else stops it without a write to GitHub. Check in the list each repository other than the target that a link is written in and, below the steps, the kinds the run file turns off, such as `turned off in the run file: reviews; the replay carries none of them, and only the archive keeps them`. For the test's source, `ada-example/tool`, with a sub-issue link to an invented `ada-example/plans`, the list reads:

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
Type ada-example/tool-replay-20261116-1215 to confirm:
```

Step 8 prints, for this replay, the commands of [Taking over the source's name](#taking-over-the-sources-name) other than the moves of step 7, as four steps, each with what it does: the reads of what neither script sees in the source, the archive, the rename and the settings, the fresh clone, and the run's files to delete; run them in their order. Above the commands of the archive, a note names what only the archive then keeps, the default branch where the plan renamed it, so that you use `main` in the new clone, and an archive name `<repository>-archive` that is taken already, so that you give the archive another name in the first two commands. It prints the line of secret scanning only where GitHub reports it for the source, which it does not for a private repository without [GitHub Secret Protection](https://docs.github.com/en/code-security/secret-scanning/introduction/about-secret-scanning). Where `final_name` is not the source, the first command only archives the source.

Where it stops, it names the step and says how to go on. A stop before the confirmation writes nothing to GitHub, and the next run starts over with a new mirror and event file; the stopped run's stay in `backup`. After the confirmation it keeps its progress in the progress file next to the run file, `~/github-rewriter.progress.json` for the run file above: the mirror, the event file and the steps done. Once you have removed the cause of the stop, run the same command again: it asks you to confirm again, skips the creation and the settings where they are done, lets `run-replay.py` resume where [Stopping and resuming](../docs/replay/stopping-and-resuming.md#stopping-and-resuming) says, compares again, and moves the links that are not moved yet. Ctrl-C reaches the script that runs, so in the replay step it stops `run-replay.py` as [Stopping and resuming](../docs/replay/stopping-and-resuming.md#stopping-and-resuming) says. A run file that changed after the confirmation stops it; undo the change to resume. Where the comparison finds a difference that you accept, take the remaining steps by hand, as the sections below describe them.

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

Before the archive and rename, read what neither script reads in the source, and carry over by hand what these show: a count other than 0, or a collaborator other than you:

```sh
gh api repos/tiavelum/git-alias-map/actions/secrets --jq .total_count
gh api repos/tiavelum/git-alias-map/actions/variables --jq .total_count
gh api repos/tiavelum/git-alias-map/hooks --jq length
gh api repos/tiavelum/git-alias-map/keys --jq length
gh api repos/tiavelum/git-alias-map/collaborators --jq '.[].login'
```

Then archive the source under a new name first, since its issues, pull requests and comments exist nowhere else, then rename the replay; for `tiavelum/mac-config` replayed into `tiavelum/mac-config-new`:

```sh
gh api -X PATCH repos/tiavelum/mac-config -f name=mac-config-archive
gh api -X PATCH repos/tiavelum/mac-config-archive -F archived=true
gh api -X PATCH repos/tiavelum/mac-config-new -f name=mac-config
```

[GitHub redirects a renamed repository](https://docs.github.com/en/repositories/creating-and-managing-repositories/renaming-a-repository) until another repository takes its old name, so the third command ends the redirect from `mac-config` to the archive. For the same reason, run such a replay with `--final-name tiavelum/mac-config`, so that the links its squash messages end in name the repository the replay becomes, not `mac-config-new`.

Then give the replay the settings of the source, such as its merge methods, wiki and description, and turn Actions on again. These commands show the source's settings, then turn Actions on, merge commits off and the description empty, as for `tiavelum/mac-config`, whose source allowed no merge commits and had no description:

```sh
gh api repos/tiavelum/mac-config-archive --jq '{description, allow_merge_commit, allow_squash_merge, allow_rebase_merge, delete_branch_on_merge, has_wiki, has_projects, has_discussions, visibility, security_and_analysis}'
gh api -X PUT repos/tiavelum/mac-config/actions/permissions -F enabled=true
gh api -X PATCH repos/tiavelum/mac-config -F allow_merge_commit=false -f description=
```

[Update a repository](https://docs.github.com/en/rest/repos/repos#update-a-repository) does not list `has_discussions` among its body parameters, so check after the command that the replay has the source's, with `gh api repos/tiavelum/mac-config --jq .has_discussions`.

Where the source is public and you created the replay private, so that nobody sees it before it is checked, make it public; for `tiavelum/git-alias-map`:

```sh
gh api -X PATCH repos/tiavelum/git-alias-map -f visibility=public
```

Then, where the source has secret scanning and push protection on, as its `security_and_analysis` shows, turn them on in the replay, as [Update a repository](https://docs.github.com/en/rest/repos/repos#update-a-repository) takes them:

```sh
gh api -X PATCH repos/tiavelum/git-alias-map -f 'security_and_analysis[secret_scanning][status]=enabled' -f 'security_and_analysis[secret_scanning_push_protection][status]=enabled'
```

Delete each branch of the replay that the source no longer has, such as the branch of a pull request the source closed unmerged and whose branch it deleted:

```sh
gh api -X DELETE repos/tiavelum/mac-config/git/refs/heads/feat/192-log-date
```

Then replace your local clone of the source with a fresh clone of the replay at the same path, since their histories differ; these show what the old clone holds uncommitted, keep it in `~/vc/git-alias-map-old` for you to delete, and clone the replay; where `~/vc/git-alias-map-old` exists already, remove or rename it first, since `mv` would move the old clone into it:

```sh
test ! -d ~/vc/git-alias-map || { git -C ~/vc/git-alias-map status --short; mv ~/vc/git-alias-map ~/vc/git-alias-map-old; }
gh repo clone tiavelum/git-alias-map ~/vc/git-alias-map
```

## Known limits

- What the target does not get, from reactions, milestones and projects to the branches, tags and releases left behind, [What the target ends with](../docs/replay/what-a-replay-carries.md#what-the-target-ends-with) lists below its list; a release's discussion and the download counts of its assets are not carried either.
- Reviews become comments, and the comparison checks a review's comment against the text the plan wrote and against the review's body, not its line comments, which it does not read again. A review with all its review comments can be longer than GitHub takes for a comment; the plan warns of one over 65'536 characters, the length [GitHub's community reports](https://github.community/t/maximum-length-for-the-comment-body-in-issues-and-pr/148867), since GitHub's REST documentation names none, and the run stops at it.
- Releases have not been carried on GitHub yet. The run downloads an asset with `gh api` and `Accept: application/octet-stream`, to which GitHub [answers with the content or a redirect to it](https://docs.github.com/en/rest/releases/assets#get-a-release-asset), and relies on `gh` following that redirect, which gh 2.105.0 did in a read-only download from a public release, the file byte for byte as its `digest` names it; it uploads to the release's `upload_url`, on `uploads.github.com`, which [Upload a release asset](https://docs.github.com/en/rest/releases/assets#upload-a-release-asset) names, and relies on `gh api` taking that URL whole as its endpoint, which [its manual](https://cli.github.com/manual/gh_api) does not describe. The test's fake follows GitHub's documentation in both, so a trial with a source that has a release with an asset settles them ([#129](https://github.com/tiavelum/github-rewriter/issues/129)).
- GitHub [renames asset filenames that have special characters, non-alphanumeric characters, and leading or trailing periods](https://docs.github.com/en/rest/releases/assets#upload-a-release-asset) on upload, and does not say what they become. The run uploads each asset under the name the source's list gives, which is the name GitHub made of it at its own upload, and takes that name to stay as it is; this is not verified, which the trial of [#129](https://github.com/tiavelum/github-rewriter/issues/129) settles, and the test's fake keeps every name ([#90](https://github.com/tiavelum/github-rewriter/issues/90)). Where GitHub renames it again, the run's check after the last event stops at `has the assets […], planned […]`, and a run resumed after a lost answer of that upload uploads it again, which GitHub refuses as a second asset of that name, until the asset is deleted in the target.
- An unsigned tag whose message ends with a complete signature block pasted into its text, from an opening line such as `-----BEGIN PGP SIGNATURE-----` to its closing line, loses that block: the plan and the comparison cannot tell it by its text from a signature git appended, so both take it for one, and the run recreates the tag without it. A block inside the message, with text after it, stays.
- A carriage return in a commit or tag message does not survive: the scripts read git's output as text, which turns `\r\n` and a lone `\r` into `\n`, so the recreated message has a line break in its place. The comparison reads the target's messages the same way, so it does not see the difference; bodies and comments, which GitHub's JSON carries, keep theirs. Keeping them, and having the comparison see them, is [#130](https://github.com/tiavelum/github-rewriter/issues/130).
- An item is replayed in its final state: one reopened and closed again is closed once, with its labels and assignees as they are now.
- A pull request without commits of its own, or one whose base is not the default branch, is planned with a warning, since GitHub may refuse to create it; the run then stops at it.
- A draft pull request of the source is created as a draft in the target, which the replay creates private, and [Create a pull request](https://docs.github.com/en/rest/pulls/pulls#create-a-pull-request) says that drafts are available in private repositories only with GitHub Team and GitHub Enterprise Cloud. For an account on GitHub Free or Pro, the run therefore likely stops at the first draft, after the events before it are written; this is not verified, since it needs a replay into such an account ([#89](https://github.com/tiavelum/github-rewriter/issues/89)). Before planning such a replay, mark each draft pull request of the source ready for review, so that the replay carries it as ready.
- A source whose default branch is neither `main` nor `master`, such as `develop`, has not been replayed on GitHub yet, nor has a replay for an account that [has set another name for its new repositories](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/managing-repository-settings/managing-the-default-branch-name-for-your-repositories). GitHub then names the target's default branch other than the plan does, and [Changing the default branch](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-branches-in-your-repository/changing-the-default-branch) says that "your repository must have more than one branch" to change it, so whether GitHub lets `replay.py` set it in step 5, once the replay has pushed it, is open until a trial settles it ([#131](https://github.com/tiavelum/github-rewriter/issues/131)). Where GitHub refuses, `replay.py` stops in step 5 at every run: set the default branch on GitHub by hand, as an administrator of the target, once it has more than one branch, then run the same command again. A source whose default branch is `master` was replayed on GitHub on 25 Nov 2026 and compared without a difference ([#83](https://github.com/tiavelum/github-rewriter/issues/83)).

## Documents

| Document | Answers |
|---|---|
| [Running the steps of a replay alone](../docs/replay/running-the-steps-alone.md) | How do I plan a replay, run it and compare its result one script at a time, and what do I check in what each prints? |
| [What a replay carries](../docs/replay/what-a-replay-carries.md) | What does the target end with, what stays with the archive of the source, and how are titles typed and pull requests merged? |
| [Stopping and resuming](../docs/replay/stopping-and-resuming.md) | Where does a run stop, and how does it resume? |
| [The event file and the state file](../docs/replay/file-formats.md) | What do the files hold that the scripts write? |

## Files

| File | Step |
|---|---|
| `replay.py` | Runs a whole replay from a run file: mirrors, plans, creates and sets up the target, replays, compares, moves the sub-issue links and prints the commands that give the replay the source's name |
| `plan-replay.py` | Reads the source from a mirror and from GitHub and writes the event file |
| `run-replay.py` | Applies the event file to an empty target, the assets of its releases downloaded from the source, and keeps the state file, so that a stopped run resumes |
| `compare-replay.py` | Compares the finished target with the source, the event file and the state file, read-only, and names every difference |
| `tests/` | The pytest suite that tests the scripts of this folder, as processes, against a source built in a temporary folder and fake `gh` scripts for the source and the targets, without contacting GitHub, with its fixtures, the fakes and the pinned requirements; `--basetemp <folder>` keeps the folder it builds them in |
