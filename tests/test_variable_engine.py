# -*- coding: utf-8 -*-
"""
@Author: byy
@Desc: 变量引擎测试，验证递归替换、钩子函数和异常提示。
"""

import unittest

import rsa

from app import create_app
from app.extensions import db
from app.services.hook_functions import HookFunctionError
from app.services.variable_engine import build_variable_context
from app.services.variable_engine import VariableReplacementError
from app.services.variable_engine import replace_variables


class VariableEngineTestCase(unittest.TestCase):
    """集中验证变量替换与内置钩子函数。"""
    def test_replace_variables_recursively(self):
        """验证变量引擎可以递归替换嵌套数据中的变量。"""
        context = {
            "global_vars": {"base_url": "http://example.com", "token": "abc"},
            "runtime_vars": {"user_id": "1001"},
        }
        value = {
            "url": "{{base_url}}/users/${user_id}",
            "headers": {"Authorization": "Bearer {{token}}"},
            "items": ["${user_id}", 1],
        }

        result = replace_variables(value, context)

        self.assertEqual(result["url"], "http://example.com/users/1001")
        self.assertEqual(result["headers"]["Authorization"], "Bearer abc")
        self.assertEqual(result["items"], ["1001", 1])

    def test_missing_variable_raises_friendly_error(self):
        """验证引用不存在变量时会返回易理解的错误。"""
        with self.assertRaises(VariableReplacementError) as ctx:
            replace_variables("{{base_url}}/${token}", {"global_vars": {}, "runtime_vars": {}})

        self.assertIn("{{base_url}}", ctx.exception.missing_variables)
        self.assertIn("${token}", ctx.exception.missing_variables)

    def test_hook_function_can_use_runtime_variable_argument(self):
        """验证内置钩子函数可以接收运行时变量参数。"""
        pubkey, private_key = rsa.newkeys(512)
        context = {
            "global_vars": {"base_url": "http://example.com"},
            "runtime_vars": {"pubkey": pubkey.save_pkcs1().decode("utf-8")},
        }

        result = replace_variables(
            {
                "url": "{{base_url}}/login/${setrsa('u','${pubkey}')}",
                "params": {"p": "${setrsa('p','${pubkey}')}"},
                "headers": {"X-Password": "${setrsa('h','${pubkey}')}"},
                "body": {"userPwd": "${setrsa('secret','${pubkey}')}", "publicKey": "${pubkey}"},
                "ws_steps": [
                    {"action": "send", "message": "${setrsa('send','${pubkey}')}"},
                    {"action": "receive_assert", "expected": "${setrsa('expected','${pubkey}')}"},
                ],
            },
            context,
        )

        encrypted_password = base64_to_bytes(result["body"]["userPwd"])
        self.assertEqual(rsa.decrypt(encrypted_password, private_key).decode("utf-8"), "secret")
        self.assertNotIn("${", result["url"])
        self.assertNotIn("${", result["params"]["p"])
        self.assertNotIn("${", result["headers"]["X-Password"])
        self.assertNotIn("${", result["ws_steps"][0]["message"])
        self.assertNotIn("${", result["ws_steps"][1]["expected"])

    def test_missing_hook_argument_variable_raises_variable_error(self):
        """验证钩子参数引用缺失变量时会抛出变量错误。"""
        with self.assertRaises(VariableReplacementError) as ctx:
            replace_variables(
                "${setrsa('secret','${pubkey}')}",
                {"global_vars": {}, "runtime_vars": {}},
            )

        self.assertIn("${pubkey}", ctx.exception.missing_variables)

    def test_unknown_hook_function_raises_clear_error(self):
        """验证调用未知钩子函数时会返回明确错误。"""
        with self.assertRaises(HookFunctionError):
            replace_variables("${not_exist('x')}", {"global_vars": {}, "runtime_vars": {}})


class VariableApiTestCase(unittest.TestCase):
    """集中验证变量、项目分页和钩子函数接口。"""
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

    def test_variable_is_independent_from_environment(self):
        """验证项目变量与执行环境保持独立。"""
        project_id = self.client.post("/api/project/create", json={"name": "Demo"}).json["data"]["id"]
        environment_id = self.client.post(
            "/api/execution-environment/create",
            json={"name": "test", "base_url": "http://example.com"},
        ).json["data"]["id"]
        response = self.client.post(
            "/api/global-variable/create",
            json={"project_id": project_id, "var_key": "token", "var_value": "abc"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.json["data"]["environment_id"])
        context = build_variable_context(project_id, environment_id)
        self.assertEqual(context["global_vars"]["token"], "abc")
        self.assertEqual(context["global_vars"]["base_url"], "http://example.com")

    def test_project_list_supports_pagination(self):
        """验证项目列表接口支持分页查询。"""
        for index in range(12):
            self.client.post("/api/project/create", json={"name": "Demo %s" % index})

        response = self.client.post("/api/project/list", json={"page": 2, "page_size": 5})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json["data"]), 5)
        self.assertEqual(response.json["pagination"]["page"], 2)
        self.assertEqual(response.json["pagination"]["page_size"], 5)
        self.assertEqual(response.json["pagination"]["total"], 12)
        self.assertEqual(response.json["pagination"]["pages"], 3)

    def test_hook_function_list_api(self):
        """验证内置钩子函数列表接口返回完整配置。"""
        response = self.client.post("/api/hook-function/list", json={})

        self.assertEqual(response.status_code, 200)
        names = [item["name"] for item in response.json["data"]]
        self.assertIn("setrsa", names)

    def test_hook_function_params_include_description(self):
        """验证每个钩子函数参数都带有名称和说明，避免页面渲染出 undefined。"""
        response = self.client.post("/api/hook-function/list", json={})

        self.assertEqual(response.status_code, 200)
        incomplete = []
        for item in response.json["data"]:
            for param in item.get("params") or []:
                name = str(param.get("name") or "").strip()
                description = str(param.get("description") or "").strip()
                if not name or not description:
                    incomplete.append("%s(%s)" % (item.get("name"), name or "未命名参数"))

        self.assertEqual(
            incomplete,
            [],
            "以下钩子函数的参数缺少名称或说明: %s" % ", ".join(incomplete),
        )


def base64_to_bytes(value):
    """将 Base64 文本解码为原始字节数据。"""
    import base64

    return base64.b64decode(value.encode("utf-8"))


if __name__ == "__main__":
    unittest.main()
