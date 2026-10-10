"""Independent cron entry point; inspect, notify, and persist the latest result."""

import argparse
import fcntl
import os
from pathlib import Path
import socket
import sys

from disk_ha.activity.CheckDisks import CheckDisks
from disk_ha.constants.DDiskHA import DDiskHA
from disk_ha.interface.HealthConfiguration import HealthConfiguration
from disk_ha.interface.HealthResult import HealthResult


def run(config: Path, result: Path, email_report: bool = False) -> int:
    with config.with_suffix(".lock").open("a") as stream:
        try:
            # Requested email reports wait for the current check instead of being skipped.
            fcntl.flock(stream, fcntl.LOCK_EX | (0 if email_report else fcntl.LOCK_NB))
        except BlockingIOError:
            print("Health check skipped: another check is active.")
            return 0
        configuration = HealthConfiguration(config)
        if not configuration.enabled and not email_report:
            print("Health check skipped: monitoring is disabled.")
            return 0
        if configuration.notification is None:
            raise ValueError("Configure email notification settings before requesting a report.")
        inspect = (configuration.inspection.inspect_verbose if email_report
                   else configuration.inspection.inspect)
        notify = (configuration.notification.send_report if email_report
                  else configuration.notification.send)
        report = CheckDisks(configuration.disks, socket.getfqdn(),
                            inspect, notify).run(notify_always=email_report)
        HealthResult(result).write(report)
        print(report.render(verbose=email_report), end="")
        if email_report and report.notification_error is None:
            print("Verbose disk report emailed.")
        return report.exit_status


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path(DDiskHA.HEALTH_CONFIG))
    parser.add_argument("--result", type=Path, default=Path(DDiskHA.HEALTH_RESULT))
    parser.add_argument("--email-report", action="store_true",
                        help="Inspect full SMART data and email a report even when disks are healthy.")
    args = parser.parse_args()
    if os.geteuid() != 0:
        parser.exit(1, "Run disk health checks as root.\n")
    os.umask(0o077)
    try:
        return run(args.config, args.result, email_report=args.email_report)
    except (OSError, ValueError) as error:
        print(f"Health check command failure: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
