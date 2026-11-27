#!/usr/bin/env python3
"""Open a temporary Condor administrator session through an SSH tunnel."""

import argparse
import json
from pathlib import Path
import selectors
import shutil
import socket
import socketserver
import subprocess
import sys
import threading
import time
import webbrowser


class LoginError(RuntimeError):
    """A safe-to-display login or tunnel error."""


def limited_port(value: str) -> int:
    port = int(value)
    if not 1 <= port <= 65535:
        raise argparse.ArgumentTypeError("端口必须在 1 到 65535 之间")
    return port


def parse_args(argv=None):
    root = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description="通过 SSH 临时登录 Condor")
    parser.add_argument("--host", default="103.193.150.25")
    parser.add_argument("--user", default="root")
    parser.add_argument("--key", type=Path, default=root / "ssh" / "id_ed25519")
    parser.add_argument("--known-hosts", type=Path, default=root / "ssh" / "known_hosts")
    parser.add_argument("--port", type=limited_port, default=18082)
    parser.add_argument("--no-open", action="store_true")
    return parser.parse_args(argv)


def ssh_base_args(args):
    return [
        "ssh",
        "-o", "BatchMode=yes",
        "-o", "IdentitiesOnly=yes",
        "-o", "StrictHostKeyChecking=yes",
        "-o", f"UserKnownHostsFile={args.known_hosts}",
        "-i", str(args.key),
        f"{args.user}@{args.host}",
    ]


def validate_environment(args):
    if shutil.which("ssh") is None:
        raise LoginError("未找到 ssh，请先安装 OpenSSH 客户端")
    if not args.key.is_file():
        raise LoginError(f"SSH 私钥不存在：{args.key}")
    if not args.known_hosts.is_file():
        raise LoginError(f"主机指纹文件不存在：{args.known_hosts}")


def create_session(args):
    remote_python = (
        "import json; from condor.web.auth import create_jwt; "
        "from config_manager import get_config_manager; "
        "cm=get_config_manager(); admin_id=cm.admin_id; "
        "print(json.dumps({'token':create_jwt(admin_id,username='admin',"
        "first_name='Admin',role='admin'),'user':{'id':admin_id,"
        "'username':'admin','first_name':'Admin','role':'admin'}}))"
    )
    command = ssh_base_args(args) + [
        f"cd /root/condor && .venv/bin/python -c \"{remote_python}\""
    ]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise LoginError("SSH 会话生成失败，请检查网络和服务器状态") from exc
    if result.returncode != 0:
        raise LoginError(
            f"SSH 会话生成失败（退出码 {result.returncode}），未输出远端敏感内容"
        )
    try:
        session = json.loads(result.stdout)
        if not isinstance(session["token"], str) or not session["token"]:
            raise ValueError("missing token")
        if not isinstance(session["user"], dict) or not session["user"]["id"]:
            raise ValueError("missing user")
    except (ValueError, KeyError, TypeError) as exc:
        raise LoginError("服务器返回了无法识别的会话结构") from exc
    return session


def reserve_backend_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def receive_headers(client, limit=65536):
    data = bytearray()
    while b"\r\n\r\n" not in data:
        chunk = client.recv(8192)
        if not chunk:
            raise LoginError("浏览器在发送完整请求头前断开了连接")
        data.extend(chunk)
        if len(data) > limit:
            raise LoginError("HTTP 请求头超过 64 KiB")
    head, extra = bytes(data).split(b"\r\n\r\n", 1)
    return head + b"\r\n\r\n", extra


def relay_bidirectional(client, upstream, initial):
    upstream.sendall(initial)
    with selectors.DefaultSelector() as selector:
        selector.register(client, selectors.EVENT_READ, upstream)
        selector.register(upstream, selectors.EVENT_READ, client)
        while True:
            for key, _ in selector.select():
                source, destination = key.fileobj, key.data
                chunk = source.recv(65536)
                if not chunk:
                    return
                destination.sendall(chunk)


class LoginProxy:
    def __init__(self, host, port, backend_port, session):
        self.backend_port = backend_port
        self._login_lock = threading.Lock()
        token = json.dumps(session["token"]).replace("</", "<\\/")
        user = json.dumps(session["user"], separators=(",", ":")).replace("</", "<\\/")
        self._login_html = (
            "<!doctype html><meta charset='utf-8'><title>Condor login</title>"
            f"<script>localStorage.setItem(\"condor_token\",{token});"
            f"localStorage.setItem(\"condor_user\",JSON.stringify({user}));"
            "location.replace('/');</script>"
        ).encode("utf-8")
        proxy = self

        class Handler(socketserver.BaseRequestHandler):
            def handle(self):
                client = self.request
                try:
                    head, extra = receive_headers(client)
                    path = head.split(b" ", 2)[1]
                    if path == b"/__condor_login":
                        with proxy._login_lock:
                            html, proxy._login_html = proxy._login_html, None
                        if html is None:
                            client.sendall(
                                b"HTTP/1.1 302 Found\r\nLocation: /\r\n"
                                b"Cache-Control: no-store\r\nContent-Length: 0\r\n"
                                b"Connection: close\r\n\r\n"
                            )
                            return
                        client.sendall(
                            b"HTTP/1.1 200 OK\r\n"
                            b"Content-Type: text/html; charset=utf-8\r\n"
                            b"Cache-Control: no-store\r\nConnection: close\r\n"
                            b"Content-Length: " + str(len(html)).encode()
                            + b"\r\n\r\n" + html
                        )
                        return
                    with socket.create_connection(
                        ("127.0.0.1", proxy.backend_port), timeout=10
                    ) as upstream:
                        relay_bidirectional(client, upstream, head + extra)
                except (ConnectionError, OSError, LoginError):
                    return

        class Server(socketserver.ThreadingTCPServer):
            allow_reuse_address = True
            daemon_threads = True

        self._server = Server((host, port), Handler)
        self._thread = None

    @property
    def address(self):
        return self._server.server_address

    def start(self):
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def close(self):
        if self._thread is not None:
            self._server.shutdown()
            self._thread.join(timeout=5)
        self._server.server_close()


class SshTunnel:
    def __init__(self, args, backend_port):
        self.args = args
        self.backend_port = backend_port
        self.process = None

    def start(self):
        command = [
            "ssh", "-N", "-L",
            f"127.0.0.1:{self.backend_port}:127.0.0.1:8088",
            "-o", "ExitOnForwardFailure=yes",
            "-o", "ServerAliveInterval=30",
            "-o", "ServerAliveCountMax=3",
            "-o", "BatchMode=yes",
            "-o", "IdentitiesOnly=yes",
            "-o", "StrictHostKeyChecking=yes",
            "-o", f"UserKnownHostsFile={self.args.known_hosts}",
            "-i", str(self.args.key),
            f"{self.args.user}@{self.args.host}",
        ]
        try:
            self.process = subprocess.Popen(
                command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
        except OSError as exc:
            raise LoginError("无法启动 SSH 隧道，请检查 OpenSSH 客户端") from exc
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                raise LoginError(f"SSH 隧道启动失败（退出码 {self.process.returncode}）")
            try:
                with socket.create_connection(("127.0.0.1", self.backend_port), timeout=0.5):
                    return
            except OSError:
                time.sleep(0.1)
        raise LoginError("SSH 隧道在 15 秒内未就绪")

    def is_running(self):
        if self.process is None or self.process.poll() is not None:
            raise LoginError("SSH 隧道已断开，请重新运行脚本")
        return True

    def close(self):
        if self.process is None or self.process.poll() is not None:
            return
        self.process.terminate()
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=5)


def main(argv=None):
    tunnel = None
    proxy = None
    try:
        args = parse_args(argv)
        validate_environment(args)
        session = create_session(args)
        tunnel = SshTunnel(args, reserve_backend_port())
        tunnel.start()
        try:
            proxy = LoginProxy("127.0.0.1", args.port, tunnel.backend_port, session)
        except OSError as exc:
            raise LoginError(
                f"本地端口 {args.port} 已被占用，请使用 --port 指定其他端口"
            ) from exc
        finally:
            session.clear()
        proxy.start()
        login_url = f"http://localhost:{proxy.address[1]}/__condor_login"
        print(f"Condor 已就绪：http://localhost:{proxy.address[1]}/")
        print("管理员会话有效期为 24 小时；保持本窗口运行，按 Ctrl+C 退出。")
        if not args.no_open and not webbrowser.open(login_url):
            print(f"无法自动打开浏览器，请手动访问：{login_url}")
        while tunnel.is_running():
            time.sleep(1)
        return 0
    except KeyboardInterrupt:
        print("\n正在关闭 Condor 临时访问……")
        return 0
    except LoginError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1
    finally:
        if proxy is not None:
            proxy.close()
        if tunnel is not None:
            tunnel.close()


if __name__ == "__main__":
    raise SystemExit(main())
