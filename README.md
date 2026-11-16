# github-rewriter

Scripts for changing the history of a GitHub repository safely, in one of two ways: rewrite the names and addresses of its commits in place, or replay the repository into a new one, with its issues, pull requests, comments and labels under the same numbers.

## What it is for

Use the rewrite when the commits of a repository carry names or addresses that should be one identity, such as an old address or a machine's default name: it backs the repository up, rewrites the identities, checks that nothing else changed and pushes; it changes no content, dates or messages, and no issues or pull requests. Use the replay when the history should start over in a new repository, also with typed titles and squash merges instead of merge commits, and leave the original as it is: it recreates everything in an empty repository, with the original commit dates, but with the time of the replay on items, comments and merges. Neither renames, archives or deletes a repository.

## Getting started

Requires a POSIX shell, git with [git-filter-repo](https://github.com/newren/git-filter-repo) (tested with git 2.43 and git-filter-repo a40bce548d2c), `ssh-keygen` for the signing tests, and Python 3.10 or later and git 2.38 or later for the replay's test; what a replay itself needs is in [replay/README.md](replay/README.md).

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
65 passed, 0 failed
```

To rewrite a repository, follow the steps in [rewrite/README.md](rewrite/README.md); to replay it into a new one, those in [replay/README.md](replay/README.md). To have Claude prepare, plan and check a replay with you, ask it to replay the repository: Claude Code finds the skill in `.claude/skills/` of a clone of this repository, and the Claude app once it is uploaded as below.

## After changing the skill

Package the skill as a ZIP that holds its folder:

```bash
cd ~/vc/github-rewriter/.claude/skills
rm -f ~/Downloads/replay-repository.zip
zip -q -r ~/Downloads/replay-repository.zip replay-repository -x '*.DS_Store'
```

Then upload `~/Downloads/replay-repository.zip` in the Claude app under Customize > Skills: +, Create skill, Upload a skill.

## Content and structure

| Path | Contains |
|---|---|
| [`rewrite/`](rewrite/README.md) | The scripts that rewrite the identities of a repository's history in place, one step each, and their test |
| [`replay/`](replay/README.md) | The scripts that plan the replay of a repository into a new one, with its issues and pull requests under the same numbers, as an event file, and apply that file to an empty repository, with their test |
| `.claude/skills/` | The skill `replay-repository`, with which Claude takes a replay from the owner's first answers to the replay holding the source's name, using the scripts of [`replay/`](replay/README.md) |
| `docs/decisions/` | The decisions that constrain every run, such as why a repository is replayed into a new one rather than rewritten or forked |
| `.github/workflows/` | The workflow that runs the tests on macOS and Linux, and the formatter and linter on the Python files, for every pull request and every push to `main` |
| `project-instructions.md`, `CLAUDE.md` | The rules for Claude working in this repository |

## License

MIT. See [LICENSE](LICENSE).
