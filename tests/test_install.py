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
        executable_check = patch.object(installer.os, "access", return_value=True)
        executable_check.start()
        self.addCleanup(executable_check.stop)
        for target, value in (("SystemAccount.provision", SimpleNamespace(pw_uid=os.geteuid(), pw_gid=os.getegid())),
                              ("DatabaseProvisioning.provision", None)):
            provisioning = patch.object(getattr(installer, target.split('.')[0]), target.split('.')[1],
                                        return_value=value)
            provisioning.start()
            self.addCleanup(provisioning.stop)
        service = patch.object(installer.DDISKHA, "WEB_SERVICE_FILE",
                               str(Path(temporary.name) / "disk-ha-web.service"))
        service.start()
        self.addCleanup(service.stop)
        control = patch.object(installer, "systemctl")
        self.control = control.start()
        self.addCleanup(control.stop)
        readiness = patch.object(installer, "restart")
        self.restart = readiness.start()
        self.addCleanup(readiness.stop)
        metadata = patch.object(installer.DDISKHA, "INSTALL_DIR", str(self.target))
        metadata.start()
        self.addCleanup(metadata.stop)
        output = redirect_stdout(io.StringIO())
        output.__enter__()
        self.addCleanup(output.__exit__, None, None, None)

    def test_install_upgrade_and_uninstall_preserve_local_files(self):
        installer.install()
        constants = self.target / "disk_ha/constants/DDISKHA.py"
        expected = (ROOT / "disk_ha/constants/DDISKHA.py").read_bytes()
        self.assertEqual(constants.read_bytes(), expected)
        for directory in (self.target, self.target / "bin", constants.parent.parent, constants.parent):
            self.assertEqual(directory.stat().st_mode & 0o777, 0o755)
        self.assertEqual(constants.stat().st_mode & 0o777, 0o644)
        executable = self.target / "bin/disk-ha-web"
        self.assertEqual(executable.stat().st_mode & 0o777, 0o755)
        with zipfile.ZipFile(executable) as archive:
            self.assertEqual(archive.read("disk_ha/server/static/index.html"),
                             (ROOT / "disk_ha/server/static/index.html").read_bytes())
        service = Path(installer.DDISKHA.WEB_SERVICE_FILE)
        self.assertEqual(service.stat().st_mode & 0o777, 0o644)
        self.assertIn(f"ExecStart={executable} --host 0.0.0.0 --port 23300", service.read_text())
        self.assertIn("User=diskha\nGroup=diskha", service.read_text())
        self.assertIn(f"LoadCredential=database.env:{installer.DDISKHA.DATABASE_ENV}", service.read_text())
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
             "from disk_ha.constants.DDISKHA import DDISKHA; print(DDISKHA.VERSION)"],
            cwd=self.target, text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), installer.DDISKHA.VERSION)
        preserved = {}
        for name in ("conf/settings.json", "conf/credentials.env", "data/state.json"):
            path = self.target / name
            path.write_text("Local configuration or data\n")
            path.chmod(0o600)
            preserved[path] = path.read_bytes()
        constants.write_text('VERSION = "old release"\n')
        installer.install()
        self.assertEqual(constants.read_bytes(), expected)
        installer.uninstall()
        installer.uninstall()
        self.assertFalse((self.target / "disk_ha").exists())
        self.assertFalse(executable.exists())
        self.assertFalse(checker.exists())
        self.scheduling.assert_any_call(self.target, None)
        self.assertFalse(service.exists())
        self.control.assert_any_call("disable", "--now", service.name)
        for path, content in preserved.items():
            self.assertEqual(path.read_bytes(), content)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_staging_failure_keeps_installed_metadata(self):
        installer.install()
        constants = self.target / "disk_ha/constants/DDISKHA.py"
        original = constants.read_bytes()
        with patch.object(installer.shutil, "copytree", side_effect=OSError("Staging failed")):
            with self.assertRaisesRegex(OSError, "Staging failed"):
                installer.install()
        self.assertEqual(constants.read_bytes(), original)
        self.assertEqual(list(self.target.glob(".disk-ha-install-*")), [])

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
