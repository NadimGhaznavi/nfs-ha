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
from threading import Event, Thread
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
        with patch("disk_ha.server.DrivePage.DDiskHA.HEALTH_RESULT", str(self.result)), \
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
                    patch("disk_ha.server.DrivePage.DDiskHA.HEALTH_RESULT", str(self.result)):
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
        with patch("disk_ha.server.DrivePage.DDiskHA.HEALTH_RESULT", str(self.result)):
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

    def test_requested_report_checks_both_disks_and_emails_every_health_outcome(self):
        self.values.update(enabled=False, expression=None)
        self.save_config()
        healthy = "SMART overall-health self-assessment test result: PASSED\n"
        outputs = (healthy, healthy + "197 Pending 0x0033 100 100 000 Old_age Always - 1\n",
                   healthy.replace("PASSED", "FAILED"), "SMART unavailable")
        for output in outputs:
            with self.subTest(output=output), \
                    patch("disk_ha.interface.SmartInspection.SmartInspection.inspect_verbose",
                          side_effect=lambda disk: DiskHealth.from_smart(disk, output, 0)) as inspect, \
                    patch("disk_ha.interface.EmailNotification.EmailNotification.send_report") as email, \
                    redirect_stdout(io.StringIO()):
                status = run(self.config, self.result, email_report=True)
            self.assertEqual(inspect.call_count, 2)
            email.assert_called_once()
            self.assertEqual(status, 0 if output == healthy else 1)
            self.assertEqual([disk["smart_output"] for disk in HealthResult(self.result).read()["disks"]],
                             [output, output])
        self.assertFalse(HealthConfiguration(self.config).enabled)

    def test_report_email_failure_is_persisted(self):
        with patch("disk_ha.interface.SmartInspection.SmartInspection.inspect_verbose",
                   side_effect=lambda disk: DiskHealth(disk)), \
                patch("disk_ha.interface.EmailNotification.EmailNotification.send_report",
                      side_effect=NotificationError("Email delivery timed out.")), redirect_stdout(io.StringIO()):
            self.assertEqual(run(self.config, self.result, email_report=True), 1)
        self.assertEqual(HealthResult(self.result).read()["notification_error"], "Email delivery timed out.")

    def test_report_without_mail_settings_preserves_last_result(self):
        self.values.update(enabled=False, expression=None, mail=None)
        self.save_config()
        self.result.write_text("previous result")
        with patch("disk_ha.health.CheckDisks") as activity, self.assertRaisesRegex(ValueError, "email"):
            run(self.config, self.result, email_report=True)
        activity.assert_not_called()
        self.assertEqual(self.result.read_text(), "previous result")

    def test_report_waits_for_active_check_and_then_emails(self):
        locking = Event()
        inspected = Event()
        flock = fcntl.flock
        errors = []

        def lock(stream, operation):
            self.assertEqual(operation, fcntl.LOCK_EX)
            locking.set()
            flock(stream, operation)

        def worker():
            try:
                run(self.config, self.result, email_report=True)
            except Exception as error:
                errors.append(error)

        def inspect(disk):
            inspected.set()
            return DiskHealth(disk)

        with self.config.with_suffix(".lock").open("a") as active, \
                patch("disk_ha.health.fcntl.flock", side_effect=lock), \
                patch("disk_ha.interface.SmartInspection.SmartInspection.inspect_verbose", side_effect=inspect), \
                patch("disk_ha.interface.EmailNotification.EmailNotification.send_report") as email, \
                redirect_stdout(io.StringIO()):
            flock(active, fcntl.LOCK_EX)
            thread = Thread(target=worker, daemon=True)
            thread.start()
            try:
                self.assertTrue(locking.wait(2))
                self.assertFalse(inspected.is_set())
            finally:
                flock(active, fcntl.LOCK_UN)
                thread.join(timeout=3)
            self.assertFalse(thread.is_alive())
            self.assertEqual(errors, [])
            email.assert_called_once()

    def test_failed_atomic_replace_keeps_previous_result_and_cleans_candidate(self):
        self.worker(lambda disk: DiskHealth(disk))
        previous = self.result.read_bytes()
        with patch("disk_ha.interface.HealthResult.Path.replace", side_effect=OSError("Disk full")), \
                self.assertRaises(OSError):
            self.worker(lambda disk: DiskHealth(disk, ("FAIL",)))
        self.assertEqual(self.result.read_bytes(), previous)
        self.assertEqual(set(self.root.iterdir()), {self.config, self.result, self.config.with_suffix(".lock")})

    def test_missing_corrupt_and_invalid_shape_results_show_explicit_web_state(self):
        with patch("disk_ha.server.DrivePage.DDiskHA.HEALTH_RESULT", str(self.result)):
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

        with patch("disk_ha.interface.CronSchedule.subprocess.run", side_effect=crontab):
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
        with patch("disk_ha.interface.CronSchedule.subprocess.run",
                   side_effect=[SimpleNamespace(returncode=1, stdout="", stderr="no crontab for root"),
                                SimpleNamespace(returncode=0)]) as command:
            HealthSchedule.apply(self.root, HealthConfiguration(self.config))
        self.assertEqual(command.call_count, 2)
        with patch("disk_ha.interface.CronSchedule.subprocess.run",
                   return_value=SimpleNamespace(returncode=1, stdout="", stderr="Permission denied")) as command:
            with self.assertRaises(OSError):
                HealthSchedule.apply(self.root, HealthConfiguration(self.config))
        self.assertEqual(command.call_count, 1)

    def test_schedule_reads_cron_instead_of_saved_expression(self):
        tab = "MAILTO=other@example.com\n15 2 * * * /other # unrelated\n"
        tab += "*/20 6-18 * * 1-5 /checker # disk-ha-health-check\n"
        with patch("disk_ha.interface.CronSchedule.subprocess.run",
                   return_value=SimpleNamespace(returncode=0, stdout=tab, stderr="")):
            self.assertEqual(HealthSchedule.read(), {"enabled": True, "expression": "*/20 6-18 * * 1-5"})
        with patch.object(HealthSchedule, "_crontab", return_value=""):
            self.assertEqual(HealthSchedule.read(), {"enabled": False, "expression": ""})
        with patch.object(HealthSchedule, "_crontab", return_value=tab + tab):
            with self.assertRaisesRegex(ValueError, "Multiple"):
                HealthSchedule.read()

    def test_schedule_updates_preserve_other_jobs_and_roll_back_on_cron_failure(self):
        conf = self.root / "conf"
        conf.mkdir()
        config = conf / "health.json"
        config.write_text(json.dumps(self.values))
        unrelated = "MAILTO=other@example.com\n15 2 * * * /other # unrelated\n"
        tab = unrelated

        def crontab(arguments, **kwargs):
            nonlocal tab
            if arguments[-1] == "-l":
                return SimpleNamespace(returncode=0, stdout=tab, stderr="")
            tab = kwargs["input"]
            return SimpleNamespace(returncode=0)

        with patch("disk_ha.interface.CronSchedule.subprocess.run", side_effect=crontab):
            self.assertEqual(HealthSchedule.update(self.root, True, "*/15 * * * *"),
                             {"enabled": True, "expression": "*/15 * * * *"})
            self.assertTrue(tab.startswith(unrelated))
            self.assertEqual(HealthConfiguration(config).expression, "*/15 * * * *")
            previous = config.read_bytes()
            with patch.object(HealthSchedule, "apply", side_effect=OSError("cron denied")):
                with self.assertRaises(OSError):
                    HealthSchedule.update(self.root, True, "0 2 * * *")
            self.assertEqual(json.loads(config.read_bytes()), json.loads(previous))
            with config.with_suffix(".lock").open("a") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                with self.assertRaisesRegex(OSError, "active"):
                    HealthSchedule.update(self.root, False, "0 2 * * *")
            self.assertEqual(HealthSchedule.update(self.root, False, "*/15 * * * *"),
                             {"enabled": False, "expression": ""})
            self.assertEqual(tab, unrelated)
            self.assertFalse(HealthConfiguration(config).enabled)

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
