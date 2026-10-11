"""Validate disk identities, direction, schedule, and rsync timeout."""

import json
import math
from pathlib import Path
from uuid import UUID

from disk_ha.interface.HealthConfiguration import validate_expression


def mount_identity(values: dict) -> tuple[Path, str]:
    if not isinstance(values, dict) or set(values) != {"mount", "uuid"}:
        raise ValueError("Provide a mount path and filesystem UUID for each disk.")
    mount = values["mount"]
    if (not isinstance(mount, str) or not mount.startswith("/") or mount == "/"
            or any(part in ("", ".", "..") for part in mount.split("/")[1:])
            or any(character.isspace() for character in mount)):
        raise ValueError("Use an absolute, non-root mount path without relative components.")
    if not isinstance(values["uuid"], str):
        raise ValueError("Filesystem UUID must be a string.")
    identity = str(UUID(values["uuid"]))
    return Path(mount), identity


class SyncConfiguration:
    def __init__(self, path: Path):
        values = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(values, dict) or set(values) != {"enabled", "expression", "source", "target", "timeout"}:
            raise ValueError("Invalid synchronization configuration fields.")
        if type(values["enabled"]) is not bool:
            raise ValueError("Sync enabled must be a boolean.")
        self.enabled = values["enabled"]
        self.expression = validate_expression(values["expression"]) if values["expression"] is not None else None
        if self.enabled and self.expression is None:
            raise ValueError("Enabled synchronization requires a cron expression.")
        self.source, self.source_uuid = mount_identity(values["source"])
        self.target, self.target_uuid = mount_identity(values["target"])
        if (self.source_uuid == self.target_uuid or self.source == self.target
                or self.source in self.target.parents or self.target in self.source.parents):
            raise ValueError("Source and target must be distinct, non-nested disks.")
        if (type(values["timeout"]) not in (int, float)
                or not math.isfinite(values["timeout"]) or values["timeout"] <= 0):
            raise ValueError("Rsync timeout must be finite and positive.")
        self.timeout = values["timeout"]
