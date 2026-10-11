"""Verify guarded mirroring and output using temporary disks and simulated mounts."""

from contextlib import redirect_stdout
import fcntl
import io
import json
from pathlib import Path
import signal
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from disk_ha.constants.DDiskHA import DDiskHA
from disk_ha.interface.HealthSchedule import HealthSchedule
from disk_ha.interface.MountInspection import MountInspection
from disk_ha.interface.RsyncMirror import RsyncMirror
from disk_ha.interface.SyncConfiguration import SyncConfiguration
from disk_ha.interface.SyncSchedule import SyncSchedule
from disk_ha.server.SyncPage import render_sync_output
from disk_ha.sync import run


class SyncTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="disk-ha-sync-test-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        (self.root / "conf").mkdir()
        (self.root / "data").mkdir()
        self.config = self.root / "conf/sync.json"
        self.result = self.root / "data/sync-output.log"
        self.values = json.loads((Path(__file__).resolve().parents[1] / "conf/sync.json").read_text())
        self.source = self.root / "disk1"
        self.target = self.root / "disk2"
        self.source.mkdir()
        self.target.mkdir()
        self.values["source"]["mount"] = str(self.source)
        self.values["target"]["mount"] = str(self.target)
        self.save()

    def save(self):
        self.config.write_text(json.dumps(self.values))

    def worker(self):
        with redirect_stdout(io.StringIO()):
            return run(self.config, self.result)

    def mount_command(self, arguments, **kwargs):
        path = arguments[arguments.index("--mountpoint") + 1]
        role = "source" if path == str(self.source) else "target"
        return SimpleNamespace(returncode=0, stdout=json.dumps({"filesystems": [{
            "target": path, "uuid": self.values[role]["uuid"],
            "maj:min": "8:1" if role == "source" else "8:2", "fsroot": "/"}]}))

    def test_exact_mount_identities_allow_sync(self):
        with patch("disk_ha.interface.MountInspection.subprocess.run", side_effect=self.mount_command) as command:
            MountInspection().verify(SyncConfiguration(self.config))
        self.assertEqual(command.call_count, 2)
        self.assertEqual(command.call_args.kwargs["timeout"], 10)

    def test_missing_wrong_reversed_bind_and_identical_filesystems_prevent_rsync(self):
        def altered(kind):
            def command(arguments, **kwargs):
                value = self.mount_command(arguments, **kwargs)
                record = json.loads(value.stdout)["filesystems"][0]
                if kind == "missing":
                    value.returncode = 1
                elif kind == "wrong":
                    record["uuid"] = "unknown"
                elif kind == "reversed":
                    record["uuid"] = self.values["target" if record["target"] == str(self.source) else "source"]["uuid"]
                elif kind == "bind":
                    record["fsroot"] = "/subdirectory"
                elif kind == "same":
                    record["maj:min"] = "8:1"
                elif kind == "ancestor":
                    record["target"] = str(self.root)
                value.stdout = json.dumps({"filesystems": [record]})
                return value
            return command

        self.result.write_text("previous output")
        for kind in ("missing", "wrong", "reversed", "bind", "same", "ancestor"):
            with self.subTest(kind=kind), \
                    patch("disk_ha.interface.MountInspection.subprocess.run", side_effect=altered(kind)), \
                    patch.object(RsyncMirror, "run") as mirror:
                self.assertEqual(self.worker(), 1)
                mirror.assert_not_called()
                self.assertEqual(self.result.read_text(), "previous output")

    def test_alias_and_missing_directories_are_rejected(self):
        alias = self.root / "alias"
        alias.symlink_to(self.source, target_is_directory=True)
        with self.assertRaises(ValueError):
            MountInspection().inspect(alias, self.values["source"]["uuid"])
        with self.assertRaises(OSError):
            MountInspection().inspect(self.root / "absent", self.values["source"]["uuid"])

    def test_real_rsync_mirrors_contents_and_deletions_despite_health_alert(self):
        (self.source / "folder").mkdir()
        (self.source / "folder/keep.txt").write_text("new data")
        (self.target / "obsolete.txt").write_text("remove me")
        (self.root / "data/health.json").write_text('{"disks":[{"problems":["FAIL"]}]}')
        with patch.object(MountInspection, "verify") as mounts:
            self.assertEqual(self.worker(), 0)
        self.assertEqual(mounts.call_count, 2)
        self.assertEqual((self.target / "folder/keep.txt").read_text(), "new data")
        self.assertFalse((self.target / "obsolete.txt").exists())
        output = self.result.read_text()
        self.assertIn("folder/keep.txt", output)
        self.assertIn("deleting obsolete.txt", output)
        self.assertIn("Outcome: Success", output)
        self.assertEqual(self.result.stat().st_mode & 0o777, 0o640)
        self.assertEqual(self.result.stat().st_gid, self.result.parent.stat().st_gid)

    def test_partial_failure_and_timeout_publish_output_as_failed(self):
        def partial(configuration, output):
            output.write("one-file-copied\n")
            output.flush()
            return 23
        with patch.object(MountInspection, "verify"), patch.object(RsyncMirror, "run", side_effect=partial):
            self.assertEqual(self.worker(), 1)
        self.assertIn("one-file-copied", self.result.read_text())
        self.assertIn("Outcome: Failed (rsync exit status 23)", self.result.read_text())
        with patch.object(MountInspection, "verify"), \
                patch.object(RsyncMirror, "run", side_effect=subprocess.TimeoutExpired("rsync", 1)):
            self.assertEqual(self.worker(), 1)
        self.assertIn("timeout exceeded", self.result.read_text())
        self.assertIn("Outcome: Failed", self.result.read_text())
        # Both failed runs release the lock so another verified attempt can proceed.
        with patch.object(MountInspection, "verify"), patch.object(RsyncMirror, "run", return_value=0):
            self.assertEqual(self.worker(), 0)

    def test_disabled_and_overlapping_runs_preserve_output(self):
        self.result.write_text("previous output")
        with self.config.with_suffix(".lock").open("a") as lock, patch.object(RsyncMirror, "run") as mirror:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.assertEqual(self.worker(), 0)
            mirror.assert_not_called()
        self.values.update(enabled=False, expression=None)
        self.save()
        with patch.object(RsyncMirror, "run") as mirror:
            self.assertEqual(self.worker(), 0)
            mirror.assert_not_called()
        self.assertEqual(self.result.read_text(), "previous output")

    def test_configuration_rejects_unsafe_paths_direction_and_timeout(self):
        cases = ({"target": self.values["source"]},
                 {"target": {"mount": str(self.source / "nested"), "uuid": self.values["target"]["uuid"]}},
                 {"source": {"mount": "/", "uuid": self.values["source"]["uuid"]}},
                 {"source": {"mount": "/exports/../disk1", "uuid": self.values["source"]["uuid"]}},
                 {"source": {"mount": str(self.source), "uuid": "bad"}},
                 {"timeout": 0}, {"timeout": float("inf")}, {"enabled": 1}, {"expression": None})
        for changes in cases:
            with self.subTest(changes=changes):
                self.config.write_text(json.dumps(dict(self.values, **changes)))
                with self.assertRaises(ValueError):
                    SyncConfiguration(self.config)

    def test_output_page_escapes_large_transcript_and_handles_missing_output(self):
        with patch.object(DDiskHA, "SYNC_RESULT", str(self.result)):
            self.assertIn(b"No data sync has run yet", b"".join(render_sync_output()))
            self.result.write_text('<script>alert(1)</script>\n' + "x" * 70000)
            chunks = list(render_sync_output())
            self.assertGreaterEqual(len(chunks), 4)
            page = b"".join(chunks)
            self.assertIn(b"&lt;script&gt;", page)
            self.assertNotIn(b"<script>", page)
            self.assertIn(b"Most Recent Data Sync Output", page)

    def test_shared_cron_edits_preserve_health_and_unrelated_jobs_and_rollback(self):
        tab = "15 2 * * * /other # unrelated\n0 14 * * * /check # disk-ha-health-check\n"
        original = tab
        def crontab(arguments, **kwargs):
            nonlocal tab
            if arguments[-1] == "-l":
                return SimpleNamespace(returncode=0, stdout=tab, stderr="")
            tab = kwargs["input"]
            return SimpleNamespace(returncode=0)
        with patch("disk_ha.interface.CronSchedule.subprocess.run", side_effect=crontab):
            SyncSchedule.apply(self.root, SyncConfiguration(self.config))
            self.assertTrue(tab.startswith(original))
            self.assertIn("0 */4 * * *", tab)
            self.assertIn("disk-ha-sync", tab)
            self.assertEqual(SyncSchedule.read()["expression"], "0 */4 * * *")
            previous = json.loads(self.config.read_text())
            with patch.object(SyncSchedule, "apply", side_effect=OSError("cron denied")):
                with self.assertRaises(OSError):
                    SyncSchedule.update(self.root, True, "0 2 * * *")
            self.assertEqual(json.loads(self.config.read_text()), previous)
            with (self.root / "conf/cron.lock").open("a") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                with self.assertRaisesRegex(OSError, "cron update"):
                    HealthSchedule.apply(self.root, None)
            SyncSchedule.apply(self.root, None)
            self.assertEqual(tab, original)

    def test_timeout_kills_rsync_process_group_before_returning(self):
        process = Mock(pid=1234)
        process.wait.side_effect = [subprocess.TimeoutExpired("rsync", 1), 0]
        with patch("disk_ha.interface.RsyncMirror.subprocess.Popen") as popen, \
                patch("disk_ha.interface.RsyncMirror.os.killpg") as kill:
            popen.return_value.__enter__.return_value = process
            with self.assertRaises(subprocess.TimeoutExpired):
                RsyncMirror().run(SyncConfiguration(self.config), io.StringIO())
        command = popen.call_args.args[0]
        self.assertEqual(command, [DDiskHA.RSYNC, "-avr", "--delete", "--", str(self.source) + "/", str(self.target) + "/"])
        self.assertTrue(popen.call_args.kwargs["start_new_session"])
        kill.assert_called_once_with(1234, signal.SIGKILL)
