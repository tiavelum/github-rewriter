# Copying the project instructions

How to update the copy of `project-instructions.md` in the claude.ai project "github-rewriter" after a change to the file, for the maintainer of this repository.

Once the change is on `main`, copy the file as `main` holds it, whichever branch the clone has checked out:

```bash
git -C ~/vc/github-rewriter fetch -q origin main && \
  git -C ~/vc/github-rewriter show origin/main:project-instructions.md | pbcopy
```

Then paste it into the instructions field of the claude.ai project "github-rewriter", replacing its content. That field holds a copy, which no tool updates; Claude Code reads the file from its clone through `CLAUDE.md`.
