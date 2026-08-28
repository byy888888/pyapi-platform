# -*- coding: utf-8 -*-
"""
@Author: byy
@Desc: WebSocket SSE 测试，验证接口与用例页面的实时消息链路。
"""

import json
import os
import time
import unittest
from unittest.mock import patch

from app import create_app
from app.services.case_debug_service import case_debug_registry
from app.services.websocket_debug_service import debug_registry
from tests.test_runners import _WebSocketServerThread


class WebSocketSseTestCase(unittest.TestCase):
    """验证接口和用例页面使用 SSE 实时接收 WebSocket 日志。"""

    def setUp(self):
        """创建不启动外部服务的测试应用。"""
        self.app = create_app("testing")
        self.client = self.app.test_client()

    def test_interface_debug_sse_streams_buffered_message(self):
        """接口调试 SSE 应立即推送已经进入后端缓冲区的消息。"""
        server = _WebSocketServerThread()
        server.start()
        session_id = ""
        response = None
        try:
            created = debug_registry.create(server.url, {}, {"runtime_vars": {}})
            session_id = created["session_id"]
            response = self.client.get(
                "/api/websocket-debug/events?session_id=%s&after_sequence=0"
                % session_id,
                buffered=False,
            )
            first_event = next(response.response).decode("utf-8")
        finally:
            if response is not None:
                response.close()
            if session_id:
                debug_registry.close(session_id)
            server.stop()

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.content_type.startswith("text/event-stream"))
        self.assertIn("event: websocket_message", first_event)
        self.assertIn('"event":"connected"', first_event)

    def test_interface_debug_sse_streams_every_continuous_server_push(self):
        """服务端连续下发多条消息时，SSE 必须逐条、按顺序送达页面。"""
        expected = ["continuous-%02d" % index for index in range(12)]
        server = _WebSocketServerThread(
            push_messages=expected,
            push_interval=0.005,
        )
        server.start()
        session_id = ""
        response = None
        received = []
        try:
            created = debug_registry.create(server.url, {}, {"runtime_vars": {}})
            session_id = created["session_id"]
            response = self.client.get(
                "/api/websocket-debug/events?session_id=%s&after_sequence=0"
                % session_id,
                buffered=False,
            )
            for chunk in response.response:
                content = chunk.decode("utf-8")
                data_line = next(
                    (
                        line[6:]
                        for line in content.splitlines()
                        if line.startswith("data: ")
                    ),
                    "",
                )
                if not data_line:
                    continue
                item = json.loads(data_line)
                if item.get("direction") == "receive":
                    received.append(item.get("data"))
                if len(received) >= len(expected):
                    break
        finally:
            if response is not None:
                response.close()
            if session_id:
                debug_registry.close(session_id)
            server.stop()

        self.assertEqual(received, expected)

    def test_case_debug_sse_streams_message_and_final_result(self):
        """用例调试 SSE 应按顺序推送收发消息和最终执行结果。"""
        execution_id = ""

        def fake_run_case(
            _case_id,
            _environment_id,
            runtime_vars=None,
            debug=False,
            event_callback=None,
        ):
            """模拟执行器实时产生一条消息后返回最终结果。"""
            event_callback(
                {
                    "sequence": 1,
                    "direction": "receive",
                    "message_type": "text",
                    "data": "server-message",
                }
            )
            return {"success": True, "runner": {"ws_messages": []}}

        try:
            with patch(
                "app.services.case_debug_service.run_case",
                side_effect=fake_run_case,
            ):
                execution_id = case_debug_registry.start(self.app, 1, 1)
                execution = case_debug_registry.get(execution_id)
                deadline = time.monotonic() + 2
                while not execution.completed and time.monotonic() < deadline:
                    time.sleep(0.01)

            response = self.client.get(
                "/api/test-case/debug/events?execution_id=%s" % execution_id
            )
            content = response.get_data(as_text=True)
        finally:
            if execution_id:
                case_debug_registry.discard(execution_id)

        self.assertEqual(response.status_code, 200)
        self.assertIn("event: websocket_message", content)
        self.assertIn("server-message", content)
        self.assertIn("event: case_result", content)

    def test_websocket_pages_use_event_source_without_message_polling(self):
        """两个 WebSocket 页面都必须使用 EventSource，不能继续轮询消息接口。"""
        static_folder = self.app.static_folder
        with open(
            os.path.join(static_folder, "js", "websocket_interface_edit.js"),
            "r",
            encoding="utf-8",
        ) as source_file:
            interface_script = source_file.read()
        with open(
            os.path.join(static_folder, "js", "websocket_case_edit.js"),
            "r",
            encoding="utf-8",
        ) as source_file:
            case_script = source_file.read()

        self.assertIn("new EventSource('/api/websocket-debug/events", interface_script)
        self.assertNotIn("/api/websocket-debug/messages", interface_script)
        self.assertNotIn("renderMessages([resp.data])", interface_script)
        self.assertIn("pendingMessages[lastSequence + 1]", interface_script)
        self.assertIn("/api/test-case/debug/start", case_script)
        self.assertIn("new EventSource('/api/test-case/debug/events", case_script)


if __name__ == "__main__":
    unittest.main()
