# 0001 Replay into a new repository

This record states why a repository is replayed into a new one, rather than rewritten in place or forked, for whoever plans or runs a replay with the scripts in `replay/`.

Status: accepted, 15 Nov 2026

## Context

The commits of a repository carry identities that should become one, and their titles lack the type that pull request titles now need. Changing a commit changes its hash and every hash after it, so the history has to be written anew. On GitHub a repository's history is not only its commits: in tiavelum/mac-config, the first source, issues and pull requests share one sequence of numbers, pull request pages show the commits they merged, and squash commits name their pull request as `(#N)`. Whatever replaces the history decides what becomes of those.

## Decision

Replay the repository into a new, empty repository with `replay/plan-replay.py` and `replay/run-replay.py`: every commit of the default branch and of the pull requests' branches recreated in order with mapped identities and typed titles, every issue and pull request recreated in number order, so it keeps its number, and every pull request that the source merged merged again. The source stays as it is, as the record of the original, and is archived under a new name once the replay is checked, so the replay can take over its name.

## Alternatives considered

1. **Rewrite in place** with `rewrite/`: keeps every issue, pull request, date and message, but leaves the pull request pages showing the old commits with the old identities, and needs a force push of the default branch, which [GW-16 of the engineering standards](https://github.com/tiavelum/engineering-standards/blob/main/standards/git-workflow.md) forbids; an instruction of the owner for the task has to override it.
2. **Replay into the same repository**: pull requests cannot be deleted, except by GitHub Support where they hold [sensitive data](https://github.community/t/delete-an-unmerged-pull-request/118488), so every replayed pull request would stand as a duplicate beside its original under a new number.
3. **Fork first, then rewrite**: a fork can have [its own issues and pull requests](https://docs.github.com/en/pull-requests/reference/forks), and the source's stay in the source, so the fork holds only the git data; and [a private repository's private forks are deleted with it](https://docs.github.com/en/pull-requests/collaborating-with-pull-requests/working-with-forks/what-happens-to-forks-when-a-repository-is-deleted-or-changes-visibility), so a fork is no backup of a private repository.

## Consequences

1. Numbers stay: a link to `…/issues/N` under the source's name reaches the replayed item once the replay holds that name, since [a renamed repository redirects](https://docs.github.com/en/repositories/creating-and-managing-repositories/renaming-a-repository) only until another repository takes its old name.
2. The replay's items, comments and merges are by the account that runs it, at the time of the replay, and so is each squash commit a merge makes; the source keeps the original authors and times. See [What the target ends with](../../replay/README.md#what-the-target-ends-with).
3. Every commit gets a new hash; hashes in later text are replaced, and a link to an old hash works only under the archived source's new name.
4. The run is paced for GitHub's [limits on content-creating requests](https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api), so a large source takes hours.
