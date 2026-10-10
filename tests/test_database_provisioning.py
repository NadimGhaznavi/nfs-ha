"""Verify database provisioning with private files and simulated MariaDB commands."""

from concurrent.futures import ThreadPoolExecutor
import hashlib
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from disk_ha.constants.DDiskHA import DDiskHA
from disk_ha.interface.DatabaseEnvironment import DatabaseEnvironment
from disk_ha.interface.DatabaseProvisioning import DatabaseProvisioning


class ProvisioningTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix="diskha-database-")
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.credentials = self.root / "conf/database.env"
        self.provisioner = DatabaseProvisioning(self.credentials)
        self.root_patch = patch.object(DatabaseProvisioning, "_require_root")
        self.root_patch.start()
        self.addCleanup(self.root_patch.stop)
        password = patch("disk_ha.interface.DatabaseProvisioning.secrets.token_hex",
                         return_value="0123456789abcdef" * 4)
        password.start()
        self.addCleanup(password.stop)
        self.options = []
        client = patch("disk_ha.interface.DatabaseProvisioning.subprocess.run", side_effect=self.client)
        self.run = client.start()
        self.addCleanup(client.stop)

    def client(self, command, **arguments):
        if command[1].startswith("--defaults-file="):
            options = Path(command[1].split("=", 1)[1])
            self.assertEqual(options.stat().st_mode & 0o777, 0o600)
            self.options.append(options.read_text())
            return subprocess.CompletedProcess(command, 0, stdout="")
        return subprocess.CompletedProcess(command, 0, stdout="/run/mysqld/mysqld.sock\n")

    def existing(self, *, password='test-only;#"\\password'):
        self.credentials.parent.mkdir()
        self.credentials.write_text("DB_HOST=database.example\nDB_PORT=3307\nDB_NAME=custom\n"
                                    f"DB_USER=custom\nDB_PASSWORD={password}\n")
        self.credentials.chmod(0o600)
        return self.credentials.read_bytes()

    def test_first_install_provisions_account_verifies_access_and_publishes_private_credentials(self):
        self.provisioner.provision()
        values = DatabaseEnvironment.read(self.credentials)
        self.assertEqual(values["DB_NAME"], "diskha")
        self.assertEqual(values["DB_USER"], "diskha")
        self.assertEqual(values["DB_SOCKET"], "/run/mysqld/mysqld.sock")
        self.assertEqual(self.credentials.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.credentials.stat().st_uid, os.geteuid())
        self.assertEqual(self.credentials.parent.stat().st_mode & 0o777, 0o700)
        self.assertEqual(self.run.call_count, 2)
        admin, application = self.run.call_args_list
        sql = admin.kwargs["input"]
        digest = hashlib.sha1(hashlib.sha1(values["DB_PASSWORD"].encode()).digest()).hexdigest().upper()
        self.assertIn(f"USING '*{digest}'", sql)
        self.assertIn("CREATE DATABASE IF NOT EXISTS `diskha`", sql)
        self.assertIn("ON `diskha`.* TO 'diskha'@'localhost'", sql)
        self.assertNotIn(values["DB_PASSWORD"], sql)
        self.assertNotIn("DROP ", sql)
        self.assertNotIn("ALTER USER 'root'", sql)
        self.assertEqual(application.kwargs["input"], "SELECT 1;")
        self.assertIn("--protocol=socket", self.run.call_args.args[0])
        self.assertIn("--skip-ssl", admin.args[0])
        self.assertIn("--skip-ssl", application.args[0])
        self.assertIn('database="diskha"', self.options[0])
        self.assertNotIn("host=", self.options[0])
        self.assertNotIn("port=", self.options[0])
        for call in self.run.call_args_list:
            self.assertNotIn(values["DB_PASSWORD"], " ".join(call.args[0]))
            self.assertEqual(call.kwargs["timeout"], 30)
            self.assertTrue(call.kwargs["check"])
        self.assertEqual(list(self.credentials.parent.iterdir()), [self.credentials])

    def test_existing_custom_credentials_are_retained_without_account_commands(self):
        before = self.existing()
        self.provisioner.provision()
        self.assertEqual(self.credentials.read_bytes(), before)
        self.run.assert_called_once()
        self.assertIn("--protocol=tcp", self.run.call_args.args[0])
        self.assertNotIn("--skip-ssl", self.run.call_args.args[0])
        self.assertIn('host="database.example"', self.options[0])
        self.assertIn('password="test-only;#\\"\\\\password"', self.options[0])
        self.assertNotIn("CREATE USER", self.run.call_args.kwargs["input"])
        self.assertEqual(list(self.credentials.parent.iterdir()), [self.credentials])

    def test_invalid_existing_credentials_are_not_replaced(self):
        self.credentials.parent.mkdir()
        self.credentials.write_text("DB_HOST=localhost\n")
        self.credentials.chmod(0o600)
        with self.assertRaises(ValueError):
            self.provisioner.provision()
        self.assertEqual(self.credentials.read_text(), "DB_HOST=localhost\n")
        self.run.assert_not_called()

    def test_public_credentials_are_rejected(self):
        before = self.existing()
        self.credentials.chmod(0o644)
        with self.assertRaisesRegex(ValueError, "0600"):
            self.provisioner.provision()
        self.assertEqual(self.credentials.read_bytes(), before)
        self.run.assert_not_called()

    def test_failure_retains_existing_credentials_and_cleans_client_options(self):
        before = self.existing()
        self.run.side_effect = subprocess.CalledProcessError(1, "mariadb", stderr="private SQL")
        with self.assertRaises(ValueError) as error:
            self.provisioner.provision()
        self.assertNotIn("private SQL", str(error.exception))
        self.assertEqual(self.credentials.read_bytes(), before)
        self.assertEqual(list(self.credentials.parent.iterdir()), [self.credentials])

    def test_bootstrap_and_connection_failures_do_not_publish_credentials_and_allow_retry(self):
        failures = (FileNotFoundError(), subprocess.TimeoutExpired("mariadb", 30),
                    subprocess.CalledProcessError(1, "mariadb", stderr="private SQL"))
        for failure in failures:
            for after_bootstrap in (False, True):
                with self.subTest(failure=type(failure).__name__, after_bootstrap=after_bootstrap):
                    self.run.side_effect = ([subprocess.CompletedProcess([], 0, stdout="/tmp/db.sock\n"), failure]
                                            if after_bootstrap else failure)
                    with self.assertRaises(ValueError) as error:
                        self.provisioner.provision()
                    self.assertNotIn("private SQL", str(error.exception))
                    self.assertFalse(self.credentials.exists())
                    self.assertEqual(list(self.credentials.parent.iterdir()), [])
        self.run.side_effect = self.client
        self.provisioner.provision()
        self.assertTrue(self.credentials.is_file())

    def test_invalid_socket_does_not_publish_credentials(self):
        for socket in ("", "relative.sock", "/tmp/db.sock\nsecond row"):
            with self.subTest(socket=socket):
                self.run.side_effect = None
                self.run.return_value = subprocess.CompletedProcess([], 0, stdout=socket)
                with self.assertRaisesRegex(ValueError, "socket"):
                    self.provisioner.provision()
                self.assertFalse(self.credentials.exists())

    def test_invalid_and_administrative_names_are_rejected_before_sql(self):
        for database, user in (("diskha`; DROP DATABASE other", "diskha"),
                               ("diskha", "root"), ("mysql", "diskha")):
            with self.subTest(database=database, user=user), \
                    patch.object(DDiskHA, "DATABASE_NAME", database), \
                    patch.object(DDiskHA, "DATABASE_USER", user), self.assertRaises(ValueError):
                self.provisioner.provision()
        self.run.assert_not_called()

    def test_symlink_file_and_directory_are_rejected(self):
        self.credentials.parent.mkdir()
        target = self.root / "elsewhere"
        self.credentials.symlink_to(target)
        with self.assertRaisesRegex(ValueError, "symlinks"):
            self.provisioner.provision()
        self.assertFalse(target.exists())
        self.credentials.unlink()
        linked = self.root / "linked"
        linked.symlink_to(self.credentials.parent, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "symlinks"):
            DatabaseProvisioning(linked / "database.env").provision()
        self.run.assert_not_called()

    def test_inherited_mysql_overrides_are_not_used(self):
        with patch.dict(os.environ, {"MYSQL_PWD": "test-only", "MYSQL_HOST": "elsewhere",
                                     "MYSQL_TCP_PORT": "3307", "MYSQL_UNIX_PORT": "/other.sock"}):
            self.provisioner.provision()
        for call in self.run.call_args_list:
            self.assertFalse(any(key.startswith("MYSQL_") for key in call.kwargs["env"]))

    def test_concurrent_provisioning_creates_credentials_once(self):
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(self.provisioner.provision) for _ in range(2)]
            for future in futures:
                future.result(timeout=5)
        self.assertEqual(sum(call.args[0][1] == "--no-defaults" for call in self.run.call_args_list), 1)
        self.assertEqual(self.run.call_count, 3)
        DatabaseEnvironment.read(self.credentials)

    def test_nonroot_provisioning_is_rejected_before_database_changes(self):
        self.root_patch.stop()
        with patch("os.geteuid", return_value=1000), self.assertRaises(PermissionError):
            self.provisioner.provision()
        self.run.assert_not_called()

