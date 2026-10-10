"""Read or update the installed cron schedule and request manual health checks."""

import json
from pathlib import Path
import subprocess

from disk_ha.constants.DDISKHA import DDISKHA
from disk_ha.interface.HealthConfiguration import validate_expression


def _schedule(request: dict) -> dict:
    result = subprocess.run(
        [DDISKHA.SUDO, "-n", str(Path(DDISKHA.INSTALL_DIR) / "bin/disk-ha-schedule")],
        input=json.dumps(request), capture_output=True, text=True,
        timeout=35 if request["action"] == "read" else 130)
    if result.returncode == 2:
        raise ValueError(json.loads(result.stdout)["error"])
    if result.returncode != 0:
        raise OSError("Cannot access the installed cron schedule.")
    return json.loads(result.stdout)


def read_schedule() -> dict:
    return _schedule({"action": "read"})


def update_schedule(enabled: bool, expression: str) -> dict:
    if type(enabled) is not bool or not isinstance(expression, str):
        raise ValueError("Provide an enabled flag and a cron expression.")
    if expression or enabled:
        expression = validate_expression(expression)
    return _schedule({"action": "update", "enabled": enabled, "expression": expression})


def request_check() -> None:
    if not read_schedule()["enabled"]:
        raise ValueError("Monitoring is disabled.")
    subprocess.run([DDISKHA.SUDO, "-n", DDISKHA.SYSTEMCTL, "start", "--no-block",
                    Path(DDISKHA.HEALTH_SERVICE_FILE).name],
                   capture_output=True, check=True, timeout=10)
