# -*- coding: utf-8 -*-
"""
@Author: byy
@Desc: 定时任务与通知测试，验证调度上下文、环境选择和报告通知。
"""

import json
import threading
from typing import Any
from typing import Dict
import unittest
from http.server import BaseHTTPRequestHandler
from http.server import HTTPServer
from unittest.mock import patch

from flask import has_app_context

from app import create_app
from app.enums import TriggerType
from app.extensions import db
from app.models import ExecutionHistory
from app.models import Notification
from app.models import ScheduledTask
from app.models import TaskNotification
from app.models import TaskSuite
from app.services.scheduler_service import execute_scheduled_task
from app.services.scheduler_service import execute_task


class _OkHandler(BaseHTTPRequestHandler):
    """为定时任务测试提供成功响应的 HTTP 请求处理器。"""
    def do_GET(self):
        """处理测试服务收到的 GET 请求并返回预设数据。"""
        body = json.dumps({"ok": True}).encode("utf-8")
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
        self.server = HTTPServer(("127.0.0.1", 0), _OkHandler)
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


class _FakeDingTalkResponse(object):
    """模拟钉钉机器人接口返回的响应对象。"""
    def raise_for_status(self):
        """模拟正常响应，不抛出 HTTP 状态异常。"""
        return None

    def json(self):
        """返回模拟钉钉接口的 JSON 响应内容。"""
        return {"errcode": 0, "errmsg": "ok"}


class TaskNotificationTestCase(unittest.TestCase):
    """集中验证定时任务、集合执行和通知发送流程。"""
    def setUp(self):
        """为当前测试准备独立的应用、数据库和依赖资源。"""
        self.app = create_app("testing")
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.create_all()
        self.client = self.app.test_client()
        self.server = _HttpServerThread()
        self.server.start()

    def tearDown(self):
        """清理当前测试创建的应用、数据库和临时资源。"""
        self.server.stop()
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def test_task_can_bind_suite_notification_and_send_report_link(self):
        """验证定时任务可绑定集合和通知并发送报告链接。"""
        project_id = self.client.post("/api/project/create", json={"name": "Demo"}).json["data"]["id"]
        environment_id = self.client.post(
            "/api/execution-environment/create",
            json={"name": "test", "base_url": self.server.url},
        ).json["data"]["id"]
        interface_id = self.client.post(
            "/api/interface-definition/create",
            json={
                "project_id": project_id,
                "name": "ok",
                "interface_type": "http",
                "method": "GET",
                "url": "{{base_url}}/ok",
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
                "name": "ok case",
                "assertions": [
                    {
                        "source": "status_code",
                        "comparator": "equals",
                        "expected": "200",
                        "value_type": "int",
                    }
                ],
            },
        ).json["data"]["id"]
        suite_id = self.client.post(
            "/api/test-suite/create",
            json={
                "project_id": project_id,
                "environment_id": environment_id,
                "name": "smoke",
                "suite_type": "single",
                "steps": [{"case_id": case_id, "is_active": True}],
            },
        ).json["data"]["id"]
        notification_id = self.client.post(
            "/api/notification-channel/create",
            json={
                "name": "ding",
                "notification_type": "dingtalk",
                "config": {"webhook": "http://dingtalk.invalid/robot"},
                "message_template": "任务 {task_name} 报告 {report_links}",
                "is_active": True,
            },
        ).json["data"]["id"]
        task_id = self.client.post(
            "/api/scheduled-task/create",
            json={
                "name": "scheduled smoke",
                "environment_type": "testing",
                "schedule_type": "interval",
                "interval_seconds": 300,
                "suite_ids": [suite_id],
                "notification_ids": [notification_id],
                "enabled": True,
            },
        ).json["data"]["id"]

        sent_payloads = []

        def fake_post(url, json=None, timeout=None):
            """模拟通知服务的 HTTP POST 请求并记录调用参数。"""
            sent_payloads.append(json)
            return _FakeDingTalkResponse()

        with patch("app.services.notifier.requests.post", side_effect=fake_post):
            response = self.client.post("/api/scheduled-task/execute", json={"task_id": task_id})
            execute_task(task_id, TriggerType.SCHEDULED)

        result = response.json["data"]
        self.assertEqual(response.status_code, 200)
        self.assertEqual(result["total_count"], 1)
        self.assertEqual(result["success_count"], 1)
        self.assertTrue(result["report_links"])
        self.assertTrue(result["notifications"][0]["success"])
        self.assertEqual(ScheduledTask.query.count(), 1)
        self.assertEqual(TaskSuite.query.count(), 1)
        self.assertEqual(TaskNotification.query.count(), 1)
        self.assertEqual(Notification.query.count(), 1)
        self.assertIn("/reports/", sent_payloads[0]["markdown"]["text"])
        histories = ExecutionHistory.query.order_by(
            ExecutionHistory.id.asc()
        ).all()
        self.assertEqual(
            [history.trigger_type for history in histories],
            [TriggerType.MANUAL, TriggerType.SCHEDULED],
        )
        dashboard_response = self.client.post(
            "/api/dashboard/statistics",
            json={"project_id": project_id, "days": 7},
        )
        dashboard_data = dashboard_response.json["data"]
        self.assertEqual(dashboard_data["metrics"]["report_count"], 1)
        self.assertEqual(dashboard_data["distribution"]["total"], 1)

    def test_task_runs_each_suite_with_its_own_environment_and_validates_type(self):
        """验证定时任务按集合环境执行并校验环境类型。"""
        project_id = self.client.post("/api/project/create", json={"name": "Env Demo"}).json["data"]["id"]
        testing_environment_id = self.client.post(
            "/api/execution-environment/create",
            json={"name": "testing", "environment_type": "testing", "base_url": self.server.url},
        ).json["data"]["id"]
        staging_environment_id = self.client.post(
            "/api/execution-environment/create",
            json={"name": "staging", "environment_type": "staging", "base_url": self.server.url},
        ).json["data"]["id"]
        interface_id = self.client.post(
            "/api/interface-definition/create",
            json={
                "project_id": project_id,
                "name": "ok",
                "interface_type": "http",
                "method": "GET",
                "url": "{{base_url}}/ok",
                "headers_template": {},
                "body_template": {},
                "body_type": "none",
            },
        ).json["data"]["id"]
        case_id = self.client.post(
            "/api/test-case/create",
            json={"project_id": project_id, "interface_id": interface_id, "name": "ok case"},
        ).json["data"]["id"]

        def create_suite(name, environment_id):
            """创建定时任务测试所需的场景集合。"""
            return self.client.post(
                "/api/test-suite/create",
                json={
                    "project_id": project_id,
                    "environment_id": environment_id,
                    "name": name,
                    "suite_type": "single",
                    "steps": [{"case_id": case_id, "is_active": True}],
                },
            ).json["data"]["id"]

        testing_suite_id = create_suite("testing suite", testing_environment_id)
        staging_suite_id = create_suite("staging suite", staging_environment_id)
        invalid_response = self.client.post(
            "/api/scheduled-task/create",
            json={
                "name": "invalid task",
                "environment_type": "testing",
                "schedule_type": "interval",
                "interval_seconds": 60,
                "suite_ids": [staging_suite_id],
            },
        )
        self.assertEqual(invalid_response.status_code, 400)
        self.assertIn("环境类型", invalid_response.json["message"])

        task_id = self.client.post(
            "/api/scheduled-task/create",
            json={
                "name": "testing task",
                "environment_type": "testing",
                "schedule_type": "interval",
                "interval_seconds": 60,
                "suite_ids": [testing_suite_id],
            },
        ).json["data"]["id"]
        response = self.client.post("/api/scheduled-task/execute", json={"task_id": task_id})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["data"]["total_count"], 1)
        history = ScheduledTask.query.get(task_id).execution_histories[0]
        self.assertEqual(history.environment_id, testing_environment_id)

    def test_task_list_supports_name_and_environment_type_filter(self):
        """验证任务列表支持按名称和环境类型筛选。"""
        project_id = self.client.post("/api/project/create", json={"name": "Search Demo"}).json["data"]["id"]
        environment_id = self.client.post(
            "/api/execution-environment/create",
            json={"name": "development", "environment_type": "development", "base_url": self.server.url},
        ).json["data"]["id"]
        interface_id = self.client.post(
            "/api/interface-definition/create",
            json={"project_id": project_id, "name": "ok", "interface_type": "http", "method": "GET", "url": "/ok", "body_type": "none"},
        ).json["data"]["id"]
        case_id = self.client.post(
            "/api/test-case/create",
            json={"project_id": project_id, "interface_id": interface_id, "name": "case"},
        ).json["data"]["id"]
        suite_id = self.client.post(
            "/api/test-suite/create",
            json={"project_id": project_id, "environment_id": environment_id, "name": "dev suite", "suite_type": "single", "steps": [{"case_id": case_id}]},
        ).json["data"]["id"]
        self.client.post(
            "/api/scheduled-task/create",
            json={"name": "开发冒烟任务", "environment_type": "development", "schedule_type": "interval", "interval_seconds": 60, "suite_ids": [suite_id]},
        )
        response = self.client.post(
            "/api/scheduled-task/list",
            json={"keyword": "冒烟", "environment_type": "development"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json["data"]), 1)
        self.assertEqual(response.json["data"][0]["environment_type_name"], "开发")

    def test_email_notification_accepts_recipient_string(self):
        """验证邮件通知支持使用字符串形式的收件人列表。"""
        response = self.client.post(
            "/api/notification-channel/create",
            json={
                "name": "mail",
                "notification_type": "email",
                "config": {
                    "mail_server": "smtp.example.com",
                    "mail_port": "465",
                    "recipients": "a@example.com，b@example.com",
                },
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["data"]["config"]["recipients"], ["a@example.com", "b@example.com"])

    def test_email_notification_rejects_invalid_port(self):
        """验证邮件通知会拒绝无效的 SMTP 端口。"""
        response = self.client.post(
            "/api/notification-channel/create",
            json={
                "name": "mail",
                "notification_type": "email",
                "config": {
                    "mail_server": "smtp.example.com",
                    "mail_port": "abc",
                    "recipients": ["a@example.com"],
                },
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json["message"], "邮件端口必须是数字")

    def test_scheduler_status_reports_disabled_testing_scheduler(self):
        """验证测试环境禁用调度器时会返回正确状态。"""
        response = self.client.post("/api/scheduler/status", json={})

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json["data"]["enabled_config"])
        self.assertFalse(response.json["data"]["running"])

    def test_scheduled_task_wrapper_creates_application_context(self):
        """调度器后台线程进入应用上下文并标记为自动执行。"""
        observed = {}
        errors = []

        def fake_execute(task_id: int, trigger_type: str) -> Dict[str, Any]:
            """模拟定时任务执行函数并记录执行结果。"""
            observed["has_app_context"] = has_app_context()
            observed["task_id"] = task_id
            observed["trigger_type"] = trigger_type
            return {"success": True}

        def run_in_background() -> None:
            """在应用上下文中模拟调度器后台执行任务。"""
            try:
                execute_scheduled_task(self.app, 123)
            except Exception as exc:
                errors.append(exc)

        with patch(
            "app.services.scheduler_service.execute_task",
            side_effect=fake_execute,
        ):
            thread = threading.Thread(target=run_in_background)
            thread.start()
            thread.join(timeout=2)

        self.assertFalse(thread.is_alive())
        self.assertEqual(errors, [])
        self.assertTrue(observed["has_app_context"])
        self.assertEqual(observed["task_id"], 123)
        self.assertEqual(observed["trigger_type"], TriggerType.SCHEDULED)


if __name__ == "__main__":
    unittest.main()
