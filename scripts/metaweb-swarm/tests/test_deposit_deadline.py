from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from metaweb_swarm.actions import digest_file
from metaweb_swarm.deposit_worker import execute_bounded


class DripHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_PUT(self):
        self.rfile.read(int(self.headers.get("Content-Length", "0")))
        self.server.started.set()
        # A peer sends an unfinished header often enough to avoid idle timeout.
        self.wfile.write(b"HTTP/1.1 201 Created\r\nX-Drip: ")
        self.wfile.flush()
        try:
            while not self.server.stop_drip.wait(.03):
                self.wfile.write(b"x")
                self.wfile.flush()
        except OSError:
            pass


class DepositDeadlineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.source = self.base / "source.bin"
        self.source.write_bytes(b"public fixture")
        self.expected = digest_file(self.source, 100)

    def tearDown(self):
        self.temp.cleanup()

    def test_drip_http_headers_cannot_outlive_process_deadline(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), DripHandler)
        server.daemon_threads = True
        server.started, server.stop_drip = threading.Event(), threading.Event()
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        resource = {"id": "drip", "kind": "http_put", "endpoint": f"http://127.0.0.1:{server.server_port}/objects",
                    "allow_loopback_http": True, "max_bytes": 100, "cost_usd": 0}
        before = time.monotonic()
        try:
            with self.assertRaises(TimeoutError):
                execute_bounded(resource, self.source, "fixture.bin", self.expected, [], timeout=.4)
            self.assertLess(time.monotonic() - before, 2)
            self.assertTrue(server.started.is_set())
        finally:
            server.stop_drip.set()
            server.shutdown()
            server.server_close()
            thread.join(timeout=1)

    def test_local_child_is_verified_and_environment_excludes_host_credentials(self):
        resource = {"id": "local", "kind": "local_directory", "directory": str(self.base / "deposit"), "max_bytes": 100, "cost_usd": 0}
        original_run = subprocess.run
        observed = {}

        def inspecting_run(*args, **kwargs):
            observed.update(command=args[0], environment=kwargs["env"])
            return original_run(*args, **kwargs)

        with patch.dict(os.environ, {"OPENAI_API_KEY": "fixture-openai-secret", "PYTHONPATH": "malicious-fixture",
                                    "HTTP_PROXY": "http://fixture.invalid", "DOCKER_HOST": "fixture-remote"}):
            with patch("metaweb_swarm.deposit_worker.subprocess.run", side_effect=inspecting_run):
                receipt = execute_bounded(resource, self.source, "fixture.bin", self.expected, [], timeout=2)
        self.assertTrue(receipt["host_verified"])
        self.assertEqual((self.base / "deposit/fixture.bin").read_bytes(), self.source.read_bytes())
        self.assertEqual(observed["command"][1:3], ["-I", "-S"])
        self.assertTrue(Path(observed["command"][0]).is_absolute())
        self.assertTrue(Path(observed["command"][3]).is_absolute())
        self.assertFalse({"OPENAI_API_KEY", "PYTHONPATH", "HTTP_PROXY", "DOCKER_HOST"} & set(observed["environment"]))

    def test_failed_child_returns_only_generic_error_no_remote_or_local_secret(self):
        resource = {"id": "local", "kind": "local_directory", "directory": str(self.base / "deposit"), "max_bytes": 100, "cost_usd": 0}
        self.source.write_bytes(b"unapproved fixture-secret")
        with self.assertRaises(ValueError) as caught:
            execute_bounded(resource, self.source, "fixture.bin", self.expected, [], timeout=2)
        self.assertNotIn("fixture-secret", str(caught.exception))
        self.assertFalse((self.base / "deposit").exists())
