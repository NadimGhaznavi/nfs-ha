"""Deliver health reports through msmtp without handling mail credentials."""

from email.message import EmailMessage
from email.utils import formatdate
import math
from pathlib import Path
import subprocess

from disk_ha.constants.DDiskHA import DDiskHA
from disk_ha.entity.DiskCheckReport import DiskCheckReport


class NotificationError(RuntimeError):
    """Expected notification delivery failure, safe to include in reports."""


class EmailNotification:
    def __init__(self, recipient: str, sender: str, config_path: str, timeout: float):
        for address in (recipient, sender):
            if (not address or "@" not in address
                    or any(character.isspace() for character in address)):
                raise ValueError("Configure a sender and recipient email address.")
        if not Path(config_path).is_absolute():
            raise ValueError("Configure an absolute msmtp configuration path.")
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("Notification timeout must be finite and positive.")
        self.recipient = recipient
        self.sender = sender
        self.config_path = config_path
        self.timeout = timeout

    def send(self, report: DiskCheckReport, hostname: str) -> None:
        self._send(report.render(), f"SMART disk alert on {hostname}")

    def send_report(self, report: DiskCheckReport, hostname: str) -> None:
        self._send(report.render(verbose=True), f"SMART disk report on {hostname}")

    def _send(self, body: str, subject: str) -> None:
        message = EmailMessage()
        message["To"] = self.recipient
        message["From"] = self.sender
        message["Subject"] = subject
        message["Date"] = formatdate(localtime=True)
        message.set_content(body, charset="utf-8")
        try:
            result = subprocess.run(
                [DDiskHA.MSMTP, f"--file={self.config_path}", "--account=default", "-t"],
                input=message.as_string(), text=True, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, timeout=self.timeout, check=False)
        except subprocess.TimeoutExpired:
            raise NotificationError("Email delivery timed out.") from None
        except OSError:
            raise NotificationError("Email delivery command is unavailable.") from None
        if result.returncode != 0:
            raise NotificationError(f"Email delivery failed with status {result.returncode}.")
