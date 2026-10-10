"""Verify schedule presentation and the narrow manual-run command without live checks."""

from pathlib import Path
import subprocess
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from disk_ha.constants.DDISKHA import DDISKHA
from disk_ha.interface.HealthControl import read_schedule, update_schedule, request_check
from disk_ha.server.DrivePage import render_schedule


class HealthControlTests(unittest.TestCase):
    def test_settings_read_installed_cron_helper(self):
        with patch("disk_ha.interface.HealthControl.subprocess.run",
                   return_value=SimpleNamespace(returncode=0, stdout='{"enabled": true, "expression": "0 14 * * *"}')) as command:
            self.assertEqual(read_schedule(), {"enabled": True, "expression": "0 14 * * *"})
        self.assertEqual(command.call_args.args[0],
                         [DDISKHA.SUDO, "-n", str(Path(DDISKHA.INSTALL_DIR) / "bin/disk-ha-schedule")])
        self.assertEqual(command.call_args.kwargs["input"], '{"action": "read"}')

    def test_schedule_enabled_disabled_and_unavailable(self):
        for enabled in (True, False):
            with patch("disk_ha.server.DrivePage.read_schedule",
                       return_value={"enabled": enabled, "expression": "0 14 * * *"}):
                html = render_schedule()
            self.assertIn("0 14 * * *", html)
            self.assertIn("Run Now", html)
            self.assertEqual(" disabled" in html, not enabled)
        with patch("disk_ha.server.DrivePage.read_schedule", side_effect=OSError("denied")):
            self.assertIn("Cron schedule unavailable", render_schedule())
            self.assertIn(" disabled", render_schedule())

    def test_start_uses_only_fixed_service_with_timeout(self):
        with patch("disk_ha.interface.HealthControl.read_schedule",
                   return_value={"enabled": True}), \
                patch("disk_ha.interface.HealthControl.subprocess.run") as command:
            request_check()
        command.assert_called_once_with(
            [DDISKHA.SUDO, "-n", DDISKHA.SYSTEMCTL, "start", "--no-block", "disk-ha-health.service"],
            capture_output=True, check=True, timeout=10)

    def test_disabled_and_failed_requests_do_not_report_success(self):
        with patch("disk_ha.interface.HealthControl.read_schedule",
                   return_value={"enabled": False}), \
                patch("disk_ha.interface.HealthControl.subprocess.run") as command:
            with self.assertRaises(ValueError):
                request_check()
            command.assert_not_called()
        with patch("disk_ha.interface.HealthControl.read_schedule",
                   return_value={"enabled": True}), \
                patch("disk_ha.interface.HealthControl.subprocess.run", side_effect=subprocess.TimeoutExpired("start", 10)):
            with self.assertRaises(subprocess.TimeoutExpired):
                request_check()

    def test_schedule_update_validates_before_invoking_privileged_helper(self):
        with patch("disk_ha.interface.HealthControl._schedule",
                   return_value={"enabled": True, "expression": "*/20 * * * *"}) as helper:
            self.assertEqual(update_schedule(True, "*/20   * * * *")["expression"], "*/20 * * * *")
            helper.assert_called_once_with({"action": "update", "enabled": True,
                                            "expression": "*/20 * * * *"})
            helper.reset_mock()
            for enabled, expression in ((1, "0 3 * * *"), (True, None), (True, "60 * * * *"),
                                        (True, "0 3 * * *\n/root/command")):
                with self.assertRaises(ValueError):
                    update_schedule(enabled, expression)
            helper.assert_not_called()
