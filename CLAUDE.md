@project-instructions.md

## Claude Code only

- Test: `sh rewrite/test-history-rewrite.sh && .venv/bin/pytest replay/tests`
- Lint: `ruff format --check && ruff check && shfmt -d $(git ls-files '*.sh') && shellcheck $(git ls-files '*.sh')`, with the versions the workflow pins
