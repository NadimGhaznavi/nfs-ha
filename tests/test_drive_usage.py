"""Verify drive readings and missing or inaccessible mount presentation."""

from types import SimpleNamespace
import unittest
from unittest.mock import patch

from disk_ha.interface.DriveUsage import read_usage
from disk_ha.server.DrivePage import render_page


class DriveUsageTests(unittest.TestCase):
    def test_unmounted_path_does_not_read_root_filesystem_usage(self):
        with patch("disk_ha.interface.DriveUsage.os.path.ismount", return_value=False), \
                patch("disk_ha.interface.DriveUsage.shutil.disk_usage") as usage:
            self.assertIsNone(read_usage("/exports/disk1"))
        usage.assert_not_called()

    def test_mounted_path_reads_byte_counts(self):
        expected = SimpleNamespace(total=8 * 10**12, used=3 * 10**12)
        with patch("disk_ha.interface.DriveUsage.os.path.ismount", return_value=True), \
                patch("disk_ha.interface.DriveUsage.shutil.disk_usage", return_value=expected) as usage:
            self.assertIs(read_usage("/exports/disk2"), expected)
        usage.assert_called_once_with("/exports/disk2")

    def test_page_formats_each_drive_in_decimal_terabytes(self):
        readings = [SimpleNamespace(total=8 * 10**12, used=3.125 * 10**12),
                    SimpleNamespace(total=6 * 10**12, used=2 * 10**12)]
        with patch("disk_ha.server.DrivePage.read_usage", side_effect=readings) as usage:
            page = render_page().decode()
        self.assertEqual([call.args[0] for call in usage.call_args_list],
                         ["/exports/disk1", "/exports/disk2"])
        self.assertIn('<th scope="row">Disk 1</th><td>Source</td><td>8.00</td><td>3.12</td>', page)
        self.assertIn('<th scope="row">Disk 2</th><td>Target</td><td>6.00</td><td>2.00</td>', page)
        self.assertNotIn("{{disk", page)

    def test_missing_and_unreadable_drives_have_explicit_states(self):
        for failure, label in [(None, "Not mounted"), (PermissionError(), "Unavailable")]:
            with self.subTest(label=label), \
                    patch("disk_ha.server.DrivePage.read_usage", side_effect=[
                        failure, SimpleNamespace(total=8 * 10**12, used=0)]):
                page = render_page().decode()
            self.assertIn(f'<th scope="row">Disk 1</th><td>Source</td><td>{label}</td><td>{label}</td>', page)
            self.assertIn('<th scope="row">Disk 2</th><td>Target</td><td>8.00</td><td>0.00</td>', page)


if __name__ == "__main__":
    unittest.main()
