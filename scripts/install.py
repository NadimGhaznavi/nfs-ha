"""Install, restart, or remove disk-ha's Web UI; preserve configuration and data."""

import argparse
import fcntl
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener
import zipapp

REPOSITORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY))

from disk_ha.constants.DDISKHA import DDISKHA
from disk_ha.interface.DatabaseProvisioning import DatabaseProvisioning
from disk_ha.interface.SystemAccount import SystemAccount
from disk_ha.interface.HealthConfiguration import HealthConfiguration
from disk_ha.interface.HealthSchedule import HealthSchedule


def systemctl(*arguments: str) -> None:
    subprocess.run([DDISKHA.SYSTEMCTL, *arguments], check=True, timeout=30)


def restart() -> None:
    service = Path(DDISKHA.WEB_SERVICE_FILE).name
    systemctl("restart", service)
    url = f"http://127.0.0.1:{DDISKHA.WEB_PORT}{DDISKHA.WEB_READY_PATH}"
    opener = build_opener(ProxyHandler({}))
    deadline = time.monotonic() + 10
    while True:
        try:
            systemctl("is-active", "--quiet", service)
            with opener.open(Request(url, method="HEAD"), timeout=1) as response:
                if response.status != 200:
                    raise ValueError(f"Web UI returned HTTP {response.status}.")
            break
        except subprocess.CalledProcessError as error:
            if error.returncode != 3:
                raise
            if time.monotonic() >= deadline:
                raise ValueError(f"Web UI service did not become active; check journalctl -u {service}.") from None
        except HTTPError as error:
            status = error.code
            error.close()
            raise ValueError(f"Web UI readiness returned HTTP {status}; check journalctl -u {service}.") from None
        except (URLError, TimeoutError):
            if time.monotonic() >= deadline:
                raise ValueError(f"Web UI did not respond on port {DDISKHA.WEB_PORT}; "
                                 f"check journalctl -u {service}.") from None
        time.sleep(0.1)
    print(f"disk-ha Web UI: active on port {DDISKHA.WEB_PORT} (listening on {DDISKHA.WEB_HOST})")


def install() -> None:
    for executable in ("/usr/bin/python3", DDISKHA.SYSTEMCTL, DDISKHA.MARIADB,
                       DDISKHA.USERADD, DDISKHA.GROUPADD, DDISKHA.NOLOGIN, DDISKHA.CRONTAB,
                       DDISKHA.SUDO, DDISKHA.VISUDO):
        if not os.access(executable, os.X_OK):
            raise ValueError(f"Required executable is missing: {executable}")
    account = SystemAccount.provision()
    root = Path(DDISKHA.INSTALL_DIR)
    upgrading = (root / "bin/disk-ha-check").exists()
    root.mkdir(parents=True, exist_ok=True)
    root.chmod(0o755)
    for name in ("bin", "conf", "data"):
        directory = root / name
        directory.mkdir(exist_ok=True)
        directory.chmod(0o755 if name == "bin" else 0o700)
    # Root writes SMART results; the Web UI group may only read them.
    os.chown(root / "data", os.geteuid(), account.pw_gid)
    (root / "data").chmod(0o750)
    configuration = root / "conf/health.json"
    if not configuration.exists():
        with configuration.open("x") as stream:
            stream.write((REPOSITORY / "conf/health.json").read_text())
    configuration.chmod(0o600)
    health = HealthConfiguration(configuration)
    if health.enabled:
        for executable in (DDISKHA.SMARTCTL, DDISKHA.MSMTP, DDISKHA.CRONTAB):
            if not os.access(executable, os.X_OK):
                raise ValueError(f"Required executable is missing: {executable}")
    log = root / "data/health.log"
    if log.is_symlink() or (log.exists() and (not log.is_file() or log.stat().st_uid != os.geteuid())):
        raise ValueError("Health log must be a regular file owned by root.")
    log.touch(exist_ok=True)
    os.chown(log, os.geteuid(), account.pw_gid)
    log.chmod(0o640)
    DatabaseProvisioning().provision()
    # Stage the package before replacing installed files. Individual replacements
    # are atomic, including the constants file read by CMDB scanners.
    with tempfile.TemporaryDirectory(prefix=".disk-ha-install-", dir=root) as temporary:
        staging = Path(temporary)
        source_root = staging / "source"
        staged = source_root / "disk_ha"
        shutil.copytree(REPOSITORY / "disk_ha", staged,
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        (source_root / "__main__.py").write_text(
            "from disk_ha.server.__main__ import main\nmain()\n")
        archive = staging / "disk-ha-web"
        zipapp.create_archive(source_root, target=archive, interpreter="/usr/bin/python3")
        archive.chmod(0o755)
        archive.replace(root / "bin/disk-ha-web")
        (source_root / "__main__.py").write_text(
            "from disk_ha.health import main\nraise SystemExit(main())\n")
        checker = staging / "disk-ha-check"
        zipapp.create_archive(source_root, target=checker, interpreter="/usr/bin/python3")
        checker.chmod(0o755)
        checker.replace(root / "bin/disk-ha-check")
        (source_root / "__main__.py").write_text(
            "from disk_ha.schedule import main\nraise SystemExit(main())\n")
        scheduler = staging / "disk-ha-schedule"
        zipapp.create_archive(source_root, target=scheduler, interpreter="/usr/bin/python3")
        scheduler.chmod(0o755)
        scheduler.replace(root / "bin/disk-ha-schedule")
        package = root / "disk_ha"
        package.mkdir(exist_ok=True)
        package.chmod(0o755)
        for source in sorted(staged.rglob("*")):
            destination = package / source.relative_to(staged)
            if source.is_dir():
                destination.mkdir(exist_ok=True)
                destination.chmod(0o755)
            else:
                source.chmod(0o644)
                source.replace(destination)
    service = Path(DDISKHA.WEB_SERVICE_FILE)
    health_service = Path(DDISKHA.HEALTH_SERVICE_FILE)
    health_service.write_text(
        "[Unit]\nDescription=disk-ha manual health check\n\n"
        "[Service]\nType=oneshot\nUser=root\nGroup=root\nUMask=0077\nTimeoutStartSec=0\n"
        f"ExecStart={root}/bin/disk-ha-check --config {configuration} --result {root}/data/health.json\n"
        f"StandardOutput=append:{root}/data/health.log\nStandardError=append:{root}/data/health.log\n")
    health_service.chmod(0o644)
    # Grant exactly this start command, without access to other units or commands.
    sudoers = Path(DDISKHA.HEALTH_SUDOERS_FILE)
    with tempfile.NamedTemporaryFile(mode="w", prefix=".disk-ha-health-", dir=sudoers.parent,
                                     delete=False) as stream:
        staged_rule = Path(stream.name)
        stream.write(
            f"{DDISKHA.SERVICE_USER} ALL=(root) NOPASSWD: {DDISKHA.SYSTEMCTL} "
            f"start --no-block {health_service.name}\n"
            f'{DDISKHA.SERVICE_USER} ALL=(root) NOPASSWD: {root}/bin/disk-ha-schedule ""\n')
    try:
        staged_rule.chmod(0o440)
        subprocess.run([DDISKHA.VISUDO, "-cf", str(staged_rule)],
                       check=True, capture_output=True, timeout=10)
        staged_rule.replace(sudoers)
    finally:
        staged_rule.unlink(missing_ok=True)
    service.write_text(
        "[Unit]\nDescription=disk-ha Web UI\nAfter=network.target\n\n"
        f"[Service]\nType=exec\nUser={DDISKHA.SERVICE_USER}\nGroup={DDISKHA.SERVICE_GROUP}\n"
        f"LoadCredential=database.env:{DDISKHA.DATABASE_ENV}\n"
        f"ExecStart={root}/bin/disk-ha-web --host {DDISKHA.WEB_HOST} --port {DDISKHA.WEB_PORT}\n"
        "Restart=on-failure\nRestartSec=2\n\n[Install]\nWantedBy=multi-user.target\n")
    service.chmod(0o644)
    systemctl("daemon-reload")
    systemctl("enable", service.name)
    with configuration.with_suffix(".lock").open("a") as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        if upgrading:
            installed = HealthSchedule.read()
            values = json.loads(configuration.read_text())
            values.update(enabled=installed["enabled"], expression=installed["expression"] or None)
            HealthSchedule.save_configuration(configuration, values)
        health = HealthConfiguration(configuration)
        HealthSchedule.apply(root, health)
    if health.enabled:
        systemctl("enable", "--now", "cron.service")
    restart()
    print(f"Installed disk-ha {DDISKHA.VERSION} in {root}; configuration and data preserved.")


def uninstall() -> None:
    root = Path(DDISKHA.INSTALL_DIR)
    configuration = root / "conf/health.json"
    if configuration.parent.exists():
        with configuration.with_suffix(".lock").open("a") as stream:
            fcntl.flock(stream, fcntl.LOCK_EX)
            HealthSchedule.apply(root, None)
    service = Path(DDISKHA.WEB_SERVICE_FILE)
    health_service = Path(DDISKHA.HEALTH_SERVICE_FILE)
    reload_required = service.exists() or health_service.exists()
    if health_service.exists():
        systemctl("stop", health_service.name)
        health_service.unlink()
    Path(DDISKHA.HEALTH_SUDOERS_FILE).unlink(missing_ok=True)
    if service.exists():
        systemctl("disable", "--now", service.name)
        service.unlink()
    if reload_required:
        systemctl("daemon-reload")
    (root / "bin/disk-ha-web").unlink(missing_ok=True)
    (root / "bin/disk-ha-check").unlink(missing_ok=True)
    (root / "bin/disk-ha-schedule").unlink(missing_ok=True)
    package = Path(DDISKHA.INSTALL_DIR) / "disk_ha"
    if package.exists():
        shutil.rmtree(package)
    print("Removed disk-ha's Web UI service, executable, Python package, and CMDB metadata; "
          "accounts, database, configuration, credentials, and data preserved.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("install", "upgrade", "uninstall", "restart"))
    args = parser.parse_args()
    if os.geteuid() != 0:
        print("Run this script as root.", file=sys.stderr)
        return 1
    if sys.version_info < (3, 10):
        print("Python 3.10 or newer is required.", file=sys.stderr)
        return 1
    os.umask(0o077)
    try:
        {"install": install, "upgrade": install, "uninstall": uninstall, "restart": restart}[args.action]()
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print(f"disk-ha: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
