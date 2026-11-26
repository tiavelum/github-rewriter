# Stopping and resuming

Where a run of `run-replay.py`, one of the scripts of [`replay/`](../../replay/README.md), stops and how it resumes, for whoever runs a replay.

Ctrl-C stops the run after the event in progress; a second Ctrl-C stops it at once. It reaches a running `git` too, so the run may stop in the middle of an event, which the next run checks and finishes. A run also stops, with a message, at the first of these:

- An issue or pull request gets a number other than the planned one, as when someone else creates an issue in the target during the run; nothing more is done.
- After a merge, the tree of the default branch differs from the source's tree after that merge.
- GitHub refuses a call, answers a write with nothing, or is still rate limited after 5 retries.
- A commit of the push in progress, rebuilt on resuming, gets another hash than the state file records for it; the run stops before the push, so the target never gets a second history.
- A tag, rebuilt on resuming, gets another object than the state file records for it, or the target holds it at another; the run stops before the push, so the target never gets a second tag of that name.
- A downloaded asset has another size, or another SHA-256 digest, than GitHub lists for it in the source.

To resume, find and remove the cause, and run the same command again, with the same `--sign` and `--final-name`; a state file that records other ones stops the run. It checks the target against the state file: its highest number and the commit its default branch is at must be those the state file records. The event that was in progress may account for one difference, and it checks what of it is done: an item with its planned number and title, a comment that is already the last of its item, a merged pull request, a label that exists, a pushed commit, a pushed tag, a release under its tag, an asset of it uploaded whole, by its name, state, size and digest, and a release already published, as [List releases](https://docs.github.com/en/rest/releases/releases#list-releases) shows it, are taken over, not made again. An asset of that name that is not whole, such as the empty one in the state `starter` that GitHub says [an upload that fails may leave](https://docs.github.com/en/rest/releases/assets#upload-a-release-asset), the run deletes and uploads again, since GitHub refuses a second asset of the same name. Where the target differs in another way, the run stops and names the difference. Run on a finished replay, it checks the target again.

A resumed run rebuilds the commits of the push that was in progress, or the tag, and takes the pushed ones over only where they get the same hashes. An Ed25519 SSH key signs the same commit or tag the same way each time, which the test checks for commits; an OpenPGP signature holds the time it was made, and other SSH keys may sign differently each time, so with such a key a run stopped in a push of signed commits, or in a signed tag, stops again there. Replay into a new empty target then, or sign with an Ed25519 SSH key.
