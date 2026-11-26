# github-rewriter

Scripts for changing the history of a GitHub repository safely, in one of two ways: rewrite the names and addresses of its commits in place, or replay the repository into a new one, with its issues, pull requests, comments and labels under the same numbers.

## What it is for

Use the rewrite when the commits of a repository carry names or addresses that should be one identity, such as an old address or a machine's default name: it backs the repository up, rewrites the identities, checks that nothing else changed and pushes; it changes no content, dates or messages, and no issues or pull requests. Use the replay when the history should start over in a new repository, also with typed titles and squash merges instead of merge commits, and leave the original as it is: it recreates the commits, issues, pull requests, comments, reviews (as comments), labels, tags and releases, with their assets, in an empty repository, with the original author and tag dates and, as after a rebase, the time of the replay as committer dates, and with the time of the replay on items, comments, merges and releases, and names what it leaves to the original, such as branches without a pull request. Neither renames, archives or deletes a repository.

## Getting started

Requires a POSIX shell, git with [git-filter-repo](https://github.com/newren/git-filter-repo) (tested with git 2.43 and git-filter-repo a40bce548d2c), `ssh-keygen` for the signing tests, and Python 3.10 or later and git 2.38 or later for the replay's test, a pytest suite that needs [pytest 9.2.0, which runs on Python 3.10 to 3.15](https://pypi.org/project/pytest/9.2.0/) and which the commands below install into a virtual environment of the clone; what a replay itself needs is in [replay/README.md](replay/README.md).

```bash
git clone git@github.com:tiavelum/github-rewriter.git ~/vc/github-rewriter
brew install git-filter-repo
sh ~/vc/github-rewriter/rewrite/test-history-rewrite.sh
python3 -m venv ~/vc/github-rewriter/.venv
~/vc/github-rewriter/.venv/bin/pip install -q \
  -r ~/vc/github-rewriter/replay/tests/requirements.txt
~/vc/github-rewriter/.venv/bin/pytest ~/vc/github-rewriter/replay/tests
```

The tests run every script in throwaway repositories and contact no server; the first ends with:

```
24 passed, 0 failed
```

The second, the pytest suite of the replay, takes three to six minutes and ends with a line such as:

```
======================= 199 passed in 371.16s (0:06:11) ========================
```

Without `ssh-keygen`, it skips the 12 tests of signing with an SSH key, names them, and counts them as skipped.

Where `~/vc/github-rewriter/.venv/bin/pytest ~/vc/github-rewriter/replay/tests` runs the whole suite, a test's node id runs that test alone, in seconds, as `~/vc/github-rewriter/.venv/bin/pytest ~/vc/github-rewriter/replay/tests/test_plan_replay.py::test_writes_the_plan_and_prints_the_totals_without_warnings` does.

To rewrite a repository, follow the steps in [rewrite/README.md](rewrite/README.md); to replay it into a new one with one command, those in [replay/README.md](replay/README.md). To have Claude prepare, plan and check a replay with you, ask it to replay the repository: Claude Code finds the skill in `.claude/skills/` of a clone of this repository, and the Claude app once it is uploaded as below.

## Testing a pull request on macOS

```bash
gh pr edit <number> -R tiavelum/github-rewriter --add-label test-macos
```

This starts the tests on macOS for that pull request, beside those on Linux, and for each later push to it; the run shows the check `test (macos-15)` with its result. Add the label where the change was not tested with the commands of "Getting started" on a Mac, since macOS runs the tests under its own `/bin/sh`, bash 3.2, and the BSD tools, which have found defects that Linux let pass; without it, a pull request waits for no macOS runner, which often queues for longer than the tests take ([#75](https://github.com/tiavelum/github-rewriter/issues/75)). A push to `main` always runs the tests on macOS too, so a defect that only macOS finds shows there after the merge at the latest. To run both on a branch without a pull request (a run started by hand does not report its checks on a pull request, so set the label there):

```bash
gh workflow run test -R tiavelum/github-rewriter --ref <branch>
```

## After changing the skill

Package the skill as a ZIP that holds its folder:

```bash
cd ~/vc/github-rewriter/.claude/skills
rm -f ~/Downloads/replay-repository.zip
zip -q -r ~/Downloads/replay-repository.zip replay-repository -x '*.DS_Store'
```

Then upload `~/Downloads/replay-repository.zip` in the Claude app: in the sidebar, open More, which shows the plugins, connectors and skills, then click Add and Upload a skill.

## After changing the project instructions

Once the change is on `main`, copy the file:

```bash
git -C ~/vc/github-rewriter pull --ff-only && pbcopy < ~/vc/github-rewriter/project-instructions.md
```

Then paste it into the instructions field of the claude.ai project "github-rewriter", replacing its content. That field holds a copy, which no tool updates; Claude Code reads the file from its clone through `CLAUDE.md`.

## Content and structure

| Path | Contains |
|---|---|
| [`rewrite/`](rewrite/README.md) | The scripts that rewrite the identities of a repository's history in place, one step each, and their test |
| [`replay/`](replay/README.md) | The scripts that plan the replay of a repository into a new one, with its issues and pull requests under the same numbers, as an event file, apply that file to an empty repository and compare the result with the source, the script that runs them in turn from one run file, and their test |
| `.claude/skills/` | The skill `replay-repository`, with which Claude takes a replay from the owner's first answers to the replay holding the source's name, using the scripts of [`replay/`](replay/README.md) |
| `.github/workflows/` | The workflow that runs the tests on Linux, and the formatters and linters, for every pull request and every push to `main`, and the tests on macOS too for every push to `main` and every pull request labelled `test-macos`, see [Testing a pull request on macOS](#testing-a-pull-request-on-macos) |
| `project-instructions.md`, `CLAUDE.md` | The rules for Claude working in this repository |

## License

MIT. See [LICENSE](LICENSE).
