"""Verify email presentation preserves SMART information without interpreting health."""

from datetime import datetime, timezone
from html.parser import HTMLParser
import unittest

from disk_ha.entity.Disk import Disk
from disk_ha.entity.DiskHealth import DiskHealth
from disk_ha.entity.DiskCheckReport import DiskCheckReport
from disk_ha.presentation.SmartEmail import attributes, render


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = set()
        self.targets = set()

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if "id" in values:
            self.ids.add(values["id"])
        if values.get("href", "").startswith("#"):
            self.targets.add(values["href"][1:])


class SmartEmailTests(unittest.TestCase):
    def test_standard_brief_and_compound_raw_values_preserved(self):
        standard = ("ID# ATTRIBUTE_NAME FLAG VALUE WORST THRESH TYPE UPDATED WHEN_FAILED RAW_VALUE\n"
                    "5 Reallocated_Sector_Ct 0x0033 100 099 010 Pre-fail Always - 0\n")
        brief = ("ID# ATTRIBUTE_NAME FLAGS VALUE WORST THRESH FAIL RAW_VALUE\n"
                 "5 Reallocated_Sector_Ct PO--CK 100 099 010 - 0\n"
                 "188 Command_Timeout -O--CK 100 099 000 - 0 0 0\n"
                 "194 Temperature_Celsius -O---K 041 051 000 - 41 (Min/Max 22/50)\n")
        self.assertEqual(attributes(standard)[0], ["5", "Reallocated_Sector_Ct", "100", "099", "010", "0"])
        rows = attributes(standard + "\nExtended report:\n" + brief + "\n5 unrelated log row\n")
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[1][-1], "0 0 0")
        self.assertEqual(rows[2][-1], "41 (Min/Max 22/50)")
        self.assertEqual(attributes("ID# ATTRIBUTE_NAME FLAGS VALUE WORST THRESH FAIL RAW_VALUE\n5 missing\n"), [])

    def test_summary_sections_links_escaping_and_full_output(self):
        output = ("Device Model: Seagate <disk>\nSerial Number: serial&1\n"
                  "SMART overall-health self-assessment test result: PASSED\n"
                  "ID# ATTRIBUTE_NAME FLAGS VALUE WORST THRESH FAIL RAW_VALUE\n"
                  "197 Current_Pending_Sector -O--C- 100 100 000 - 0\n\n"
                  "SCT Error Recovery Control command not supported\n<script>alert(1)</script>\n")
        disks = (DiskHealth(Disk("/dev/disk/by-id/ata-source"), smart_output=output, smart_status=0),
                 DiskHealth(Disk("/dev/disk/by-id/ata-target"), ("Pending <sector> & unreadable",), smart_status=4))
        html = render(DiskCheckReport(disks, "Delivery <failed>"), "host<script>",
                      datetime(2026, 10, 10, 20, 30, 40, tzinfo=timezone.utc))
        self.assertIn("Overall health: FAIL", html)
        self.assertIn("2026-10-10 20:30:40 UTC", html)
        self.assertIn("Seagate &lt;disk&gt;", html)
        self.assertIn("Pending &lt;sector&gt; &amp; unreadable", html)
        self.assertIn("Delivery &lt;failed&gt;", html)
        self.assertIn("SCT Error Recovery Control command not supported", html)
        self.assertIn("No readable SMART attribute table", html)
        self.assertNotIn("<script>", html)
        links = Links()
        links.feed(html)
        self.assertTrue(links.targets)
        self.assertLessEqual(links.targets, links.ids)
        self.assertIn("Source", html)
        self.assertIn("Target", html)

    def test_unavailable_data_and_healthy_results_have_explicit_states(self):
        disk = Disk("/dev/disk/by-id/ata-source")
        for health in (DiskHealth(disk), DiskHealth(disk, ("SMART unavailable",))):
            html = render(DiskCheckReport((health,)), "host", datetime.now(timezone.utc))
            self.assertIn("Overall health: " + ("FAIL" if health.failed else "PASS"), html)
            self.assertIn("No readable SMART attribute table", html)
            self.assertIn("No additional diagnostics included", html)
            self.assertIn("Unavailable", html)


if __name__ == "__main__":
    unittest.main()
