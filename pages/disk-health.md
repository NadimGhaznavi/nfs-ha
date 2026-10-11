---
title: Disk health classes
---

[Documentation index]({{ site.baseurl }}{% link index.md %})

The Python classes model `/opt/dev/utils/bin/check-disks.sh`:

| Layer | Class | Responsibility |
| --- | --- | --- |
| Entity | `Disk` | Validated stable device path under `/dev/disk/by-id/` |
| Entity | `DiskHealth` | SMART result and failure/degradation rules |
| Entity | `DiskCheckReport` | Combined text report and exit status |
| Interface | `SmartInspection` | Block-device check and bounded `smartctl -H -A` command |
| Interface | `EmailNotification` | Bounded msmtp delivery using an external credential file |
| Activity | `CheckDisks` | Inspect both disks and send one combined alert on problems |

Construct `CheckDisks` with two distinct `Disk` objects, a hostname,
`SmartInspection.inspect`, and `EmailNotification.send`. Command timeouts,
sender, recipient, and msmtp configuration path are required caller settings.
`run()` returns a report; callers print `report.render()` and use
`report.exit_status` (0 for healthy disks, 1 for problems or failed delivery).

The health policy flags smartctl exit bits 0–5 and positive raw values for ATA
attributes 5, 187, 196, 197, and 198. Unsupported attributes are skipped.
Missing devices, command failures, absent overall ATA health results, and
malformed monitored values produce failures. Bits 6–7 alone do not raise an
alert, matching the script. Raw SMART output accompanies disk problems.
Both standard and brief ATA attribute tables are parsed using their RAW_VALUE
column. Email delivery failure is recorded separately from disk health.

## Scheduling and results

Installation deploys `/opt/prod/disk-ha/bin/disk-ha-check` and creates a root-owned
`/opt/prod/disk-ha/conf/health.json` (mode `0600`) if it does not exist. Monitoring
is enabled daily at 14:00 server time (`0 14 * * *`), using the existing script's
two stable disk paths and email sender and recipient. The existing
`/root/.msmtprc` supplies credentials; installation does not create or copy it.
Both command timeouts start at 30 seconds.
Change **Enabled** and **Cron Schedule** in Health Check Schedule and click **Update**.
The field reads the actual root cron entry on every page load. An absent entry
shows disabled monitoring and an empty expression. Updates preserve unrelated jobs
and update `health.json`; a cron write failure restores the previous settings.
To change disk paths, timeouts, or the `mail` object (`recipient`, `sender`,
`config_path`, and `timeout`), edit `health.json`, then run `sudo scripts/upgrade.sh`.
Expressions support numbers, wildcards, ranges, lists, and steps; cron uses the
server's configured timezone. Upgrades retain the live cron schedule and reflect
external removal as disabled monitoring.

The installer maintains one `disk-ha-health-check` entry in root's crontab,
preserving unrelated jobs, and enables `cron.service` when monitoring is enabled.
Root is required to inspect the block devices and access the configured msmtp
credential file. The worker rechecks `enabled` and skips overlapping runs using
a file lock. Schedule edits during a check report an error; retry after it completes.

The latest completed check replaces `/opt/prod/disk-ha/data/health.json`
atomically. It stores a server-local timestamp with a timezone offset and
second precision, both disks' SMART results and raw output,
and any notification failure. The result belongs to root and the `diskha` group
with mode `0640`; `data/` is root-owned with mode `0750`, so the Web UI can read
results without changing them. The Web UI reads this file on each page request
and shows the last recorded result and local timestamp (`YYYY-MM-DD HH:MM:SS`),
along with the cron schedule. **Run Now** requests the root-owned `disk-ha-health.service` in the
background; reload the page after the check completes. The service uses the same
configuration, result file, overlap lock, and log as cron. Disabled monitoring
also prevents manual checks. The Web UI does not access mail credentials.
Missing and corrupt files have explicit display states.

Cron appends reports, skipped-run messages, and command failures to
`data/health.log`. A disabled or overlapping run preserves the previous result.
A configuration or persistence failure exits with status 1 and leaves the last
completed result in place; check its timestamp and the log.
Mail credentials stay in the external msmtp file and are not logged.
**Email disk report** uses the configured mail recipient and runs `smartctl -x`
on both disks after a normal `smartctl -H -A` health check. The normal check
determines disk health; optional extended-command failures remain visible in the
report without changing that verdict. It emails one report with full SMART output
even when both disks pass. Emails include an HTML report with a table of contents,
health summary, per-disk identity and SMART attribute tables, and full diagnostics.
A plain-text alternative is included for mail clients that do not display HTML. The command is `disk-ha-check --email-report`, run as root. This request
works with scheduling disabled and waits on the shared health-check lock.
Delivery errors are saved with the latest health result; detailed reports and
command failures are written to `data/health.log`.
Upgrade and removal preserve configuration, results, and logs. Removal deletes
the named cron entry, manual-check and email-report services, sudo permissions, and checker and
schedule-helper executables.

## Troubleshooting

A `FAIL` result can mean the inspection failed, rather than a failed drive. Read
the saved `smart_output` in `data/health.json` or the report in `data/health.log`.
Extended SMART queries may fail on unsupported optional commands.

A missing msmtp configuration produces an explicit notification failure. The
configured `mail.config_path` must point to an existing root-readable msmtp file
with the `default` account. Installation does not provision SMTP credentials.
For other mail failures, consult msmtp's configured logfile or syslog; diagnostics
and credentials are not exposed in the Web UI.
