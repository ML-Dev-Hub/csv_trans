"""Offline loopback integration tests for the standard-library HTTP transport."""

from __future__ import annotations

from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading
import unittest

from csv_trans.providers.base import (
    HttpTransportResponseTooLarge,
    HttpTransportTimeout,
    UrllibHttpClient,
)


class _LoopbackHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"

    def log_message(self, format, *args):  # pragma: no cover - silence test server
        return

    def do_POST(self):  # noqa: N802 - BaseHTTPRequestHandler protocol name
        if self.path != "/ok":
            self._respond(404, b"not found")
            return
        length = int(self.headers.get("Content-Length", "0"))
        self.server.last_body = self.rfile.read(length)
        self.server.last_test_header = self.headers.get("X-Test")
        self._respond(
            200,
            b"local-ok",
            headers={"Content-Type": "text/plain; charset=utf-8"},
        )

    def do_GET(self):  # noqa: N802 - BaseHTTPRequestHandler protocol name
        if self.path == "/status":
            self._respond(418, b"teapot")
        elif self.path == "/redirect":
            self._respond(302, b"stay-here", headers={"Location": "/target"})
        elif self.path == "/target":
            self.server.target_requests += 1
            self._respond(200, b"redirect-followed")
        elif self.path == "/large-declared":
            self._respond(200, b"x" * 64)
        elif self.path == "/large-stream":
            self._respond(200, b"y" * 64, include_length=False)
        elif self.path == "/timeout":
            self.server.timeout_started.set()
            self.server.timeout_release.wait(5)
        else:
            self._respond(404, b"not found")

    def _respond(self, status, body, *, headers=None, include_length=True):
        self.send_response(status)
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        if include_length:
            self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            # Size-limit tests deliberately close without consuming the body.
            pass


@contextmanager
def _loopback_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _LoopbackHandler)
    server.target_requests = 0
    server.last_body = None
    server.last_test_header = None
    server.timeout_started = threading.Event()
    server.timeout_release = threading.Event()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        yield server, f"http://{host}:{port}"
    finally:
        server.timeout_release.set()
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


class UrllibHttpClientLoopbackTests(unittest.TestCase):
    def test_success_sends_method_headers_and_body(self):
        with _loopback_server() as (server, base_url):
            response = UrllibHttpClient().request(
                "post",
                f"{base_url}/ok",
                headers={"X-Test": "local-value"},
                body=b"request-body",
                timeout=2,
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.text, "local-ok")
        self.assertEqual(server.last_body, b"request-body")
        self.assertEqual(server.last_test_header, "local-value")

    def test_non_success_status_is_returned_with_its_body(self):
        with _loopback_server() as (_, base_url):
            response = UrllibHttpClient().request(
                "GET", f"{base_url}/status", timeout=2
            )

        self.assertEqual(response.status_code, 418)
        self.assertEqual(response.body, b"teapot")

    def test_redirect_is_returned_without_contacting_the_target(self):
        with _loopback_server() as (server, base_url):
            response = UrllibHttpClient().request(
                "GET", f"{base_url}/redirect", timeout=2
            )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers.get("Location"), "/target")
        self.assertEqual(response.body, b"stay-here")
        self.assertEqual(server.target_requests, 0)

    def test_declared_and_streamed_oversized_responses_are_rejected(self):
        client = UrllibHttpClient(max_response_bytes=8)
        with _loopback_server() as (_, base_url):
            for path in ("large-declared", "large-stream"):
                with self.subTest(path=path):
                    with self.assertRaises(HttpTransportResponseTooLarge):
                        client.request("GET", f"{base_url}/{path}", timeout=2)

    def test_inactive_loopback_response_maps_to_stable_timeout(self):
        with _loopback_server() as (server, base_url):
            with self.assertRaises(HttpTransportTimeout):
                UrllibHttpClient().request(
                    "GET", f"{base_url}/timeout", timeout=0.1
                )
            self.assertTrue(server.timeout_started.is_set())


if __name__ == "__main__":
    unittest.main()
