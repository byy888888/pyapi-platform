# -*- coding: utf-8 -*-
"""
@Author: byy
@Desc: HTTP 与 WebSocket 执行器测试，包含本地模拟服务和连续消息场景。
"""

import base64
import hashlib
import json
import socket
import struct
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler
from http.server import HTTPServer

from app.services.http_runner import run_http_case
from app.services.websocket_debug_service import WebSocketDebugRegistry
from app.services.websocket_runner import run_websocket_case


class _JsonHandler(BaseHTTPRequestHandler):
    """为执行器测试提供 JSON 响应的 HTTP 请求处理器。"""
    def do_POST(self):
        """处理测试服务收到的 POST 请求并回显预设数据。"""
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length).decode("utf-8")
        content_type = self.headers.get("Content-Type", "")
        if "application/json" in content_type:
            parsed_body = json.loads(body)
        else:
            parsed_body = body
        payload = {"path": self.path, "body": parsed_body, "content_type": content_type}
        content = json.dumps(payload).encode("utf-8")
        self.send_response(201)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def log_message(self, format, *args):
        """关闭测试 HTTP 服务的默认控制台访问日志。"""
        return


class _HttpServerThread(object):
    """在后台线程中运行测试所需的临时 HTTP 服务。"""
    def __init__(self):
        """初始化后台 HTTP 测试服务及其线程。"""
        self.server = HTTPServer(("127.0.0.1", 0), _JsonHandler)
        self.url = "http://127.0.0.1:%s" % self.server.server_port
        self.thread = threading.Thread(target=self.server.serve_forever)
        self.thread.daemon = True

    def start(self):
        """启动后台测试服务。"""
        self.thread.start()

    def stop(self):
        """停止后台测试服务并释放监听端口。"""
        self.server.shutdown()
        self.thread.join(timeout=2)
        self.server.server_close()


class _WebSocketServerThread(object):
    """在后台线程中运行测试所需的临时 WebSocket 服务。"""
    def __init__(self, push_messages=None, push_interval=0.01):
        """初始化后台 WebSocket 测试服务及其状态。"""
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(1)
        self.port = self.sock.getsockname()[1]
        self.url = "ws://127.0.0.1:%s" % self.port
        self.thread = threading.Thread(target=self._serve)
        self.thread.daemon = True
        self.stop_event = threading.Event()
        self.push_messages = list(push_messages) if push_messages is not None else ["server-push"]
        self.push_interval = push_interval
        self.send_lock = threading.Lock()

    def start(self):
        """启动后台测试服务。"""
        self.thread.start()

    def stop(self):
        """停止后台测试服务并释放监听端口。"""
        self.stop_event.set()
        try:
            self.sock.close()
        except Exception:
            pass
        self.thread.join(timeout=2)

    def _serve(self):
        """接受客户端连接并持续处理 WebSocket 数据帧。"""
        conn = None
        try:
            conn, _addr = self.sock.accept()
            self._handshake(conn)
            threading.Thread(target=self._push_later, args=(conn,)).start()
            while not self.stop_event.is_set():
                message = self._read_frame(conn)
                if message is None:
                    break
                self._send_frame(conn, "echo:%s" % message)
        except Exception:
            pass
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass

    def _push_later(self, conn):
        """延迟向客户端主动推送测试消息。"""
        time.sleep(0.15)
        for message in self.push_messages:
            if self.stop_event.is_set():
                return
            try:
                self._send_frame(conn, message)
            except Exception:
                return
            time.sleep(self.push_interval)

    def _handshake(self, conn):
        """完成测试 WebSocket 连接的 HTTP 升级握手。"""
        request = b""
        while b"\r\n\r\n" not in request:
            chunk = conn.recv(1024)
            if not chunk:
                raise RuntimeError("handshake failed")
            request += chunk
        headers = request.decode("latin1").split("\r\n")
        key = ""
        for header in headers:
            if header.lower().startswith("sec-websocket-key:"):
                key = header.split(":", 1)[1].strip()
        accept = base64.b64encode(
            hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode("ascii")).digest()
        ).decode("ascii")
        response = (
            "HTTP/1.1 101 Switching Protocols\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            "Sec-WebSocket-Accept: %s\r\n\r\n" % accept
        )
        conn.sendall(response.encode("ascii"))

    def _read_frame(self, conn):
        """读取并解析客户端发送的一个 WebSocket 数据帧。"""
        first = conn.recv(2)
        if len(first) < 2:
            return None
        opcode = first[0] & 0x0F
        if opcode == 8:
            return None
        masked = first[1] & 0x80
        length = first[1] & 0x7F
        if length == 126:
            length = struct.unpack("!H", self._recv_exact(conn, 2))[0]
        elif length == 127:
            length = struct.unpack("!Q", self._recv_exact(conn, 8))[0]
        mask = self._recv_exact(conn, 4) if masked else b"\x00\x00\x00\x00"
        payload = self._recv_exact(conn, length)
        if masked:
            payload = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
        return payload.decode("utf-8")

    def _send_frame(self, conn, message):
        """将指定内容封装为 WebSocket 数据帧后发送。"""
        payload = message.encode("utf-8")
        header = bytearray([0x81])
        length = len(payload)
        if length < 126:
            header.append(length)
        elif length < 65536:
            header.append(126)
            header.extend(struct.pack("!H", length))
        else:
            header.append(127)
            header.extend(struct.pack("!Q", length))
        with self.send_lock:
            conn.sendall(bytes(header) + payload)

    def _recv_exact(self, conn, length):
        """从套接字读取指定长度的完整字节数据。"""
        data = b""
        while len(data) < length:
            chunk = conn.recv(length - len(data))
            if not chunk:
                raise RuntimeError("connection closed")
            data += chunk
        return data


class RunnerTestCase(unittest.TestCase):
    """集中验证 HTTP 与 WebSocket 底层执行器。"""
    def test_http_runner_independent_call(self):
        """验证 HTTP 执行器可以独立完成请求调用。"""
        server = _HttpServerThread()
        server.start()
        try:
            result = run_http_case(
                {
                    "method": "POST",
                    "url": "{{base_url}}/login",
                    "headers": {"Content-Type": "application/json"},
                    "body": {"username": "${username}"},
                    "body_type": "json",
                    "timeout_seconds": 5,
                },
                {
                    "global_vars": {"base_url": server.url},
                    "runtime_vars": {"username": "alice"},
                },
            )
        finally:
            server.stop()

        self.assertTrue(result["success"])
        self.assertEqual(result["response_context"]["status_code"], 201)
        self.assertEqual(result["response_context"]["body_json"]["body"]["username"], "alice")

    def test_http_runner_joins_relative_url_with_base_url(self):
        """验证 HTTP 执行器会将相对路径与基础地址正确拼接。"""
        server = _HttpServerThread()
        server.start()
        try:
            result = run_http_case(
                {
                    "method": "POST",
                    "url": "/api/login",
                    "headers": {"Content-Type": "application/json"},
                    "body": {"username": "alice"},
                    "body_type": "json",
                    "timeout_seconds": 5,
                },
                {
                    "global_vars": {"base_url": server.url},
                    "runtime_vars": {},
                },
            )
        finally:
            server.stop()

        self.assertTrue(result["success"])
        self.assertEqual(result["request"]["url"], server.url + "/api/login")
        self.assertEqual(result["response_context"]["body_json"]["path"], "/api/login")

    def test_http_runner_joins_relative_url_with_environment_base_url(self):
        """验证 HTTP 执行器会使用环境中的基础地址拼接相对路径。"""
        server = _HttpServerThread()
        server.start()
        try:
            result = run_http_case(
                {
                    "method": "POST",
                    "url": "/api/login",
                    "headers": {"Content-Type": "application/json"},
                    "body": {"username": "alice"},
                    "body_type": "json",
                    "timeout_seconds": 5,
                },
                {
                    "global_vars": {},
                    "environment": {"base_url": server.url},
                    "runtime_vars": {},
                },
            )
        finally:
            server.stop()

        self.assertTrue(result["success"])
        self.assertEqual(result["request"]["url"], server.url + "/api/login")
        self.assertEqual(result["response_context"]["body_json"]["path"], "/api/login")

    def test_http_runner_sends_urlencoded_body(self):
        """验证 HTTP 执行器能够发送 URL 编码请求体。"""
        server = _HttpServerThread()
        server.start()
        try:
            result = run_http_case(
                {
                    "method": "POST",
                    "url": "{{base_url}}/submit",
                    "body": {"username": "alice"},
                    "body_type": "x-www-form-urlencoded",
                    "timeout_seconds": 5,
                },
                {"global_vars": {"base_url": server.url}, "runtime_vars": {}},
            )
        finally:
            server.stop()

        self.assertTrue(result["success"])
        self.assertIn("application/x-www-form-urlencoded", result["response_context"]["body_json"]["content_type"])
        self.assertEqual(result["response_context"]["body_json"]["body"], "username=alice")

    def test_http_runner_sends_form_data_body(self):
        """验证 HTTP 执行器能够发送表单请求体。"""
        server = _HttpServerThread()
        server.start()
        try:
            result = run_http_case(
                {
                    "method": "POST",
                    "url": "{{base_url}}/upload",
                    "body": {"username": "alice"},
                    "body_type": "form-data",
                    "timeout_seconds": 5,
                },
                {"global_vars": {"base_url": server.url}, "runtime_vars": {}},
            )
        finally:
            server.stop()

        self.assertTrue(result["success"])
        self.assertIn("multipart/form-data", result["response_context"]["body_json"]["content_type"])
        self.assertIn('name="username"', result["response_context"]["body_json"]["body"])
        self.assertIn("alice", result["response_context"]["body_json"]["body"])

    def test_websocket_runner_decoupled_send_receive(self):
        """验证 WebSocket 执行器的连接、发送和接收流程彼此解耦且可用。"""
        server = _WebSocketServerThread()
        server.start()
        try:
            result = run_websocket_case(
                {
                    "url": "{{ws_url}}",
                    "timeout_seconds": 2,
                    "ws_steps": [
                        {"action": "connect"},
                        {"action": "send", "message": "first"},
                        {"action": "receive_assert", "expected": "server-push", "timeout_seconds": 2},
                        {"action": "send", "message": "second"},
                        {"action": "receive_assert", "expected": "echo:second", "timeout_seconds": 2},
                        {"action": "close"},
                    ],
                },
                {"global_vars": {"ws_url": server.url}, "runtime_vars": {}},
            )
        finally:
            server.stop()

        self.assertTrue(result["success"])
        self.assertTrue(result["connected"])
        self.assertTrue(result["closed"])
        messages = "\n".join([item.get("data", "") for item in result["ws_messages"]])
        self.assertIn("server-push", messages)
        self.assertIn("echo:second", messages)

    def test_websocket_session_waiter_wakes_when_message_arrives(self):
        """SSE 使用的会话等待器应在服务端消息到达时立即唤醒。"""
        server = _WebSocketServerThread()
        registry = WebSocketDebugRegistry()
        server.start()
        session_id = ""
        try:
            created = registry.create(server.url, {}, {"runtime_vars": {}})
            session_id = created["session_id"]
            sent = registry.send(session_id, "debug-message", "text")
            session = registry.get(session_id)
            started_at = time.monotonic()
            messages = session.wait_for_messages_after(
                int(sent["sequence"]),
                timeout_seconds=1,
            )
            elapsed = time.monotonic() - started_at
        finally:
            if session_id:
                registry.close(session_id)
            server.stop()

        received = [
            item for item in messages
            if item.get("direction") == "receive"
        ]
        self.assertTrue(received)
        self.assertLess(elapsed, 0.9)

    def test_websocket_session_keeps_all_continuous_server_pushes(self):
        """连续服务端推送（包括空文本帧）不能让接收线程提前停止或丢消息。"""
        expected = ["push-%02d" % index for index in range(12)]
        expected.insert(5, "")
        server = _WebSocketServerThread(
            push_messages=expected,
            push_interval=0.005,
        )
        registry = WebSocketDebugRegistry()
        server.start()
        session_id = ""
        try:
            created = registry.create(server.url, {}, {"runtime_vars": {}})
            session_id = created["session_id"]
            session = registry.get(session_id)
            deadline = time.monotonic() + 2
            received = []
            while time.monotonic() < deadline:
                received = [
                    item.get("data")
                    for item in session.messages_after(0)
                    if item.get("direction") == "receive"
                ]
                if len(received) >= len(expected):
                    break
                time.sleep(0.01)
        finally:
            if session_id:
                registry.close(session_id)
            server.stop()

        self.assertEqual(received, expected)

    def test_websocket_runner_optional_connect_message_and_simple_assertion(self):
        """连接后消息可选开启，并能使用简化等待断言模型。"""
        server = _WebSocketServerThread()
        server.start()
        try:
            result = run_websocket_case(
                {
                    "url": "{{ws_url}}?token={{token}}",
                    "timeout_seconds": 3,
                    "ws_config": {
                        "headers": {},
                        "connect_timeout_ms": 1000,
                        "connect_message": {
                            "enabled": True,
                            "message_type": "json",
                            "content": {"type": "auth", "payload": {"token": "{{token}}"}},
                        },
                        "heartbeat": {"enabled": False},
                    },
                    "ws_steps": [
                        {
                            "type": "wait_assert",
                            "name": "等待认证响应",
                            "timeout_seconds": 2,
                            "target": {
                                "mode": "condition",
                                "consume": True,
                                "conditions": [
                                    {
                                        "source": "body_text",
                                        "comparator": "contains",
                                        "value_type": "string",
                                        "expected": "echo:",
                                    }
                                ],
                            },
                            "assertions": [
                                {
                                    "name": "认证报文已回显",
                                    "source": "body_text",
                                    "comparator": "contains",
                                    "value_type": "string",
                                    "expected": "auth",
                                }
                            ],
                            "extractors": [],
                        }
                    ],
                },
                {
                    "global_vars": {"ws_url": server.url, "token": "secret-token"},
                    "runtime_vars": {},
                },
            )
        finally:
            server.stop()

        self.assertTrue(result["success"])
        self.assertTrue(result["steps"][1]["assertions"][0]["passed"])
        self.assertGreaterEqual(result["steps"][1]["response_time_ms"], 0)
        sent_messages = [
            item for item in result["ws_messages"] if item.get("direction") == "send"
        ]
        self.assertTrue(sent_messages[0]["is_connect_message"])


if __name__ == "__main__":
    unittest.main()
