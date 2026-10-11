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
        raw_column = 9
        has_header = any(line.split()[:2] == ["ID#", "ATTRIBUTE_NAME"] for line in output.splitlines())
        in_attributes = not has_header
        for line in output.splitlines():
            fields = line.split()
            if fields[:2] == ["ID#", "ATTRIBUTE_NAME"]:
                raw_column = fields.index("RAW_VALUE") if "RAW_VALUE" in fields else None
                in_attributes = True
                continue
            if has_header and (not fields or not fields[0].isdigit()):
                in_attributes = False
            if not in_attributes or not fields or fields[0] not in {"5", "187", "196", "197", "198"}:
                continue
            if fields[0] in seen:
                continue
            seen.add(fields[0])
            if raw_column is None or len(fields) <= raw_column or not re.fullmatch(r"[0-9]+", fields[raw_column]):
                problems.append(f"SMART attribute {fields[0]} raw value is unavailable.")
            elif int(fields[raw_column]) > 0:
                problems.append(f"{fields[1]} = {fields[raw_column]}")
        return cls(disk, tuple(problems), output, status)
