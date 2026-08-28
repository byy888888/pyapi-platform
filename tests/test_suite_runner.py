# -*- coding: utf-8 -*-
"""
@Author: byy
@Desc: 集合执行器测试，验证步骤覆盖、变量传递、失败策略和历史记录。
"""

import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler
from http.server import HTTPServer
from urllib.parse import parse_qs
from urllib.parse import urlsplit

from app import create_app
from app.extensions import db
from app.models import ExecutionDetail
from app.models import ExecutionHistory
from app.models import SuiteCase


class _SuiteHandler(BaseHTTPRequestHandler):
    """为场景集合测试提供可控响应的 HTTP 请求处理器。"""
    def do_GET(self):
        """处理测试服务收到的 GET 请求并返回预设数据。"""
        parsed_url = urlsplit(self.path)
        if parsed_url.path.endswith("/ok"):
            payload = {"ok": True, "token": "suite-token"}
            status = 200
        elif parsed_url.path.endswith("/profile"):
            params = parse_qs(parsed_url.query)
            auth_header = self.headers.get("Authorization", "")
            received_token = params.get("token", [""])[0]
            token_valid = auth_header == "Bearer suite-token" and received_token == "suite-token"
            payload = {"ok": token_valid, "token": received_token}
            status = 200 if token_valid else 401
        else:
            payload = {"ok": False}
            status = 500
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
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
        self.server = HTTPServer(("127.0.0.1", 0), _SuiteHandler)
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


class SuiteRunnerTestCase(unittest.TestCase):
    """集中验证场景集合的编排、执行与结果记录。"""
    def setUp(self):
        """为当前测试准备独立的应用、数据库和依赖资源。"""
        self.app = create_app("testing")
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.create_all()
        self.client = self.app.test_client()
        self.server = _HttpServerThread()
        self.server.start()
        self.project_id = self.client.post("/api/project/create", json={"name": "Demo"}).json["data"]["id"]
        self.environment_id = self.client.post(
            "/api/execution-environment/create",
            json={"name": "test", "base_url": self.server.url},
        ).json["data"]["id"]
        self.ok_case_id = self._create_case("ok case", "ok", "200")
        self.fail_case_id = self._create_case("fail case", "fail", "200")
        self.second_ok_case_id = self._create_case("second ok", "ok", "200")

    def tearDown(self):
        """清理当前测试创建的应用、数据库和临时资源。"""
        self.server.stop()
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def test_scene_suite_stops_and_writes_history_details(self):
        """验证场景集合失败后会停止执行并写入历史明细。"""
        suite_id = self._create_suite("scene suite", "scene", [self.ok_case_id, self.fail_case_id, self.second_ok_case_id])

        response = self.client.post(
            "/api/test-suite/execute",
            json={"suite_id": suite_id, "environment_id": self.environment_id},
        )

        result = response.json["data"]
        self.assertEqual(response.status_code, 200)
        self.assertTrue(result["interrupted"])
        self.assertEqual(result["total_count"], 3)
        self.assertEqual(result["success_count"], 1)
        self.assertEqual(result["fail_count"], 1)
        statuses = [item["status"] for item in result["details"]]
        self.assertEqual(statuses, ["pass", "fail", "skipped"])
        self.assertIn("request_snapshot", result["details"][0])
        self.assertIn("response_snapshot", result["details"][0])
        self.assertIn("assertions_detail", result["details"][0])
        self.assertEqual(result["details"][0]["request_snapshot"]["url"], self.server.url + "/ok")
        self.assertEqual(result["details"][0]["response_snapshot"]["status_code"], 200)
        self.assertEqual(ExecutionHistory.query.count(), 1)
        self.assertEqual(ExecutionDetail.query.count(), 3)
        history = ExecutionHistory.query.first()
        history_response = self.client.post(
            "/api/test-suite/execution-history-detail",
            json={"history_id": history.id},
        )
        self.assertEqual(history_response.status_code, 200)
        history_detail = history_response.json["data"]["details"][0]
        self.assertEqual(history_detail["request_snapshot"]["url"], self.server.url + "/ok")
        self.assertEqual(history_detail["response_snapshot"]["status_code"], 200)
        self.assertTrue(history_detail["assertions_detail"])
        self.assertIn("失败断言", history.report_html)
        self.assertIn("实际值", history.report_html)
        self.assertIn("期望值", history.report_html)
        report_page = self.client.get("/reports/%s" % history.id)
        self.assertEqual(report_page.status_code, 200)
        self.assertIn("fail case", report_page.data.decode("utf-8"))

    def test_single_suite_continues_after_failure(self):
        """验证单接口集合在步骤失败后按配置继续执行。"""
        suite_id = self._create_suite("single suite", "single", [self.fail_case_id, self.second_ok_case_id])

        response = self.client.post(
            "/api/test-suite/execute",
            json={"suite_id": suite_id, "environment_id": self.environment_id},
        )

        result = response.json["data"]
        self.assertFalse(result["interrupted"])
        self.assertEqual(result["total_count"], 2)
        self.assertEqual(result["success_count"], 1)
        self.assertEqual(result["fail_count"], 1)
        self.assertEqual([item["status"] for item in result["details"]], ["fail", "pass"])

    def test_suite_save_persists_default_environment(self):
        """验证保存集合时会持久化默认执行环境。"""
        other_environment_id = self.client.post(
            "/api/execution-environment/create",
            json={"name": "staging", "base_url": self.server.url},
        ).json["data"]["id"]
        suite_id = self._create_suite(
            "environment suite",
            "single",
            [self.ok_case_id],
            environment_id=self.environment_id,
        )

        detail_response = self.client.post(
            "/api/test-suite/detail",
            json={"suite_id": suite_id},
        )
        update_response = self.client.post(
            "/api/test-suite/save",
            json={
                "suite_id": suite_id,
                "project_id": self.project_id,
                "environment_id": other_environment_id,
                "name": "environment suite",
                "suite_type": "single",
                "steps": [{"case_id": self.ok_case_id, "is_active": True}],
            },
        )
        updated_detail_response = self.client.post(
            "/api/test-suite/detail",
            json={"suite_id": suite_id},
        )

        self.assertEqual(detail_response.json["data"]["environment_id"], self.environment_id)
        self.assertEqual(update_response.status_code, 200)
        self.assertEqual(updated_detail_response.json["data"]["environment_id"], other_environment_id)
        self.assertEqual(updated_detail_response.json["data"]["environment_name"], "staging")

    def test_extracted_runtime_variable_can_be_used_by_next_case(self):
        """验证前一步提取的运行变量可被后续用例引用。"""
        login_case_id = self._create_case(
            "login case",
            "ok",
            "200",
            extractors=[
                {
                    "jsonpath": "$.token",
                    "variable_name": "token",
                    "required": True,
                }
            ],
        )
        profile_case_id = self._create_case(
            "profile case",
            "profile",
            "200",
            headers_override={"Authorization": "Bearer ${token}"},
            params_template={"token": "${token}"},
        )
        suite_id = self._create_suite("token suite", "scene", [login_case_id, profile_case_id])

        response = self.client.post(
            "/api/test-suite/execute",
            json={"suite_id": suite_id, "environment_id": self.environment_id},
        )

        result = response.json["data"]
        self.assertEqual(response.status_code, 200)
        self.assertEqual(result["success_count"], 2)
        self.assertEqual(result["runtime_vars"]["token"], "suite-token")
        self.assertEqual([item["status"] for item in result["details"]], ["pass", "pass"])

        profile_detail = ExecutionDetail.query.filter_by(case_id=profile_case_id).first()
        self.assertEqual(profile_detail.request_snapshot["headers"]["Authorization"], "Bearer suite-token")
        self.assertEqual(profile_detail.request_snapshot["params"]["token"], "suite-token")

    def test_suite_step_override_allows_duplicate_case_instances(self):
        """验证集合步骤覆盖配置支持重复引用同一用例。"""
        profile_case_id = self._create_case("profile case", "profile", "401")
        suite_id = self._create_suite(
            "duplicate override suite",
            "single",
            [
                {
                    "case_id": profile_case_id,
                    "step_name": "profile with a",
                    "method": "GET",
                    "url": "{{base_url}}/profile",
                    "body_type": "none",
                    "request_params": {"token": "a"},
                    "headers": {},
                    "body": {},
                    "assertions": [
                        {
                            "source": "status_code",
                            "comparator": "equals",
                            "expected": "401",
                            "value_type": "int",
                        }
                    ],
                    "extractors": [],
                    "ws_steps": [],
                    "timeout_seconds": 3,
                },
                {
                    "case_id": profile_case_id,
                    "step_name": "profile with b",
                    "method": "GET",
                    "url": "{{base_url}}/profile",
                    "body_type": "none",
                    "request_params": {"token": "b"},
                    "headers": {},
                    "body": {},
                    "assertions": [
                        {
                            "source": "status_code",
                            "comparator": "equals",
                            "expected": "401",
                            "value_type": "int",
                        }
                    ],
                    "extractors": [],
                    "ws_steps": [],
                    "timeout_seconds": 3,
                },
            ],
        )

        response = self.client.post(
            "/api/test-suite/execute",
            json={"suite_id": suite_id, "environment_id": self.environment_id},
        )

        result = response.json["data"]
        self.assertEqual(response.status_code, 200)
        self.assertEqual(result["success_count"], 2)
        self.assertEqual([item["case_name"] for item in result["details"]], ["profile with a", "profile with b"])
        self.assertEqual(result["details"][0]["request_snapshot"]["params"]["token"], "a")
        self.assertEqual(result["details"][1]["request_snapshot"]["params"]["token"], "b")
        stored_steps = SuiteCase.query.filter_by(suite_id=suite_id).order_by(
            SuiteCase.sort_order.asc()
        ).all()
        self.assertEqual(stored_steps[0].request_params_override, {"token": "a"})
        self.assertEqual(stored_steps[1].request_params_override, {"token": "b"})

    def test_suite_step_request_line_override_is_used_when_running(self):
        """验证集合执行时会采用步骤覆盖后的请求方法和地址。"""
        suite_id = self._create_suite(
            "request line override suite",
            "single",
            [
                {
                    "case_id": self.ok_case_id,
                    "step_name": "ok case calls profile",
                    "method": "GET",
                    "url": "{{base_url}}/profile",
                    "body_type": "none",
                    "request_params": {"token": "manual"},
                    "headers": {},
                    "body": {},
                    "assertions": [
                        {
                            "source": "status_code",
                            "comparator": "equals",
                            "expected": "401",
                            "value_type": "int",
                        }
                    ],
                    "extractors": [],
                    "ws_steps": [],
                    "timeout_seconds": 3,
                }
            ],
        )

        response = self.client.post(
            "/api/test-suite/execute",
            json={"suite_id": suite_id, "environment_id": self.environment_id},
        )

        result = response.json["data"]
        detail = result["details"][0]
        stored_step = SuiteCase.query.filter_by(suite_id=suite_id).first()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(result["success_count"], 1)
        self.assertEqual(stored_step.url_override, "{{base_url}}/profile")
        self.assertEqual(detail["request_snapshot"]["url"], self.server.url + "/profile")
        self.assertEqual(detail["request_snapshot"]["params"]["token"], "manual")
        self.assertEqual(detail["method"], "GET")

    def test_save_steps_applies_to_next_run_without_changing_suite_environment(self):
        """单独保存步骤后立即生效，且不修改集合默认执行环境。"""
        other_environment_id = self.client.post(
            "/api/execution-environment/create",
            json={"name": "manual-run", "base_url": self.server.url},
        ).json["data"]["id"]
        suite_id = self._create_suite(
            "save steps suite",
            "single",
            [self.ok_case_id],
            environment_id=self.environment_id,
        )

        save_response = self.client.post(
            "/api/test-suite/save-steps",
            json={
                "suite_id": suite_id,
                "steps": [
                    {
                        "case_id": self.ok_case_id,
                        "step_name": "updated profile step",
                        "method": "GET",
                        "url": "{{base_url}}/profile",
                        "body_type": "none",
                        "request_params": {"token": "changed-token"},
                        "headers": {},
                        "body": {},
                        "assertions": [
                            {
                                "source": "status_code",
                                "comparator": "equals",
                                "expected": "401",
                                "value_type": "int",
                            }
                        ],
                        "extractors": [],
                        "ws_steps": [],
                        "timeout_seconds": 3,
                    }
                ],
            },
        )
        run_response = self.client.post(
            "/api/test-suite/execute",
            json={"suite_id": suite_id, "environment_id": other_environment_id},
        )
        detail_response = self.client.post(
            "/api/test-suite/detail",
            json={"suite_id": suite_id},
        )

        self.assertEqual(save_response.status_code, 200)
        self.assertEqual(run_response.status_code, 200)
        self.assertEqual(run_response.json["data"]["success_count"], 1)
        detail = run_response.json["data"]["details"][0]
        self.assertEqual(detail["request_snapshot"]["params"]["token"], "changed-token")
        self.assertEqual(detail["request_snapshot"]["url"], self.server.url + "/profile")
        self.assertEqual(detail_response.json["data"]["environment_id"], self.environment_id)
        self.assertEqual(detail_response.json["data"]["steps"][0]["step_name"], "updated profile step")

    def test_suite_step_same_config_does_not_persist_override_fields(self):
        """验证步骤配置未变化时不会保存多余的覆盖字段。"""
        suite_id = self._create_suite(
            "inherit suite",
            "single",
            [
                {
                    "case_id": self.ok_case_id,
                    "method": "GET",
                    "url": "{{base_url}}/ok",
                    "body_type": "none",
                    "request_params": {},
                    "headers": {},
                    "body": {},
                    "assertions": [
                        {
                            "source": "status_code",
                            "comparator": "equals",
                            "expected": "200",
                            "value_type": "int",
                        }
                    ],
                    "extractors": [],
                    "ws_steps": [],
                    "timeout_seconds": 3,
                }
            ],
        )

        stored_step = SuiteCase.query.filter_by(suite_id=suite_id).first()

        self.assertIsNone(stored_step.method_override)
        self.assertIsNone(stored_step.url_override)
        self.assertIsNone(stored_step.body_type_override)
        self.assertIsNone(stored_step.request_params_override)
        self.assertIsNone(stored_step.headers_override)
        self.assertIsNone(stored_step.body_override)
        self.assertIsNone(stored_step.assertions_override)
        self.assertIsNone(stored_step.extractors_override)
        self.assertIsNone(stored_step.ws_steps_override)
        self.assertIsNone(stored_step.timeout_seconds_override)

    def _create_case(
        self,
        name,
        path,
        expected_status,
        extractors=None,
        headers_override=None,
        params_template=None,
    ):
        """创建场景集合测试所需的接口用例。"""
        interface_id = self.client.post(
            "/api/interface-definition/create",
            json={
                "project_id": self.project_id,
                "name": "%s interface" % name,
                "interface_type": "http",
                "method": "GET",
                "url": "{{base_url}}/%s" % path,
                "headers_template": "{}",
                "params_template": params_template or {},
                "body_template": "{}",
                "body_type": "none",
            },
        ).json["data"]["id"]
        return self.client.post(
            "/api/test-case/create",
            json={
                "project_id": self.project_id,
                "interface_id": interface_id,
                "name": name,
                "assertions": [
                    {
                        "source": "status_code",
                        "comparator": "equals",
                        "expected": expected_status,
                        "value_type": "int",
                    }
                ],
                "headers_override": headers_override or {},
                "extractors": extractors or [],
                "timeout_seconds": 3,
            },
        ).json["data"]["id"]

    def _create_suite(self, name, suite_type, steps, environment_id=None):
        """创建包含指定步骤的测试场景集合。"""
        normalized_steps = [
            step if isinstance(step, dict) else {"case_id": step, "is_active": True}
            for step in steps
        ]
        return self.client.post(
            "/api/test-suite/create",
            json={
                "project_id": self.project_id,
                "environment_id": environment_id or self.environment_id,
                "name": name,
                "suite_type": suite_type,
                "steps": normalized_steps,
            },
        ).json["data"]["id"]


if __name__ == "__main__":
    unittest.main()
