---
title: Data synchronization
---

[Documentation index]({{ site.baseurl }}{% link index.md %})

Data Sync Schedule mirrors the contents of `/exports/disk1/` to
`/exports/disk2/`. Deletions on Disk 1 propagate to Disk 2.
The initial cron schedule is `0 */4 * * *`: every four hours at the top of the
hour, in server local time. Edit **Enabled** and **Cron Schedule**, then click
**Update**. The form reads the actual root cron entry; disabling removes it.
Health alerts do not disable synchronization.

## Configuration and safeguards

Installation creates `/opt/prod/disk-ha/conf/sync.json`, owned by root with mode
`0600`. Its source and target mount paths and UUIDs match the disk layout in the
project scope. The finite `timeout` bounds a complete rsync run in seconds; the
initial value is 86400 (24 hours). Adjust these settings in the installed file.
Upgrades preserve settings and the live cron schedule.

Before each sync, the worker checks that both configured filesystems are mounted
at their exact paths and have the expected UUIDs. Missing, wrong, reversed,
identical, nested, indirect, or subdirectory bind mounts prevent rsync from starting.
A shared worker lock prevents overlapping syncs. A schedule edit during a sync
fails clearly; retry after the run finishes. Health checks use a separate lock.

Cron invokes the root-owned `disk-ha-sync` worker, which runs:

```sh
rsync -avr --delete -- /exports/disk1/ /exports/disk2/
```

The trailing slashes mirror contents directly into Disk 2. Both scheduled jobs
have separate markers in root's crontab, and updates preserve unrelated jobs.
The worker does not require the web service to run.

## Output and failures

**Most recent sync output** opens `/sync/output`. It shows the latest rsync
transcript, start and finish timestamps, and an explicit success or failure.
Partial failures and timeouts are recorded as failed; timeout handling terminates
the rsync process group before releasing the sync lock.

Completed attempts atomically replace `data/sync-output.log`, owned by root with
mode `0640` and the `diskha` group. While a sync runs, the page continues to show
the previous transcript. A disabled, overlapping, or mount-rejected run preserves
that transcript. The output page displays filenames as text and streams large logs.

Cron appends skipped-run reasons, completion messages, and command failures to
`data/sync.log`. A failed sync exits with status 1; inspect this log if no new
transcript appears. Upgrade and removal preserve configuration and saved logs.
Uninstall removes disk-ha's sync cron entry and executable.
