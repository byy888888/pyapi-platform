# -*- coding: utf-8 -*-
"""
@Author: byy
@Desc: 断言引擎测试，验证比较器、强类型和不同响应来源。
"""

import unittest

from app.services.assert_engine import assert_response
from app.services.assert_engine import normalize_assertion_definitions
from app.services.assert_engine import validate_assertion_definitions


class AssertEngineTestCase(unittest.TestCase):
    """集中验证 HTTP 与 WebSocket 断言引擎的判断结果。"""
    def test_assert_response_success_and_failure(self):
        """验证响应断言能够正确区分通过和失败结果。"""
        context = {
            "status_code": 200,
            "headers": {"Content-Type": "application/json"},
            "body_json": {"data": {"id": 1001}},
            "body_text": '{"ok": true}',
            "body_type": "json",
            "elapsed_ms": 88,
        }
        assertions = [
            {"source": "status_code", "comparator": "equals", "expected": "200", "value_type": "int"},
            {"source": "body_json", "jsonpath": "$.data.id", "comparator": "equals", "expected": "1001", "value_type": "int"},
            {"source": "body_text", "comparator": "contains", "expected": "missing"},
        ]

        results = assert_response(assertions, context)

        self.assertTrue(results[0]["passed"])
        self.assertTrue(results[1]["passed"])
        self.assertFalse(results[2]["passed"])
        self.assertIn("实际值", results[2]["message"])

    def test_websocket_message_assertion(self):
        """验证 WebSocket 消息断言能够匹配目标消息并校验字段。"""
        context = {"ws_messages": [{"data": "server-push"}, {"data": "echo:hello"}]}
        results = assert_response(
            [
                {
                    "source": "ws_message",
                    "comparator": "receive_contains_within",
                    "expected": "echo:hello",
                }
            ],
            context,
        )

        self.assertTrue(results[0]["passed"])

    def test_declared_type_requires_exact_response_type(self):
        """声明类型只转换期望值，不允许把实际响应值强制转换后通过。"""
        assertions = [
            {
                "source": "body_json",
                "jsonpath": "$.id",
                "comparator": "equals",
                "expected": "1001",
                "value_type": "int",
            },
            {
                "source": "body_json",
                "jsonpath": "$.enabled",
                "comparator": "equals",
                "expected": "1",
                "value_type": "int",
            },
            {
                "source": "body_json",
                "jsonpath": "$.score",
                "comparator": "equals",
                "expected": "1.0",
                "value_type": "float",
            },
        ]
        context = {
            "body_json": {
                "id": "1001",
                "enabled": True,
                "score": 1,
            }
        }

        results = assert_response(assertions, context)

        self.assertFalse(results[0]["passed"])
        self.assertEqual(results[0]["actual_type"], "string")
        self.assertEqual(results[0]["expected_type"], "int")
        self.assertIn("断言要求类型为 int", results[0]["message"])
        self.assertFalse(results[1]["passed"])
        self.assertEqual(results[1]["actual_type"], "bool")
        self.assertFalse(results[2]["passed"])
        self.assertEqual(results[2]["actual_type"], "int")

    def test_invalid_expected_type_returns_assertion_failure(self):
        """期望值转换失败时返回断言失败，不中断整个执行请求。"""
        results = assert_response(
            [
                {
                    "source": "status_code",
                    "comparator": "equals",
                    "expected": "abc",
                    "value_type": "int",
                }
            ],
            {"status_code": 200},
        )

        self.assertFalse(results[0]["passed"])
        self.assertEqual(results[0]["comparator_label"], "等于")
        self.assertIn("无法转换为 int", results[0]["message"])

    def test_header_assertion_and_source_configuration_validation(self):
        """响应头按名称忽略大小写读取，并校验来源专属字段。"""
        results = assert_response(
            [
                {
                    "source": "headers",
                    "header": "content-type",
                    "comparator": "contains",
                    "expected": "application/json",
                    "value_type": "string",
                }
            ],
            {"headers": {"Content-Type": "application/json; charset=utf-8"}},
        )

        self.assertTrue(results[0]["passed"])
        self.assertEqual(
            validate_assertion_definitions(
                [{"source": "headers", "comparator": "equals"}]
            ),
            "第 1 条断言：响应头名称不能为空",
        )
        self.assertEqual(
            validate_assertion_definitions(
                [{"source": "body_json", "comparator": "equals"}]
            ),
            "第 1 条断言：JSONPath 不能为空",
        )

    def test_null_comparator_and_normalization_ignore_expected_value(self):
        """空值比较器忽略期望值，并清理与来源无关的字段。"""
        assertion = {
            "source": "status_code",
            "jsonpath": "$.unused",
            "header": "X-Unused",
            "comparator": "is_not_none",
            "expected": "unused",
            "value_type": "int",
        }

        normalized = normalize_assertion_definitions([assertion])[0]
        result = assert_response([normalized], {"status_code": 200})[0]

        self.assertNotIn("jsonpath", normalized)
        self.assertNotIn("header", normalized)
        self.assertNotIn("expected", normalized)
        self.assertEqual(normalized["value_type"], "")
        self.assertTrue(result["passed"])


if __name__ == "__main__":
    unittest.main()
