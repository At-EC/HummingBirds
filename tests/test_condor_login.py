import argparse
import json
from pathlib import Path
import subprocess
import unittest
from unittest import mock

import condor_login


class ArgumentTests(unittest.TestCase):
    def test_defaults_and_overrides(self):
        args = condor_login.parse_args([])
        self.assertEqual(args.host, "103.193.150.25")
        self.assertEqual(args.user, "root")
        self.assertEqual(args.port, 18082)
        self.assertEqual(args.key.name, "id_ed25519")
        self.assertEqual(args.known_hosts.name, "known_hosts")

        custom = condor_login.parse_args([
            "--host", "example.test", "--user", "ops", "--port", "19090",
            "--key", "custom-key", "--known-hosts", "custom-hosts", "--no-open",
        ])
        self.assertEqual(custom.host, "example.test")
        self.assertEqual(custom.user, "ops")
        self.assertEqual(custom.port, 19090)
        self.assertTrue(custom.no_open)

    def test_invalid_port_is_rejected(self):
        with self.assertRaises(SystemExit):
            condor_login.parse_args(["--port", "70000"])


class SessionTests(unittest.TestCase):
    def args(self, root: Path):
        return argparse.Namespace(
            host="example.test", user="root", key=root / "key",
            known_hosts=root / "hosts", port=18082, no_open=True,
        )

    @mock.patch("condor_login.subprocess.run")
    def test_session_is_returned_without_logging_token(self, run):
        run.return_value = subprocess.CompletedProcess([], 0, stdout=json.dumps({
            "token": "secret-test-token",
            "user": {"id": 7, "username": "admin", "first_name": "Admin", "role": "admin"},
        }), stderr="")
        with mock.patch("builtins.print") as output:
            session = condor_login.create_session(self.args(Path("/unused")))
        self.assertEqual(session["token"], "secret-test-token")
        printed = " ".join(str(call.args) for call in output.call_args_list)
        self.assertNotIn("secret-test-token", printed)
        ssh_command = run.call_args.args[0]
        self.assertIn("StrictHostKeyChecking=yes", ssh_command)
        self.assertIn("BatchMode=yes", ssh_command)

    @mock.patch("condor_login.subprocess.run")
    def test_remote_stdout_is_not_exposed_on_failure(self, run):
        run.return_value = subprocess.CompletedProcess(
            [], 1, stdout="secret-test-token", stderr="private details"
        )
        with self.assertRaisesRegex(condor_login.LoginError, "退出码 1") as raised:
            condor_login.create_session(self.args(Path("/unused")))
        self.assertNotIn("secret-test-token", str(raised.exception))
        self.assertNotIn("private details", str(raised.exception))


if __name__ == "__main__":
    unittest.main()


import socket
import socketserver
import threading


def recv_exact(client, size):
    data = bytearray()
    while len(data) < size:
        chunk = client.recv(size - len(data))
        if not chunk:
            raise AssertionError(f"连接提前关闭，只收到 {len(data)}/{size} 字节")
        data.extend(chunk)
    return bytes(data)


def recv_until(client, marker):
    data = bytearray()
    while marker not in data:
        chunk = client.recv(8192)
        if not chunk:
            raise AssertionError("连接在收到预期标记前关闭")
        data.extend(chunk)
    return bytes(data)


def http_request(port, path, body=b""):
    with socket.create_connection(("127.0.0.1", port), timeout=5) as client:
        client.settimeout(5)
        request = (
            f"GET {path} HTTP/1.1\r\nHost: localhost\r\n"
            f"Content-Length: {len(body)}\r\nConnection: close\r\n\r\n"
        ).encode() + body
        client.sendall(request)
        response = bytearray()
        while True:
            chunk = client.recv(65536)
            if not chunk:
                break
            response.extend(chunk)
        return bytes(response)


def unused_backend_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class EchoServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


class EchoHandler(socketserver.BaseRequestHandler):
    def handle(self):
        head = bytearray()
        while not head.endswith(b"\r\n\r\n"):
            chunk = self.request.recv(1)
            if not chunk:
                return
            head.extend(chunk)
        content_length = 0
        for line in head.split(b"\r\n"):
            if line.lower().startswith(b"content-length:"):
                content_length = int(line.split(b":", 1)[1])
        body = recv_exact(self.request, content_length)
        self.request.sendall(
            b"HTTP/1.1 200 OK\r\nContent-Length: " + str(len(body)).encode()
            + b"\r\nConnection: close\r\n\r\n" + body
        )


class UpgradeEchoHandler(socketserver.BaseRequestHandler):
    def handle(self):
        recv_until(self.request, b"\r\n\r\n")
        self.request.sendall(
            b"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\n"
            b"Connection: Upgrade\r\n\r\n"
        )
        while True:
            data = self.request.recv(65536)
            if not data:
                return
            self.request.sendall(data)


class ProxyTests(unittest.TestCase):
    def setUp(self):
        self.session = {
            "token": "secret-test-token",
            "user": {"id": 7, "username": "admin", "first_name": "Admin", "role": "admin"},
        }

    def start_backend(self, handler):
        backend = EchoServer(("127.0.0.1", 0), handler)
        thread = threading.Thread(target=backend.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(backend.server_close)
        self.addCleanup(backend.shutdown)
        return backend

    def test_login_is_same_origin_no_store_and_single_use(self):
        proxy = condor_login.LoginProxy("127.0.0.1", 0, unused_backend_port(), self.session)
        proxy.start()
        self.addCleanup(proxy.close)
        port = proxy.address[1]
        response = http_request(port, "/__condor_login")
        self.assertIn(b"200", response.split(b"\r\n", 1)[0])
        self.assertIn(b"Cache-Control: no-store", response)
        self.assertIn(b'localStorage.setItem("condor_token"', response)
        self.assertIn(b"secret-test-token", response)
        second = http_request(port, "/__condor_login")
        self.assertIn(b"302", second.split(b"\r\n", 1)[0])
        self.assertNotIn(b"secret-test-token", second)

    def test_http_request_and_response_are_forwarded(self):
        backend = self.start_backend(EchoHandler)
        proxy = condor_login.LoginProxy(
            "127.0.0.1", 0, backend.server_address[1], self.session
        )
        proxy.start()
        self.addCleanup(proxy.close)
        response = http_request(proxy.address[1], "/bots", body=b'{"read_only":true}')
        self.assertIn(b'{"read_only":true}', response)

    def test_websocket_upgrade_bytes_are_relayed(self):
        backend = self.start_backend(UpgradeEchoHandler)
        proxy = condor_login.LoginProxy(
            "127.0.0.1", 0, backend.server_address[1], self.session
        )
        proxy.start()
        self.addCleanup(proxy.close)
        with socket.create_connection(proxy.address, timeout=5) as client:
            client.settimeout(5)
            client.sendall(
                b"GET /ws HTTP/1.1\r\nHost: localhost\r\nUpgrade: websocket\r\n\r\n"
            )
            self.assertIn(b"101 Switching Protocols", recv_until(client, b"\r\n\r\n"))
            payload = b"binary-frame-\x00\xff"
            client.sendall(payload)
            self.assertEqual(recv_exact(client, len(payload)), payload)

    def test_proxy_binds_loopback_only(self):
        proxy = condor_login.LoginProxy("127.0.0.1", 0, unused_backend_port(), self.session)
        self.assertEqual(proxy.address[0], "127.0.0.1")
        proxy.close()


import io
from contextlib import redirect_stderr, redirect_stdout


class LifecycleTests(unittest.TestCase):
    def args(self):
        return argparse.Namespace(
            host="example.test", user="root", key=Path("key"),
            known_hosts=Path("hosts"), port=18082, no_open=True,
        )

    @mock.patch("condor_login.socket.create_connection")
    @mock.patch("condor_login.subprocess.Popen")
    def test_tunnel_command_and_owned_process_cleanup(self, popen, connect):
        process = popen.return_value
        process.poll.return_value = None
        connect.return_value.__enter__.return_value = mock.Mock()
        tunnel = condor_login.SshTunnel(self.args(), 23456)
        tunnel.start()
        command = popen.call_args.args[0]
        self.assertIn("127.0.0.1:23456:127.0.0.1:8088", command)
        self.assertIn("ExitOnForwardFailure=yes", command)
        tunnel.close()
        process.terminate.assert_called_once()
        process.wait.assert_called_once_with(timeout=5)

    @mock.patch("condor_login.subprocess.Popen")
    def test_tunnel_early_exit_is_safe_error(self, popen):
        popen.return_value.poll.return_value = 255
        popen.return_value.returncode = 255
        tunnel = condor_login.SshTunnel(self.args(), 23456)
        with self.assertRaisesRegex(condor_login.LoginError, "退出码 255"):
            tunnel.start()

    @mock.patch("condor_login.webbrowser.open", return_value=True)
    @mock.patch("condor_login.LoginProxy")
    @mock.patch("condor_login.SshTunnel")
    @mock.patch("condor_login.create_session")
    @mock.patch("condor_login.validate_environment")
    def test_main_cleans_up_on_keyboard_interrupt(self, validate, session, tunnel, proxy, browser):
        session.return_value = {"token": "secret", "user": {"id": 1}}
        tunnel.return_value.is_running.side_effect = KeyboardInterrupt
        proxy.return_value.address = ("127.0.0.1", 18082)
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            self.assertEqual(condor_login.main(["--no-open"]), 0)
        proxy.return_value.close.assert_called_once()
        tunnel.return_value.close.assert_called_once()
        browser.assert_not_called()
        self.assertNotIn("secret", stdout.getvalue())

    @mock.patch("condor_login.webbrowser.open", return_value=True)
    @mock.patch("condor_login.LoginProxy", side_effect=OSError("occupied"))
    @mock.patch("condor_login.SshTunnel")
    @mock.patch("condor_login.create_session")
    @mock.patch("condor_login.validate_environment")
    def test_port_conflict_closes_tunnel(self, validate, session, tunnel, proxy, browser):
        session.return_value = {"token": "secret", "user": {"id": 1}}
        stderr = io.StringIO()
        with redirect_stderr(stderr):
            self.assertEqual(condor_login.main([]), 1)
        tunnel.return_value.close.assert_called_once()
        browser.assert_not_called()
        self.assertIn("已被占用", stderr.getvalue())
        self.assertNotIn("secret", stderr.getvalue())


class LauncherTests(unittest.TestCase):
    def test_windows_launcher_uses_script_directory_and_forwards_arguments(self):
        launcher = Path(condor_login.__file__).resolve().with_name("condor_login.cmd")
        self.assertTrue(launcher.is_file(), "缺少 Windows 双击启动器")
        content = launcher.read_text(encoding="utf-8")
        self.assertIn('cd /d "%~dp0"', content)
        self.assertIn('py -3 "condor_login.py" %*', content)
        self.assertIn('python "condor_login.py" %*', content)
        self.assertNotIn("condor_token", content)
