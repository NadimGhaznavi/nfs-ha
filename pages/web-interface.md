---
title: Web interface
author_profile: true
layout: single
---

[Documentation index]({{ site.baseurl }}{% link index.md %})

The web interface at `http://<server>:23300/` displays a dark teal title bar
with the caption “Vigilent since October 2026” and a Drive Configuration table.
Disk 1 is the source at `/exports/disk1`; Disk 2 is the destination at
`/exports/disk2`. Capacity and used space are shown in decimal TB
(1 TB = 1,000,000,000,000 bytes), rounded to two decimal places.
Reload the page to refresh the readings. Missing mounts display “Not mounted”;
failed usage readings display “Unavailable”.
The Disk Health panel reads the latest saved check results and displays their
timestamp in server local time (`YYYY-MM-DD HH:MM:SS`), each disk's status and
details, and email delivery failures.
No recorded result and unreadable or corrupt results have explicit messages.
The Health Check Schedule section reads the installed cron entry to populate
**Enabled** and **Cron Schedule**.
Edit the five-field expression and click **Update** to save it. Uncheck **Enabled**
and click **Update** to remove the job. An absent job shows an empty schedule.
Times use the server's timezone. In Disk Health, click **Run Now** to request a background health check, then reload
to see its completed result. Checks retain their email alerts and overlap protection.
The button is disabled when monitoring is disabled or settings are unavailable.
See [disk health]({{ site.baseurl }}{% link pages/disk-health.md %}) for scheduling.
It listens on all IPv4 interfaces and requires no third-party Python packages.

## Install and manage

On a Linux host with Python 3.10 or newer, systemd with `LoadCredential` support,
cron with the `crontab` command, and a running local MariaDB server with the
`mariadb` client, run from the checkout. Enabled monitoring also needs `smartctl`
and `msmtp` with a configured credential file.
Root must be able to connect to MariaDB through Unix socket authentication.
Schedule controls and manual checks also require `sudo` and `visudo`.

```sh
sudo scripts/install.sh
sudo scripts/upgrade.sh
sudo scripts/restart.sh
```

Installation bundles the server and its page into `/opt/prod/disk-ha/bin/disk-ha-web`,
deploys the Python package and readable CMDB metadata, and enables
`disk-ha-web.service` at boot. The service runs under the persistent `diskha` account;
serving this page requires no root privileges. The account needs directory
access to both mount points to read filesystem usage; it does not read file contents.

## Accounts and database

Installation creates the `diskha` Linux system account and group with a non-login
shell and no separate home directory. Application code stays root-owned;
`/opt/prod/disk-ha/data/` belongs to root and the `diskha` group with mode `0750`.
Root runs scheduled health checks and writes results with mode `0640`;
the Web UI account has read access.
The root-owned `disk-ha-health.service` runs manual checks. Validated rules in
`/etc/sudoers.d/disk-ha-health` let `diskha` start that service and call the
`disk-ha-schedule` helper to read or update only disk-ha's marked root cron entry.
The helper validates settings, preserves unrelated jobs, and keeps the worker's
configuration consistent with GUI updates. The Web UI cannot read mail credentials.
The Web UI is intended for a trusted network; users with page access can update
schedules and request checks.

Following the BMDynIP provisioning pattern, installation creates:

- MariaDB database `diskha`, using `utf8mb4` with `utf8mb4_bin` collation.
- Local MariaDB account `'diskha'@'localhost'` with a generated password.
- Root-owned credentials at `/opt/prod/disk-ha/conf/database.env`, mode `0600`,
  inside the root-only `conf/` directory.

The database account receives `SELECT`, `INSERT`, `UPDATE`, `DELETE`, `CREATE`,
`ALTER`, `INDEX`, and `REFERENCES` privileges on `diskha` only. The database
currently has no application tables.

Systemd supplies a private copy of `database.env` to the service through
`LoadCredential`; the service can read it under `$CREDENTIALS_DIRECTORY`.
The page does not query the database yet.

Upgrade validates and retains saved credentials. If the credential file is
missing, installation generates a new password for the local application
database account while preserving the database. Uninstall preserves both
accounts, the Linux group, the database, credentials, and saved data.

## Service checks

Check readiness and logs:

```sh
curl --fail http://127.0.0.1:23300/ready
systemctl status disk-ha-web.service
journalctl -u disk-ha-web.service
```

Remove the service and application with `sudo scripts/uninstall.sh`.
Upgrade and removal preserve configuration, credentials, and saved data in
`/opt/prod/disk-ha/conf/` and `/opt/prod/disk-ha/data/`.

## Run from a checkout

```sh
python3 -m disk_ha.server
```

Use `--host 127.0.0.1` to listen locally or `--port <port>` to override the port.
Stop the foreground server with Ctrl+C.
