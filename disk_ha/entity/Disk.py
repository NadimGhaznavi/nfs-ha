"""Configured identity of a disk to inspect."""

from dataclasses import dataclass
from pathlib import PurePosixPath


@dataclass(frozen=True)
class Disk:
    device_path: str

    def __post_init__(self):
        if (str(PurePosixPath(self.device_path).parent) != "/dev/disk/by-id"
                or ".." in PurePosixPath(self.device_path).parts
                or any(character.isspace() for character in self.device_path)
                or self.device_path.endswith("/")):
            raise ValueError("Configure a stable /dev/disk/by-id/ device path.")
