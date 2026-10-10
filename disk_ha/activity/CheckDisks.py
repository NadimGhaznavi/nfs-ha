"""Inspect both configured disks and notify the operator on health problems."""

from dataclasses import replace
from typing import Callable

from disk_ha.entity.Disk import Disk
from disk_ha.entity.DiskCheckReport import DiskCheckReport
from disk_ha.entity.DiskHealth import DiskHealth
from disk_ha.interface.EmailNotification import NotificationError


class CheckDisks:
    def __init__(self, disks: tuple[Disk, Disk], hostname: str,
                 inspect: Callable[[Disk], DiskHealth],
                 notify: Callable[[DiskCheckReport, str], None]):
        if len(disks) != 2 or disks[0].device_path == disks[1].device_path:
            raise ValueError("Configure two distinct disks.")
        if not hostname or any(character.isspace() for character in hostname):
            raise ValueError("Configure a hostname without whitespace.")
        self.disks = tuple(disks)
        self.hostname = hostname
        self.inspect = inspect
        self.notify = notify

    def run(self) -> DiskCheckReport:
        report = DiskCheckReport(tuple(self.inspect(disk) for disk in self.disks))
        if report.failed:
            try:
                self.notify(report, self.hostname)
            except NotificationError as error:
                report = replace(report, notification_error=str(error))
        return report
