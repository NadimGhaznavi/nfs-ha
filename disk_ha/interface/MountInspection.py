"""Verify exact mounted filesystems before a mirror can propagate deletions."""

import json
from pathlib import Path
import subprocess

from disk_ha.constants.DDiskHA import DDiskHA
from disk_ha.interface.SyncConfiguration import SyncConfiguration


class MountInspection:
    def inspect(self, mount: Path, identity: str) -> str:
        if mount.resolve(strict=True) != mount or not mount.is_dir():
            raise ValueError(f"Mount path is missing, indirect, or not a directory: {mount}")
        result = subprocess.run(
            [DDiskHA.FINDMNT, "--json", "--mountpoint", str(mount), "--output", "TARGET,UUID,MAJ:MIN,FSROOT"],
            capture_output=True, text=True, timeout=10, check=False)
        if result.returncode != 0:
            raise ValueError(f"Expected disk is not mounted at {mount}.")
        values = json.loads(result.stdout)
        mounts = values.get("filesystems") if isinstance(values, dict) else None
        if not isinstance(mounts, list) or len(mounts) != 1 or not isinstance(mounts[0], dict):
            raise ValueError(f"Cannot identify the filesystem at {mount}.")
        current = mounts[0]
        if (current.get("target") != str(mount) or current.get("uuid") != identity
                or current.get("fsroot") != "/" or not isinstance(current.get("maj:min"), str)):
            raise ValueError(f"Filesystem identity does not match the configured disk at {mount}.")
        return current["maj:min"]

    def verify(self, configuration: SyncConfiguration) -> None:
        source = self.inspect(configuration.source, configuration.source_uuid)
        target = self.inspect(configuration.target, configuration.target_uuid)
        if source == target:
            raise ValueError("Source and target resolve to the same filesystem.")
