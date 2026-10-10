"""Root-only schedule helper; accept a bounded JSON request on standard input."""

import json
import os
from pathlib import Path
import subprocess
import sys

from disk_ha.constants.DDISKHA import DDISKHA
from disk_ha.interface.HealthConfiguration import validate_expression
from disk_ha.interface.HealthSchedule import HealthSchedule


def dispatch(request: dict) -> dict:
    if request == {"action": "read"}:
        return HealthSchedule.read()
    if (isinstance(request, dict) and set(request) == {"action", "enabled", "expression"}
            and request["action"] == "update"):
        if type(request["enabled"]) is not bool or not isinstance(request["expression"], str):
            raise ValueError("Provide an enabled flag and a cron expression.")
        if request["expression"] or request["enabled"]:
            validate_expression(request["expression"])
        if request["enabled"]:
            subprocess.run([DDISKHA.SYSTEMCTL, "enable", "--now", "cron.service"],
                           capture_output=True, check=True, timeout=30)
        return HealthSchedule.update(Path(DDISKHA.INSTALL_DIR), request["enabled"], request["expression"])
    raise ValueError("Invalid schedule request.")


def main() -> int:
    if os.geteuid() != 0 or len(sys.argv) != 1:
        print("Schedule helper requires root and no arguments.", file=sys.stderr)
        return 1
    os.umask(0o077)
    try:
        source = sys.stdin.read(1025)
        if len(source) > 1024:
            raise ValueError("Schedule request is too large.")
        result = dispatch(json.loads(source))
    except ValueError as error:
        print(json.dumps({"error": str(error)}))
        return 2
    except (OSError, subprocess.SubprocessError):
        print(json.dumps({"error": "Cannot access cron or save settings; check permissions and retry."}))
        return 1
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
