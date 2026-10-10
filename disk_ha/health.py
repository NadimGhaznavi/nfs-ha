"""Independent cron entry point; inspect, notify, and persist the latest result."""

import argparse
import fcntl
import os
from pathlib import Path
import socket
import sys

from disk_ha.activity.CheckDisks import CheckDisks
from disk_ha.constants.DDISKHA import DDISKHA
from disk_ha.interface.HealthConfiguration import HealthConfiguration
from disk_ha.interface.HealthResult import HealthResult


def run(config: Path, result: Path) -> int:
    with config.with_suffix(".lock").open("a") as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("Health check skipped: another check is active.")
            return 0
        configuration = HealthConfiguration(config)
        if not configuration.enabled:
            print("Health check skipped: monitoring is disabled.")
            return 0
        report = CheckDisks(configuration.disks, socket.getfqdn(),
                            configuration.inspection.inspect, configuration.notification.send).run()
        HealthResult(result).write(report)
        print(report.render(), end="")
        return report.exit_status


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path(DDISKHA.HEALTH_CONFIG))
    parser.add_argument("--result", type=Path, default=Path(DDISKHA.HEALTH_RESULT))
    args = parser.parse_args()
    if os.geteuid() != 0:
        parser.exit(1, "Run disk health checks as root.\n")
    os.umask(0o077)
    try:
        return run(args.config, args.result)
    except (OSError, ValueError) as error:
        print(f"Health check command failure: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
