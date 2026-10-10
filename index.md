# disk-ha

This project formalizes two existing scripts for disk health monitoring and
scheduled disk mirroring on Wintermute, a server with two local disks.
Its purpose is to notify the operator when either disk starts failing, giving
them time to act before a second disk failure causes data loss.

## Background

Wintermute was rebuilt, but the automated disk checks and synchronization were
not restored. The omission was discovered on October 8, 2026, and a manual sync
was started. This project should make the setup straightforward to reinstall
and verify after future rebuilds.

The existing scripts are in `/opt/dev/utils/bin`:

- `check-disks.sh` checks both disks using SMART, including overall health and
  attributes that can indicate degradation. It prints a report and sends an
  email alert when it detects a problem.
- `sync-drives.sh` uses rsync to mirror the primary disk to the recovery disk.
  It propagates deletions and writes a synchronization log.

## Disk layout

| Role | Mount point | Filesystem UUID | Existing sync path |
| --- | --- | --- | --- |
| Primary | `/exports/disk1` | `824971c7-d263-4b6a-a562-3452c3482ece` | `/exports/old` |
| Recovery copy | `/exports/disk2` | `b14c1ec0-df91-4f3d-a990-b0c820b81a9c` | `/exports/new` |

Both filesystems are ext4 and are mounted by UUID through `/etc/fstab`.
Synchronization runs from the primary to the recovery copy.

## Agreed scope and behavior

- Check both disks regularly for failure or degradation and notify the operator
  when a problem is detected.
- Synchronize the recovery disk on a schedule.
- Continue scheduled synchronization when a disk health check raises an alert.
- Verify that both expected disks are mounted before synchronization. A missing
  or incorrect mount must prevent that sync run, especially because rsync uses
  `--delete`.
- Make configuration, scheduling, installation, and verification clear enough
  to restore reliably after a server rebuild.

The recovery disk is a mirror: deletions on the primary propagate to it. It does
not retain earlier versions. Monitoring and mirroring reduce the risk of data
loss but cannot guarantee protection against two sudden disk failures.

## Manual response and boundaries

Disk replacement and recovery are manual. On receiving a disk failure alert,
the operator will power down the server, disconnect the drives, obtain one or
two replacements as needed, reconnect the appropriate drives, and synchronize
the replacement storage.

NFS configuration, NFS failover, and automatic recovery are outside this
project's scope.

## Decisions still to make

- Synchronization frequency.

The [web interface]({{ site.baseurl }}{% link pages/web-interface.md %}) currently
displays a title bar and a Drive Configuration table with capacity and usage
in TB for both mounted disks on port `23300`.
[Disk health]({{ site.baseurl }}{% link pages/disk-health.md %}) runs through a
configured cron job and saves results in a flat JSON file displayed by the Web UI.
Health Check Schedule reads and edits the installed cron schedule. The Disk Health
panel provides **Run Now** for a background health check.
The initial schedule checks daily at 14:00 server time and retains the existing
script's email settings. Installed settings are preserved on upgrade.
Scheduled synchronization is not yet implemented.

## Development

[Coding guidelines]({{ site.baseurl }}{% link pages/coding-guidelines.md %})
