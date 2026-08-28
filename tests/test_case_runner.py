# -*- coding: utf-8 -*-
"""
@Author: byy
@Desc: 用例执行与 API 测试，验证保存、调试、断言选项和 WebSocket 步骤。
"""

import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler
from http.server import HTTPServer

from app import create_app
from app.extensions import db


class _TokenHandler(BaseHTTPRequestHandler):
    """为用例执行测试提供固定令牌响应的 HTTP 请求处理器。"""
    def do_GET(self):
        """处理测试服务收到的 GET 请求并返回预设数据。"""
        body = json.dumps(
            {"data": {"id": 1001, "token": "abc"}, "ok": True}
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        """关闭测试 HTTP 服务的默认控制台访问日志。"""
        return


class _HttpServerThread(object):
    """在后台线程中运行测试所需的临时 HTTP 服务。"""
    def __init__(self):
        """初始化后台 HTTP 测试服务及其线程。"""
        self.server = HTTPServer(("127.0.0.1", 0), _TokenHandler)
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


class CaseRunnerTestCase(unittest.TestCase):
    """集中验证接口用例保存、调试与执行流程。"""
    def setUp(self):
        """为当前测试准备独立的应用、数据库和依赖资源。"""
        self.app = create_app("testing")
        self.app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.create_all()
        self.client = self.app.test_client()

    def tearDown(self):
        """清理当前测试创建的应用、数据库和临时资源。"""
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def test_assertion_options_are_provided_by_backend(self):
        """用例与集合页面复用后端提供的断言中文选项。"""
        case_response = self.client.post("/api/test-case/options", json={})
        suite_response = self.client.post("/api/test-suite/options", json={})

        self.assertEqual(case_response.status_code, 200)
        self.assertEqual(suite_response.status_code, 200)
        case_options = case_response.json["data"]
        suite_options = suite_response.json["data"]
        self.assertIn(
            {"value": "equals", "label": "等于"},
            case_options["assertion_comparators"],
        )
        self.assertEqual(
            case_options["assertion_comparators"],
            suite_options["assertion_comparators"],
        )
        self.assertIn(
            {"value": "int", "label": "整数（int）"},
            case_options["assertion_value_types"],
        )

    def test_debug_http_case_returns_assertions_extractors_and_jsonpaths(self):
        """验证 HTTP 用例调试会返回断言、提取结果和可点选的 JSONPath。"""
        server = _HttpServerThread()
        server.start()
        try:
            project_id = self.client.post("/api/project/create", json={"name": "Demo"}).json["data"]["id"]
            environment_id = self.client.post(
                "/api/execution-environment/create",
                json={"name": "test", "base_url": server.url},
            ).json["data"]["id"]
            interface_id = self.client.post(
                "/api/interface-definition/create",
                json={
                    "project_id": project_id,
                    "name": "get token",
                    "interface_type": "http",
                    "method": "GET",
                    "url": "{{base_url}}/token",
                    "headers_template": "{}",
                    "body_template": "{}",
                    "body_type": "none",
                },
            ).json["data"]["id"]
            case_id = self.client.post(
                "/api/test-case/create",
                json={
                    "project_id": project_id,
                    "interface_id": interface_id,
                    "name": "debug http",
                    "assertions": [
                        {
                            "source": "status_code",
                            "comparator": "equals",
                            "expected": "200",
                            "value_type": "int",
                        },
                        {
                            "source": "body_json",
                            "jsonpath": "$.data.id",
                            "comparator": "equals",
                            "expected": "1001",
                            "value_type": "int",
                        },
                    ],
                    "extractors": [
                        {
                            "jsonpath": "$.data.token",
                            "variable_name": "token",
                            "required": True,
                        }
                    ],
                    "timeout_seconds": 3,
                },
            ).json["data"]["id"]

            response = self.client.post(
                "/api/test-case/debug",
                json={"case_id": case_id, "environment_id": environment_id},
            )
        finally:
            server.stop()

        result = response.json["data"]
        self.assertEqual(response.status_code, 200)
        self.assertTrue(result["success"])
        self.assertEqual(result["runner"]["response"]["status_code"], 200)
        self.assertTrue(result["assertions"][0]["passed"])
        self.assertTrue(result["assertions"][1]["passed"])
        self.assertEqual(result["extractors"][0]["value"], "abc")
        self.assertIn("$.data.token", result["jsonpaths"])

    def test_case_save_persists_environment_id(self):
        """验证保存接口用例时会持久化所选环境。"""
        project_id = self.client.post("/api/project/create", json={"name": "Demo"}).json["data"]["id"]
        environment_id = self.client.post("/api/execution-environment/create", json={"name": "test"}).json["data"]["id"]
        other_environment_id = self.client.post("/api/execution-environment/create", json={"name": "test-ip"}).json["data"]["id"]
        interface_id = self.client.post(
            "/api/interface-definition/create",
            json={
                "project_id": project_id,
                "name": "get token",
                "interface_type": "http",
                "method": "GET",
                "url": "/token",
                "headers_template": "{}",
                "body_template": "{}",
                "body_type": "none",
            },
        ).json["data"]["id"]

        response = self.client.post(
            "/api/test-case/create",
            json={
                "project_id": project_id,
                "interface_id": interface_id,
                "environment_id": environment_id,
                "name": "case env",
            },
        )
        case_id = response.json["data"]["id"]
        self.assertEqual(response.json["data"]["environment_id"], environment_id)

        update_response = self.client.post(
            "/api/test-case/save",
            json={
                "case_id": case_id,
                "project_id": project_id,
                "interface_id": interface_id,
                "environment_id": other_environment_id,
                "name": "case env",
                "assertions": [
                    {
                        "source": "status_code",
                        "jsonpath": "$.unused",
                        "header": "X-Unused",
                        "comparator": "equals",
                        "expected": "200",
                        "value_type": "int",
                    }
                ],
            },
        )
        get_response = self.client.post("/api/test-case/detail", json={"case_id": case_id})

        self.assertEqual(update_response.status_code, 200)
        self.assertEqual(get_response.json["data"]["environment_id"], other_environment_id)
        saved_assertion = get_response.json["data"]["assertions"][0]
        self.assertNotIn("jsonpath", saved_assertion)
        self.assertNotIn("header", saved_assertion)

        invalid_response = self.client.post(
            "/api/test-case/save",
            json={
                "case_id": case_id,
                "project_id": project_id,
                "interface_id": interface_id,
                "environment_id": other_environment_id,
                "name": "case env",
                "assertions": [
                    {
                        "source": "headers",
                        "comparator": "equals",
                        "expected": "application/json",
                        "value_type": "string",
                    }
                ],
            },
        )
        self.assertEqual(invalid_response.status_code, 400)
        self.assertIn("响应头名称不能为空", invalid_response.json["message"])

    def test_websocket_case_saves_simple_wait_assert_step(self):
        """WebSocket 用例只保存消息步骤，不生成 HTTP 状态码断言。"""
        project_id = self.client.post(
            "/api/project/create",
            json={"name": "WebSocket 项目"},
        ).json["data"]["id"]
        environment_id = self.client.post(
            "/api/execution-environment/create",
            json={"name": "ws-test"},
        ).json["data"]["id"]
        interface_id = self.client.post(
            "/api/interface-definition/create",
            json={
                "project_id": project_id,
                "module_name": "推送",
                "name": "消息接口",
                "interface_type": "websocket",
                "url": "ws://127.0.0.1:9000/ws",
                "ws_config": {},
            },
        ).json["data"]["id"]
        response = self.client.post(
            "/api/test-case/create",
            json={
                "project_id": project_id,
                "interface_id": interface_id,
                "environment_id": environment_id,
                "name": "等待登录结果",
                "timeout_seconds": 60,
                "ws_steps": [
                    {
                        "type": "wait_assert",
                        "timeout_seconds": 10,
                        "target": {"mode": "next", "conditions": []},
                        "assertions": [
                            {
                                "name": "业务状态码",
                                "source": "body_json",
                                "jsonpath": "$.code",
                                "comparator": "equals",
                                "value_type": "int",
                                "expected": "200",
                            }
                        ],
                    }
                ],
            },
        )

        self.assertEqual(response.status_code, 200)
        item = response.json["data"]
        self.assertEqual(item["assertions"], [])
        self.assertEqual(item["ws_steps"][0]["type"], "wait_assert")
        self.assertEqual(item["timeout_seconds"], 60)
        page = self.client.get("/cases/%s/edit/websocket" % item["id"])
        self.assertEqual(page.status_code, 200)
        self.assertIn("等待并校验消息", page.get_data(as_text=True))


if __name__ == "__main__":
    unittest.main()
