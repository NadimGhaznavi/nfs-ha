"""Combined health report and process outcome."""

from dataclasses import dataclass

from disk_ha.entity.DiskHealth import DiskHealth


@dataclass(frozen=True)
class DiskCheckReport:
    disks: tuple[DiskHealth, ...]
    notification_error: str | None = None

    @property
    def failed(self) -> bool:
        return any(disk.failed for disk in self.disks)

    @property
    def exit_status(self) -> int:
        return int(self.failed or self.notification_error is not None)

    def render(self) -> str:
        separator = "=" * 60
        lines = []
        for health in self.disks:
            lines.extend((separator, f"Disk: {health.disk.device_path}"))
            if health.failed:
                lines.extend(f"FAIL: {problem}" for problem in health.problems)
                if health.smart_output:
                    lines.extend(("", health.smart_output.rstrip()))
            else:
                lines.append("PASS")
        lines.extend((separator, f"Overall result: {'FAIL' if self.failed else 'PASS'}"))
        if self.notification_error is not None:
            lines.append(f"Notification failure: {self.notification_error}")
        return "\n".join(lines) + "\n"
