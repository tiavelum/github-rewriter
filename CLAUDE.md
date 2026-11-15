@project-instructions.md

## Claude Code only

- Test: `sh rewrite/test-history-rewrite.sh && sh replay/test-replay.sh`
- Lint: `ruff format --check && ruff check && shfmt -d $(git ls-files '*.sh') && shellcheck $(git ls-files '*.sh')`, with the versions the workflow pins
