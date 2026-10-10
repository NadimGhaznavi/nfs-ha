---
title: Web interface
author_profile: true
layout: single
---

[Documentation index]({{ site.baseurl }}{% link index.md %})

The web interface at `http://<server>:23300/` displays a dark teal title bar
with the caption “Vigilent since October 2026” and an empty content area.
It listens on all IPv4 interfaces and requires no third-party Python packages.

## Install and manage

On a Linux host with Python 3.10 or newer, systemd with `LoadCredential` support,
and a running local MariaDB server with the `mariadb` client, run from the checkout.
Root must be able to connect to MariaDB through Unix socket authentication.

```sh
sudo scripts/install.sh
sudo scripts/upgrade.sh
sudo scripts/restart.sh
```

Installation bundles the server and its page into `/opt/prod/disk-ha/bin/disk-ha-web`,
deploys the Python package and readable CMDB metadata, and enables
`disk-ha-web.service` at boot. The service runs under the persistent `diskha` account;
serving this page requires no root privileges or disk access.

## Accounts and database

Installation creates the `diskha` Linux system account and group with a non-login
shell and no separate home directory. Application code stays root-owned;
`/opt/prod/disk-ha/data/` belongs to `diskha` with mode `0700`.

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
