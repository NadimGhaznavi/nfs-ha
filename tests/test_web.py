"""Verify the web server and installed archive without production changes."""

from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import select
import socket
import subprocess
import sys
import tempfile
from threading import Thread
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener

from http.server import ThreadingHTTPServer
from disk_ha.server.__main__ import WebHandler
from disk_ha.server.DrivePage import render_page
from test_install import installer


ROOT = Path(__file__).resolve().parents[1]


class WebTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), WebHandler)
        cls.thread = Thread(target=cls.server.serve_forever)
        cls.thread.start()
        cls.url = f"http://127.0.0.1:{cls.server.server_port}"
        cls.opener = build_opener(ProxyHandler({}))

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)

    @patch("disk_ha.server.DrivePage.read_usage", return_value=None)
    def test_page_and_head(self, usage):
        expected = render_page()
        with self.opener.open(self.url + "/?test=1", timeout=2) as response:
            self.assertEqual(response.status, 200)
            self.assertEqual(response.read(), expected)
            self.assertEqual(response.headers["Content-Type"], "text/html; charset=utf-8")
            self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
        with self.opener.open(Request(self.url + "/", method="HEAD"), timeout=2) as response:
            self.assertEqual(int(response.headers["Content-Length"]), len(expected))
            self.assertEqual(response.read(), b"")

    def test_readiness_and_unknown_paths(self):
        with self.opener.open(self.url + "/ready", timeout=2) as response:
            self.assertEqual(json.load(response), {"ready": True})
        for path in ("/unknown", "/../constants/DDISKHA.py", "/conf/credentials.env"):
            with self.assertRaises(HTTPError) as raised:
                self.opener.open(self.url + path, timeout=2)
            self.assertEqual(raised.exception.code, 404)
            raised.exception.close()

    def test_packaged_server_serves_without_checkout(self):
        with tempfile.TemporaryDirectory(prefix="disk-ha-web-test-") as temporary:
            target = Path(temporary) / "prod"
            with patch.object(installer.DDISKHA, "INSTALL_DIR", str(target)), \
                    patch.object(installer.DDISKHA, "WEB_SERVICE_FILE", str(Path(temporary) / "service")), \
                    patch.object(installer.SystemAccount, "provision",
                                 return_value=SimpleNamespace(pw_uid=os.geteuid(), pw_gid=os.getegid())), \
                    patch.object(installer.DatabaseProvisioning, "provision"), \
                    patch.object(installer.HealthSchedule, "apply"), \
                    patch.object(installer.os, "access", return_value=True), \
                    patch.object(installer, "systemctl"), patch.object(installer, "restart"), \
                    redirect_stdout(io.StringIO()):
                installer.install()
            archive = target / "bin/disk-ha-web"
            with socket.socket() as listener:
                listener.bind(("127.0.0.1", 0))
                port = listener.getsockname()[1]
            process = subprocess.Popen(
                [str(archive), "--host", "127.0.0.1", "--port", str(port)],
                cwd=temporary, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            try:
                self.assertTrue(select.select([process.stdout], [], [], 5)[0], "Startup timed out")
                self.assertIn(f"http://127.0.0.1:{port}/", process.stdout.readline())
                with self.opener.open(f"http://127.0.0.1:{port}/", timeout=2) as response:
                    page = response.read()
                    self.assertIn(b"Drive Configuration", page)
                    self.assertIn(b"Disk 1", page)
                    self.assertIn(b"Disk 2", page)
                    self.assertNotIn(b"{{disk", page)
            finally:
                process.terminate()
                process.communicate(timeout=5)
            process = subprocess.Popen(
                [sys.executable, str(archive), "--host", "127.0.0.1", "--port", str(self.server.server_port)],
                cwd=temporary, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            # An occupied port must fail, rather than report successful startup.
            stdout, stderr = process.communicate(timeout=5)
            self.assertEqual(process.returncode, 1)
            self.assertIn("disk-ha:", stderr)
            self.assertNotIn("Web UI:", stdout)
            process = subprocess.Popen(
                [sys.executable, "-u", str(archive), "--host", "127.0.0.1", "--port", "0"],
                cwd=temporary, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            stdout, stderr = process.communicate(timeout=5)
            self.assertEqual(process.returncode, 2)
            self.assertIn("--port must be between", stderr)


class ReadinessTests(unittest.TestCase):
    def test_restart_checks_service_and_http_with_timeouts(self):
        opener = MagicMock()
        opener.open.return_value.__enter__.return_value.status = 200
        with patch.object(installer, "systemctl") as control, \
                patch.object(installer, "build_opener", return_value=opener), redirect_stdout(io.StringIO()):
            installer.restart()
        control.assert_any_call("restart", "disk-ha-web.service")
        control.assert_any_call("is-active", "--quiet", "disk-ha-web.service")
        args, kwargs = opener.open.call_args
        self.assertEqual(args[0].full_url, "http://127.0.0.1:23300/ready")
        self.assertEqual(args[0].method, "HEAD")
        self.assertEqual(kwargs["timeout"], 1)

    def test_unavailable_server_fails_after_deadline(self):
        opener = MagicMock()
        opener.open.side_effect = URLError("Connection refused")
        with patch.object(installer, "systemctl"), \
                patch.object(installer, "build_opener", return_value=opener), \
                patch.object(installer.time, "monotonic", side_effect=[0, 11]):
            with self.assertRaisesRegex(ValueError, "did not respond on port 23300"):
                installer.restart()


if __name__ == "__main__":
    unittest.main()
