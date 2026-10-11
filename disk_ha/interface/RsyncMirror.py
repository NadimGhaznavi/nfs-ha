"""Own the bounded rsync command and stream verbose output to a result file."""

import subprocess
import os
import signal
from typing import TextIO

from disk_ha.constants.DDiskHA import DDiskHA
from disk_ha.interface.SyncConfiguration import SyncConfiguration


class RsyncMirror:
    def run(self, configuration: SyncConfiguration, output: TextIO) -> int:
        with subprocess.Popen(
            [DDiskHA.RSYNC, "-avr", "--delete", "--", str(configuration.source) + "/",
             str(configuration.target) + "/"],
            stdout=output, stderr=subprocess.STDOUT, start_new_session=True) as process:
            try:
                return process.wait(timeout=configuration.timeout)
            except subprocess.TimeoutExpired:
                # Local rsync starts children; terminate the entire run before releasing its lock.
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait(timeout=5)
                raise
