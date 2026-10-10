"""Read monitoring settings and request the fixed root-owned health service."""

import os
from pathlib import Path
import subprocess

from disk_ha.constants.DDISKHA import DDISKHA
from disk_ha.interface.HealthConfiguration import HealthConfiguration


def configuration() -> HealthConfiguration:
    directory = os.environ.get("CREDENTIALS_DIRECTORY")
    path = Path(directory) / "health.json" if directory else Path(DDISKHA.HEALTH_CONFIG)
    return HealthConfiguration(path)


def request_check() -> None:
    if not configuration().enabled:
        raise ValueError("Monitoring is disabled.")
    subprocess.run([DDISKHA.SUDO, "-n", DDISKHA.SYSTEMCTL, "start", "--no-block",
                    Path(DDISKHA.HEALTH_SERVICE_FILE).name],
                   capture_output=True, check=True, timeout=10)
