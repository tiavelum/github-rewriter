# 0003 Carry reviews as comments

This record states what a replay makes of the reviews of the source's pull requests, for whoever plans or runs a replay with the scripts in `replay/`.

Status: accepted, 16 Nov 2026

## Context

A replay dropped the reviews and review comments of the source's pull requests, but findings stand there, such as those of the agents that check pull requests, and issues refer to them, so after the rename those references led to pull requests without them. A replay cannot submit a review for someone else: GitHub records a review as by the account that submits it. #53 (Decide whether a replay keeps pull request reviews) asked whether a replay keeps them.

## Decision

Carry each submitted review as a comment on its pull request, placed at its submission among the other comments: the reviewer, the review's state and the commit it was made on, then its body and each of its review comments under the file and lines it was made on. A pending review is left out.

## Alternatives considered

1. **Leave reviews in the archive**: no change to the replay, but a reference to a review on a pull request leads to one without it, and the reader has to know to look in the archive.
2. **Submit the reviews again**: each review would be by the account that runs the replay, whoever reviewed in the source, and an approval would count as that account's.

## Consequences

1. Every review's text stays under the pull request's number.
2. The comments are by the account that runs the replay and are not attached to the diff; GitHub counts none of them as an approval.
3. Each review is one more content-creating request of the run, toward GitHub's limit per hour.
