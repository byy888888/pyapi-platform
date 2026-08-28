# -*- coding: utf-8 -*-
"""
@Author: byy
@Desc: JSONPath 服务测试，验证字段读取和候选路径枚举。
"""

import unittest

from app.services.jsonpath_service import extract_by_jsonpath
from app.services.jsonpath_service import list_jsonpaths


class JsonPathServiceTestCase(unittest.TestCase):
    """集中验证 JSONPath 提取和候选路径生成能力。"""
    def test_extract_by_jsonpath(self):
        """验证能够按 JSONPath 从响应数据中提取目标值。"""
        data = {"data": {"id": 1001, "items": [{"name": "A"}, {"name": "B"}]}}

        self.assertEqual(extract_by_jsonpath(data, "$.data.id"), 1001)
        self.assertEqual(extract_by_jsonpath(data, "$.data.items[*].name"), ["A", "B"])
        self.assertIsNone(extract_by_jsonpath(data, "$.missing"))

    def test_list_jsonpaths(self):
        """验证能够列出响应数据中可供点选的 JSONPath。"""
        data = {"data": {"items": [{"name": "A"}]}, "trace-id": "x"}
        paths = list_jsonpaths(data)

        self.assertIn("$", paths)
        self.assertIn("$.data.items[0].name", paths)
        self.assertIn("$['trace-id']", paths)


if __name__ == "__main__":
    unittest.main()
