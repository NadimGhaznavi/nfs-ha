"""Verify schedule presentation and the narrow manual-run command without live checks."""

from pathlib import Path
import subprocess
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from disk_ha.constants.DDiskHA import DDiskHA
from disk_ha.interface.HealthControl import read_schedule, update_schedule, request_check, request_email_report, request_sync
from disk_ha.server.DrivePage import render_schedule, render_email_notification, render_sync_schedule


class HealthControlTests(unittest.TestCase):
    def test_sync_now_uses_fixed_service_and_disabled_schedule_blocks_start(self):
        for enabled in (True, False):
            with patch("disk_ha.server.DrivePage.read_sync_schedule",
                       return_value={"enabled": enabled, "expression": "0 */4 * * *"}):
                html = render_sync_schedule()
            self.assertLess(html.index('id="update-sync-schedule"'), html.index('id="sync-now"'))
            self.assertEqual('type="button" disabled>Sync Now' in html, not enabled)
            with patch("disk_ha.interface.HealthControl.read_sync_schedule", return_value={"enabled": enabled}), \
                    patch("disk_ha.interface.HealthControl.subprocess.run") as command:
                if enabled:
                    request_sync()
                    command.assert_called_once_with(
                        [DDiskHA.SUDO, "-n", DDiskHA.SYSTEMCTL, "start", "--no-block", "disk-ha-sync.service"],
                        capture_output=True, check=True, timeout=10)
                else:
                    with self.assertRaises(ValueError):
                        request_sync()
                    command.assert_not_called()
        with patch("disk_ha.interface.HealthControl.read_sync_schedule", return_value={"enabled": True}), \
                patch("disk_ha.interface.HealthControl.subprocess.run", side_effect=subprocess.TimeoutExpired("start", 10)):
            with self.assertRaises(subprocess.TimeoutExpired):
                request_sync()

    def test_email_contact_display_and_unconfigured_state(self):
        with patch("disk_ha.server.DrivePage.read_contact", return_value="<operator>@example.com"):
            html = render_email_notification()
            self.assertIn("Contact: &lt;operator&gt;@example.com", html)
            self.assertIn("Email disk report", html)
            self.assertNotIn(" disabled", html)
        with patch("disk_ha.server.DrivePage.read_contact", return_value=None):
            self.assertIn("Not configured", render_email_notification())
            self.assertIn(" disabled", render_email_notification())
        with patch("disk_ha.server.DrivePage.read_contact", side_effect=OSError("denied")):
            self.assertIn("Unavailable", render_email_notification())

    def test_email_report_uses_fixed_service_without_reading_cron(self):
        with patch("disk_ha.interface.HealthControl.read_contact", return_value="operator@example.com"), \
                patch("disk_ha.interface.HealthControl.read_schedule") as cron, \
                patch("disk_ha.interface.HealthControl.subprocess.run") as command:
            request_email_report()
            cron.assert_not_called()
        command.assert_called_once_with(
            [DDiskHA.SUDO, "-n", DDiskHA.SYSTEMCTL, "start", "--no-block", "disk-ha-email-report.service"],
            capture_output=True, check=True, timeout=10)
        with patch("disk_ha.interface.HealthControl.read_contact", return_value=None), \
                patch("disk_ha.interface.HealthControl.subprocess.run") as command:
            with self.assertRaises(ValueError):
                request_email_report()
            command.assert_not_called()
    def test_settings_read_installed_cron_helper(self):
        with patch("disk_ha.interface.HealthControl.subprocess.run",
                   return_value=SimpleNamespace(returncode=0, stdout='{"enabled": true, "expression": "0 14 * * *"}')) as command:
            self.assertEqual(read_schedule(), {"enabled": True, "expression": "0 14 * * *"})
        self.assertEqual(command.call_args.args[0],
                         [DDiskHA.SUDO, "-n", str(Path(DDiskHA.INSTALL_DIR) / "bin/disk-ha-schedule")])
        self.assertEqual(command.call_args.kwargs["input"], '{"action": "read"}')

    def test_schedule_enabled_disabled_and_unavailable(self):
        for enabled in (True, False):
            with patch("disk_ha.server.DrivePage.read_schedule",
                       return_value={"enabled": enabled, "expression": "0 14 * * *"}):
                html, run_control = render_schedule()
            self.assertIn("0 14 * * *", html)
            self.assertIn("Run Now", run_control)
            self.assertEqual(" disabled" in run_control, not enabled)
        with patch("disk_ha.server.DrivePage.read_schedule", side_effect=OSError("denied")):
            html, run_control = render_schedule()
            self.assertIn("Cron schedule unavailable", html)
            self.assertIn(" disabled", run_control)

    def test_start_uses_only_fixed_service_with_timeout(self):
        with patch("disk_ha.interface.HealthControl.read_schedule",
                   return_value={"enabled": True}), \
                patch("disk_ha.interface.HealthControl.subprocess.run") as command:
            request_check()
        command.assert_called_once_with(
            [DDiskHA.SUDO, "-n", DDiskHA.SYSTEMCTL, "start", "--no-block", "disk-ha-health.service"],
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
