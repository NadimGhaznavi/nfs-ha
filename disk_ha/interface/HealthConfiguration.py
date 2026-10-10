"""Validate the root-owned health configuration before using external interfaces."""

import json
from pathlib import Path
import re

from disk_ha.entity.Disk import Disk
from disk_ha.interface.EmailNotification import EmailNotification
from disk_ha.interface.SmartInspection import SmartInspection


def validate_expression(expression: str) -> str:
    if (not isinstance(expression, str) or len(expression) > 255
            or "\n" in expression or "\r" in expression):
        raise ValueError("Provide a five-field numeric cron expression.")
    fields = expression.split()
    if len(fields) != 5:
        raise ValueError("Provide five cron fields: minute hour day month weekday.")
    for field, (minimum, maximum) in zip(fields, ((0, 59), (0, 23), (1, 31), (1, 12), (0, 7))):
        for part in field.split(","):
            match = re.fullmatch(r"(\*|[0-9]+(?:-[0-9]+)?)(?:/([0-9]+))?", part)
            if match is None:
                raise ValueError("Cron fields must use numbers, *, ranges, lists, or steps.")
            span, step = match.groups()
            if step is not None and not 1 <= int(step) <= maximum - minimum + 1:
                raise ValueError("Cron step is out of range.")
            if span != "*":
                numbers = [int(value) for value in span.split("-")]
                if not all(minimum <= value <= maximum for value in numbers) or numbers[0] > numbers[-1]:
                    raise ValueError("Cron field is out of range.")
    return " ".join(fields)


class HealthConfiguration:
    def __init__(self, path: Path):
        values = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(values, dict) or set(values) != {
                "enabled", "expression", "disks", "smart_timeout", "mail"}:
            raise ValueError("Invalid health configuration fields.")
        if type(values["enabled"]) is not bool:
            raise ValueError("Health enabled must be a boolean.")
        self.enabled = values["enabled"]
        self.expression = (validate_expression(values["expression"])
                           if values["expression"] is not None else None)
        if self.enabled and self.expression is None:
            raise ValueError("Enabled monitoring requires a cron expression.")
        if not isinstance(values["disks"], list) or len(values["disks"]) != 2:
            raise ValueError("Configure two distinct stable disk paths.")
        if not all(isinstance(path, str) for path in values["disks"]):
            raise ValueError("Disk paths must be strings.")
        self.disks = tuple(Disk(path) for path in values["disks"])
        if self.disks[0] == self.disks[1]:
            raise ValueError("Configure two distinct disks.")
        if type(values["smart_timeout"]) not in (int, float):
            raise ValueError("SMART timeout must be numeric.")
        self.inspection = SmartInspection(values["smart_timeout"])
        mail = values["mail"]
        if mail is None and not self.enabled:
            self.notification = None
            return
        if not isinstance(mail, dict) or set(mail) != {"recipient", "sender", "config_path", "timeout"}:
            raise ValueError("Configure mail recipient, sender, config_path, and timeout.")
        if (not all(isinstance(mail[key], str) for key in ("recipient", "sender", "config_path"))
                or type(mail["timeout"]) not in (int, float)):
            raise ValueError("Invalid mail configuration types.")
        self.notification = EmailNotification(**mail)
