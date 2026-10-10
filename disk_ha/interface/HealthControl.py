"""Read or update the installed cron schedule and request manual health checks."""

import json
from pathlib import Path
import subprocess

from disk_ha.constants.DDiskHA import DDiskHA
from disk_ha.interface.HealthConfiguration import validate_expression


def _schedule(request: dict) -> dict:
    result = subprocess.run(
        [DDiskHA.SUDO, "-n", str(Path(DDiskHA.INSTALL_DIR) / "bin/disk-ha-schedule")],
        input=json.dumps(request), capture_output=True, text=True,
        timeout=130 if request["action"] == "update" else 35)
    if result.returncode == 2:
        raise ValueError(json.loads(result.stdout)["error"])
    if result.returncode != 0:
        raise OSError("Cannot access the installed cron schedule.")
    return json.loads(result.stdout)


def read_schedule() -> dict:
    return _schedule({"action": "read"})


def read_contact() -> str | None:
    return _schedule({"action": "contact"})["recipient"]


def request_email_report() -> None:
    if read_contact() is None:
        raise ValueError("Email contact is not configured.")
    subprocess.run([DDiskHA.SUDO, "-n", DDiskHA.SYSTEMCTL, "start", "--no-block",
                    Path(DDiskHA.EMAIL_REPORT_SERVICE_FILE).name],
                   capture_output=True, check=True, timeout=10)


def update_schedule(enabled: bool, expression: str) -> dict:
    if type(enabled) is not bool or not isinstance(expression, str):
        raise ValueError("Provide an enabled flag and a cron expression.")
    if expression or enabled:
        expression = validate_expression(expression)
    return _schedule({"action": "update", "enabled": enabled, "expression": expression})


def request_check() -> None:
    if not read_schedule()["enabled"]:
        raise ValueError("Monitoring is disabled.")
    subprocess.run([DDiskHA.SUDO, "-n", DDiskHA.SYSTEMCTL, "start", "--no-block",
                    Path(DDiskHA.HEALTH_SERVICE_FILE).name],
                   capture_output=True, check=True, timeout=10)
