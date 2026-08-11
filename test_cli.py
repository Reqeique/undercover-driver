"""Local validation of src.cli (undercover-driver CLI) against a mock session server.

Boots a tiny HTTP server that mimics the real session-server contract
(POST /command, GET /health, Bearer auth) and drives the CLI through its
public main().  Asserts:
  - health hits GET /health
  - command subcommands build the right JSON payloads (goto/fill/click)
  - non-2xx / ok:false paths produce non-zero exit codes
  - auth token is sent when configured
"""

import json
import socket
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.path.insert(0, "src")

from src.cli import main  # noqa: E402


LOG: list[dict] = []
REQUIRED_TOKEN = "sekrit"


class MockHandler(BaseHTTPRequestHandler):
    def log_message(self, *a):  # silence
        pass

    def _read_body(self):
        n = int(self.headers.get("Content-Length", 0))
        return self.rfile.read(n) if n else b""

    def _reply(self, code: int, obj: dict):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/health":
            LOG.append({"method": "GET", "path": "/health", "auth": self.headers.get("Authorization")})
            if REQUIRED_TOKEN and self.headers.get("Authorization") != f"Bearer {REQUIRED_TOKEN}":
                self._reply(401, {"detail": "missing/invalid token"})
                return
            self._reply(200, {"ready": True, "url": "https://example.com", "title": "Example"})
        else:
            self._reply(404, {"detail": "not found"})

    def do_POST(self):
        body = self._read_body()
        LOG.append({"method": "POST", "path": self.path, "body": json.loads(body or b"{}"),
                    "auth": self.headers.get("Authorization")})
        if self.path != "/command":
            self._reply(404, {"detail": "not found"})
            return
        if REQUIRED_TOKEN and self.headers.get("Authorization") != f"Bearer {REQUIRED_TOKEN}":
            self._reply(401, {"detail": "missing/invalid token"})
            return
        cmd = (json.loads(body or b"{}") or {}).get("cmd")
        if cmd == "goto":
            self._reply(200, {"cmd": "goto", "ok": True, "url": "https://example.com"})
        elif cmd == "fill":
            self._reply(200, {"cmd": "fill", "ok": True})
        elif cmd == "eval":
            self._reply(200, {"cmd": "eval", "ok": False, "error": "ReferenceError: kaboom"})
        else:
            self._reply(200, {"cmd": cmd, "ok": True})


def start_mock_server() -> str:
    srv = HTTPServer(("127.0.0.1", 0), MockHandler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    return f"http://127.0.0.1:{srv.server_address[1]}"


def test_health():
    base = start_mock_server()
    code = main(["--url", base, "--token", REQUIRED_TOKEN, "health"])
    assert code == 0
    assert LOG[-1]["method"] == "GET" and LOG[-1]["path"] == "/health"
    assert LOG[-1]["auth"] == "Bearer sekrit"


def test_goto_payload():
    base = start_mock_server()
    code = main(["--url", base, "--token", REQUIRED_TOKEN, "goto", "https://example.com"])
    assert code == 0
    req = LOG[-1]
    assert req["method"] == "POST" and req["path"] == "/command"
    assert req["body"] == {"cmd": "goto", "url": "https://example.com"}


def test_fill_payload_with_wait_ms():
    base = start_mock_server()
    code = main(["--url", base, "--token", REQUIRED_TOKEN, "fill", "@e4", "hi@x.io", "--wait-ms", "300"])
    assert code == 0
    assert LOG[-1]["body"] == {"cmd": "fill", "target": "@e4", "value": "hi@x.io", "wait_ms": 300}


def test_click_default_no_wait():
    base = start_mock_server()
    code = main(["--url", base, "--token", REQUIRED_TOKEN, "click", "@e3"])
    assert code == 0
    assert LOG[-1]["body"] == {"cmd": "click", "target": "@e3"}


def test_ok_false_exits_1():
    base = start_mock_server()
    code = main(["--url", base, "--token", REQUIRED_TOKEN, "eval", "foo.bar()"])
    assert code == 1


def test_bad_token_exits_2():
    base = start_mock_server()
    code = main(["--url", base, "--token", "wrong", "health"])
    assert code == 2


def test_connection_error_exits_2():
    # Bind a port then let it close so nothing is listening.
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    code = main(["--url", f"http://127.0.0.1:{port}", "status"])
    assert code == 2


if __name__ == "__main__":
    test_health()
    test_goto_payload()
    test_fill_payload_with_wait_ms()
    test_click_default_no_wait()
    test_ok_false_exits_1()
    test_bad_token_exits_2()
    test_connection_error_exits_2()
    print("ALL CLI TESTS PASSED")
