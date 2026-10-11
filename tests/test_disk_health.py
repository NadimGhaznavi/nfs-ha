"""Verify health policy and failures without inspecting live disks or sending mail."""

from email import message_from_string
import stat
import tempfile
from pathlib import Path
import subprocess
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from disk_ha.activity.CheckDisks import CheckDisks
from disk_ha.constants.DDiskHA import DDiskHA
from disk_ha.entity.Disk import Disk
from disk_ha.entity.DiskHealth import DiskHealth
from disk_ha.interface.EmailNotification import EmailNotification, NotificationError
from disk_ha.interface.SmartInspection import SmartInspection


HEALTHY = "SMART overall-health self-assessment test result: PASSED\n"
DISKS = (Disk("/dev/disk/by-id/ata-primary"), Disk("/dev/disk/by-id/ata-recovery"))


class DiskHealthTests(unittest.TestCase):
    def test_healthy_and_optional_unsupported_attributes(self):
        for status in (0, 64, 128, 192):
            with self.subTest(status=status):
                self.assertFalse(DiskHealth.from_smart(DISKS[0], HEALTHY, status).failed)

    def test_standard_and_brief_tables_use_raw_column_and_ignore_later_logs(self):
        for header, columns in (
                ("ID# ATTRIBUTE_NAME FLAG VALUE WORST THRESH TYPE UPDATED WHEN_FAILED RAW_VALUE",
                 "0x0033 100 100 000 Old_age Always -"),
                ("ID# ATTRIBUTE_NAME FLAGS VALUE WORST THRESH FAIL RAW_VALUE", "PO--CK 100 100 000 -")):
            for raw in ("0", "7", "unreadable", ""):
                with self.subTest(header=header, raw=raw):
                    text = HEALTHY + header + "\n" + f"197 Current_Pending_Sector {columns} {raw}\n"
                    text += "\nSPAN MIN_LBA MAX_LBA CURRENT_TEST_STATUS\n5 0 0 Not_testing\n"
                    health = DiskHealth.from_smart(DISKS[0], text, 0)
                    self.assertEqual(health.failed, raw != "0")
                    if raw == "7":
                        self.assertEqual(health.problems, ("Current_Pending_Sector = 7",))

    def test_each_script_status_bit_alerts(self):
        for bit in range(6):
            with self.subTest(bit=bit):
                health = DiskHealth.from_smart(DISKS[0], HEALTHY, 1 << bit)
                self.assertIn(f"smartctl exit status: {1 << bit}", health.problems)

    def test_each_degradation_attribute_alerts_on_nonzero_raw_value(self):
        for identifier in (5, 187, 196, 197, 198):
            for value in (0, 1, 12):
                with self.subTest(identifier=identifier, value=value):
                    output = HEALTHY + f"{identifier} Attribute 0x0033 100 100 000 Old_age Always - {value}\n"
                    health = DiskHealth.from_smart(DISKS[0], output, 0)
                    self.assertEqual(health.failed, value > 0)

    def test_unavailable_or_failed_health_is_not_a_pass(self):
        for output in ("", "SMART support is: Unavailable", HEALTHY.replace("PASSED", "FAILED"),
                       HEALTHY + "197 Pending 0x0033 100 100 000 Old_age Always - unreadable"):
            with self.subTest(output=output):
                self.assertTrue(DiskHealth.from_smart(DISKS[0], output, 0).failed)

    def test_configuration_requires_two_distinct_stable_disk_paths(self):
        for path in ("/dev/sda", "relative", "/dev/disk/by-id/", "/dev/disk/by-id/../sda"):
            with self.subTest(path=path), self.assertRaises(ValueError):
                Disk(path)
        for disks in ((DISKS[0],), (DISKS[0], DISKS[0])):
            with self.assertRaises(ValueError):
                CheckDisks(disks, "host", Mock(), Mock())

    def test_both_healthy_disks_checked_without_notification(self):
        inspect = Mock(side_effect=lambda disk: DiskHealth(disk))
        notify = Mock()
        report = CheckDisks(DISKS, "host", inspect, notify).run()
        self.assertEqual([call.args[0] for call in inspect.call_args_list], list(DISKS))
        notify.assert_not_called()
        self.assertEqual(report.exit_status, 0)
        self.assertEqual(report.render().count("\nPASS\n"), 2)
        self.assertIn("Overall result: PASS", report.render())

    def test_failed_first_disk_still_checks_second_and_sends_combined_report(self):
        inspect = Mock(side_effect=[DiskHealth(DISKS[0], ("Device missing",)),
                                    DiskHealth.from_smart(DISKS[1], HEALTHY, 8)])
        notify = Mock()
        report = CheckDisks(DISKS, "host", inspect, notify).run()
        self.assertEqual(inspect.call_count, 2)
        notify.assert_called_once_with(report, "host")
        self.assertEqual(report.exit_status, 1)
        self.assertIn(HEALTHY.rstrip(), report.render())
        self.assertIn("Overall result: FAIL", report.render())

    def test_notification_failure_is_reported_and_programming_errors_surface(self):
        inspect = Mock(side_effect=lambda disk: DiskHealth(disk, ("Disk failure",)))
        notify = Mock(side_effect=NotificationError("Email unavailable"))
        report = CheckDisks(DISKS, "host", inspect, notify).run()
        self.assertEqual(report.exit_status, 1)
        self.assertIn("Notification failure: Email unavailable", report.render())
        notify.side_effect = TypeError("Programming error")
        with self.assertRaises(TypeError):
            CheckDisks(DISKS, "host", inspect, notify).run()


class SmartInspectionTests(unittest.TestCase):
    def test_verbose_inspection_requests_extended_smart_data(self):
        with patch("disk_ha.interface.SmartInspection.os.stat",
                   return_value=SimpleNamespace(st_mode=stat.S_IFBLK)), \
                patch("disk_ha.interface.SmartInspection.subprocess.run",
                      return_value=SimpleNamespace(stdout=HEALTHY + "Device Model: Example\n", returncode=0)) as run:
            health = SmartInspection(10).inspect_verbose(DISKS[0])
        self.assertFalse(health.failed)
        self.assertIn("Device Model", health.smart_output)
        self.assertEqual([call.args[0] for call in run.call_args_list],
                         [[DDiskHA.SMARTCTL, "-H", "-A", DISKS[0].device_path],
                          [DDiskHA.SMARTCTL, "-x", DISKS[0].device_path]])
        self.assertEqual(run.call_args.kwargs["timeout"], 10)

    def test_verbose_optional_command_failure_does_not_change_primary_health(self):
        for status in (0, 4, 8):
            with self.subTest(status=status), \
                    patch("disk_ha.interface.SmartInspection.os.stat", return_value=SimpleNamespace(st_mode=stat.S_IFBLK)), \
                    patch("disk_ha.interface.SmartInspection.subprocess.run", side_effect=[
                        SimpleNamespace(stdout=HEALTHY, returncode=status),
                        SimpleNamespace(stdout=HEALTHY + "SCT Error Recovery Control command not supported\n", returncode=4)]):
                health = SmartInspection(10).inspect_verbose(DISKS[0])
            self.assertEqual(health.failed, status != 0)
            self.assertEqual(health.smart_status, status)
            self.assertIn("Extended SMART diagnostics status: 4", health.smart_output)
            self.assertIn("SCT Error Recovery", health.smart_output)

    def test_nonzero_smart_status_is_parsed_and_command_has_timeout(self):
        with patch("disk_ha.interface.SmartInspection.os.stat",
                   return_value=SimpleNamespace(st_mode=stat.S_IFBLK)), \
                patch("disk_ha.interface.SmartInspection.subprocess.run",
                      return_value=SimpleNamespace(stdout=HEALTHY, returncode=8)) as run:
            health = SmartInspection(10).inspect(DISKS[0])
        self.assertTrue(health.failed)
        self.assertEqual(health.smart_status, 8)
        self.assertEqual(run.call_args.args[0], [DDiskHA.SMARTCTL, "-H", "-A", DISKS[0].device_path])
        self.assertEqual(run.call_args.kwargs["timeout"], 10)
        self.assertFalse(run.call_args.kwargs["check"])

    def test_missing_or_non_block_device_does_not_run_command(self):
        for value in (FileNotFoundError("Missing"), SimpleNamespace(st_mode=stat.S_IFREG)):
            with self.subTest(value=value), \
                    patch("disk_ha.interface.SmartInspection.os.stat") as metadata, \
                    patch("disk_ha.interface.SmartInspection.subprocess.run") as run:
                if isinstance(value, Exception):
                    metadata.side_effect = value
                else:
                    metadata.return_value = value
                self.assertTrue(SmartInspection(10).inspect(DISKS[0]).failed)
                run.assert_not_called()

    def test_command_unavailable_timeout_and_signal_are_failures(self):
        for failure in (FileNotFoundError(), PermissionError(),
                        subprocess.TimeoutExpired("smartctl", 10), None):
            with self.subTest(failure=failure), \
                    patch("disk_ha.interface.SmartInspection.os.stat",
                          return_value=SimpleNamespace(st_mode=stat.S_IFBLK)), \
                    patch("disk_ha.interface.SmartInspection.subprocess.run", side_effect=failure,
                          return_value=SimpleNamespace(stdout="", returncode=-9)):
                self.assertTrue(SmartInspection(10).inspect(DISKS[0]).failed)


class EmailNotificationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.mail_config = Path(temporary.name) / "mail.conf"
        self.mail_config.write_text("# simulated credentials\n")
        self.notification = EmailNotification("operator@example.com", "disk@example.com",
                                              str(self.mail_config), 10)
        self.report = CheckDisks(DISKS, "host", lambda disk: DiskHealth(disk, ("Failure",)),
                                 Mock()).run()

    def test_missing_mail_configuration_is_explicit_and_does_not_invoke_msmtp(self):
        self.mail_config.unlink()
        with patch("disk_ha.interface.EmailNotification.subprocess.run") as command:
            with self.assertRaisesRegex(NotificationError, "configuration file is missing"):
                self.notification.send(self.report, "host")
            command.assert_not_called()
        with patch("disk_ha.interface.EmailNotification.Path.is_file", side_effect=PermissionError("secret")), \
                patch("disk_ha.interface.EmailNotification.subprocess.run") as command:
            with self.assertRaisesRegex(NotificationError, "configuration file is missing or inaccessible"):
                self.notification.send(self.report, "host")
            command.assert_not_called()

    def test_email_contains_host_and_combined_report(self):
        with patch("disk_ha.interface.EmailNotification.subprocess.run",
                   return_value=SimpleNamespace(returncode=0)) as run:
            self.notification.send(self.report, "host")
        self.assertEqual(run.call_args.args[0],
                         [DDiskHA.MSMTP, f"--file={self.mail_config}", "--account=default", "-t"])
        self.assertEqual(run.call_args.kwargs["timeout"], 10)
        message = message_from_string(run.call_args.kwargs["input"])
        self.assertEqual(message["Subject"], "SMART disk alert on host")
        self.assertEqual(message["To"], "operator@example.com")
        self.assertEqual(message.get_content_type(), "multipart/alternative")
        self.assertEqual([part.get_content_type() for part in message.get_payload()], ["text/plain", "text/html"])
        html = message.get_payload(1).get_payload(decode=True).decode()
        self.assertIn("Table of contents", html)
        self.assertIn('href="#disk-1"', html)
        self.assertIn("Health summary", html)
        self.assertEqual(message.get_payload(0).get_payload(decode=True).decode(), self.report.render())

    def test_delivery_errors_do_not_expose_mail_diagnostics_or_credentials(self):
        for failure in (OSError("secret"), subprocess.TimeoutExpired("secret", 10), None):
            with self.subTest(failure=failure), \
                    patch("disk_ha.interface.EmailNotification.subprocess.run", side_effect=failure,
                          return_value=SimpleNamespace(returncode=1)), \
                    self.assertRaises(NotificationError) as caught:
                self.notification.send(self.report, "host")
            self.assertNotIn("secret", str(caught.exception))

    def test_requested_report_contains_raw_smart_output_for_both_healthy_disks(self):
        report = CheckDisks(DISKS, "host", lambda disk: DiskHealth(disk, smart_output=f"Full data: {disk.device_path}\n"),
                            Mock()).run()
        with patch("disk_ha.interface.EmailNotification.subprocess.run",
                   return_value=SimpleNamespace(returncode=0)) as command:
            self.notification.send_report(report, "host")
        message = message_from_string(command.call_args.kwargs["input"])
        self.assertEqual(message["Subject"], "SMART disk report on host")
        self.assertEqual(message["To"], "operator@example.com")
        self.assertEqual(message.get_content_type(), "multipart/alternative")
        self.assertEqual([part.get_content_type() for part in message.get_payload()], ["text/plain", "text/html"])
        html = message.get_payload(1).get_payload(decode=True).decode()
        self.assertIn("Table of contents", html)
        self.assertIn('href="#disk-1"', html)
        self.assertIn("Health summary", html)
        body = message.get_payload(0).get_payload(decode=True).decode()
        for disk in DISKS:
            self.assertIn(f"Full data: {disk.device_path}", body)
        self.assertIn("Overall result: PASS", body)

    def test_invalid_command_configuration_is_rejected(self):
        for timeout in (0, -1, float("inf"), float("nan")):
            with self.subTest(timeout=timeout), self.assertRaises(ValueError):
                SmartInspection(timeout)
            with self.subTest(timeout=timeout), self.assertRaises(ValueError):
                EmailNotification("a@example.com", "b@example.com", "/tmp/mail.conf", timeout)
        with self.assertRaises(ValueError):
            EmailNotification("a@example.com\nBcc: x@example.com", "b@example.com", "/tmp/mail.conf", 10)
        with self.assertRaises(ValueError):
            EmailNotification("a@example.com", "b@example.com", "relative", 10)


if __name__ == "__main__":
    unittest.main()
