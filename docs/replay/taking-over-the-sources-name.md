# Taking over the source's name

How to give a checked replay made with the scripts of [`replay/`](../../replay/README.md) the source's name, for the owner of the source and the target.

Once the replay is checked, give it the source's name, so that links to the source's items reach the replayed ones under the same numbers. `replay.py` moves the sub-issue links itself and prints the other commands of this page for its replay; where you run the steps alone, take them all as follows.

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
