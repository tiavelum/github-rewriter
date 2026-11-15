# github-rewriter

Scripts for changing the history of a GitHub repository safely: back it up, rewrite the names and addresses of its commits, check that nothing else changed, push, and know what the change leaves behind on GitHub.

## What it is for

Use it when the commits of a repository carry names or addresses that should be one identity, such as an old address or a machine's default name. It does not change the content, dates or messages of a history, and it does not touch a repository's issues or pull requests.

## Getting started

Requires a POSIX shell, git with [git-filter-repo](https://github.com/newren/git-filter-repo) (tested with git 2.43 and git-filter-repo a40bce548d2c), `ssh-keygen` for the signing tests, and Python 3.10 or later for the replay.

```bash
git clone git@github.com:tiavelum/github-rewriter.git ~/vc/github-rewriter
brew install git-filter-repo
sh ~/vc/github-rewriter/rewrite/test-history-rewrite.sh
sh ~/vc/github-rewriter/replay/test-replay.sh
```

The tests run every script in throwaway repositories and contact no server; the first ends with:

```
24 passed, 0 failed
```

The second ends with:

```
30 passed, 0 failed
```

To rewrite a repository, follow the steps in [rewrite/README.md](rewrite/README.md); to plan its replay into a new one, those in [replay/README.md](replay/README.md).

## Content and structure

| Path | Contains |
|---|---|
| [`rewrite/`](rewrite/README.md) | The scripts that rewrite the identities of a repository's history in place, one step each, and their test |
| [`replay/`](replay/README.md) | The script that plans the replay of a repository into a new one, with its issues and pull requests under the same numbers, as an event file, and its test |
| `.github/workflows/` | The workflow that runs the tests on macOS and Linux, and the formatter and linter on the Python files, for every pull request and every push to `main` |
| `project-instructions.md`, `CLAUDE.md` | The rules for Claude working in this repository |

## License

MIT. See [LICENSE](LICENSE).
