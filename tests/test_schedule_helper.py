"""Verify the root helper's request boundary without accessing real cron."""

from contextlib import redirect_stdout
import io
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from disk_ha import schedule
from disk_ha.constants.DDiskHA import DDiskHA


class ScheduleHelperTests(unittest.TestCase):
    def test_sync_requests_use_only_the_fixed_sync_policy(self):
        with patch.object(schedule.SyncSchedule, "read", return_value={"enabled": True, "expression": "0 */4 * * *"}):
            self.assertEqual(schedule.dispatch({"action": "read-sync"})["expression"], "0 */4 * * *")
        with patch.object(schedule.SyncSchedule, "update") as update, \
                patch.object(schedule.subprocess, "run"), patch.object(schedule.HealthSchedule, "update") as health:
            schedule.dispatch({"action": "update-sync", "enabled": True, "expression": "0 */4 * * *"})
            update.assert_called_once_with(Path(DDiskHA.INSTALL_DIR), True, "0 */4 * * *")
            health.assert_not_called()
    def test_contact_returns_only_configured_recipient(self):
        with patch.object(schedule, "HealthConfiguration", return_value=SimpleNamespace(
                notification=SimpleNamespace(recipient="operator@example.com"))):
            self.assertEqual(schedule.dispatch({"action": "contact"}), {"recipient": "operator@example.com"})
        with patch.object(schedule, "HealthConfiguration", return_value=SimpleNamespace(notification=None)):
            self.assertEqual(schedule.dispatch({"action": "contact"}), {"recipient": None})
    def test_reads_only_owned_schedule_settings(self):
        with patch.object(schedule.HealthSchedule, "read",
                          return_value={"enabled": True, "expression": "0 14 * * *"}) as read:
            self.assertEqual(schedule.dispatch({"action": "read"}),
                             {"enabled": True, "expression": "0 14 * * *"})
        read.assert_called_once_with()

    def test_update_starts_cron_before_saving_and_uses_fixed_root(self):
        with patch.object(schedule.subprocess, "run") as command, \
                patch.object(schedule.HealthSchedule, "update") as update:
            schedule.dispatch({"action": "update", "enabled": True, "expression": "0 3 * * *"})
            command.assert_called_once_with([DDiskHA.SYSTEMCTL, "enable", "--now", "cron.service"],
                                            capture_output=True, check=True, timeout=30)
            update.assert_called_once_with(Path(DDiskHA.INSTALL_DIR), True, "0 3 * * *")

    def test_bad_requests_cannot_choose_commands_or_paths(self):
        with patch.object(schedule.subprocess, "run") as command, \
                patch.object(schedule.HealthSchedule, "update") as update:
            for request in ({"action": "read", "user": "other"}, {"action": "run"}, [],
                            {"action": "update", "enabled": True, "expression": "* * * * *; /command"},
                            {"action": "update", "enabled": 1, "expression": "0 3 * * *"}):
                with self.assertRaises(ValueError):
                    schedule.dispatch(request)
            command.assert_not_called()
            update.assert_not_called()

    def test_entry_point_rejects_extra_arguments_and_oversized_input(self):
        with patch.object(schedule.os, "geteuid", return_value=0), \
                patch.object(schedule.sys, "argv", ["disk-ha-schedule", "--path", "/other"]), \
                patch.object(schedule.sys, "stderr", io.StringIO()), \
                patch.object(schedule, "dispatch") as dispatch:
            self.assertEqual(schedule.main(), 1)
            dispatch.assert_not_called()
        with patch.object(schedule.os, "geteuid", return_value=0), \
                patch.object(schedule.os, "umask"), \
                patch.object(schedule.sys, "argv", ["disk-ha-schedule"]), \
                patch.object(schedule.sys, "stdin", io.StringIO("x" * 1025)), \
                redirect_stdout(io.StringIO()) as output:
            self.assertEqual(schedule.main(), 2)
            self.assertIn("too large", json.loads(output.getvalue())["error"])
