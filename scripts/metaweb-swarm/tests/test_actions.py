"""Free configured connectors against temporary storage and a loopback fixture."""
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from metaweb_swarm.actions import digest_file, execute_deposit, object_name, validate_resources


class FixtureHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _record(self):
        self.server.requests.append({"method": self.command, "path": self.path, "headers": dict(self.headers)})

    def do_PUT(self):
        self._record()
        payload = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        if self.server.redirect_put:
            self.send_response(307)
            self.send_header("Location", "/redirected")
            self.end_headers()
            return
        if self.path in self.server.objects and self.headers.get("If-None-Match") == "*":
            self.send_response(412)
            self.end_headers()
            return
        self.server.objects[self.path] = payload
        self.send_response(201)
        self.end_headers()

    def do_GET(self):
        self._record()
        if self.server.redirect_get:
            self.send_response(302)
            self.send_header("Location", "/redirected")
            self.end_headers()
            return
        if self.server.get_error_reason:
            self.send_response(403, self.server.get_error_reason)
            self.end_headers()
            return
        payload = self.server.get_payload if self.server.get_payload is not None else self.server.objects[self.path]
        self.send_response(200)
        self.end_headers()
        self.wfile.write(payload)


class ActionFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.project = self.base / "production"
        self.project.mkdir()
        self.run = self.base / "run"
        self.run.mkdir()
        self.source = self.run / "specimen.pdf"
        self.source.write_bytes(b"public preserved build")
        self.expected = digest_file(self.source, 100)
        self.forbidden = [self.project, self.run]

    def tearDown(self):
        self.temp.cleanup()

    def local(self, directory=None, maximum=100):
        return {"id": "copy", "kind": "local_directory", "directory": str(directory or (self.base / "deposit")), "max_bytes": maximum, "cost_usd": 0}


class LocalActionTests(ActionFixture):
    def test_local_copy_has_readback_receipt_and_exact_retry_is_idempotent(self):
        resource = self.local()
        validate_resources([resource])
        receipt = execute_deposit(resource, self.source, "build.pdf", self.expected, self.forbidden)
        self.assertTrue(receipt["host_verified"])
        target = Path(receipt["location"])
        self.assertEqual(target.read_bytes(), self.source.read_bytes())
        self.assertEqual(receipt["sha256"], hashlib.sha256(target.read_bytes()).hexdigest())
        retry = execute_deposit(resource, self.source, "build.pdf", self.expected, self.forbidden)
        self.assertTrue(retry["already_present"])
        self.assertFalse((self.project / "build.pdf").exists())

    def test_local_collision_never_overwrites_other_bytes(self):
        resource = self.local()
        target = Path(resource["directory"])
        target.mkdir()
        (target / "build.pdf").write_bytes(b"unrelated object")
        with self.assertRaisesRegex(ValueError, "different bytes"):
            execute_deposit(resource, self.source, "build.pdf", self.expected, self.forbidden)
        self.assertEqual((target / "build.pdf").read_bytes(), b"unrelated object")

    def test_production_run_and_their_ancestors_are_forbidden_targets(self):
        for target in (self.project, self.project / "nested", self.run / "nested", self.base):
            with self.assertRaisesRegex(ValueError, "overlaps"):
                execute_deposit(self.local(target), self.source, "build.pdf", self.expected, self.forbidden)
        self.assertFalse((self.project / "nested").exists())

    def test_changed_source_and_resource_size_abort_before_side_effect(self):
        self.source.write_bytes(b"changed")
        with self.assertRaisesRegex(ValueError, "changed"):
            execute_deposit(self.local(), self.source, "build.pdf", self.expected, self.forbidden)
        self.assertFalse((self.base / "deposit").exists())
        with self.assertRaisesRegex(ValueError, "limit"):
            execute_deposit(self.local(maximum=2), self.source, "build.pdf", self.expected, self.forbidden)

    def test_filename_is_single_bounded_object_name(self):
        self.assertEqual(object_name("", "a" * 64), "a" * 64 + ".bin")
        for name in ("../file", "folder/file", "C:\\file", "file:stream", "..", "x" * 161):
            with self.assertRaises(ValueError):
                object_name(name, "a" * 64)

    def test_resource_validation_keeps_only_free_explicit_capabilities(self):
        invalid = [dict(self.local(), cost_usd=1), dict(self.local(), directory="relative"),
                   dict(self.local(), credential_env="OPENAI_API_KEY"), dict(self.local(), arbitrary_shell="echo")]
        for resource in invalid:
            with self.assertRaises(ValueError):
                validate_resources([resource])
        with self.assertRaises(ValueError):
            validate_resources([self.local(), self.local()])


class HTTPActionTests(ActionFixture):
    def setUp(self):
        super().setUp()
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), FixtureHandler)
        self.server.daemon_threads = True
        self.server.requests, self.server.objects = [], {}
        self.server.redirect_put = self.server.redirect_get = False
        self.server.get_payload = self.server.get_error_reason = None
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.resource = {"id": "loopback-test", "kind": "http_put", "endpoint": f"http://127.0.0.1:{self.server.server_port}/objects",
                         "max_bytes": 100, "cost_usd": 0, "allow_loopback_http": True}

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        super().tearDown()

    def deposit(self, expected=None):
        return execute_deposit(self.resource, self.source, "build.pdf", expected or self.expected, self.forbidden, timeout=3)

    def test_put_then_get_authentication_receipts_never_contain_credentials(self):
        secret = "fixture-deposit-secret"
        self.resource["credential_env"] = "META_SWARM_CRED_FIXTURE"
        validate_resources([self.resource])
        with patch.dict(os.environ, {"META_SWARM_CRED_FIXTURE": secret}):
            receipt = self.deposit()
        self.assertTrue(receipt["host_verified"])
        self.assertEqual([item["method"] for item in self.server.requests], ["PUT", "GET"])
        self.assertEqual(self.server.requests[0]["headers"]["If-None-Match"], "*")
        self.assertEqual({key.lower(): value for key, value in self.server.requests[0]["headers"].items()}["x-content-sha256"], self.expected["sha256"])
        self.assertTrue(all(item["headers"]["Authorization"] == "Bearer " + secret for item in self.server.requests))
        self.assertNotIn(secret, json.dumps(receipt))
        self.assertNotIn("Authorization", json.dumps(receipt))

    def test_conditional_put_retries_same_bytes_and_does_not_overwrite_different_bytes(self):
        self.deposit()
        self.assertTrue(self.deposit()["host_verified"])
        stored = self.server.objects["/objects/build.pdf"]
        self.source.write_bytes(b"new candidate bytes")
        changed = digest_file(self.source, 100)
        with self.assertRaisesRegex(ValueError, "verified"):
            self.deposit(changed)
        self.assertEqual(self.server.objects["/objects/build.pdf"], stored)

    def test_readback_hash_mismatch_never_reports_success(self):
        self.server.get_payload = b"different bytes"
        with self.assertRaisesRegex(ValueError, "verified"):
            self.deposit()

    def test_readback_resource_limit_is_enforced(self):
        self.server.get_payload = b"x" * 101
        with self.assertRaisesRegex(ValueError, "size limit"):
            self.deposit()

    def test_put_and_get_redirects_are_never_followed(self):
        for method in ("PUT", "GET"):
            self.server.redirect_put = method == "PUT"
            self.server.redirect_get = method == "GET"
            self.server.requests.clear()
            with self.assertRaisesRegex(ValueError, "redirect"):
                self.deposit()
            self.assertTrue(all(item["path"] != "/redirected" for item in self.server.requests))

    def test_source_limit_prevents_even_first_http_request(self):
        self.resource["max_bytes"] = 1
        with self.assertRaises(ValueError):
            self.deposit()
        self.assertFalse(self.server.requests)

    def test_get_error_cannot_echo_resource_credential_into_host_audit(self):
        secret = "fixture-deposit-secret"
        self.resource["credential_env"] = "META_SWARM_CRED_FIXTURE"
        self.server.get_error_reason = secret
        with patch.dict(os.environ, {"META_SWARM_CRED_FIXTURE": secret}):
            with self.assertRaises((ValueError, OSError)) as caught:
                self.deposit()
        self.assertNotIn(secret, str(caught.exception))

    def test_endpoint_credentials_queries_plain_http_and_api_key_reuse_are_rejected(self):
        for field, value in (("endpoint", "http://example.org/objects"), ("endpoint", "https://user:pass@example.org/objects"),
                             ("endpoint", "https://example.org/objects?secret=token"), ("credential_env", "OPENAI_API_KEY"),
                             ("credential_env", "GITHUB_TOKEN"), ("credential_env", "GITLAB_TOKEN"),
                             ("credential_env", "CODEBERG_TOKEN"), ("credential_env", "SWARM_FIXTURE_CREDENTIAL")):
            with self.assertRaises(ValueError):
                validate_resources([dict(self.resource, **{field: value})])

    def test_legacy_adapter_cannot_bypass_forge_production_or_private_address_protection(self):
        for endpoint in ("https://api.github.com/repos/owner/site", "https://gitlab.com/api/v4/projects/1",
                         "https://codeberg.org/api/v1/repos/owner/site", "https://vojtamaur.cz/objects",
                         "https://127.0.0.1/objects", "https://10.0.0.1/objects", "https://[::1]/objects"):
            with self.subTest(endpoint=endpoint), self.assertRaises(ValueError):
                validate_resources([dict(self.resource, endpoint=endpoint)])
        self.assertFalse(self.server.requests)

    def test_ambient_forge_credentials_and_proxies_do_not_authenticate_legacy_deposit(self):
        with patch.dict(os.environ, {"GITHUB_TOKEN": "fixture-owner-github", "GITLAB_TOKEN": "fixture-owner-gitlab",
                                    "CODEBERG_TOKEN": "fixture-owner-codeberg", "HTTP_PROXY": "http://127.0.0.1:1",
                                    "HTTPS_PROXY": "http://127.0.0.1:1", "ALL_PROXY": "http://127.0.0.1:1"}):
            self.assertTrue(self.deposit()["host_verified"])
        self.assertTrue(all("Authorization" not in request["headers"] and "Cookie" not in request["headers"]
                            for request in self.server.requests))

    def test_legacy_adapter_uses_public_dns_validation_before_network_connect(self):
        self.resource.update(endpoint="https://public-fixture.example/objects", allow_loopback_http=False)
        with patch("metaweb_swarm.http_transport.socket.getaddrinfo", return_value=[
            (2, 1, 6, "", ("127.0.0.1", 443))
        ]), patch("metaweb_swarm.http_transport.socket.socket") as socket_factory:
            with self.assertRaisesRegex(ValueError, "non-public"):
                self.deposit()
        socket_factory.assert_not_called()
