Repository tiavelum/github-rewriter.

Scripts and a procedure for rewriting or replaying the history of a GitHub repository, kept so that each run repeats and improves the last.

- Record what a run hit in its own issue, as ISS-19 says, and a decision that constrains future runs in `docs/decisions/`.
- Commit no mailmap, export or test data with a real person's address other than the account owner's; tests use invented identities.
- A script that pushes, deletes or changes a setting on GitHub asks for confirmation first, and its test runs without contacting GitHub.
- Done: run `sh rewrite/test-history-rewrite.sh` and `sh replay/test-replay.sh`. If you cannot run them, wait for the CI run of your commit and report its result.
