"""Read filesystem usage only for mounted drives."""

import os
import shutil


def read_usage(mount_path: str):
    """Return byte counts, or None when the expected mount is absent."""
    if not os.path.ismount(mount_path):
        return None
    return shutil.disk_usage(mount_path)
