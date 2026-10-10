"""Verify account creation and reuse without changing host accounts."""

import os
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from disk_ha.constants.DDiskHA import DDiskHA
from disk_ha.interface.SystemAccount import SystemAccount


class AccountTests(unittest.TestCase):
    def setUp(self):
        self.account = SimpleNamespace(pw_uid=998, pw_gid=998, pw_shell=DDiskHA.NOLOGIN,
                                       pw_dir=DDiskHA.INSTALL_DIR)
        self.group = SimpleNamespace(gr_gid=998)

    def test_missing_account_and_group_are_created_without_login_or_home_creation(self):
        with patch("os.geteuid", return_value=0), \
                patch("grp.getgrnam", side_effect=[KeyError(), self.group]), \
                patch("pwd.getpwnam", side_effect=[KeyError(), self.account]), \
                patch("disk_ha.interface.SystemAccount.subprocess.run") as run:
            self.assertEqual(SystemAccount.provision(), self.account)
        self.assertEqual(run.call_args_list[0].args[0], [DDiskHA.GROUPADD, "--system", "diskha"])
        command = run.call_args_list[1].args[0]
        self.assertIn("--no-create-home", command)
        self.assertIn(DDiskHA.NOLOGIN, command)
        self.assertIn("--system", command)
        for call in run.call_args_list:
            self.assertEqual(call.kwargs, {"check": True, "timeout": 30})

    def test_existing_account_is_reused_without_mutation(self):
        with patch("os.geteuid", return_value=0), \
                patch("grp.getgrnam", return_value=self.group), \
                patch("pwd.getpwnam", return_value=self.account), \
                patch("disk_ha.interface.SystemAccount.subprocess.run") as run:
            self.assertEqual(SystemAccount.provision(), self.account)
        run.assert_not_called()

    def test_conflicting_existing_account_is_rejected(self):
        for field, value in (("pw_uid", 0), ("pw_gid", 0), ("pw_shell", "/bin/bash"),
                             ("pw_dir", "/root")):
            with self.subTest(field=field):
                account = SimpleNamespace(**vars(self.account))
                setattr(account, field, value)
                with patch("os.geteuid", return_value=0), \
                        patch("grp.getgrnam", return_value=self.group), \
                        patch("pwd.getpwnam", return_value=account), \
                        patch("disk_ha.interface.SystemAccount.subprocess.run") as run:
                    with self.assertRaises(ValueError):
                        SystemAccount.provision()
                    run.assert_not_called()

    def test_nonroot_provisioning_is_rejected(self):
        with patch("os.geteuid", return_value=1000), self.assertRaises(PermissionError):
            SystemAccount.provision()
