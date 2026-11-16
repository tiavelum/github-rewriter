# 0002 Commit recreated commits at the time of the replay

This record states which dates the commits of a replay carry, for whoever plans or runs a replay with the scripts in `replay/`.

Status: accepted, 16 Nov 2026

## Context

`run-replay.py` recreates each commit of the source with `git commit-tree`, and GitHub makes each merge through its merge API, whose body takes no date, so a merge carries the time of the replay. With the original author and committer dates on the recreated commits, a branch that starts on a replayed merge held commits older than their parent, a history no work can make; git accepts it, but walks limited by date, such as `git log --since`, stop at the first commit older than the limit. #62 (Decide which dates the commits of a replay carry) asked which dates the commits carry.

## Decision

Give each recreated commit its original author date and the time of its recreation as committer date, never earlier than the committer date of a parent, as a rebase leaves a history, and keep merging through GitHub. The date is recorded in the state file before each push, so that a resumed run rebuilds the same hashes.

## Alternatives considered

1. **Keep the original committer dates**: no change, but a branch's commits stay older than the merge they start on.
2. **Original dates on the merges too**, by building each squash commit in the run and pushing it: every commit keeps the source's dates, but GitHub then shows each pull request as closed rather than merged, without the link to its commit and without the Verified mark on the merge, against the choice of #10 (Decide who commits the replayed squash merges in mac-config-new) to merge through GitHub.

## Consequences

1. Every original time stays in an author date; the committer dates of a replay are those of its run.
2. A state file written before this decision has no committer dates; its run keeps the original ones, also when resumed, and the comparison expects them.
3. `SOURCE_DATE_EPOCH` fixes the time of the recreation, which the test uses so that two runs build the same hashes.
