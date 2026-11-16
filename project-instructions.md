Repository tiavelum/github-rewriter.

Scripts and a procedure for rewriting or replaying the history of a GitHub repository, kept so that each run repeats and improves the last.

- Read tracking issue #6 before working here, and update its state section whenever an issue starts, finishes or blocks.
- Record what a run hit in its own issue, as ISS-19 says; what the work teaches about recording and learning goes into #8, and a decision that constrains future runs into `docs/decisions/`.
- Commit no mailmap, export or test data with a real person's address other than the account owner's; tests use invented identities.
- A script that pushes, deletes or changes a setting on GitHub asks for confirmation first, and its test runs without contacting GitHub.
- Done: run `sh rewrite/test-history-rewrite.sh` and `sh replay/test-replay.sh`. If you cannot run them, wait for the CI run of your commit and report its result.
