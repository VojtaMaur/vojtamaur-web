"""Real loopback HTTP tests; no API calls, public uploads or host credentials."""
import hashlib
import json
import socket
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from metaweb_swarm.http_transport import (
    HttpPolicyError, HttpTransportError, _resolve, execute_request,
    normalize_request, redact, validate_http_config,
)
from metaweb_swarm.workspace import Workspace


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    def handle_request(self):
        body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        self.server.requests.append({"method": self.command, "path": self.path,
                                     "headers": dict(self.headers), "body": body})
        if self.path == "/redirect":
            self.send_response(307)
            self.send_header("Location", self.server.origin + "/mutate")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if self.path == "/slow":
            self.send_response(200)
            self.send_header("Content-Length", "10")
            self.end_headers()
            for _ in range(10):
                try:
                    self.wfile.write(b"x")
                    self.wfile.flush()
                except OSError:
                    break
                time.sleep(0.06)
            return
        status, kind = (418 if self.path == "/error" else 200), "application/json"
        if self.path == "/binary":
            result, kind = b"\x00\xff\x01public-build\x80", "application/octet-stream"
        elif self.path == "/large":
            result, kind = b"x" * 8192, "application/octet-stream"
        elif self.path == "/secrets":
            result = json.dumps({"password": "server-password", "nested": {"access_token": "server-token"},
                                 "echo": self.headers.get("Authorization", ""), "value": "public"}).encode()
        else:
            result = json.dumps({"method": self.command, "path": self.path, "body": body.decode("utf-8", "replace"),
                                 "headers": dict(self.headers)}).encode()
        self.send_response(status)
        self.send_header("Content-Type", kind)
        self.send_header("Set-Cookie", "session=do-not-store")
        self.send_header("Content-Length", str(len(result)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(result)

    do_GET = do_HEAD = do_OPTIONS = do_POST = do_PUT = do_PATCH = do_DELETE = handle_request


class HttpTransportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.server.daemon_threads = True
        cls.origin = f"http://127.0.0.1:{cls.server.server_address[1]}"
        cls.server.origin = cls.origin
        cls.server.requests = []
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=3)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        snapshot = root / "snapshot"
        snapshot.mkdir()
        self.workspace = Workspace(snapshot, root / "workspace")
        self.config = {"http_access": "enabled", "max_http_requests": 10,
                       "max_http_request_bytes": 4096, "max_http_response_bytes": 4096,
                       "max_http_total_bytes": 65536, "http_timeout_seconds": 3,
                       "http_credentials": [], "http_test_origins": [self.origin]}

    def tearDown(self):
        self.temp.cleanup()

    def request(self, path="/echo", **spec):
        descriptor, prepared = normalize_request({"method": "GET", "url": self.origin + path, **spec}, self.config, self.workspace)
        metadata, body = execute_request(prepared, self.config)
        return descriptor, metadata, body


    def test_connection_failure_preserves_safe_cause_before_send(self):
        config=dict(self.config)
        descriptor, prepared=normalize_request({'method':'GET','url':self.origin+'/read'},config,self.workspace)
        with patch('metaweb_swarm.http_transport.socket.socket') as make_socket:
            make_socket.return_value.connect.side_effect=ConnectionRefusedError(10061, 'connection refused')
            with self.assertRaises(HttpTransportError) as caught:
                execute_request(prepared,config,2)
        self.assertFalse(caught.exception.outcome_uncertain)
        self.assertEqual(caught.exception.stage,'connect')
        self.assertIn('ConnectionRefusedError',str(caught.exception))

    def test_json_query_methods_and_http_error(self):
        for method in ("POST", "PUT", "PATCH", "DELETE"):
            with self.subTest(method=method):
                descriptor, metadata, body = self.request(method=method, query={"q": "a b"}, body_json='{"x":42}')
                result = json.loads(body)
                self.assertEqual(result["method"], method)
                self.assertEqual(result["path"], "/echo?q=a+b")
                self.assertEqual(result["body"], '{"x":42}')
                self.assertEqual(descriptor["bytes"], 8)
                self.assertEqual(metadata["status"], 200)
                self.assertNotIn("Set-Cookie", metadata["headers"])
        _, metadata, _ = self.request("/error")
        self.assertEqual(metadata["status"], 418)
        _, metadata, body = self.request(method="HEAD")
        self.assertEqual(body, b"")
        self.assertEqual(metadata["response_bytes"], 0)

    def test_binary_roundtrip_and_confined_upload(self):
        expected = b"\x00\xff\x01public-build\x80"
        _, metadata, body = self.request("/binary", response_path="work/download.bin")
        self.assertEqual(body, expected)
        self.assertEqual(metadata["raw_sha256"], hashlib.sha256(expected).hexdigest())
        self.assertEqual(metadata["raw_sha256"], metadata["stored_sha256"])
        self.workspace.write_file("work/build.bin", expected)
        descriptor, _, _ = self.request(method="PUT", upload_path="work/build.bin")
        self.assertEqual(self.server.requests[-1]["body"], expected)
        self.assertEqual(descriptor["files"][0]["sha256"], hashlib.sha256(expected).hexdigest())
        for relative in ("../outside", str(self.workspace.root), ".metaweb-workspace.json"):
            with self.subTest(path=relative), self.assertRaises(ValueError):
                self.request(method="PUT", upload_path=relative)
        with self.assertRaises(ValueError):
            self.request(response_path="../outside")

    def test_multipart_deterministic_exact_file_bytes(self):
        data = b"\x00\xffsample\x01"
        self.workspace.write_file("work/archive.zip", data)
        spec = {"method": "POST", "url": self.origin + "/echo", "multipart_fields": {"title": "Metaweb"},
                "multipart_files": [{"field": "file", "path": "work/archive.zip", "filename": "build.zip", "content_type": "application/zip"}]}
        first, prepared = normalize_request(spec, self.config, self.workspace)
        second, prepared_again = normalize_request(spec, self.config, self.workspace)
        self.assertEqual(first, second)
        self.assertEqual(prepared.body, prepared_again.body)
        self.assertIn(data, prepared.body)
        metadata, _ = execute_request(prepared, self.config)
        sent = self.server.requests[-1]
        self.assertIn('name="title"\r\n\r\nMetaweb', sent["body"].decode("latin-1"))
        self.assertIn('filename="build.zip"', sent["body"].decode("latin-1"))
        self.assertEqual(int(sent["headers"]["Content-Length"]), len(prepared.body))
        self.assertEqual(metadata["request_bytes"], len(prepared.body))

    def test_redirect_not_followed_and_no_cookie_jar(self):
        start = len(self.server.requests)
        _, metadata, _ = self.request("/redirect", method="POST", body_text="sample")
        self.assertEqual(metadata["status"], 307)
        self.assertFalse(metadata["redirected"])
        self.assertEqual(len(self.server.requests), start + 1)
        self.request()
        self.assertNotIn("Cookie", self.server.requests[-1]["headers"])

    def test_ambient_proxy_credentials_are_never_used(self):
        with patch.dict("os.environ", {"HTTP_PROXY": "http://127.0.0.1:1", "HTTPS_PROXY": "http://127.0.0.1:1",
                                        "GITHUB_TOKEN": "ambient-do-not-read", "OPENAI_API_KEY": "ambient-do-not-read"}):
            self.request()
        self.assertNotIn("Authorization", self.server.requests[-1]["headers"])

    def test_dedicated_credential_and_response_redaction(self):
        secret = "dedicated-swarm-token-12345"
        self.config["http_credentials"] = [{"id": "fixture", "env": "META_SWARM_CRED_FIXTURE",
                                           "hosts": ["127.0.0.1"], "header": "Authorization", "scheme": "Bearer"}]
        descriptor, prepared = normalize_request({"url": self.origin + "/secrets", "credential_id": "fixture"}, self.config, self.workspace)
        self.assertNotIn(secret, json.dumps(descriptor))
        with patch.dict("os.environ", {"META_SWARM_CRED_FIXTURE": secret}):
            metadata, body = execute_request(prepared, self.config)
        self.assertEqual(self.server.requests[-1]["headers"]["Authorization"], "Bearer " + secret)
        self.assertNotIn(secret, body.decode())
        self.assertNotIn("server-password", body.decode())
        self.assertNotIn("server-token", body.decode())
        self.assertTrue(metadata["sanitized"])
        self.assertNotEqual(metadata["raw_sha256"], metadata["stored_sha256"])
        self.assertEqual(json.loads(body)["value"], "public")
        with self.assertRaises(HttpPolicyError):
            normalize_request({"url": "https://other.example/", "credential_id": "fixture"}, self.config, self.workspace)
        self.config["http_credentials"][0]["env"] = "GITHUB_TOKEN"
        with self.assertRaises(HttpPolicyError):
            validate_http_config(self.config)

    def test_approval_binding_includes_redacted_wire_values_and_grants(self):
        a, _ = normalize_request({"url": self.origin + "/echo?token=first"}, self.config, self.workspace)
        b, _ = normalize_request({"url": self.origin + "/echo?token=second"}, self.config, self.workspace)
        self.assertEqual(a["url"], b["url"])
        self.assertNotEqual(a["wire_sha256"], b["wire_sha256"])
        self.assertNotIn("first", json.dumps(a))
        a, _ = normalize_request({"url": self.origin + "/", "body_json": '{"password":"private-value"}', "method": "POST"}, self.config, self.workspace)
        self.assertNotIn("private-value", json.dumps(a))

    def test_limits_truncation_and_total_deadline(self):
        self.config["max_http_response_bytes"] = 10
        _, metadata, body = self.request("/large", method="POST")
        self.assertEqual(len(body), 10)
        self.assertEqual(metadata["response_bytes"], 11)
        self.assertTrue(metadata["truncated"])
        self.assertTrue(metadata["outcome_uncertain"])
        self.config["http_timeout_seconds"] = 0.15
        started = time.monotonic()
        _, metadata, _ = self.request("/slow", method="POST")
        self.assertLess(time.monotonic() - started, 0.45)
        self.assertTrue(metadata["timed_out"])
        self.assertTrue(metadata["outcome_uncertain"])
        self.config["max_http_request_bytes"] = 10
        with self.assertRaises(HttpPolicyError):
            self.request(method="POST", body_text="x" * 11)
        with self.assertRaises(HttpPolicyError):
            self.request(method="POST", multipart_fields={"title": "x" * 11})

    def test_header_url_method_and_protected_site_restrictions(self):
        for headers in ({"Authorization": "Bearer no"}, {"Cookie": "x=y"}, {"Host": "private"},
                        {"Content-Length": "1"}, {"Transfer-Encoding": "chunked"}, {"X-Api-Key": "no"},
                        {"Good": "x\r\nBad:y"}, {"Accept-Encoding": "gzip"}, {"X-HTTP-Method-Override": "DELETE"},
                        {"X-Method-Override": "PUT"}, {"X-HTTP-Method": "POST"}):
            with self.subTest(headers=headers), self.assertRaises(HttpPolicyError):
                normalize_request({"url": self.origin, "headers": headers}, self.config, self.workspace)
        for url in ("http://public.example/", "https://user:pass@public.example/", "https://127.0.0.1/",
                    "https://10.1.2.3/", "https://[::1]/", "https://[64:ff9b::a01:203]/", "file:///tmp/a",
                    "https://localhost/", "https://abc.local/", "https://example.com./", "https://public.example:0/"):
            with self.subTest(url=url), self.assertRaises(HttpPolicyError):
                normalize_request({"url": url}, self.config, self.workspace)
        for host in ("github.com", "api.github.com", "gist.github.com", "gitlab.com", "codeberg.org", "vojtamaur.cz", "www.vojtamaur.cz"):
            with self.subTest(host=host), self.assertRaises(HttpPolicyError):
                normalize_request({"method": "POST", "url": "https://" + host + "/"}, self.config, self.workspace)
        with self.assertRaises(HttpPolicyError):
            normalize_request({"url": "https://unknown.example/info/refs?service=git%252dreceive%252dpack"}, self.config, self.workspace)
        self.config["http_access"] = "read-only"
        with self.assertRaises(HttpPolicyError):
            self.request(method="POST")
        self.config["http_access"] = "disabled"
        with self.assertRaises(HttpPolicyError):
            self.request()

    def test_dns_all_addresses_checked_and_resolution_deadline(self):
        mixed = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443)),
                 (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.1", 443))]
        with patch("socket.getaddrinfo", return_value=mixed):
            with self.assertRaises(HttpPolicyError):
                _resolve("service.example", 443, False, time.monotonic() + 2)
        def slow(*args, **kwargs):
            time.sleep(0.3)
            return mixed[:1]
        started = time.monotonic()
        with patch("socket.getaddrinfo", side_effect=slow):
            with self.assertRaises(TimeoutError):
                _resolve("service.example", 443, False, time.monotonic() + 0.05)
        self.assertLess(time.monotonic() - started, 0.2)

    def test_public_socket_is_pinned_and_tls_uses_original_hostname(self):
        class FakeSocket:
            def __init__(self):
                self.buffer = bytearray(b'HTTP/1.1 200 OK\r\nContent-Length: 11\r\nContent-Type: application/json\r\n\r\n{"ok":true}')
                self.connected, self.sent = None, bytearray()
            def settimeout(self, value):
                pass
            def connect(self, address):
                self.connected = address
            def sendall(self, data):
                self.sent.extend(data)
            def recv_into(self, buffer):
                size = min(len(buffer), len(self.buffer))
                buffer[:size] = self.buffer[:size]
                del self.buffer[:size]
                return size
            def close(self):
                pass
        fake = FakeSocket()
        class Context:
            hostname = None
            def wrap_socket(self, sock, server_hostname):
                self.hostname = server_hostname
                return sock
        context = Context()
        _, prepared = normalize_request({"url": "https://service.example/api"}, self.config, self.workspace)
        records = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))]
        with patch("socket.getaddrinfo", return_value=records) as dns, patch("socket.socket", return_value=fake), patch("ssl.create_default_context", return_value=context):
            metadata, body = execute_request(prepared, self.config)
        self.assertEqual(metadata["status"], 200)
        self.assertEqual(body, b'{"ok":true}')
        self.assertEqual(dns.call_count, 1)
        self.assertEqual(fake.connected, ("93.184.216.34", 443))
        self.assertEqual(context.hostname, "service.example")
        self.assertIn(b"Host: service.example\r\n", fake.sent)

    def test_explicit_test_origins_are_loopback_only_and_redaction_recursive(self):
        for origin in ("http://localhost:8000", "https://127.0.0.1:8000", "http://10.0.0.1:8000", self.origin + "/", "http://127.0.0.1:0"):
            with self.subTest(origin=origin), self.assertRaises(HttpPolicyError):
                validate_http_config({**self.config, "http_test_origins": [origin]})
        value = {"Authorization": "Bearer value", "nested": [{"refresh_token": "value"}], "normal": "explicit-secret"}
        rendered = json.dumps(redact(value, ["explicit-secret"]))
        self.assertNotIn("explicit-secret", rendered)
        self.assertNotIn("Bearer value", rendered)

    def test_http_10_close_delimited_response_keeps_socket_alive_until_reader_finishes(self):
        class OldHandler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.0"
            def log_message(self, *args):
                pass
            def do_GET(self):
                self.send_response(200)
                self.end_headers()  # EOF-delimited body, no Content-Length.
                self.wfile.write(b"public-response-body")
        server = ThreadingHTTPServer(("127.0.0.1", 0), OldHandler)
        server.daemon_threads = True
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        origin = f"http://127.0.0.1:{server.server_address[1]}"
        try:
            config = {**self.config, "http_test_origins": [origin]}
            _, prepared = normalize_request({"url": origin}, config, self.workspace)
            metadata, body = execute_request(prepared, config)
            self.assertEqual(metadata["status"], 200)
            self.assertEqual(body, b"public-response-body")
            self.assertNotIn("error", metadata)
            self.assertFalse(metadata["outcome_uncertain"])
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)

    def test_premature_response_eof_does_not_certify_complete_download(self):
        class ShortHandler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass
            def do_POST(self):
                self.send_response(200)
                self.send_header("Content-Length", "100")
                self.end_headers()
                self.wfile.write(b"short")
        server = ThreadingHTTPServer(("127.0.0.1", 0), ShortHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        origin = f"http://127.0.0.1:{server.server_address[1]}"
        try:
            config = {**self.config, "http_test_origins": [origin]}
            _, prepared = normalize_request({"method": "POST", "url": origin}, config, self.workspace)
            metadata, body = execute_request(prepared, config)
            self.assertEqual(body, b"short")
            self.assertTrue(metadata["truncated"])
            self.assertTrue(metadata["outcome_uncertain"])
            self.assertIn("Content-Length", metadata["error"])
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)


if __name__ == "__main__":
    unittest.main()
