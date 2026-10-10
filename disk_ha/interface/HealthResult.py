"""Atomically publish and validate the latest health result for the Web UI."""

from dataclasses import asdict
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile

from disk_ha.entity.DiskCheckReport import DiskCheckReport


class HealthResult:
    def __init__(self, path: Path):
        self.path = Path(path)

    def write(self, report: DiskCheckReport) -> None:
        values = {"checked_at": datetime.now(timezone.utc).isoformat(),
                  "disks": [asdict(disk) for disk in report.disks],
                  "notification_error": report.notification_error}
        with NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.path.parent,
                                delete=False) as stream:
            candidate = Path(stream.name)
            try:
                json.dump(values, stream)
                stream.flush()
                os.fsync(stream.fileno())
                os.chown(candidate, -1, self.path.parent.stat().st_gid)
                candidate.chmod(0o640)
                candidate.replace(self.path)
            finally:
                candidate.unlink(missing_ok=True)

    def read(self) -> dict | None:
        try:
            values = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        if not isinstance(values, dict) or set(values) != {"checked_at", "disks", "notification_error"}:
            raise ValueError("Invalid health result.")
        if not isinstance(values["checked_at"], str):
            raise ValueError("Invalid health timestamp.")
        if datetime.fromisoformat(values["checked_at"]).tzinfo is None:
            raise ValueError("Health timestamp must include timezone.")
        if not isinstance(values["disks"], list) or len(values["disks"]) != 2:
            raise ValueError("Health result must contain two disks.")
        for disk in values["disks"]:
            if (not isinstance(disk, dict) or not isinstance(disk.get("disk"), dict)
                    or not isinstance(disk["disk"].get("device_path"), str)
                    or not isinstance(disk.get("problems"), list)
                    or not all(isinstance(problem, str) for problem in disk["problems"])):
                raise ValueError("Invalid disk health result.")
        if values["notification_error"] is not None and not isinstance(values["notification_error"], str):
            raise ValueError("Invalid notification result.")
        return values
