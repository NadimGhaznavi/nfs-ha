"""Cron policy for mirroring Disk 1 to Disk 2."""

from disk_ha.interface.CronSchedule import CronSchedule
from disk_ha.interface.SyncConfiguration import SyncConfiguration


class SyncSchedule(CronSchedule):
    COMMENT = "disk-ha-data-sync"
    CONFIG_NAME = "sync.json"
    RUNNER_NAME = "disk-ha-sync"
    RESULT_NAME = "sync-output.log"
    LOG_NAME = "sync.log"
    CONFIGURATION = SyncConfiguration
