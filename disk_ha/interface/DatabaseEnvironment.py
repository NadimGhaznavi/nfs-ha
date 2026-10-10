"""Read protected database settings as data, never as shell code."""

import os
from pathlib import Path
import stat

from disk_ha.constants.DDiskHA import DDiskHA


class DatabaseEnvironment:
    @staticmethod
    def read(path: Path | None = None) -> dict[str, str]:
        path = Path(DDiskHA.DATABASE_ENV) if path is None else Path(path)
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(descriptor) as stream:
            info = os.fstat(stream.fileno())
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                    or stat.S_IMODE(info.st_mode) != 0o600):
                raise ValueError("Database credentials must belong to the current user with mode 0600.")
            content = stream.read().strip()
        values = {}
        for line in content.splitlines():
            key, separator, value = line.partition("=")
            if not separator or key in values:
                raise ValueError("Invalid database environment file.")
            values[key] = value
        required = {"DB_HOST", "DB_PORT", "DB_NAME", "DB_USER", "DB_PASSWORD"}
        if values.keys() not in (required, required | {"DB_SOCKET"}) or not all(values.values()):
            raise ValueError("Unexpected database environment fields.")
        if any(character in value for value in values.values() for character in ("\r", "\0")):
            raise ValueError("Invalid database environment values.")
        if not 1 <= int(values["DB_PORT"]) <= 65535:
            raise ValueError("Invalid database port.")
        return values
