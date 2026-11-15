# rewrite

How to change the author and committer names and addresses of every commit in a GitHub repository with the scripts of this folder, for the owner of that repository.

The scripts change the identities through a [mailmap](https://git-scm.com/docs/gitmailmap) and keep dates, messages and content. They need `git-filter-repo`. Each runs one step and takes its inputs as arguments; run without arguments, each prints its usage.

## Steps

A mailmap maps one identity per line, for authors and committers alike. These two lines give every commit made under either address one identity:

```
Andreas Tiefenauer <tiavelum@gmail.com> <old@example.com>
Andreas Tiefenauer <tiavelum@gmail.com> <tiavelum@gmail.com>
```

The steps, for `tiavelum/claude-setup` with the mailmap in `~/rewrite-mailmap`:

```sh
cd ~/vc/github-rewriter/rewrite
./backup-mirror.sh tiavelum/claude-setup                    # mirror in ~/vc-backup
dir=$(./rewrite-identities.sh tiavelum/claude-setup ~/rewrite-mailmap | tee /dev/stderr | tail -n 1)
./sign-commits.sh "$dir" tiavelum@gmail.com                 # your own commits, signed again
./compare-rewrite.sh "$dir"                                 # same commits, dates and tree
./force-push-rewrite.sh "$dir"                              # asks for the name, then pushes
./reset-clone.sh ~/vc/claude-setup                          # your clone onto the new history
```

`rewrite-identities.sh` prints how often each identity occurs after the rewrite; check it before pushing. It drops every signature, and `sign-commits.sh` signs the commits of the default branch again whose committer has the address you give, with the signing key of your git configuration, before anything is pushed. It leaves the other commits unsigned: a commit that GitHub or someone else committed, signed with your key, would show as unverified rather than unsigned. Given a repository instead of a folder, it signs a fresh clone, for a history that was pushed unsigned. `force-push-rewrite.sh` overwrites the default branch on GitHub and turns off the rulesets that block that for the push only.

## What a rewrite leaves behind

- Every commit gets a new hash, so links to commits point to the old ones, which pull request pages keep showing with the old identities.
- Commits that GitHub or someone else committed lose their signature for good; only your own are signed again.
- GitHub counts each rewritten commit as a new contribution, until GitHub Support rebuilds the counts.
- Other clones must not push before `reset-clone.sh` has moved them, or the old history comes back.

## Files

| File | Step |
|---|---|
| `backup-mirror.sh` | Mirrors the repository, with every branch, tag and pull request ref, into a backup folder |
| `rewrite-identities.sh` | Rewrites the identities of a fresh clone through the mailmap |
| `sign-commits.sh` | Signs again the commits you committed yourself |
| `compare-rewrite.sh` | Checks that the rewrite kept every commit, date and tree |
| `force-push-rewrite.sh` | Overwrites the default branch on GitHub, after you type the repository's name |
| `reset-clone.sh` | Moves a local clone onto the rewritten default branch |
| `test-history-rewrite.sh` | Tests every script in throwaway repositories, without contacting GitHub |
