# 0001 Replay into a new repository

Status: accepted, 15 Nov 2026

## Context

The commits of a repository carry identities that should become one, and their titles lack the type that pull request titles now need. Changing a commit changes its hash and every hash after it, so the history has to be written anew. On GitHub a repository's history is not only its commits: issues and pull requests number in one sequence, pull request pages show the commits they merged, and squash commits name their pull request as `(#N)`. Whatever replaces the history decides what becomes of those.

## Decision

Replay the repository into a new, empty repository with `replay/plan-replay.py` and `replay/run-replay.py`: every commit recreated in order with mapped identities and typed titles, every issue and pull request recreated in number order, so it keeps its number, and every pull request merged again through GitHub. The source stays as it is, as the record of the original, and is archived and renamed once the replay is checked, so the replay can take over its name.

## Alternatives considered

1. **Rewrite in place** with `rewrite/`: keeps every issue, pull request, date and message, but leaves the pull request pages showing the old commits with the old identities, and needs a force push of the default branch, which GW-16 of the engineering standards forbids; a rule of the owner has to override it.
2. **Replay into the same repository**: pull requests cannot be deleted, except by GitHub Support where they hold [sensitive data](https://github.community/t/delete-an-unmerged-pull-request/118488), so every replayed item would stand as a duplicate beside its original under a new number.
3. **Fork first, then rewrite**: a fork has [its own issues and pull requests](https://docs.github.com/en/pull-requests/reference/forks) and copies none, and [a private repository's private forks are deleted with it](https://docs.github.com/en/pull-requests/collaborating-with-pull-requests/working-with-forks/what-happens-to-forks-when-a-repository-is-deleted-or-changes-visibility), so a fork is no backup of a private repository.

## Consequences

1. Numbers stay: a link to `…/issues/N` of the source's name reaches the replayed item once the replay holds that name, since [a renamed repository redirects](https://docs.github.com/en/repositories/creating-and-managing-repositories/renaming-a-repository) only until another repository takes its old name.
2. Dates of creation, comments and merges are those of the replay; the source keeps the original ones. Commit dates stay.
3. Every commit gets a new hash; hashes in later text are replaced, older links to a hash reach only the archived source.
4. Reactions, reviews and timeline events beyond closing and merging are not replayed.
5. Nearly every event is a content-creating request, which GitHub [limits per minute and per hour](https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api), so the run is paced and a large source takes hours.
