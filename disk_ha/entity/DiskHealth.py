"""SMART health policy from check-disks.sh, independent of command execution."""

from dataclasses import dataclass
import re

from disk_ha.entity.Disk import Disk


@dataclass(frozen=True)
class DiskHealth:
    disk: Disk
    problems: tuple[str, ...] = ()
    smart_output: str = ""
    smart_status: int | None = None

    @property
    def failed(self) -> bool:
        return bool(self.problems)

    @classmethod
    def from_smart(cls, disk: Disk, output: str, status: int):
        problems = []
        if status & 0x3f:
            problems.append(f"smartctl exit status: {status}")
        health = re.search(r"SMART overall-health self-assessment test result:\s*(PASSED|FAILED)\b",
                           output)
        if health is None:
            problems.append("SMART overall health result is unavailable.")
        elif health.group(1) == "FAILED":
            problems.append("SMART overall health failed.")
        seen = set()
        for line in output.splitlines():
            fields = line.split()
            if not fields or fields[0] not in {"5", "187", "196", "197", "198"}:
                continue
            if fields[0] in seen:
                continue
            seen.add(fields[0])
            if len(fields) < 10 or not re.fullmatch(r"[0-9]+", fields[9]):
                problems.append(f"SMART attribute {fields[0]} raw value is unavailable.")
            elif int(fields[9]) > 0:
                problems.append(f"{fields[1]} = {fields[9]}")
        return cls(disk, tuple(problems), output, status)
