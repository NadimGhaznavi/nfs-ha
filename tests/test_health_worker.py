"""Verify cron ownership, persisted results, permissions, and Web UI consumption."""

from contextlib import redirect_stdout
from datetime import datetime
import fcntl
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from disk_ha.health import run
from disk_ha.entity.Disk import Disk
from disk_ha.entity.DiskHealth import DiskHealth
from disk_ha.interface.HealthConfiguration import HealthConfiguration, validate_expression
from disk_ha.interface.HealthResult import HealthResult
from disk_ha.interface.HealthSchedule import HealthSchedule
from disk_ha.interface.EmailNotification import NotificationError
from disk_ha.server.DrivePage import render_page


class HealthWorkerTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.config = self.root / "health.json"
        self.result = self.root / "result.json"
        self.values = {"enabled": True, "expression": "0 3 * * *",
                       "disks": ["/dev/disk/by-id/ata-primary", "/dev/disk/by-id/ata-recovery"],
                       "smart_timeout": 10,
                       "mail": {"recipient": "operator@example.com", "sender": "disk@example.com",
                                "config_path": "/tmp/mail.conf", "timeout": 10}}
        self.save_config()

    def save_config(self):
        self.config.write_text(json.dumps(self.values))

    def worker(self, inspect, notify=None):
        with patch("disk_ha.interface.SmartInspection.SmartInspection.inspect", side_effect=inspect), \
                patch("disk_ha.interface.EmailNotification.EmailNotification.send",
                      side_effect=notify) as email, redirect_stdout(io.StringIO()):
            status = run(self.config, self.result)
        return status, email

    def test_healthy_result_is_atomic_readable_and_used_by_web(self):
        status, email = self.worker(lambda disk: DiskHealth(disk))
        email.assert_not_called()
        self.assertEqual(status, 0)
        result = HealthResult(self.result).read()
        self.assertEqual([disk["disk"]["device_path"] for disk in result["disks"]], self.values["disks"])
        self.assertEqual(self.result.stat().st_mode & 0o777, 0o640)
        self.assertEqual(self.result.stat().st_gid, self.root.stat().st_gid)
        checked_at = datetime.fromisoformat(result["checked_at"])
        self.assertIsNotNone(checked_at.tzinfo)
        self.assertEqual(checked_at.microsecond, 0)
        with patch("disk_ha.server.DrivePage.DDISKHA.HEALTH_RESULT", str(self.result)), \
                patch("disk_ha.server.DrivePage.read_usage", return_value=None):
            page = render_page().decode()
        self.assertIn("Disk Health", page)
        self.assertIn(checked_at.astimezone().strftime("%Y-%m-%d %H:%M:%S"), page)
        self.assertIn("ata-primary", page)
        self.assertEqual(page.count("<td>PASS</td>"), 2)
        self.assertNotIn("{{health}}", page)

    def test_old_utc_results_display_in_local_time_without_fractional_seconds(self):
        self.worker(lambda disk: DiskHealth(disk))
        result = HealthResult(self.result).read()
        try:
            with patch.dict(os.environ, {"TZ": "America/Toronto"}), \
                    patch("disk_ha.server.DrivePage.DDISKHA.HEALTH_RESULT", str(self.result)):
                time.tzset()
                for timestamp, local in (("2026-01-02T02:03:04.123456+00:00", "2026-01-01 21:03:04"),
                                         ("2026-07-02T02:03:04.123456+00:00", "2026-07-01 22:03:04")):
                    result["checked_at"] = timestamp
                    self.result.write_text(json.dumps(result))
                    page = render_page().decode()
                    self.assertIn(f'>{local}</time> (server time)', page)
                    self.assertNotIn(".123456", page)
                self.worker(lambda disk: DiskHealth(disk))
                recorded = datetime.fromisoformat(HealthResult(self.result).read()["checked_at"])
                self.assertEqual(recorded.utcoffset(), recorded.astimezone().utcoffset())
                self.assertEqual(recorded.microsecond, 0)
        finally:
            time.tzset()

    def test_disk_failure_and_email_failure_are_persisted_and_html_escaped(self):
        status, email = self.worker(lambda disk: DiskHealth(disk, ("<failed & degraded>",)),
                                    NotificationError("<delivery failed>"))
        self.assertEqual(status, 1)
        email.assert_called_once()
        self.assertEqual(HealthResult(self.result).read()["notification_error"], "<delivery failed>")
        with patch("disk_ha.server.DrivePage.DDISKHA.HEALTH_RESULT", str(self.result)):
            page = render_page().decode()
        self.assertIn("&lt;failed &amp; degraded&gt;", page)
        self.assertIn("&lt;delivery failed&gt;", page)
        self.assertNotIn("<delivery failed>", page)

    def test_disabled_and_overlapping_runs_preserve_previous_result(self):
        self.result.write_text("previous result")
        self.values.update(enabled=False, expression=None, mail=None)
        self.save_config()
        with patch("disk_ha.health.CheckDisks") as activity, redirect_stdout(io.StringIO()):
            self.assertEqual(run(self.config, self.result), 0)
            activity.assert_not_called()
        self.values.update(enabled=True)
        with self.config.with_suffix(".lock").open("a") as lock, \
                patch("disk_ha.health.CheckDisks") as activity, redirect_stdout(io.StringIO()):
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.assertEqual(run(self.config, self.result), 0)
            activity.assert_not_called()
        self.assertEqual(self.result.read_text(), "previous result")

    def test_failed_atomic_replace_keeps_previous_result_and_cleans_candidate(self):
        self.worker(lambda disk: DiskHealth(disk))
        previous = self.result.read_bytes()
        with patch("disk_ha.interface.HealthResult.Path.replace", side_effect=OSError("Disk full")), \
                self.assertRaises(OSError):
            self.worker(lambda disk: DiskHealth(disk, ("FAIL",)))
        self.assertEqual(self.result.read_bytes(), previous)
        self.assertEqual(set(self.root.iterdir()), {self.config, self.result, self.config.with_suffix(".lock")})

    def test_missing_corrupt_and_invalid_shape_results_show_explicit_web_state(self):
        with patch("disk_ha.server.DrivePage.DDISKHA.HEALTH_RESULT", str(self.result)):
            self.assertIn(b"No health check recorded", render_page())
            for value in ("broken json", "[]", "{}", '{"checked_at": 2, "disks": [], "notification_error": null}'):
                self.result.write_text(value)
                self.assertIn(b"Health results unavailable", render_page())

    def test_cron_install_replace_and_remove_preserve_unrelated_jobs(self):
        previous = "MAILTO=other@example.com\n15 2 * * * /other # unrelated\n"
        installed = []

        def crontab(arguments, **kwargs):
            nonlocal previous
            self.assertEqual(kwargs["timeout"], 30)
            if arguments[-1] == "-l":
                return SimpleNamespace(returncode=0, stdout=previous, stderr="")
            previous = kwargs["input"]
            installed.append(previous)
            return SimpleNamespace(returncode=0)

        with patch("disk_ha.interface.HealthSchedule.subprocess.run", side_effect=crontab):
            HealthSchedule.apply(self.root, HealthConfiguration(self.config))
            self.values["expression"] = "*/15 * * * *"
            self.save_config()
            HealthSchedule.apply(self.root, HealthConfiguration(self.config))
            self.assertEqual(previous.count("# disk-ha-health-check"), 1)
            self.assertIn("*/15 * * * *", previous)
            self.assertIn("disk-ha-check", previous)
            HealthSchedule.apply(self.root, None)
        self.assertEqual(previous, "MAILTO=other@example.com\n15 2 * * * /other # unrelated\n")
        self.assertEqual(len(installed), 3)

    def test_absent_crontab_and_read_failure(self):
        with patch("disk_ha.interface.HealthSchedule.subprocess.run",
                   side_effect=[SimpleNamespace(returncode=1, stdout="", stderr="no crontab for root"),
                                SimpleNamespace(returncode=0)]) as command:
            HealthSchedule.apply(self.root, HealthConfiguration(self.config))
        self.assertEqual(command.call_count, 2)
        with patch("disk_ha.interface.HealthSchedule.subprocess.run",
                   return_value=SimpleNamespace(returncode=1, stdout="", stderr="Permission denied")) as command:
            with self.assertRaises(OSError):
                HealthSchedule.apply(self.root, HealthConfiguration(self.config))
        self.assertEqual(command.call_count, 1)

    def test_configuration_rejects_unsafe_or_incomplete_inputs(self):
        for expression in ("60 * * * *", "* 24 * * *", "* * 0 * *", "* * * 13 *",
                           "* * * * 8", "* * * * *\n", "@daily", "* * * * * /command",
                           "*/0 * * * *", "10-2 * * * *"):
            with self.subTest(expression=expression), self.assertRaises(ValueError):
                validate_expression(expression)
        self.assertEqual(validate_expression("0,30 1-5 * * 1-5"), "0,30 1-5 * * 1-5")
        for key, value in (("enabled", 1), ("expression", None), ("mail", None),
                           ("disks", ["/dev/sda", "/dev/sdb"]), ("smart_timeout", "30")):
            previous = self.values[key]
            self.values[key] = value
            self.save_config()
            with self.subTest(key=key), self.assertRaises(ValueError):
                HealthConfiguration(self.config)
            self.values[key] = previous


if __name__ == "__main__":
    unittest.main()
