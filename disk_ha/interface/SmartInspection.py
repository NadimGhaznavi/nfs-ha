"""Own block-device inspection and bounded smartctl execution."""

import math
import os
import stat
import subprocess

from disk_ha.constants.DDiskHA import DDiskHA
from disk_ha.entity.Disk import Disk
from disk_ha.entity.DiskHealth import DiskHealth


class SmartInspection:
    def __init__(self, timeout: float):
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("SMART timeout must be finite and positive.")
        self.timeout = timeout

    def inspect(self, disk: Disk) -> DiskHealth:
        return self._inspect(disk, ["-H", "-A"])

    def inspect_verbose(self, disk: Disk) -> DiskHealth:
        health = self.inspect(disk)
        extended = self._inspect(disk, ["-x"])
        output = extended.smart_output
        if extended.smart_status != 0:
            output += (f"\nExtended SMART diagnostics status: {extended.smart_status}.\n"
                       + "\n".join(extended.problems) + "\n")
        return DiskHealth(disk, health.problems,
                          "Health check (-H -A):\n" + health.smart_output
                          + "\nExtended report (-x):\n" + output, health.smart_status)

    def _inspect(self, disk: Disk, options: list[str]) -> DiskHealth:
        try:
            if not stat.S_ISBLK(os.stat(disk.device_path).st_mode):
                return DiskHealth(disk, ("Device is missing or is not a block device.",))
            result = subprocess.run(
                [DDiskHA.SMARTCTL, *options, disk.device_path],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, errors="replace", timeout=self.timeout, check=False)
        except (OSError, subprocess.TimeoutExpired) as error:
            return DiskHealth(disk, (f"SMART inspection unavailable: {error}",))
        if not 0 <= result.returncode <= 255:
            return DiskHealth(disk, (f"smartctl terminated with status: {result.returncode}",),
                              result.stdout, result.returncode)
        return DiskHealth.from_smart(disk, result.stdout, result.returncode)
