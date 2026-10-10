"""Read and manage only disk-ha's marked entry in root's crontab."""

import fcntl
import json
from pathlib import Path
import shlex
import subprocess
from tempfile import NamedTemporaryFile

from disk_ha.constants.DDISKHA import DDISKHA
from disk_ha.interface.HealthConfiguration import HealthConfiguration, validate_expression


class HealthSchedule:
    COMMENT = "disk-ha-health-check"

    @classmethod
    def _crontab(cls) -> str:
        result = subprocess.run([DDISKHA.CRONTAB, "-u", "root", "-l"],
                                capture_output=True, text=True, timeout=30,
                                env={"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LC_ALL": "C"})
        if result.returncode == 0:
            return result.stdout
        if result.returncode == 1 and result.stderr.strip() == "no crontab for root":
            return ""
        raise OSError("Cannot read root crontab.")

    @classmethod
    def read(cls) -> dict:
        entries = [line for line in cls._crontab().splitlines()
                   if not line.lstrip().startswith("#")
                   and line.rstrip().endswith("# " + cls.COMMENT)]
        if not entries:
            return {"enabled": False, "expression": ""}
        if len(entries) != 1:
            raise ValueError("Multiple disk-ha cron entries; repair root's crontab.")
        fields = entries[0].split(maxsplit=5)
        if len(fields) != 6:
            raise ValueError("Invalid disk-ha cron entry.")
        return {"enabled": True, "expression": validate_expression(" ".join(fields[:5]))}

    @staticmethod
    def save_configuration(path: Path, values: dict) -> None:
        with NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as stream:
            candidate = Path(stream.name)
            try:
                json.dump(values, stream)
                stream.flush()
                candidate.chmod(0o600)
                # Validate all settings before publishing the root worker's configuration.
                HealthConfiguration(candidate)
                candidate.replace(path)
            finally:
                candidate.unlink(missing_ok=True)

    @classmethod
    def update(cls, root: Path, enabled: bool, expression: str) -> dict:
        if type(enabled) is not bool or not isinstance(expression, str):
            raise ValueError("Provide an enabled flag and a cron expression.")
        expression = validate_expression(expression) if expression or enabled else None
        path = root / "conf/health.json"
        with path.with_suffix(".lock").open("a") as stream:
            try:
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise OSError("A health check or schedule update is active; retry shortly.") from None
            previous = json.loads(path.read_text(encoding="utf-8"))
            values = dict(previous, enabled=enabled, expression=expression)
            cls.save_configuration(path, values)
            try:
                cls.apply(root, HealthConfiguration(path))
            except (OSError, ValueError, subprocess.SubprocessError):
                cls.save_configuration(path, previous)
                raise
            return cls.read()

    @classmethod
    def apply(cls, root: Path, configuration: HealthConfiguration | None) -> None:
        previous = cls._crontab()
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
