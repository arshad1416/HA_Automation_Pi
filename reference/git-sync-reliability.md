# Git-sync reliability and conflict recovery

The sync job still runs on the Pi every fifteen minutes. It commits new tracked/unignored edits, and independently retries previously committed changes that have not reached `origin/main`. Failed staging, commits and pushes return a nonzero status. A clean working tree alone does not mean the backup is current.

Backlog, recovery, persistent pull-failure and conflict alerts are marked delivered only when `send_telegram` succeeds. Failure retries happen on later cron runs; delivered failure alerts remain suppressed until their incident clears. Backlog recovery means zero unpublished commits, rather than merely dropping below the alert threshold.

## Conflicts pause the job

Before a pull with local tracked edits, the job pins a Git stash snapshot at `refs/ha-git-sync/pre-pull`. If applying the autostash conflicts, it records `.git/ha-git-sync.conflict`, restores the snapshot's original index and working-file contents, and stops. It does not reset the working tree to the remote version. Later cron runs leave those files alone and retry only an undelivered conflict notification.

Git may also keep its own autostash in the stash list. The dedicated recovery ref prevents the snapshot from being garbage-collected. Untracked files are not part of this snapshot; Git normally refuses a pull that would overwrite them.

Owner reconciliation is required before resuming. Inspect locally without pasting household configuration or credential contents into logs:

```sh
git status --short
git stash list
git rev-parse refs/ha-git-sync/pre-pull
git rev-parse --git-path ha-git-sync.conflict
```

Review and reconcile the preserved local edits with the remote changes. The conflict may already be removed from Git's index because the job restored the original index; the explicit marker continues to block sync. Do not remove the marker before reconciliation and validation. If restoring the snapshot failed, its ref remains available and the job stays paused for manual recovery.

After the owner has reconciled the tree, validated configuration, and approved resuming the live job, remove the conflict marker and its `.notified` companion using the paths returned by `git rev-parse --git-path`. Remove the recovery ref only after confirming its contents are no longer needed. Any configuration reload or service restart requires separate approval under AGENTS.md.

## Offline verification

```sh
python3 verification/test_sync_reliability.py
bash verification/test_git_sync_alert.sh
bash verification/preflight.sh
bash -n git-sync.sh verification/preflight.sh
git diff --check
```

With an interpreter that has both PyYAML and Jinja2, the complete verification
directory can also be discovered with
`python3 -m unittest discover -s verification -p 'test_*.py'`.
The climate TOU check is import-safe and exposes its original assertions to
discovery while preserving its direct command-line behavior. Its import-safety
regression also removes a required tariff trigger from a temporary fixture and
confirms that discovery reports the resulting assertion failure.

The reliability tests run the whole sync script with temporary local Git remotes, synthetic configuration, rejected-push hooks and stubbed notification transport. They never contact the Pi, GitHub or Telegram. They cover staged/unstaged edit preservation, conflict pause/retry, failed-push recovery with no new edits, delivery failure and missing YAML parsers.

Preflight now fails when no available interpreter imports PyYAML. Set `PREFLIGHT_PYTHON` to an existing interpreter with PyYAML if necessary. Passing preflight still does not establish Home Assistant semantics or live device operation; the documented Pi `check_config` and approved post-deployment checks remain required.
