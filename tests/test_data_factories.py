# -*- coding: utf-8 -*-
"""
@Author: byy
@Desc: 数据工厂测试，验证配置、变量、并发执行、断言和页面交互。
"""

import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler
from http.server import HTTPServer

from app import create_app
from app.extensions import db
from app.services.hook_functions import execute_hook_function


class _FactoryHandler(BaseHTTPRequestHandler):
    """为数据工厂依赖传参测试提供本地 HTTP 接口。"""

    sequence = 0

    def do_POST(self):
        """创建接口返回 ID，消费接口回显上一接口传入的 ID。"""
        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
        if self.path == "/create":
            type(self).sequence += 1
            body = {"data": {"id": type(self).sequence}}
        elif self.path == "/consume":
            body = {"accepted": payload.get("user_id")}
        elif self.path == "/large":
            body = {"payload": "x" * 70000}
        else:
            self.send_response(404)
            self.end_headers()
            return
        content = json.dumps(body).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def log_message(self, format, *args):
        """关闭测试 HTTP 服务日志。"""
        return


class _FactoryServer(object):
    """在测试期间管理本地 HTTP 服务线程。"""

    def __init__(self):
        """初始化数据工厂测试使用的临时服务。"""
        self.server = HTTPServer(("127.0.0.1", 0), _FactoryHandler)
        self.base_url = "http://127.0.0.1:%s" % self.server.server_port
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def start(self):
        """启动本地 HTTP 服务。"""
        _FactoryHandler.sequence = 0
        self.thread.start()

    def stop(self):
        """关闭本地 HTTP 服务。"""
        self.server.shutdown()
        self.thread.join(timeout=2)
        self.server.server_close()


class DataFactoryTestCase(unittest.TestCase):
    """验证数据工厂配置、分组接口和依赖执行。"""

    def setUp(self):
        """为当前测试准备独立的应用、数据库和依赖资源。"""
        self.app = create_app("testing")
        self.context = self.app.app_context()
        self.context.push()
        db.create_all()
        self.client = self.app.test_client()

    def tearDown(self):
        """清理当前测试创建的应用、数据库和临时资源。"""
        db.session.remove()
        db.drop_all()
        self.context.pop()

    def create_environment(self, name="数据工厂环境", base_url="http://example.test"):
        """创建测试使用的执行环境。"""
        response = self.client.post(
            "/api/execution-environment/create",
            json={"name": name, "base_url": base_url},
        )
        return response.json["data"]["id"]

    def create_project(self, name="数据工厂项目"):
        """创建带两个模块的项目。"""
        response = self.client.post(
            "/api/project/create",
            json={
                "name": name,
                "modules": [
                    {"name": "用户模块", "_delete": False},
                    {"name": "订单模块", "_delete": False},
                ],
            },
        )
        return response.json["data"]

    def create_interface(self, project_id, module_id, name, url):
        """创建可被数据工厂引用的 HTTP 接口。"""
        response = self.client.post(
            "/api/interface-definition/create",
            json={
                "project_id": project_id,
                "module_id": module_id,
                "name": name,
                "interface_type": "http",
                "method": "POST",
                "url": url,
                "body_type": "json",
                "params_template": {},
                "headers_template": {"X-Source": "interface"},
                "body_template": {"name": "factory"},
            },
        )
        self.assertEqual(response.status_code, 200)
        return response.json["data"]

    def test_project_is_optional_and_interface_options_are_grouped(self):
        """独立工厂可使用自定义 URL，接口库选项按模块返回。"""
        environment_id = self.create_environment()
        independent = self.client.post(
            "/api/data-factory/create",
            json={
                "name": "独立造数",
                "project_id": None,
                "environment_id": environment_id,
                "description": "",
                "steps": [
                    {
                        "step_type": "request",
                        "source_type": "custom",
                        "name": "创建数据",
                        "method": "POST",
                        "url": "http://example.test/create",
                        "body_type": "json",
                        "params": {},
                        "headers": {},
                        "body": {},
                    }
                ],
            },
        )
        self.assertEqual(independent.status_code, 200)
        self.assertIsNone(independent.json["data"]["project_id"])
        self.assertEqual(independent.json["data"]["description"], "")

        project = self.create_project()
        modules = {item["name"]: item for item in project["modules"]}
        self.create_interface(
            project["id"], modules["用户模块"]["id"], "创建用户", "/users"
        )
        self.create_interface(
            project["id"], modules["订单模块"]["id"], "创建订单", "/orders"
        )
        groups = self.client.post(
            "/api/data-factory/interface-options",
            json={"project_id": project["id"]},
        )
        self.assertEqual(groups.status_code, 200)
        self.assertEqual(
            {item["module_name"] for item in groups.json["data"]},
            {"用户模块", "订单模块"},
        )
        self.assertEqual(
            {item["interfaces"][0]["name"] for item in groups.json["data"]},
            {"创建用户", "创建订单"},
        )

    def test_interface_reference_requires_project_and_follows_library_changes(self):
        """接口引用必须属于项目，未覆盖字段跟随接口库更新。"""
        environment_id = self.create_environment()
        project = self.create_project("引用项目")
        module = project["modules"][0]
        interface = self.create_interface(
            project["id"], module["id"], "引用接口", "/old-url"
        )
        invalid = self.client.post(
            "/api/data-factory/create",
            json={
                "name": "非法引用",
                "environment_id": environment_id,
                "steps": [
                    {
                        "step_type": "request",
                        "source_type": "interface",
                        "interface_id": interface["id"],
                        "name": interface["name"],
                    }
                ],
            },
        )
        self.assertEqual(invalid.status_code, 400)
        self.assertIn("未选择所属项目", invalid.json["message"])

        created = self.client.post(
            "/api/data-factory/create",
            json={
                "name": "接口引用工厂",
                "project_id": project["id"],
                "environment_id": environment_id,
                "steps": [
                    {
                        "step_type": "request",
                        "source_type": "interface",
                        "interface_id": interface["id"],
                        "name": interface["name"],
                        "method": interface["method"],
                        "url": interface["url"],
                        "body_type": interface["body_type"],
                        "params": interface["params_template"],
                        "headers": interface["headers_template"],
                        "body": interface["body_template"],
                    }
                ],
            },
        )
        self.assertEqual(created.status_code, 200)
        factory_id = created.json["data"]["id"]

        interface.update({"interface_id": interface["id"], "url": "/new-url"})
        saved_interface = self.client.post(
            "/api/interface-definition/save",
            json=interface,
        )
        self.assertEqual(saved_interface.status_code, 200)
        detail = self.client.post(
            "/api/data-factory/detail",
            json={"factory_id": factory_id},
        ).json["data"]
        self.assertEqual(detail["steps"][0]["url"], "/new-url")

    def test_multiple_requests_share_extractors_and_each_iteration_is_isolated(self):
        """每轮串行依赖传参，且不同轮次的运行时变量相互隔离。"""
        server = _FactoryServer()
        server.start()
        try:
            environment_id = self.create_environment("依赖环境", server.base_url)
            created = self.client.post(
                "/api/data-factory/create",
                json={
                    "name": "用户依赖造数",
                    "environment_id": environment_id,
                    "default_loop_count": 2,
                    "steps": [
                        {
                            "step_type": "request",
                            "source_type": "custom",
                            "name": "创建用户",
                            "method": "POST",
                            "url": "/create",
                            "body_type": "json",
                            "params": {},
                            "headers": {"Authorization": "secret-token"},
                            "body": {"name": "${random_string(8)}"},
                            "extractors": [
                                {
                                    "variable_name": "user_id",
                                    "jsonpath": "$.data.id",
                                    "required": True,
                                }
                            ],
                        },
                        {
                            "step_type": "wait",
                            "name": "等待依赖数据",
                            "wait_seconds": 0.1,
                        },
                        {
                            "step_type": "request",
                            "source_type": "custom",
                            "name": "消费用户",
                            "method": "POST",
                            "url": "/consume",
                            "body_type": "json",
                            "params": {},
                            "headers": {},
                            "body": {"user_id": "${user_id}"},
                            "extractors": [
                                {
                                    "variable_name": "accepted_id",
                                    "jsonpath": "$.accepted",
                                    "required": True,
                                }
                            ],
                        },
                    ],
                },
            )
            self.assertEqual(created.status_code, 200)
            executed = self.client.post(
                "/api/data-factory/execute",
                json={"factory_id": created.json["data"]["id"], "loop_count": 2},
            )
            self.assertEqual(executed.status_code, 200)
            run_id = executed.json["data"]["run_id"]
            result = self.client.post(
                "/api/data-factory/run/detail",
                json={"run_id": run_id},
            ).json["data"]
            self.assertEqual(result["run"]["status"], "success")
            self.assertEqual(result["run"]["completed_request_count"], 4)
            self.assertEqual(result["run"]["success_iteration_count"], 2)
            iterations = result["iterations"]
            self.assertEqual(len(iterations[0]["details"]), 3)
            self.assertEqual(iterations[0]["details"][1]["step_type"], "wait")
            self.assertEqual(iterations[0]["details"][1]["status"], "pass")
            self.assertNotIn("output_variables", iterations[0])
            self.assertEqual(
                [item["details"][2]["request_snapshot"]["body"]["user_id"] for item in iterations],
                ["1", "2"],
            )
            self.assertEqual(
                iterations[0]["details"][0]["request_snapshot"]["headers"]["Authorization"],
                "******",
            )
        finally:
            server.stop()

    def test_pages_use_graphical_steps_and_structured_assertions(self):
        """编辑页使用图形步骤、结构化断言和底部生成参数。"""
        list_html = self.client.get("/data-factories/").get_data(as_text=True)
        edit_html = self.client.get("/data-factories/new").get_data(as_text=True)
        run_html = self.client.get("/data-factories/runs/1").get_data(as_text=True)
        with open("app/static/js/data_factory_edit.js", encoding="utf-8") as stream:
            edit_script = stream.read()
        self.assertIn("数据工厂", list_html)
        self.assertIn("独立工厂", list_html)
        self.assertIn("生成流程", edit_html)
        self.assertIn("步骤配置", edit_html)
        self.assertIn("生成次数", edit_html)
        self.assertIn("不选择项目（仅自定义 URL）", edit_html)
        self.assertIn("描述/备注", edit_html)
        self.assertIn("响应提取", edit_script)
        self.assertIn("断言", edit_script)
        self.assertIn("＋等待步骤", edit_script)
        self.assertIn("debugResultCache", edit_script)
        self.assertIn("fillJsonpathFromPicker", edit_script)
        self.assertIn("step._tab === 'assertions'", edit_script)
        self.assertIn("step._tab !== 'extractors'", edit_script)
        self.assertIn("Query 参数", run_html)
        self.assertIn("请求头", run_html)
        self.assertIn("响应正文", run_html)
        self.assertIn("断言名称", run_html)
        self.assertIn("HTTP ", run_html)
        self.assertIn("snapshot-section-arrow", run_html)
        self.assertIn("collapsedSectionState", run_html)
        self.assertIn("activeTabByDetail", run_html)
        self.assertNotIn("初始运行变量", edit_html)
        self.assertNotIn("每轮间隔", edit_html + list_html + edit_script)
        self.assertNotIn("启用本接口", edit_html + edit_script)
        self.assertNotIn("高级断言", edit_html + edit_script)
        self.assertNotIn("最终输出：", run_html)
        self.assertNotIn("导出结果", run_html)
        self.assertNotIn("最终输出", edit_script)
        self.assertNotIn("snapshot-summary-item", run_html)
        self.assertEqual(
            self.client.get("/api/data-factory/run/export?run_id=1").status_code,
            404,
        )

    def test_assertions_use_strong_types_and_response_body_is_complete(self):
        """步骤断言执行强类型比较，运行详情保存完整响应正文。"""
        server = _FactoryServer()
        server.start()
        try:
            environment_id = self.create_environment("断言环境", server.base_url)
            created = self.client.post(
                "/api/data-factory/create",
                json={
                    "name": "强类型断言工厂",
                    "environment_id": environment_id,
                    "steps": [
                        {
                            "step_type": "request",
                            "source_type": "custom",
                            "name": "大响应",
                            "method": "POST",
                            "url": "/large",
                            "body_type": "json",
                            "params": {},
                            "headers": {},
                            "body": {},
                            "assertions": [
                                {
                                    "name": "响应长度错误类型",
                                    "source": "body_length",
                                    "comparator": "equals",
                                    "value_type": "string",
                                    "expected": "70015",
                                }
                            ],
                        }
                    ],
                },
            )
            self.assertEqual(created.status_code, 200)
            executed = self.client.post(
                "/api/data-factory/execute",
                json={"factory_id": created.json["data"]["id"]},
            )
            run_id = executed.json["data"]["run_id"]
            result = self.client.post(
                "/api/data-factory/run/detail",
                json={"run_id": run_id},
            ).json["data"]
            detail = result["iterations"][0]["details"][0]
            self.assertEqual(result["run"]["status"], "failed")
            self.assertFalse(detail["assertions_detail"][1]["passed"])
            self.assertNotIn("[truncated]", detail["response_snapshot"]["body"])
            self.assertGreater(len(detail["response_snapshot"]["body"]), 65536)
        finally:
            server.stop()

    def test_data_generation_hook_functions(self):
        """数据工厂所需基础随机函数可以由后端变量引擎执行。"""
        self.assertEqual(len(execute_hook_function("uuid", [])), 32)
        self.assertTrue(1000 <= execute_hook_function("random_int", [1000, 1001]) <= 1001)
        self.assertEqual(len(execute_hook_function("random_string", [12])), 12)
        self.assertEqual(len(execute_hook_function("random_mobile", [])), 11)


if __name__ == "__main__":
    unittest.main()
