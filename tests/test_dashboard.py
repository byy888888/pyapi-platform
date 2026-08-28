# -*- coding: utf-8 -*-
"""
@Author: byy
@Desc: 仪表盘测试，验证资源统计、定时任务筛选和趋势数据。
"""

from datetime import datetime
from datetime import time
from datetime import timedelta
import re
from typing import List
import unittest

from app import create_app
from app.enums import BodyType
from app.enums import DetailStatus
from app.enums import HistoryStatus
from app.enums import InterfaceType
from app.enums import SuiteType
from app.enums import TriggerType
from app.extensions import db
from app.models import Environment
from app.models import ExecutionDetail
from app.models import ExecutionHistory
from app.models import Interface
from app.models import Project
from app.models import ProjectModule
from app.models import Suite
from app.models import TestCase
from app.utils.datetime_utils import now_local


class DashboardApiTestCase(unittest.TestCase):
    """验证仪表盘资源和定时任务执行统计。"""

    def setUp(self):
        """创建两个项目及手动、定时执行样本。"""
        self.app = create_app("testing")
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.create_all()
        self.client = self.app.test_client()
        self.environment = Environment(name="测试环境", base_url="http://test")
        db.session.add(self.environment)

        self.first_project = Project(name="商城项目")
        self.second_project = Project(name="会员项目")
        db.session.add_all([self.first_project, self.second_project])
        db.session.flush()

        first_interfaces = self.create_project_resources(
            self.first_project,
            interface_count=2,
            suite_count=2,
        )
        second_interfaces = self.create_project_resources(
            self.second_project,
            interface_count=1,
            suite_count=1,
        )
        db.session.flush()

        first_suites = Suite.query.filter_by(
            project_id=self.first_project.id
        ).order_by(Suite.id.asc()).all()
        second_suite = Suite.query.filter_by(
            project_id=self.second_project.id
        ).first()
        today = datetime.combine(now_local().date(), time(hour=10))
        self.create_history(
            first_suites[0],
            first_interfaces[0],
            TriggerType.SCHEDULED,
            today,
            [DetailStatus.PASS, DetailStatus.FAIL],
        )
        self.create_history(
            first_suites[1],
            first_interfaces[1],
            TriggerType.SCHEDULED,
            today - timedelta(days=1),
            [DetailStatus.ERROR, DetailStatus.SKIPPED],
        )
        self.create_history(
            first_suites[0],
            first_interfaces[0],
            TriggerType.MANUAL,
            today,
            [DetailStatus.PASS],
        )
        self.create_history(
            second_suite,
            second_interfaces[0],
            TriggerType.SCHEDULED,
            today,
            [DetailStatus.PASS],
        )
        db.session.commit()

    def tearDown(self):
        """清理测试数据库。"""
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def create_project_resources(
        self,
        project: Project,
        interface_count: int,
        suite_count: int,
    ) -> List[Interface]:
        """为项目创建等量用例和指定数量集合。"""
        module = ProjectModule(project=project, name="默认模块")
        db.session.add(module)
        interfaces = []
        for index in range(interface_count):
            interface = Interface(
                module=module,
                name="接口%s" % index,
                interface_type=InterfaceType.HTTP,
                method="GET",
                url="/api/%s" % index,
                params_template={},
                headers_template={},
                body_template={},
                body_type=BodyType.NONE,
            )
            db.session.add(interface)
            db.session.add(TestCase(interface=interface, name="用例%s" % index))
            interfaces.append(interface)
        for index in range(suite_count):
            db.session.add(
                Suite(
                    project=project,
                    environment=self.environment,
                    name="集合%s" % index,
                    suite_type=SuiteType.SINGLE,
                )
            )
        return interfaces

    def create_history(
        self,
        suite: Suite,
        interface: Interface,
        trigger_type: str,
        start_time: datetime,
        statuses: List[str],
    ) -> None:
        """创建一条执行历史及其用例步骤明细。"""
        history = ExecutionHistory(
            task_name="每日回归",
            trigger_type=trigger_type,
            environment=self.environment,
            start_time=start_time,
            end_time=start_time,
            status=HistoryStatus.FINISHED,
            total_count=len(statuses),
            success_count=statuses.count(DetailStatus.PASS),
            fail_count=statuses.count(DetailStatus.FAIL),
            error_count=statuses.count(DetailStatus.ERROR),
            summary={"suite_id": suite.id},
        )
        db.session.add(history)
        db.session.flush()
        for index, status in enumerate(statuses):
            db.session.add(
                ExecutionDetail(
                    history=history,
                    suite_id=suite.id,
                    suite_name=suite.name,
                    interface_id=interface.id,
                    interface_name=interface.name,
                    interface_type=InterfaceType.HTTP,
                    method="GET",
                    url=interface.url,
                    status=status,
                    request_snapshot={},
                    response_snapshot={},
                    assertions_detail=[],
                    extractors_detail=[],
                    ws_messages=[],
                    sort_order=index,
                )
            )

    def test_statistics_scope_excludes_manual_and_other_projects(self):
        """指定项目只统计该项目的定时任务执行明细。"""
        response = self.client.post(
            "/api/dashboard/statistics",
            json={"project_id": self.first_project.id, "days": 7},
        )

        self.assertEqual(response.status_code, 200)
        data = response.json["data"]
        self.assertEqual(
            data["metrics"],
            {
                "project_count": 1,
                "interface_count": 2,
                "case_count": 2,
                "suite_count": 2,
                "report_count": 2,
            },
        )
        self.assertEqual(
            data["distribution"],
            {
                "pass": 1,
                "fail": 1,
                "error": 1,
                "skipped": 1,
                "total": 4,
                "pass_rate": 25.0,
            },
        )
        self.assertEqual(len(data["trend"]), 7)
        today_item = next(
            item
            for item in data["trend"]
            if item["date"] == now_local().date().isoformat()
        )
        self.assertEqual(today_item["pass"], 1)
        self.assertEqual(today_item["fail"], 1)
        self.assertEqual(data["scope"]["trigger_type"], TriggerType.SCHEDULED)

    def test_all_projects_statistics_and_zero_filled_dates(self):
        """全部项目统计资源总数，并为无执行日期补零。"""
        response = self.client.post(
            "/api/dashboard/statistics",
            json={"days": 14},
        )

        self.assertEqual(response.status_code, 200)
        data = response.json["data"]
        self.assertEqual(data["metrics"]["project_count"], 2)
        self.assertEqual(data["metrics"]["interface_count"], 3)
        self.assertEqual(data["metrics"]["case_count"], 3)
        self.assertEqual(data["metrics"]["suite_count"], 3)
        self.assertEqual(data["metrics"]["report_count"], 3)
        self.assertEqual(data["distribution"]["pass"], 2)
        self.assertEqual(len(data["trend"]), 14)
        self.assertTrue(
            any(
                sum(item[status] for status in DetailStatus.VALUES) == 0
                for item in data["trend"]
            )
        )

    def test_statistics_reject_invalid_filters(self):
        """统计接口拒绝不存在项目和不支持的周期。"""
        missing_project = self.client.post(
            "/api/dashboard/statistics",
            json={"project_id": 999999, "days": 14},
        )
        invalid_days = self.client.post(
            "/api/dashboard/statistics",
            json={"days": 15},
        )

        self.assertEqual(missing_project.status_code, 400)
        self.assertIn("统计项目不存在", missing_project.json["message"])
        self.assertEqual(invalid_days.status_code, 400)
        self.assertIn("仅支持 7、14 或 30 天", invalid_days.json["message"])

    def test_dashboard_page_renders_statistics_controls_and_charts(self):
        """仪表盘包含统计控件、图表以及完整日期标签逻辑。"""
        html = self.client.get("/").get_data(as_text=True)
        script_response = self.client.get("/static/js/dashboard.js")
        script = script_response.get_data(as_text=True)
        script_response.close()

        self.assertIn('id="dashboardProjectFilter"', html)
        self.assertIn('id="suiteMetric"', html)
        self.assertIn('id="trendChart"', html)
        self.assertIn('id="resultDonut"', html)
        self.assertIn("仅统计定时任务", html)
        self.assertIn("/static/js/dashboard.js", html)
        self.assertIn("items.length * minimumSlotWidth", script)
        self.assertIn("rotate(-45", script)
        self.assertNotIn("dashboardTrendLabelStep", script)
        self.assertNotIn("index % labelStep", script)

    def test_navigation_uses_confirmed_names_and_order(self):
        """公共左侧导航按确认后的业务名称和顺序展示。"""
        html = self.client.get("/").get_data(as_text=True)
        labels = re.findall(
            r'<a class="side-link[^"]*"[^>]*>([^<]+)</a>',
            html,
        )

        self.assertEqual(
            labels,
            [
                "仪表盘",
                "接口库",
                "接口用例",
                "场景集合",
                "数据工厂",
                "测试报告",
                "通知管理",
                "任务管理",
                "项目管理",
                "环境与变量管理",
            ],
        )
