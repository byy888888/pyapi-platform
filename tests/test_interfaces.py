# -*- coding: utf-8 -*-
"""
@Author: byy
@Desc: 接口、项目和用例管理测试，验证归属关系、筛选和页面入口。
"""

import unittest

from sqlalchemy import inspect

from app import create_app
from app.extensions import db


class InterfaceApiTestCase(unittest.TestCase):
    """集中验证接口库、项目和模块相关接口。"""
    def setUp(self):
        """为当前测试准备独立的应用、数据库和依赖资源。"""
        self.app = create_app("testing")
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.create_all()
        self.client = self.app.test_client()

    def tearDown(self):
        """清理当前测试创建的应用、数据库和临时资源。"""
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def create_project(self, name):
        """创建测试项目并返回 ID。"""
        response = self.client.post("/api/project/create", json={"name": name})
        self.assertEqual(response.status_code, 200)
        return response.json["data"]["id"]

    def create_interface(self, project_id, name, url, module_name="会员模块"):
        """创建带模块的测试接口并返回响应数据。"""
        response = self.client.post(
            "/api/interface-definition/create",
            json={
                "project_id": project_id,
                "module_name": module_name,
                "name": name,
                "interface_type": "http",
                "method": "GET",
                "url": url,
                "params_template": {"pageNo": "1"},
                "headers_template": {"Accept": "*/*"},
                "body_template": {},
                "body_type": "none",
                "is_active": True,
            },
        )
        self.assertEqual(response.status_code, 200)
        return response.json["data"]

    def test_interface_can_save_params_template_and_render_edit_pages(self):
        """验证接口参数模板可以保存并在编辑页面正确回显。"""
        project_id = self.client.post("/api/project/create", json={"name": "Demo"}).json["data"]["id"]

        response = self.client.post(
            "/api/interface-definition/create",
            json={
                "project_id": project_id,
                "name": "list users",
                "interface_type": "http",
                "method": "GET",
                "url": "/api/users",
                "params_template": {"pageNo": "1"},
                "headers_template": {"Accept": "*/*"},
                "body_template": {},
                "body_type": "none",
                "is_active": True,
            },
        )

        self.assertEqual(response.status_code, 200)
        interface_id = response.json["data"]["id"]
        detail = self.client.post(
            "/api/interface-definition/detail",
            json={"interface_id": interface_id},
        ).json["data"]
        self.assertEqual(detail["params_template"], {"pageNo": "1"})
        self.assertEqual(self.client.get("/interfaces/new").status_code, 200)
        self.assertEqual(self.client.get("/interfaces/%s/edit" % interface_id).status_code, 200)

    def test_websocket_interface_uses_independent_optional_configuration(self):
        """WebSocket 接口保存独立配置且不会引入 HTTP 请求字段。"""
        project_id = self.create_project("消息中心")
        response = self.client.post(
            "/api/interface-definition/create",
            json={
                "project_id": project_id,
                "module_name": "消息",
                "name": "订单推送",
                "interface_type": "websocket",
                "url": "wss://example.com/ws?token={{token}}",
                "ws_config": {
                    "headers": {},
                    "subprotocols": [],
                    "connect_timeout_ms": 5000,
                    "connect_message": {"enabled": False},
                    "heartbeat": {"enabled": False},
                    "default_message": {"message_type": "json", "content": ""},
                },
                "is_active": True,
            },
        )

        self.assertEqual(response.status_code, 200)
        item = response.json["data"]
        self.assertEqual(item["method"], "WS")
        self.assertEqual(item["params_template"], {})
        self.assertEqual(item["headers_template"], {})
        self.assertFalse(item["ws_config"]["connect_message"]["enabled"])
        self.assertEqual(self.client.get("/interfaces/new/http").status_code, 200)
        ws_page = self.client.get("/interfaces/new/websocket")
        self.assertEqual(ws_page.status_code, 200)
        self.assertIn("连接成功后自动发送消息", ws_page.get_data(as_text=True))

    def test_interface_module_creation_search_and_project_management(self):
        """验证接口模块创建、搜索和项目管理流程。"""
        project_id = self.create_project("商城")
        other_project_id = self.create_project("后台")
        first = self.create_interface(project_id, "会员列表", "/api/member/list", "会员")
        second = self.create_interface(project_id, "会员详情", "/api/member/detail", "会员")
        self.create_interface(project_id, "订单列表", "/api/order/list", "订单")
        self.create_interface(other_project_id, "后台会员", "/api/member/admin", "会员")

        self.assertEqual(first["module_id"], second["module_id"])
        response = self.client.post(
            "/api/interface-definition/list",
            json={
                "project_id": project_id,
                "module_id": first["module_id"],
                "url": "detail",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual([item["name"] for item in response.json["data"]], ["会员详情"])

        response = self.client.post(
            "/api/project-module/save",
            json={"module_id": first["module_id"], "name": "用户中心"},
        )
        self.assertEqual(response.status_code, 200)
        detail = self.client.post(
            "/api/interface-definition/detail",
            json={"interface_id": first["id"]},
        ).json["data"]
        self.assertEqual(detail["module_name"], "用户中心")

        occupied_delete = self.client.post(
            "/api/project-module/delete",
            json={"module_id": first["module_id"]},
        )
        self.assertEqual(occupied_delete.status_code, 409)
        self.assertIn("存在 2 个接口", occupied_delete.json["message"])

        free_module = self.client.post(
            "/api/project-module/create",
            json={"project_id": project_id, "name": "空模块"},
        ).json["data"]
        self.assertEqual(
            self.client.post(
                "/api/project-module/delete",
                json={"module_id": free_module["id"]},
            ).status_code,
            200,
        )

        project_detail = self.client.post(
            "/api/project/detail",
            json={"project_id": project_id},
        ).json["data"]
        self.assertEqual(
            {item["name"] for item in project_detail["modules"]},
            {"用户中心", "订单"},
        )

    def test_interface_case_count_filter_and_prefill_navigation(self):
        """验证接口用例数量、筛选和预填跳转逻辑。"""
        project_id = self.create_project("联动测试")
        item = self.create_interface(project_id, "登录", "/api/login", "认证")
        case_response = self.client.post(
            "/api/test-case/create",
            json={
                "project_id": project_id,
                "interface_id": item["id"],
                "name": "登录成功",
                "request_params": {"from": "interface"},
                "headers_override": {},
                "body_override": {},
                "assertions": [],
                "extractors": [],
                "body_type": "none",
            },
        )
        self.assertEqual(case_response.status_code, 200)

        interface_list = self.client.post(
            "/api/interface-definition/list",
            json={"project_id": project_id},
        ).json["data"]
        self.assertEqual(interface_list[0]["case_count"], 1)
        case_list = self.client.post(
            "/api/test-case/list",
            json={"interface_id": item["id"]},
        ).json["data"]
        self.assertEqual([row["name"] for row in case_list], ["登录成功"])

        page = self.client.get(
            "/cases/new?interface_id=%s&return_to=/interfaces/?project_id=%s"
            % (item["id"], project_id)
        )
        html = page.get_data(as_text=True)
        self.assertIn('id="prefillInterfaceId" value="%s"' % item["id"], html)
        self.assertIn('href="/interfaces/?project_id=%s"' % project_id, html)
        unsafe_page = self.client.get(
            "/cases/new?interface_id=%s&return_to=//evil.example/path" % item["id"]
        )
        self.assertNotIn("evil.example", unsafe_page.get_data(as_text=True))

    def test_case_list_supports_module_url_and_environment_type_filters(self):
        """用例列表可组合筛选，并返回接口所属模块信息。"""
        project_id = self.create_project("用例筛选项目")
        other_project_id = self.create_project("其他用例项目")
        member_interface = self.create_interface(
            project_id,
            "会员详情",
            "/api/member/detail",
            "会员模块",
        )
        order_interface = self.create_interface(
            project_id,
            "订单详情",
            "/api/order/detail",
            "订单模块",
        )
        other_interface = self.create_interface(
            other_project_id,
            "其他会员详情",
            "/api/member/detail",
            "会员模块",
        )
        testing_environment = self.client.post(
            "/api/execution-environment/create",
            json={"name": "筛选测试环境", "environment_type": "testing"},
        ).json["data"]
        production_environment = self.client.post(
            "/api/execution-environment/create",
            json={"name": "筛选生产环境", "environment_type": "production"},
        ).json["data"]

        cases = (
            (project_id, member_interface, testing_environment, "会员测试用例"),
            (project_id, order_interface, production_environment, "订单生产用例"),
            (other_project_id, other_interface, testing_environment, "其他会员用例"),
        )
        for case_project_id, interface, environment, case_name in cases:
            response = self.client.post(
                "/api/test-case/create",
                json={
                    "project_id": case_project_id,
                    "interface_id": interface["id"],
                    "environment_id": environment["id"],
                    "name": case_name,
                },
            )
            self.assertEqual(response.status_code, 200)

        response = self.client.post(
            "/api/test-case/list",
            json={
                "project_id": project_id,
                "module_id": member_interface["module_id"],
                "url": "member",
                "environment_type": "testing",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual([item["name"] for item in response.json["data"]], ["会员测试用例"])
        case_item = response.json["data"][0]
        self.assertEqual(case_item["module_id"], member_interface["module_id"])
        self.assertEqual(case_item["module_name"], "会员模块")
        self.assertEqual(case_item["environment_type_name"], "测试")

        environment_only = self.client.post(
            "/api/test-case/list",
            json={"environment_type": "production"},
        )
        self.assertEqual(
            [item["name"] for item in environment_only.json["data"]],
            ["订单生产用例"],
        )

        options = self.client.post("/api/test-case/options", json={}).json["data"]
        self.assertIn(
            {"value": "testing", "label": "测试"},
            options["environment_types"],
        )
        self.assertIn(
            {
                "id": member_interface["module_id"],
                "project_id": project_id,
                "name": "会员模块",
            },
            options["modules"],
        )

        mismatch = self.client.post(
            "/api/test-case/list",
            json={
                "project_id": other_project_id,
                "module_id": member_interface["module_id"],
            },
        )
        self.assertEqual(mismatch.status_code, 400)
        unsupported_type = self.client.post(
            "/api/test-case/list",
            json={"environment_type": "unknown"},
        )
        self.assertEqual(unsupported_type.status_code, 400)

    def test_case_and_suite_list_pages_render_environment_type_only(self):
        """列表页脚本仅渲染环境类型，并包含用例组合搜索控件。"""
        case_html = self.client.get("/cases/").get_data(as_text=True)
        suite_html = self.client.get("/suites/").get_data(as_text=True)

        self.assertIn('id="caseProjectFilter"', case_html)
        self.assertIn('id="caseModuleFilter" disabled', case_html)
        self.assertIn('id="caseUrlFilter"', case_html)
        self.assertIn('id="caseEnvironmentFilter"', case_html)
        self.assertIn("environmentTypeBadge(item)", case_html)
        self.assertIn("escapeHtml(item.module_name || '-')", case_html)
        self.assertIn("escapeHtml(item.url || '-')", case_html)
        self.assertNotIn("escapeHtml(item.environment_name || '-')", case_html)
        self.assertNotIn("escapeHtml(item.interface_type)", case_html)
        self.assertNotIn("item.is_active ? '<span", case_html)
        self.assertIn("environmentTypeBadge(item)", suite_html)
        self.assertNotIn("escapeHtml(item.environment_name || '-')", suite_html)

    def test_http_and_websocket_entry_routes_render_from_list_pages(self):
        """接口与用例列表应稳定渲染，并分别暴露 HTTP、WebSocket 入口。"""
        interface_page = self.client.get("/interfaces/")
        case_page = self.client.get("/cases/")

        self.assertEqual(interface_page.status_code, 200)
        self.assertEqual(case_page.status_code, 200)
        interface_html = interface_page.get_data(as_text=True)
        case_html = case_page.get_data(as_text=True)
        self.assertIn('href="/interfaces/new/http"', interface_html)
        self.assertIn('href="/interfaces/new/websocket"', interface_html)
        self.assertIn('href="/cases/new/http"', case_html)
        self.assertIn('href="/cases/new/websocket"', case_html)

        expected_endpoints = {
            "interfaces.new_http_interface",
            "interfaces.new_websocket_interface",
            "cases.new_http_case",
            "cases.new_websocket_case",
        }
        registered_endpoints = {
            rule.endpoint for rule in self.app.url_map.iter_rules()
        }
        self.assertTrue(expected_endpoints.issubset(registered_endpoints))

    def test_assertion_jsonpath_picker_and_value_type_layout(self):
        """点选优先填充聚焦输入框，并为中英文类型名称保留宽度。"""
        case_script_response = self.client.get("/static/js/case_edit.js")
        case_script = case_script_response.get_data(as_text=True)
        case_script_response.close()
        suite_html = self.client.get("/suites/new").get_data(as_text=True)

        self.assertIn(
            "if ($('#assertions-tab').hasClass('active'))",
            case_script,
        )
        self.assertIn(
            "'#assertionList .assertion-jsonpath:visible'",
            case_script,
        )
        self.assertIn(
            "lastFocusedAssertionJsonpath = this",
            case_script,
        )
        self.assertIn(
            "if (!$('#extractors-tab').hasClass('active'))",
            case_script,
        )
        self.assertIn(
            "'#extractorList .extractor-jsonpath:visible'",
            case_script,
        )
        self.assertIn(
            "lastFocusedExtractorJsonpath = this",
            case_script,
        )
        self.assertIn(
            "return focusedInput.length ? focusedInput.first() : inputs.last()",
            case_script,
        )
        self.assertNotIn(
            "bootstrap.Tab.getOrCreateInstance(extractorTab).show()",
            case_script,
        )
        self.assertIn(
            'col-md-2 assertion-value-type-field',
            case_script,
        )
        self.assertIn(
            'col-md-2 step-assertion-value-type-field',
            suite_html,
        )

    def test_case_tree_groups_and_interfaces_support_lazy_pagination(self):
        """树形视图按模块和接口分页，并沿用列表组合筛选语义。"""
        project_id = self.create_project("树形用例项目")
        member_interface = self.create_interface(
            project_id,
            "会员详情",
            "/api/member/detail",
            "会员模块",
        )
        member_list_interface = self.create_interface(
            project_id,
            "会员列表",
            "/api/member/list",
            "会员模块",
        )
        order_interface = self.create_interface(
            project_id,
            "订单详情",
            "/api/order/detail",
            "订单模块",
        )
        empty_interface = self.create_interface(
            project_id,
            "空接口",
            "/api/empty",
            "空模块",
        )
        self.assertIsNotNone(empty_interface)
        testing_environment = self.client.post(
            "/api/execution-environment/create",
            json={"name": "树形测试环境", "environment_type": "testing"},
        ).json["data"]
        production_environment = self.client.post(
            "/api/execution-environment/create",
            json={"name": "树形生产环境", "environment_type": "production"},
        ).json["data"]

        case_specs = (
            (member_interface, testing_environment, "会员测试一"),
            (member_interface, production_environment, "会员生产"),
            (member_list_interface, testing_environment, "会员测试二"),
            (order_interface, testing_environment, "订单测试"),
        )
        for interface, environment, name in case_specs:
            response = self.client.post(
                "/api/test-case/create",
                json={
                    "project_id": project_id,
                    "interface_id": interface["id"],
                    "environment_id": environment["id"],
                    "name": name,
                },
            )
            self.assertEqual(response.status_code, 200)

        groups = self.client.post(
            "/api/test-case/tree-groups",
            json={
                "project_id": project_id,
                "environment_type": "testing",
                "page": 1,
                "page_size": 1,
            },
        )
        self.assertEqual(groups.status_code, 200)
        self.assertEqual(groups.json["pagination"]["total"], 2)
        self.assertEqual(groups.json["pagination"]["pages"], 2)
        self.assertEqual(len(groups.json["data"]), 1)
        self.assertNotEqual(groups.json["data"][0]["module_name"], "空模块")

        member_group = self.client.post(
            "/api/test-case/tree-groups",
            json={
                "project_id": project_id,
                "module_id": member_interface["module_id"],
                "environment_type": "testing",
            },
        ).json["data"][0]
        self.assertEqual(member_group["interface_count"], 2)
        self.assertEqual(member_group["case_count"], 2)

        interfaces = self.client.post(
            "/api/test-case/tree-interfaces",
            json={
                "project_id": project_id,
                "module_id": member_interface["module_id"],
                "environment_type": "testing",
                "page": 1,
                "page_size": 1,
            },
        )
        self.assertEqual(interfaces.status_code, 200)
        self.assertEqual(interfaces.json["pagination"]["total"], 2)
        self.assertEqual(len(interfaces.json["data"]), 1)
        self.assertEqual(interfaces.json["data"][0]["case_count"], 1)

        url_filtered = self.client.post(
            "/api/test-case/tree-interfaces",
            json={
                "module_id": member_interface["module_id"],
                "url": "detail",
            },
        )
        self.assertEqual(
            [item["interface_name"] for item in url_filtered.json["data"]],
            ["会员详情"],
        )
        self.assertEqual(url_filtered.json["data"][0]["case_count"], 2)

        list_response = self.client.post(
            "/api/test-case/list",
            json={
                "project_id": project_id,
                "page": 1,
                "page_size": 2,
            },
        )
        self.assertEqual(list_response.status_code, 200)
        self.assertEqual(list_response.json["pagination"]["total"], 4)
        self.assertEqual(len(list_response.json["data"]), 2)

        missing_module = self.client.post(
            "/api/test-case/tree-interfaces",
            json={},
        )
        self.assertEqual(missing_module.status_code, 400)

    def test_case_page_contains_independent_list_and_tree_views(self):
        """用例页保留列表能力，并新增独立树形视图与懒加载入口。"""
        html = self.client.get("/cases/").get_data(as_text=True)

        self.assertIn('id="caseListPanel"', html)
        self.assertIn('id="caseTreePanel"', html)
        self.assertIn('data-view="list"', html)
        self.assertIn('data-view="tree"', html)
        self.assertIn("var caseListPage", html)
        self.assertIn("var caseTreePage", html)
        self.assertIn("/api/test-case/tree-groups", html)
        self.assertIn("/api/test-case/tree-interfaces", html)
        self.assertIn("/api/test-case/list", html)
        self.assertIn("加载更多接口", html)
        self.assertIn("加载更多用例", html)
        self.assertIn("group.project_name + ' / ' + group.module_name", html)
        self.assertNotIn("var showProject", html)
        self.assertIn('data-lucide="folder"', html)
        self.assertIn('data-lucide="code-2"', html)
        self.assertIn('data-lucide="file-text"', html)

    def test_case_ownership_is_derived_from_interface_module(self):
        """接口切换项目或模块后，用例归属无需更新即可自动跟随。"""
        source_project_id = self.create_project("归属源项目")
        target_project_id = self.create_project("归属目标项目")
        interface = self.create_interface(
            source_project_id,
            "归属接口",
            "/api/ownership",
            "源模块",
        )
        case_response = self.client.post(
            "/api/test-case/create",
            json={
                "project_id": source_project_id,
                "interface_id": interface["id"],
                "name": "自动跟随用例",
            },
        )
        self.assertEqual(case_response.status_code, 200)
        case_id = case_response.json["data"]["id"]

        interface_detail = self.client.post(
            "/api/interface-definition/detail",
            json={"interface_id": interface["id"]},
        ).json["data"]
        interface_detail.update(
            {
                "interface_id": interface["id"],
                "project_id": target_project_id,
                "module_id": None,
                "module_name": "目标模块",
            }
        )
        move_response = self.client.post(
            "/api/interface-definition/save",
            json=interface_detail,
        )
        self.assertEqual(move_response.status_code, 200)

        case_detail = self.client.post(
            "/api/test-case/detail",
            json={"case_id": case_id},
        ).json["data"]
        self.assertEqual(case_detail["project_id"], target_project_id)
        self.assertEqual(case_detail["project_name"], "归属目标项目")
        self.assertEqual(case_detail["module_name"], "目标模块")

        source_cases = self.client.post(
            "/api/test-case/list",
            json={"project_id": source_project_id},
        ).json["data"]
        target_cases = self.client.post(
            "/api/test-case/list",
            json={"project_id": target_project_id},
        ).json["data"]
        self.assertEqual(source_cases, [])
        self.assertEqual([item["id"] for item in target_cases], [case_id])

        moved_interface = move_response.json["data"]
        moved_interface.update(
            {
                "interface_id": interface["id"],
                "module_id": None,
                "module_name": "目标模块二",
            }
        )
        module_response = self.client.post(
            "/api/interface-definition/save",
            json=moved_interface,
        )
        self.assertEqual(module_response.status_code, 200)
        case_detail = self.client.post(
            "/api/test-case/detail",
            json={"case_id": case_id},
        ).json["data"]
        self.assertEqual(case_detail["module_name"], "目标模块二")

        interface_columns = {
            column["name"] for column in inspect(db.engine).get_columns("interface")
        }
        case_columns = {
            column["name"] for column in inspect(db.engine).get_columns("test_case")
        }
        self.assertNotIn("project_id", interface_columns)
        self.assertNotIn("project_id", case_columns)

    def test_interface_project_move_syncs_or_rejects_related_suites(self):
        """接口跨项目时同步单项目集合，并阻止集合变成多项目混合。"""
        source_project_id = self.create_project("集合源项目")
        target_project_id = self.create_project("集合目标项目")
        environment_id = self.client.post(
            "/api/execution-environment/create",
            json={"name": "集合归属环境", "environment_type": "testing"},
        ).json["data"]["id"]

        moving_interface = self.create_interface(
            source_project_id,
            "待移动接口",
            "/api/moving",
            "源模块",
        )
        staying_interface = self.create_interface(
            source_project_id,
            "保留接口",
            "/api/staying",
            "源模块",
        )
        moving_case = self.client.post(
            "/api/test-case/create",
            json={
                "project_id": source_project_id,
                "interface_id": moving_interface["id"],
                "name": "待移动用例",
            },
        ).json["data"]
        staying_case = self.client.post(
            "/api/test-case/create",
            json={
                "project_id": source_project_id,
                "interface_id": staying_interface["id"],
                "name": "保留用例",
            },
        ).json["data"]
        conflict_suite = self.client.post(
            "/api/test-suite/create",
            json={
                "project_id": source_project_id,
                "environment_id": environment_id,
                "name": "混合风险集合",
                "suite_type": "scene",
                "steps": [
                    {"case_id": moving_case["id"]},
                    {"case_id": staying_case["id"]},
                ],
            },
        )
        self.assertEqual(conflict_suite.status_code, 200)

        moving_detail = self.client.post(
            "/api/interface-definition/detail",
            json={"interface_id": moving_interface["id"]},
        ).json["data"]
        moving_detail.update(
            {
                "interface_id": moving_interface["id"],
                "project_id": target_project_id,
                "module_id": None,
                "module_name": "目标模块",
            }
        )
        conflict_response = self.client.post(
            "/api/interface-definition/save",
            json=moving_detail,
        )
        self.assertEqual(conflict_response.status_code, 409)
        self.assertIn("混合风险集合", conflict_response.json["message"])
        unchanged = self.client.post(
            "/api/interface-definition/detail",
            json={"interface_id": moving_interface["id"]},
        ).json["data"]
        self.assertEqual(unchanged["project_id"], source_project_id)

        safe_interface = self.create_interface(
            source_project_id,
            "安全移动接口",
            "/api/safe-moving",
            "源模块",
        )
        safe_case = self.client.post(
            "/api/test-case/create",
            json={
                "project_id": source_project_id,
                "interface_id": safe_interface["id"],
                "name": "安全移动用例",
            },
        ).json["data"]
        safe_suite = self.client.post(
            "/api/test-suite/create",
            json={
                "project_id": source_project_id,
                "environment_id": environment_id,
                "name": "自动同步集合",
                "suite_type": "single",
                "steps": [{"case_id": safe_case["id"]}],
            },
        ).json["data"]
        safe_detail = self.client.post(
            "/api/interface-definition/detail",
            json={"interface_id": safe_interface["id"]},
        ).json["data"]
        safe_detail.update(
            {
                "interface_id": safe_interface["id"],
                "project_id": target_project_id,
                "module_id": None,
                "module_name": "目标模块",
            }
        )
        safe_response = self.client.post(
            "/api/interface-definition/save",
            json=safe_detail,
        )
        self.assertEqual(safe_response.status_code, 200)
        synced_suite = self.client.post(
            "/api/test-suite/detail",
            json={"suite_id": safe_suite["id"]},
        ).json["data"]
        self.assertEqual(synced_suite["project_id"], target_project_id)

    def test_json_responses_render_chinese_without_ascii_escaping(self):
        """JSON 原始响应直接使用 UTF-8 中文。"""
        response = self.client.post("/api/test-case/tree-interfaces", json={})

        self.assertEqual(response.status_code, 400)
        raw_body = response.get_data(as_text=True)
        self.assertIn("模块 ID 不能为空", raw_body)
        self.assertNotIn("\\u6a21\\u5757", raw_body)

    def test_project_create_and_save_modules_in_one_transaction(self):
        """验证项目及其模块可在同一事务中创建和保存。"""
        create_response = self.client.post(
            "/api/project/create",
            json={
                "name": "统一保存项目",
                "description": "创建时维护模块",
                "is_active": True,
                "modules": [
                    {"id": None, "name": "用户模块", "_delete": False},
                    {"id": None, "name": "登录模块", "_delete": False},
                ],
            },
        )
        self.assertEqual(create_response.status_code, 200)
        project = create_response.json["data"]
        modules = {item["name"]: item for item in project["modules"]}
        self.assertEqual(set(modules), {"用户模块", "登录模块"})

        save_response = self.client.post(
            "/api/project/save",
            json={
                "project_id": project["id"],
                "name": "统一保存项目-更新",
                "description": "项目与模块一次提交",
                "is_active": True,
                "modules": [
                    {
                        "id": modules["用户模块"]["id"],
                        "name": "订单模块",
                        "_delete": False,
                    },
                    {
                        "id": modules["登录模块"]["id"],
                        "name": "登录模块",
                        "_delete": True,
                    },
                    {"id": None, "name": "支付模块", "_delete": False},
                ],
            },
        )
        self.assertEqual(save_response.status_code, 200)
        self.assertEqual(save_response.json["data"]["name"], "统一保存项目-更新")
        self.assertEqual(
            {item["name"] for item in save_response.json["data"]["modules"]},
            {"订单模块", "支付模块"},
        )

    def test_project_module_validation_and_delete_reference_rollback(self):
        """验证项目模块校验以及被引用时删除回滚。"""
        project_id = self.create_project("事务回滚项目")
        interface = self.create_interface(project_id, "会员列表", "/members", "会员")
        original_project = self.client.post(
            "/api/project/detail", json={"project_id": project_id}
        ).json["data"]
        occupied_module = original_project["modules"][0]

        response = self.client.post(
            "/api/project/save",
            json={
                "project_id": project_id,
                "name": "不应保存的新名称",
                "description": "不应保存的新描述",
                "is_active": False,
                "modules": [
                    {
                        "id": occupied_module["id"],
                        "name": occupied_module["name"],
                        "_delete": True,
                    },
                    {"id": None, "name": "不应创建", "_delete": False},
                ],
            },
        )
        self.assertEqual(response.status_code, 409)
        self.assertIn("存在 1 个接口", response.json["message"])
        after_failure = self.client.post(
            "/api/project/detail", json={"project_id": project_id}
        ).json["data"]
        self.assertEqual(after_failure["name"], "事务回滚项目")
        self.assertTrue(after_failure["is_active"])
        self.assertEqual(
            [(item["id"], item["name"]) for item in after_failure["modules"]],
            [(occupied_module["id"], "会员")],
        )
        self.assertEqual(interface["module_id"], occupied_module["id"])

        duplicate_response = self.client.post(
            "/api/project/save",
            json={
                "project_id": project_id,
                "name": "事务回滚项目",
                "modules": [
                    {"id": occupied_module["id"], "name": "会员", "_delete": False},
                    {"id": None, "name": " 会员 ", "_delete": False},
                ],
            },
        )
        self.assertEqual(duplicate_response.status_code, 409)

        other_project_id = self.create_project("其他项目")
        other_module = self.client.post(
            "/api/project-module/create",
            json={"project_id": other_project_id, "name": "其他模块"},
        ).json["data"]
        foreign_response = self.client.post(
            "/api/project/save",
            json={
                "project_id": project_id,
                "name": "事务回滚项目",
                "modules": [
                    {"id": other_module["id"], "name": "其他模块", "_delete": False}
                ],
            },
        )
        self.assertEqual(foreign_response.status_code, 400)
        self.assertIn("不属于当前项目", foreign_response.json["message"])

        validation_payloads = [
            (
                [
                    {"id": occupied_module["id"], "name": "会员", "_delete": False},
                    {"id": occupied_module["id"], "name": "会员", "_delete": False},
                ],
                "重复提交",
            ),
            ([{"id": None, "name": "", "_delete": False}], "名称不能为空"),
            ([{"id": None, "name": "临时", "_delete": True}], "不能标记为删除"),
        ]
        for modules, message in validation_payloads:
            with self.subTest(message=message):
                invalid_response = self.client.post(
                    "/api/project/save",
                    json={
                        "project_id": project_id,
                        "name": "事务回滚项目",
                        "modules": modules,
                    },
                )
                self.assertEqual(invalid_response.status_code, 400)
                self.assertIn(message, invalid_response.json["message"])

        invalid_create = self.client.post(
            "/api/project/create",
            json={
                "name": "非法新项目",
                "modules": [
                    {
                        "id": occupied_module["id"],
                        "name": "会员",
                        "_delete": False,
                    }
                ],
            },
        )
        self.assertEqual(invalid_create.status_code, 400)
        self.assertIn("不能关联已有模块", invalid_create.json["message"])


if __name__ == "__main__":
    unittest.main()
