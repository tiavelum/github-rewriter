---
name: replay-repository
description: Replay a GitHub repository into a new, empty one with the scripts of tiavelum/github-rewriter, keeping issue and pull request numbers. Use when asked to replay a repository or start its history over.
---

# Replay a repository

These steps take a replay from the owner's first answers to the replay holding the source's name. The commands, the run file's fields and what each script prints are in `replay/README.md` of tiavelum/github-rewriter; read it from `main` before the first step, and take each command from the part these steps name.

## Roles

- You survey the source, ask the owner every question in one round, plan until the types are settled, write the run file, read every output, check the result and record the run.
- The owner runs `replay.py` on their own machine with their own `gh`, since a Claude session's access to GitHub refuses to create repositories and change their settings and adds a footer to every body it creates. The owner also runs the commands it prints at the end, which archive and rename repositories and delete branches.
- Give each step of the owner's as one command block. Leave every git step over SSH to the owner's machine; a Claude session has no SSH.

## The run's issue

Open an issue in tiavelum/github-rewriter titled `Run: replay <source> into <target>` as soon as the owner names the source. Keep in its description the owner's answers, the types table and every field of the run file but the mailmap, so that a new session can resume from the issue alone. Describe the mailmap's lines by the identities they map, without the addresses the owner keeps private.

Record there too where the run file, the mirror and the event file lie on the owner's machine, each stop with its step, cause and fix, and the steps the owner reports after the run. When you take over a run, read its issue first, then ask the owner for the last lines of `replay.py` before you give a command.

## Ask the owner

Ask these in one round, each with your recommendation, before planning, and record each answer on the run's issue. Each answer that names a field becomes that field of the run file, as "Replaying with one command" names them.

1. **Replay or rewrite**: replay into a new repository, or rewrite the identities in place. Recommend the replay for the reasons of `docs/decisions/0001-replay-into-a-new-repository.md`. For a rewrite, follow `rewrite/README.md` instead of these steps.
2. **Identities**, for `mailmap`: list every identity of the source as author and as committer, with the commands of the next section, and ask which are the owner's, what becomes of `GitHub <noreply@github.com>` as the committer of changes made on github.com, of Claude as a committer, and of any test identity.
3. **Merge commits**, for `keep_merges`: squash merges, or merge commits kept.
4. **Types**, for `no_types` and `types`: typed titles, or titles as they are; with types, the owner confirms the types table and the squash summaries of the Plan section.
5. **Signing**, for `sign`: whether the owner's recreated commits are signed, with the requirements "Running a replay" names.
6. **Names**, for `source`, `final_name` and `target`: the source, the name the replay takes over at the end, and the day and time of the run, which give the target's temporary name.
7. **Times**, for `with_times`: whether each body and comment keeps its original creation time.
8. **Pace and places**, for `pace`, `backup` and `clone_url`: the seconds between two writes, the folder of the mirror and the run's files, and the URL the mirror is cloned from; recommend the defaults of "Replaying with one command", and a URL of the protocol the owner's git uses where that is not SSH.
9. **Left behind**, for `leave_behind`: list the source's tags, releases and branches other than the default branch, with the commands of the next section, and ask which of them only the archive is to keep, since the replay carries no tag and no release and no branch but those of pull requests, as "What a replay leaves behind" describes. Where the owner wants one in the replay, stop and say so on the run's issue, since the replay cannot carry it yet.
10. **Trial**: recommend a trial into a throwaway private repository first where the run uses an option, such as `sign` or `keep_merges`, that no earlier run's issue in tiavelum/github-rewriter records. For it, give `final_name` a throwaway name under the owner, such as `<repo>-trial`, and have the owner run none of the commands `replay.py` prints at its end; the owner deletes the target once its check holds.

## Survey the source

Have a mirror made as "Planning a replay" shows, then count the identities in it:

```sh
git -C "$mirror" log --all --format='%an <%ae>' | sort | uniq -c | sort -rn
git -C "$mirror" log --all --format='%cn <%ce>' | sort | uniq -c | sort -rn
```

Show them to the owner as a table of identities with their counts as author and as committer, and write the mailmap lines from the answers, as "Planning a replay" describes.

List the source's branches, tags and releases, with the owner and name of the source for `<owner>/<repo>`:

```sh
git -C "$mirror" for-each-ref --format='%(refname:short)' refs/heads/ refs/tags/
gh api 'repos/<owner>/<repo>/releases?per_page=100' --jq '.[] | "\(.tag_name) \(.draft)"'
```

GitHub lists draft releases only to those who can push to the source, so where this session cannot, have the owner run the second command.

## Plan

1. Plan once with the mailmap and with the lines the owner accepted for `leave_behind` in a file given to `--leave-behind`, as "Planning a replay" and "What a replay leaves behind" show, and read every line it prints. Where it stops at what it leaves behind, put each line it names that the owner has not accepted to the owner, as question 9 asks.
2. For each title it changed with `guessed`, such as that of a commit pushed directly to the default branch, propose a type from the commit's subject and the files it changes.
3. Read each squash message it wrote for a pull request merged with a merge commit against that pull request, and propose a `summary` line where the summary misses what the pull request did.
4. Show the owner the types and summaries as one table of hash or number, type or summary, and subject; take the confirmed ones into the `types` lines and plan again.
5. Repeat until the owner confirms the output and it reports no guessed types, since `replay.py` stops at a guessed type.

Where this session cannot read the source, give the owner the planning commands to run and read the output they paste.

## Run

1. Check with the owner the requirements "Replaying with one command" names, among them the git protocol of `gh` and the rights to create a repository and change its settings, since `replay.py` stops otherwise.
2. Give the owner one command block that writes the run file outside any repository, with every field from the answers, and runs `replay.py` on it. Have them compare the totals and changed titles it prints before its prompt with those of your last plan, and answer the prompt only where they agree, and have them send you the paths of the mirror and the event file that it prints.
3. Ask the owner to keep the machine awake until `replay.py` prints its last step.
4. When it stops, ask for its last lines, find the cause from the step it names and from "Stopping and resuming", and have the owner run the same command again once the cause is removed.

## Check

1. Ask the owner for the output of the comparison step, and record it on the run's issue; `replay.py` goes on to the links only where it found no difference.
2. Compare the target with the source yourself, read-only, as "Comparing the replay with its source" describes what the comparison covers: each point of its list, with the recreated commits and the pull request heads among them. Look in particular for a footer the source lacks and a `Co-authored-by` line added twice by a merge.
3. Record the result on the run's issue.
4. Have a `checker` agent that did not see the run check the same points against the source and the event file. Name in its brief the addresses the target may hold, and have it report any other address only by where and how often it occurs, in place of the passage, since a checker tends to name the private values it finds.
5. List for the owner what a Claude session cannot read and the owner checks before archiving: the source's secrets, variables, webhooks, deploy keys and collaborators.

## Take over the name

1. Have the owner run, in their order, the commands `replay.py` printed in its last step, as "Taking over the source's name" explains them, once the checks hold.
2. Read the sub-issue links it moved, and record them on the run's issue.
3. Record each step on the run's issue as the owner reports it, and close the issue once the last one is done.
4. Remind the owner to delete the files the last line of `replay.py` names, among them the progress file and the state file, once the replay is checked.
