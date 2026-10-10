"""Manage only disk-ha's named entry in root's crontab."""

from pathlib import Path
import shlex
import subprocess

from disk_ha.constants.DDISKHA import DDISKHA
from disk_ha.interface.HealthConfiguration import HealthConfiguration


class HealthSchedule:
    COMMENT = "disk-ha-health-check"

    @classmethod
    def apply(cls, root: Path, configuration: HealthConfiguration | None) -> None:
        result = subprocess.run([DDISKHA.CRONTAB, "-u", "root", "-l"],
                                capture_output=True, text=True, timeout=30,
                                env={"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LC_ALL": "C"})
        if result.returncode != 0:
            if result.returncode != 1 or result.stderr.strip() != "no crontab for root":
                raise OSError("Cannot read root crontab.")
            previous = ""
        else:
            previous = result.stdout
        lines = [line for line in previous.splitlines()
                 if not line.rstrip().endswith("# " + cls.COMMENT)]
        if configuration is not None and configuration.enabled:
            command = shlex.join([str(root / "bin/disk-ha-check"), "--config",
                                  str(root / "conf/health.json"), "--result",
                                  str(root / "data/health.json")])
            command += " >> " + shlex.quote(str(root / "data/health.log")) + " 2>&1"
            command = command.replace("%", r"\%")
            lines.append(f"{configuration.expression} {command} # {cls.COMMENT}")
        updated = "\n".join(lines) + ("\n" if lines else "")
        if updated != previous:
            subprocess.run([DDISKHA.CRONTAB, "-u", "root", "-"], input=updated,
                           text=True, check=True, timeout=30)
