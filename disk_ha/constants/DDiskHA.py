"""Shared disk-ha constants, including readable CMDB discovery metadata."""

from typing import Final


class DDiskHA:
    VERSION: Final[str] = "0.5.0"
    CMDB_SUBTYPE: Final[str] = "Disk Monitoring and Mirroring"
    CMDB_SUPPLIER: Final[str] = "Nadim-Daniel"
    CMDB_CODENAME: Final[str] = "Dodo"
    INSTALL_DIR: Final[str] = "/opt/prod/disk-ha"
    WEB_HOST: Final[str] = "0.0.0.0"
    WEB_PORT: Final[int] = 23300
    WEB_REQUEST_TIMEOUT: Final[int] = 15
    WEB_READY_PATH: Final[str] = "/ready"
    WEB_SERVICE_FILE: Final[str] = "/etc/systemd/system/disk-ha-web.service"
    SYSTEMCTL: Final[str] = "/usr/bin/systemctl"
    SERVICE_USER: Final[str] = "diskha"
    SERVICE_GROUP: Final[str] = "diskha"
    USERADD: Final[str] = "/usr/sbin/useradd"
    GROUPADD: Final[str] = "/usr/sbin/groupadd"
    NOLOGIN: Final[str] = "/usr/sbin/nologin"
    MARIADB: Final[str] = "/usr/bin/mariadb"
    DATABASE_NAME: Final[str] = "diskha"
    DATABASE_USER: Final[str] = "diskha"
    DATABASE_ENV: Final[str] = "/opt/prod/disk-ha/conf/database.env"
    DATABASE_CONNECT_TIMEOUT: Final[int] = 5
    SMARTCTL: Final[str] = "/usr/sbin/smartctl"
    MSMTP: Final[str] = "/usr/bin/msmtp"
    CRONTAB: Final[str] = "/usr/bin/crontab"
    HEALTH_CONFIG: Final[str] = "/opt/prod/disk-ha/conf/health.json"
    HEALTH_RESULT: Final[str] = "/opt/prod/disk-ha/data/health.json"
    HEALTH_SERVICE_FILE: Final[str] = "/etc/systemd/system/disk-ha-health.service"
    EMAIL_REPORT_SERVICE_FILE: Final[str] = "/etc/systemd/system/disk-ha-email-report.service"
    HEALTH_SUDOERS_FILE: Final[str] = "/etc/sudoers.d/disk-ha-health"
    SUDO: Final[str] = "/usr/bin/sudo"
    VISUDO: Final[str] = "/usr/sbin/visudo"
    RSYNC: Final[str] = "/usr/bin/rsync"
    FINDMNT: Final[str] = "/usr/bin/findmnt"
    SYNC_CONFIG: Final[str] = "/opt/prod/disk-ha/conf/sync.json"
    SYNC_RESULT: Final[str] = "/opt/prod/disk-ha/data/sync-output.log"
