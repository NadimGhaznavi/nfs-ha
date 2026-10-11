"""Verify deployment and preservation in temporary installation directories."""

from contextlib import redirect_stdout
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
import zipfile
from types import SimpleNamespace
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("installer", ROOT / "scripts/install.py")
installer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(installer)


class InstallationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="disk-ha-install-test-")
        self.addCleanup(temporary.cleanup)
        self.target = Path(temporary.name) / "prod"
        scheduling = patch.object(installer.HealthSchedule, "apply")
        self.scheduling = scheduling.start()
        self.addCleanup(scheduling.stop)
        reading = patch.object(installer.HealthSchedule, "read", side_effect=lambda: {
            "enabled": json.loads((self.target / "conf/health.json").read_text())["enabled"],
            "expression": json.loads((self.target / "conf/health.json").read_text())["expression"] or ""})
        self.reading = reading.start()
        self.addCleanup(reading.stop)
        sync_scheduling = patch.object(installer.SyncSchedule, "apply")
        self.sync_scheduling = sync_scheduling.start()
        self.addCleanup(sync_scheduling.stop)
        sync_reading = patch.object(installer.SyncSchedule, "read", side_effect=lambda: {
            "enabled": json.loads((self.target / "conf/sync.json").read_text())["enabled"],
            "expression": json.loads((self.target / "conf/sync.json").read_text())["expression"] or ""})
        self.sync_reading = sync_reading.start()
        self.addCleanup(sync_reading.stop)
        executable_check = patch.object(installer.os, "access", return_value=True)
        executable_check.start()
        self.addCleanup(executable_check.stop)
        for target, value in (("SystemAccount.provision", SimpleNamespace(pw_uid=os.geteuid(), pw_gid=os.getegid())),
                              ("DatabaseProvisioning.provision", None)):
            provisioning = patch.object(getattr(installer, target.split('.')[0]), target.split('.')[1],
                                        return_value=value)
            provisioning.start()
            self.addCleanup(provisioning.stop)
        service = patch.object(installer.DDiskHA, "WEB_SERVICE_FILE",
                               str(Path(temporary.name) / "disk-ha-web.service"))
        service.start()
        self.addCleanup(service.stop)
        for name, filename in (("HEALTH_SERVICE_FILE", "disk-ha-health.service"),
                               ("EMAIL_REPORT_SERVICE_FILE", "disk-ha-email-report.service"),
                               ("SYNC_SERVICE_FILE", "disk-ha-sync.service"),
                               ("HEALTH_SUDOERS_FILE", "disk-ha-health")):
            setting = patch.object(installer.DDiskHA, name, str(Path(temporary.name) / filename))
            setting.start()
            self.addCleanup(setting.stop)
        original_run = subprocess.run
        validation = patch.object(installer.subprocess, "run", wraps=subprocess.run)
        self.commands = validation.start()
        self.addCleanup(validation.stop)

        def run_command(arguments, **kwargs):
            if arguments[0] == installer.DDiskHA.VISUDO:
                return SimpleNamespace(returncode=0)
            return original_run(arguments, **kwargs)

        # Preserve real archive checks while simulating privileged validation.
        self.commands.side_effect = run_command
        control = patch.object(installer, "systemctl")
        self.control = control.start()
        self.addCleanup(control.stop)
        readiness = patch.object(installer, "restart")
        self.restart = readiness.start()
        self.addCleanup(readiness.stop)
        metadata = patch.object(installer.DDiskHA, "INSTALL_DIR", str(self.target))
        metadata.start()
        self.addCleanup(metadata.stop)
        output = redirect_stdout(io.StringIO())
        output.__enter__()
        self.addCleanup(output.__exit__, None, None, None)

    def test_install_upgrade_and_uninstall_preserve_local_files(self):
        installer.install()
        constants = self.target / "disk_ha/constants/DDiskHA.py"
        expected = (ROOT / "disk_ha/constants/DDiskHA.py").read_bytes()
        self.assertEqual(constants.read_bytes(), expected)
        for directory in (self.target, self.target / "bin", constants.parent.parent, constants.parent):
            self.assertEqual(directory.stat().st_mode & 0o777, 0o755)
        self.assertEqual(constants.stat().st_mode & 0o777, 0o644)
        executable = self.target / "bin/disk-ha-web"
        self.assertEqual(executable.stat().st_mode & 0o777, 0o755)
        with zipfile.ZipFile(executable) as archive:
            self.assertEqual(archive.read("disk_ha/server/static/index.html"),
                             (ROOT / "disk_ha/server/static/index.html").read_bytes())
        service = Path(installer.DDiskHA.WEB_SERVICE_FILE)
        self.assertEqual(service.stat().st_mode & 0o777, 0o644)
        self.assertIn(f"ExecStart={executable} --host 0.0.0.0 --port 23300", service.read_text())
        self.assertIn("User=diskha\nGroup=diskha", service.read_text())
        self.assertIn(f"LoadCredential=database.env:{installer.DDiskHA.DATABASE_ENV}", service.read_text())
        self.assertNotIn("LoadCredential=health.json", service.read_text())
        health_service = Path(installer.DDiskHA.HEALTH_SERVICE_FILE)
        sudoers = Path(installer.DDiskHA.HEALTH_SUDOERS_FILE)
        self.assertIn("User=root", health_service.read_text())
        email_service = Path(installer.DDiskHA.EMAIL_REPORT_SERVICE_FILE)
        self.assertIn("--email-report", email_service.read_text())
        self.assertIn("User=root", email_service.read_text())
        self.assertEqual(email_service.stat().st_mode & 0o777, 0o644)
        self.assertIn(f"ExecStart={self.target}/bin/disk-ha-check", health_service.read_text())
        sync_service = Path(installer.DDiskHA.SYNC_SERVICE_FILE)
        self.assertIn("User=root", sync_service.read_text())
        self.assertIn(f"ExecStart={self.target}/bin/disk-ha-sync --config {self.target}/conf/sync.json "
                      f"--result {self.target}/data/sync-output.log", sync_service.read_text())
        self.assertEqual(sync_service.stat().st_mode & 0o777, 0o644)
        self.assertEqual(sudoers.stat().st_mode & 0o777, 0o440)
        self.assertEqual(sudoers.read_text(),
                         "diskha ALL=(root) NOPASSWD: /usr/bin/systemctl start --no-block disk-ha-health.service\n"
                         "diskha ALL=(root) NOPASSWD: /usr/bin/systemctl start --no-block disk-ha-email-report.service\n"
                         "diskha ALL=(root) NOPASSWD: /usr/bin/systemctl start --no-block disk-ha-sync.service\n"
                         f'diskha ALL=(root) NOPASSWD: {self.target}/bin/disk-ha-schedule ""\n')
        self.control.assert_any_call("enable", service.name)
        self.restart.assert_called_once_with()
        self.assertEqual((self.target / "conf").stat().st_mode & 0o777, 0o700)
        self.assertEqual((self.target / "data").stat().st_mode & 0o777, 0o750)
        self.assertEqual((self.target / "data/health.log").stat().st_mode & 0o777, 0o640)
        self.assertEqual((self.target / "conf/health.json").stat().st_mode & 0o777, 0o600)
        checker = self.target / "bin/disk-ha-check"
        self.assertTrue(checker.exists())
        self.assertEqual(checker.stat().st_mode & 0o777, 0o755)
        result = subprocess.run(
            ["/usr/bin/python3", "-B", "-c",
             "from disk_ha.constants.DDiskHA import DDiskHA; print(DDiskHA.VERSION)"],
            cwd=self.target, text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), installer.DDiskHA.VERSION)
        preserved = {}
        for name in ("conf/settings.json", "conf/credentials.env", "data/state.json"):
            path = self.target / name
            path.write_text("Local configuration or data\n")
            path.chmod(0o600)
            preserved[path] = path.read_bytes()
        constants.write_text('VERSION = "old release"\n')
        legacy_constants = constants.with_name("DDISKHA.py")
        legacy_constants.write_text('class DDISKHA:\n    VERSION = "old release"\n')
        installer.install()
        self.assertEqual(constants.read_bytes(), expected)
        self.assertFalse(legacy_constants.exists())
        installer.uninstall()
        installer.uninstall()
        self.assertFalse((self.target / "disk_ha").exists())
        self.assertFalse(executable.exists())
        self.assertFalse(checker.exists())
        self.assertFalse((self.target / "bin/disk-ha-sync").exists())
        self.sync_scheduling.assert_any_call(self.target, None)
        self.assertFalse((self.target / "bin/disk-ha-schedule").exists())
        self.scheduling.assert_any_call(self.target, None)
        self.assertFalse(service.exists())
        self.assertFalse(health_service.exists())
        self.assertFalse(Path(installer.DDiskHA.SYNC_SERVICE_FILE).exists())
        self.assertFalse(Path(installer.DDiskHA.EMAIL_REPORT_SERVICE_FILE).exists())
        self.assertFalse(sudoers.exists())
        self.control.assert_any_call("disable", "--now", service.name)
        for path, content in preserved.items():
            self.assertEqual(path.read_bytes(), content)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_staging_failure_keeps_installed_metadata(self):
        installer.install()
        constants = self.target / "disk_ha/constants/DDiskHA.py"
        original = constants.read_bytes()
        with patch.object(installer.shutil, "copytree", side_effect=OSError("Staging failed")):
            with self.assertRaisesRegex(OSError, "Staging failed"):
                installer.install()
        self.assertEqual(constants.read_bytes(), original)
        self.assertEqual(list(self.target.glob(".disk-ha-install-*")), [])

    def test_invalid_sudo_rule_keeps_previous_permission_and_cleans_candidate(self):
        installer.install()
        rule = Path(installer.DDiskHA.HEALTH_SUDOERS_FILE)
        previous = rule.read_bytes()
        self.restart.reset_mock()
        self.commands.side_effect = subprocess.CalledProcessError(1, [installer.DDiskHA.VISUDO])
        with self.assertRaises(subprocess.CalledProcessError):
            installer.install()
        self.assertEqual(rule.read_bytes(), previous)
        self.assertEqual(list(rule.parent.glob(".disk-ha-health-*")), [])
        self.restart.assert_not_called()

    def test_health_configuration_results_and_logs_survive_upgrade_and_removal(self):
        installer.install()
        configuration = self.target / "conf/health.json"
        values = json.loads(configuration.read_text())
        self.assertTrue(values["enabled"])
        self.assertEqual(values["expression"], "0 14 * * *")
        self.assertEqual(values["mail"]["config_path"], "/root/.msmtprc")
        values.update(enabled=True, expression="*/30 * * * *",
                      mail={"recipient": "operator@example.com", "sender": "disk@example.com",
                            "config_path": "/tmp/mail.conf", "timeout": 10})
        configuration.write_text(json.dumps(values))
        result = self.target / "data/health.json"
        result.write_text("saved health result")
        log = self.target / "data/health.log"
        log.write_text("saved health log")
        with patch.object(installer.os, "access", return_value=True):
            installer.install()
        self.assertTrue(self.scheduling.call_args.args[1].enabled)
        self.assertEqual(self.scheduling.call_args.args[1].expression, "*/30 * * * *")
        self.control.assert_any_call("enable", "--now", "cron.service")
        self.assertEqual(json.loads(configuration.read_text()), values)
        self.assertEqual(result.read_text(), "saved health result")
        self.assertEqual(log.read_text(), "saved health log")
        installer.uninstall()
        self.assertEqual(json.loads(configuration.read_text()), values)
        self.assertEqual(result.read_text(), "saved health result")
        self.assertEqual(log.read_text(), "saved health log")

    def test_health_checker_archive_runs_without_checkout_when_disabled(self):
        installer.install()
        configuration = self.target / "conf/health.json"
        values = json.loads(configuration.read_text())
        values["enabled"] = False
        configuration.write_text(json.dumps(values))
        checker = self.target / "bin/disk-ha-check"
        result = subprocess.run(["/usr/bin/python3", "-B", str(checker), "--help"],
                                cwd=self.target, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--config", result.stdout)
        # Invoke the runner function directly to avoid requiring root in the test.
        result = subprocess.run(
            ["/usr/bin/python3", "-B", "-c",
             "from pathlib import Path; from disk_ha.health import run; "
             "raise SystemExit(run(Path('conf/health.json'), Path('data/health.json')))"],
            cwd=self.target, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("monitoring is disabled", result.stdout)
        self.assertFalse((self.target / "data/health.json").exists())

    def test_upgrade_retains_live_cron_schedule_and_external_removal(self):
        installer.install()
        config = self.target / "conf/health.json"
        original_mail = json.loads(config.read_text())["mail"]
        self.reading.side_effect = None
        self.reading.return_value = {"enabled": True, "expression": "*/20 * * * *"}
        installer.install()
        self.assertEqual(json.loads(config.read_text())["expression"], "*/20 * * * *")
        self.assertEqual(json.loads(config.read_text())["mail"], original_mail)
        self.reading.return_value = {"enabled": False, "expression": ""}
        installer.install()
        self.assertFalse(json.loads(config.read_text())["enabled"])
        self.assertFalse(self.scheduling.call_args.args[1].enabled)

    def test_sync_install_upgrade_and_removal_preserve_settings_and_output(self):
        installer.install()
        config = self.target / "conf/sync.json"
        values = json.loads(config.read_text())
        self.assertTrue(values["enabled"])
        self.assertEqual(values["expression"], "0 */4 * * *")
        self.assertEqual(config.stat().st_mode & 0o777, 0o600)
        self.assertEqual((self.target / "data/sync.log").stat().st_mode & 0o777, 0o640)
        worker = self.target / "bin/disk-ha-sync"
        self.assertEqual(worker.stat().st_mode & 0o777, 0o755)
        for name in ("SyncConfiguration", "MountInspection", "RsyncMirror", "SyncSchedule", "CronSchedule"):
            self.assertTrue((self.target / f"disk_ha/interface/{name}.py").is_file())
        result = subprocess.run([str(worker), "--help"], capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--result", result.stdout)
        output = self.target / "data/sync-output.log"
        output.write_text("last verbose output")
        values["timeout"] = 12345
        config.write_text(json.dumps(values))
        self.sync_reading.side_effect = None
        self.sync_reading.return_value = {"enabled": True, "expression": "0 */6 * * *"}
        installer.install()
        self.assertEqual(json.loads(config.read_text())["expression"], "0 */6 * * *")
        self.assertEqual(json.loads(config.read_text())["timeout"], 12345)
        self.assertEqual(json.loads(config.read_text())["source"], values["source"])
        installer.uninstall()
        self.assertFalse(worker.exists())
        self.assertTrue(config.is_file())
        self.assertEqual(output.read_text(), "last verbose output")

    def test_wrappers_delegate_from_a_checkout_with_spaces(self):
        with tempfile.TemporaryDirectory(prefix="disk-ha-wrappers-") as temporary:
            checkout = Path(temporary) / "checkout with spaces"
            scripts = checkout / "scripts"
            scripts.mkdir(parents=True)
            (scripts / "install.py").write_text(
                "import sys\nfrom pathlib import Path\n"
                "print(Path.cwd())\nprint(sys.argv[1])\nraise SystemExit(7)\n")
            for action in ("install", "upgrade", "uninstall", "restart"):
                wrapper = scripts / f"{action}.sh"
                wrapper.write_bytes((ROOT / "scripts" / wrapper.name).read_bytes())
                result = subprocess.run(["bash", str(wrapper)], cwd=temporary,
                                        text=True, capture_output=True, timeout=10)
                self.assertEqual(result.returncode, 7)
                self.assertEqual(result.stdout.splitlines(), [str(checkout), action])

    def test_non_root_action_is_rejected(self):
        with patch.object(installer.os, "geteuid", return_value=1000), \
                patch("sys.argv", ["install.py", "install"]), redirect_stdout(io.StringIO()), \
                patch("sys.stderr", new_callable=io.StringIO) as errors:
            self.assertEqual(installer.main(), 1)
        self.assertIn("Run this script as root", errors.getvalue())
        self.assertFalse(self.target.exists())

    def test_service_failure_returns_failing_status(self):
        self.control.side_effect = subprocess.CalledProcessError(1, ["systemctl"])
        with patch.object(installer.os, "geteuid", return_value=0), \
                patch("sys.argv", ["install.py", "install"]), \
                patch("sys.stderr", new_callable=io.StringIO) as errors:
            self.assertEqual(installer.main(), 1)
        self.assertIn("disk-ha:", errors.getvalue())

    def test_database_failure_does_not_replace_server_or_restart(self):
        installer.install()
        archive = self.target / "bin/disk-ha-web"
        before = archive.read_bytes()
        self.restart.reset_mock()
        with patch.object(installer.DatabaseProvisioning, "provision", side_effect=ValueError("Unavailable")):
            with self.assertRaisesRegex(ValueError, "Unavailable"):
                installer.install()
        self.assertEqual(archive.read_bytes(), before)
        self.restart.assert_not_called()


if __name__ == "__main__":
    unittest.main()
