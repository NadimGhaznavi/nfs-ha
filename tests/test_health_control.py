"""Verify schedule presentation and the narrow manual-run command without live checks."""

import os
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from disk_ha.constants.DDISKHA import DDISKHA
from disk_ha.interface.HealthControl import configuration, request_check
from disk_ha.server.DrivePage import render_schedule


class HealthControlTests(unittest.TestCase):
    def test_settings_read_private_systemd_copy(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "health.json"
            path.write_bytes((Path(__file__).resolve().parents[1] / "conf/health.json").read_bytes())
            with patch.dict(os.environ, {"CREDENTIALS_DIRECTORY": temporary}):
                self.assertEqual(configuration().expression, "0 14 * * *")

    def test_schedule_enabled_disabled_and_unavailable(self):
        for enabled in (True, False):
            with patch("disk_ha.server.DrivePage.configuration",
                       return_value=SimpleNamespace(enabled=enabled, expression="0 14 * * *")):
                html = render_schedule()
            self.assertIn("0 14 * * *", html)
            self.assertIn("Run Now", html)
            self.assertEqual(" disabled" in html, not enabled)
        with patch("disk_ha.server.DrivePage.configuration", side_effect=OSError("denied")):
            self.assertIn("Cron schedule unavailable", render_schedule())
            self.assertIn(" disabled", render_schedule())

    def test_start_uses_only_fixed_service_with_timeout(self):
        with patch("disk_ha.interface.HealthControl.configuration",
                   return_value=SimpleNamespace(enabled=True)), \
                patch("disk_ha.interface.HealthControl.subprocess.run") as command:
            request_check()
        command.assert_called_once_with(
            [DDISKHA.SUDO, "-n", DDISKHA.SYSTEMCTL, "start", "--no-block", "disk-ha-health.service"],
            capture_output=True, check=True, timeout=10)

    def test_disabled_and_failed_requests_do_not_report_success(self):
        with patch("disk_ha.interface.HealthControl.configuration",
                   return_value=SimpleNamespace(enabled=False)), \
                patch("disk_ha.interface.HealthControl.subprocess.run") as command:
            with self.assertRaises(ValueError):
                request_check()
            command.assert_not_called()
        with patch("disk_ha.interface.HealthControl.configuration",
                   return_value=SimpleNamespace(enabled=True)), \
                patch("disk_ha.interface.HealthControl.subprocess.run", side_effect=subprocess.TimeoutExpired("start", 10)):
            with self.assertRaises(subprocess.TimeoutExpired):
                request_check()
