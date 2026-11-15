Repository tiavelum/github-rewriter.

Scripts and a procedure for rewriting or replaying the history of a GitHub repository, kept so that each run repeats and improves the last.

- Read tracking issue #6 before working here, and update its state section whenever an issue starts, finishes or blocks.
- A step done by hand during a run becomes a script, or a documented step of the procedure, in the pull request that needed it.
- Documents describe the current way only. What a run hit goes into a comment on that run's tracking issue, what the work teaches about recording and learning into #8, and a decision that constrains future runs into `docs/decisions/`.
- Commit no mailmap, export or test data with a real person's address other than the account owner's; tests use invented identities.
- A script that pushes, deletes or changes a setting on GitHub asks for confirmation first, and its test runs without contacting GitHub.
- Done: run `sh rewrite/test-history-rewrite.sh`. If you cannot run it, wait for the CI run of your commit and report its result.
