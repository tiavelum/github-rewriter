# Uploading the skill

How to upload the skill `replay-repository` to the Claude app after a change to it, for the maintainer of this repository.

Once the change is on `main`, package the skill as `main` holds it, whichever branch the clone has checked out, into a ZIP that holds its folder:

```bash
git -C ~/vc/github-rewriter fetch -q origin main && \
  git -C ~/vc/github-rewriter archive --format=zip \
    --prefix=replay-repository/ -o ~/Downloads/replay-repository.zip \
    origin/main:.claude/skills/replay-repository
```

Then upload `~/Downloads/replay-repository.zip` in the Claude app: in the sidebar, open More, which shows the plugins, connectors and skills, then click Add and Upload a skill.
