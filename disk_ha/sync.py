"""Root cron entry point for a validated, locked Disk 1 to Disk 2 mirror."""

import argparse
from datetime import datetime
import fcntl
import os
from pathlib import Path
import subprocess
import sys
from tempfile import NamedTemporaryFile

from disk_ha.constants.DDiskHA import DDiskHA
from disk_ha.interface.MountInspection import MountInspection
from disk_ha.interface.RsyncMirror import RsyncMirror
from disk_ha.interface.SyncConfiguration import SyncConfiguration


def run(config: Path, result: Path) -> int:
    with config.with_suffix(".lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("Sync skipped: another synchronization or schedule edit is active.")
            return 0
        configuration = SyncConfiguration(config)
        if not configuration.enabled:
            print("Sync skipped: scheduling is disabled.")
            return 0
        try:
            MountInspection().verify(configuration)
        except (OSError, ValueError, subprocess.SubprocessError) as error:
            print(f"Sync skipped: mount validation failed: {error}")
            return 1
        started = datetime.now().astimezone().isoformat(timespec="seconds")
        with NamedTemporaryFile(mode="w", encoding="utf-8", dir=result.parent, delete=False) as output:
            candidate = Path(output.name)
            try:
                output.write(f"Started: {started}\nSource: {configuration.source}\nTarget: {configuration.target}\n\n")
                output.flush()
                # Recheck both identities immediately before handing the paths to rsync.
                MountInspection().verify(configuration)
                try:
                    status = RsyncMirror().run(configuration, output)
                except subprocess.TimeoutExpired:
                    status = 1
                    output.write("\nRsync command failed: configured timeout exceeded.\n")
                except OSError as error:
                    status = 1
                    output.write(f"\nRsync command failed: {error}\n")
                finished = datetime.now().astimezone().isoformat(timespec="seconds")
                output.write(f"\nFinished: {finished}\nOutcome: {'Success' if status == 0 else 'Failed'} "
                             f"(rsync exit status {status})\n")
                output.flush()
                os.fsync(output.fileno())
                os.chown(candidate, -1, result.parent.stat().st_gid)
                candidate.chmod(0o640)
                candidate.replace(result)
            finally:
                candidate.unlink(missing_ok=True)
        print(f"Sync {'completed successfully' if status == 0 else 'command failed'}: "
              f"rsync exit status {status}; output saved at {result}.")
        return int(status != 0)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path(DDiskHA.SYNC_CONFIG))
    parser.add_argument("--result", type=Path, default=Path(DDiskHA.SYNC_RESULT))
    args = parser.parse_args()
    if os.geteuid() != 0:
        parser.exit(1, "Run synchronization as root.\n")
    os.umask(0o077)
    try:
        return run(args.config, args.result)
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print(f"Sync command failure: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
