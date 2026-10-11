# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/)
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

This release is in memory of the **Falkland Fox** who were wiped out by 1876.

### Added

- Sync Now button beside the Data Sync Schedule Update button for guarded background mirroring.

## [1.0.0] - 2026-10-10 @ 20:06

This release is in memory of the **Elephant Bird** which died around 1000 CE.

### Added

- Data Sync Schedule with editable cron controls, an every-four-hours default,
  guarded Disk 1 to Disk 2 mirroring with deletion propagation, and a separate
  page for the most recent verbose rsync output.

- Role column in Drive Configuration identifying Disk 1 as Source and Disk 2 as Target.

## [0.5.0] - 2026-10-10 @ 19:45

This release is in memory of the last **Dodo** who died in 1681.

### Added

- Email Notification section showing the configured contact and an Email disk report
  button for fresh, verbose SMART results from both disks.

### Changed

- Moved cron controls into a separate Health Check Schedule section.
- Renamed the constants module and class to `DDiskHA` and updated release tooling.

## [0.4.2] - 2026-10-10 @ 19:00

In memory of the **Cave Bear**, the last of which died out around 24,000 years ago.

### Changed

- Last health-check times are recorded and displayed in server local time with
  second precision.
- Disk Health scheduling follows CMDB's Enabled, Cron Schedule, and Update controls,
  populated from the live cron entry and retained across upgrades.

## [0.4.1] - 2026-10-10 @ 18:45

In memory of the **Barbary Lions**, who died out in the 20th century.

### Added

- Disk Health panel shows the configured cron schedule and a Run Now button
  to request a background health check.

## [0.4.0] - 2026-10-10 @ 18:02

In memory of the **Aurochs** that went extinct in 1627.

### Added

- Configurable cron health checks with atomic flat-file results, a Web UI health
  panel, and preservation of settings and results across upgrades and removal.
- Disk health entities, SMART and email interfaces, and a check activity modeling
  the existing script, with bounded commands and explicit unavailable-result
  and notification-failure reporting.

## [0.3.4] - 2026-10-10 @ 17:21

The **Zofia** release is dedicated to [Zofia Szmydt](https://en.wikipedia.org/wiki/Zofia_Szmydt).

### Added

- Drive Configuration table showing capacity and used space in TB for Disk 1
  and Disk 2, with explicit states for unmounted or unreadable drives.

## [0.3.2] - 2026-10-10 @ 17:03

### Added

The **Yvonne** release is dedicated to [Yvonne Choquet-Bruhat](https://en.wikipedia.org/wiki/Yvonne_Choquet-Bruhat).

- Dark teal web interface title bar with the caption “Vigilent since October 2026”.

## [0.3.0] - 2026-10-08 @ 18:03

### Changed

- Rebrand the project, Python package, service, installation paths, and accounts
  to disk-ha, with documentation at `https://diskha.osoylace.com`.
- Added Jekyll theme for GitHub Pages.

## [0.2.0] - 2026-10-08 @ 05:13

### Added

- Blank web interface on port `23300`, with a bundled server and systemd service
  managed by installation, upgrade, restart, and uninstall scripts.
- Dedicated `diskha` Linux service account and local MariaDB account and database,
  with protected credentials preserved across upgrades and removal.

## [0.1.0] - 2026-10-08 @ 04:48

### Added

- Project development guidance for disk monitoring, safe mirroring, installation,
  verification, and releases.
- Installation, upgrade, and uninstall scripts targeting `/opt/prod/disk-ha`,
  preserving configuration and saved data.
- Python constants for version and CMDB discovery metadata.
- Release script to update version, codename, and changelog, publish through
  `dev` and `main`, and create the next feature branch.
