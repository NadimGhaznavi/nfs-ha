---
title: Coding Guidelines
author_profile: true
layout: single
---

[Documentation index]({{ site.baseurl }}{% link index.md %})

These are disk-ha's development standards. MUST identifies a requirement;
SHOULD identifies a default whose exceptions need a concrete reason.

## Ownership and scope

The project owner is the architect and release manager. The AI assistant is
the lead developer, responsible for implementation, verification, and documentation.

Changes MUST follow the owner's architecture and the requested scope.
Preserve existing behavior unless the task requires changing it.
Do not expand a task into an unrelated refactor.

`index.md` records the agreed scope: monitor both local disks, notify the
operator of disk failure or degradation, and mirror the primary disk to the
recovery disk on a schedule. Disk replacement and recovery are manual. NFS
configuration, NFS failover, and automatic recovery are outside this project.
Check frequencies and notification settings remain owner decisions; do not
invent production defaults for them.

ANY edits to files outside of the repository MUST be approved by the user.

Git operations and release scripts may be used within the authorized workflow.

## Architecture

- Each component MUST have a clear responsibility and resource owner.
- Transport, domain rules, persistence, background workflows, and presentation
  MUST remain separate.
- Dependencies SHOULD use narrow interfaces or injected callables.
- Construct and connect resources at explicit application entry points.
- Reuse sound distributed patterns where they provide clear ownership or reuse.
- Introduce abstractions and services only for demonstrated requirements.

Where an authoritative model or specification is adopted, implementations MUST
preserve its semantics. Verify inheritance, relationships, and cardinalities
against that source. Do not substitute an ad-hoc schema for the accepted model.

## Project structure

| Location | Responsibility |
| --- | --- |
| `index.md` | Sole documentation root |
| `pages/` | Guides and documentation images |
| `scripts/` | Maintenance and release tooling |
| `disk_ha/` | Python application package |
| `disk_ha/server/` | HTTP transport and static web interface |
| `disk_ha/constants/` | Version, CMDB metadata, and shared project constants |
| `tests/` | Application, installation, and release verification |
| `CHANGELOG.md` | User-visible changes |

Add application modules and default configuration only as implementation
requires them. Installed configuration belongs in `/opt/prod/disk-ha/conf/`;
saved data belongs in `/opt/prod/disk-ha/data/`.

`DDISKHA.VERSION` and `DDISKHA.CMDB_CODENAME` MUST remain single-line literal
strings in `disk_ha/constants/DDISKHA.py` for release tooling and CMDB discovery.
Keep `CMDB_SUBTYPE`, `CMDB_SUPPLIER`, and `INSTALL_DIR` in that same class.

## Configuration and external interfaces

- Validate disk identities, mount paths, synchronization direction, schedules,
  and notification settings at the configuration boundary.
- Before every synchronization, verify that both configured filesystems are
  mounted at their expected paths and match their configured UUIDs. Missing,
  incorrect, identical, or reversed source and destination mounts MUST prevent
  synchronization, especially when deletions propagate.
- Disk health checks MUST inspect both disks and report failure or degradation.
  A health alert MUST NOT itself disable scheduled synchronization; mount
  validation remains mandatory.
- Keep SMART inspection, mount inspection, rsync execution, and notification
  delivery behind interfaces that own their commands and validate results.
- Credentials and secrets MUST NOT appear in logs or command arguments.
- Network and subprocess operations MUST have explicit timeouts.
- Keep shared installation paths and command constants in `DDISKHA`. Keep
  deployment-specific disk identities, paths, schedules, and notification
  settings in configuration.

Internal callers MUST trust validated objects and established contracts.
Expected external failures MUST produce a clear error and a failing exit status.
Programming errors MUST surface rather than being hidden by broad exception handlers.

## Saved state and installation

Synchronization MUST prevent overlapping runs and release locks reliably on
success and failure. Record success only after synchronization completes
successfully; a partial or failed run MUST NOT be reported as a successful
mirror. Logs MUST distinguish health alerts, skipped runs, and command failures.

Tests and routine verification MUST NOT synchronize production disks or send
real operator notifications. Use temporary directories and simulated external
interfaces unless the owner explicitly authorizes a live operation.

Installation targets `/opt/prod/disk-ha` through `DDISKHA.INSTALL_DIR`. The
current installer deploys the Python package, readable CMDB metadata, and a
bundled Web UI executable managed by `disk-ha-web.service`. The Web UI serves a
title bar and an empty content area on port `23300` as the persistent `diskha` Linux account. Installation
provisions the local `diskha` MariaDB database and account, preserving credentials
in `conf/database.env`. Disk workflows, application tables, and scheduling
have not been implemented. See the
[web interface guide]({{ site.baseurl }}{% link pages/web-interface.md %})
for account permissions and credential delivery.

Installation MUST deploy all required application modules and refresh readable
CMDB metadata on upgrade. Uninstallation MUST remove deployed application code
and CMDB metadata, and remove project-owned scheduling when it is implemented.
Reinstallation and uninstallation MUST preserve configuration, saved data,
and credentials. Configuration and credential files MUST have restrictive
permissions. Installation maintenance requires root; application privileges
MUST be chosen for the implemented disk operations and documented explicitly.

## Documentation

Public documentation MUST be short, direct, and task-focused.

Include only what readers need to install, use, or develop the software.
Omit implementation narration, repeated explanations, development history,
and speculative features. Put detailed contracts in one reference and link to it.

- Keep `README.md` brief, with verified setup commands or a link to their guide.
- Every page MUST be reachable from `index.md`.
- Give each page one purpose and YAML front matter with a `title` key.
- Use `site.baseurl` and Jekyll's `link` tag for internal page links.
- Use fenced examples and tables where useful.
- Document verified behavior and commands.
- Credentials and secrets MUST NOT appear in the public site.

## Verification and review

Run checks appropriate to the change. Health-check changes MUST cover healthy
disks, degradation, disk failure, unavailable SMART results, and notification
failure. Synchronization changes MUST cover verified mounts, missing or incorrect
mounts, unsafe source and destination combinations, deletion propagation in
temporary directories, partial rsync failure, and overlapping runs. Verify that
a health alert does not disable an otherwise valid scheduled synchronization.

Installer changes MUST verify deployed modules, readable CMDB metadata,
permissions, upgrades, and preservation of configuration, data, and credentials.
Verify installation and removal of project-owned scheduling when implemented.
Release changes MUST use disposable repositories and a local remote, including
interactive confirmation and version, codename, changelog, branch, and tag updates.

Review architectural changes with `$review-architecture` when available.
These standards apply whether or not the skill is installed.

Reviews MUST identify concrete evidence, consequences, and bounded corrections.
Trace a normal operation and a relevant failure path. Distinguish defects from
preferences; passing tests alone does not establish architectural correctness.

Check documentation front matter, link targets, and navigation.
Inspect rendered output when presentation changes.

If a Jekyll site is configured, let the shared theme own presentation and use
GitHub Pages for builds. Do not add a Gemfile, require local Jekyll builds, or
commit generated site output. Report checks that could not be run.

## Changelog and releases

Record meaningful changes under `## [Unreleased]` in `CHANGELOG.md`.
Keep entries focused on user-visible outcomes.

Release tooling MUST update `DDISKHA.VERSION` and `DDISKHA.CMDB_CODENAME` and
assign the changelog version and timestamp. `scripts/new-release.sh` takes a
version, a message that becomes the codename, and an optional next feature branch.
It runs from a clean, committed feature branch, merges through `dev` and `main`,
and publishes those branches and the annotated version tag to `origin` after
interactive confirmation. Verify project paths, release messages, and owner
authorization before running it against the project's remote.
