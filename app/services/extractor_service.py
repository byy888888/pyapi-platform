# -*- coding: utf-8 -*-
"""
@Author: byy
@Desc: 响应提取服务，通过 JSONPath 将响应字段写入运行时变量。
"""

from typing import Any
from typing import Dict
from typing import List

from .jsonpath_service import extract_by_jsonpath


def run_extractors(
    extractors: List[Dict[str, Any]],
    response_context: Dict[str, Any],
    runtime_vars: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """执行响应 JSONPath 提取器并更新本轮运行时变量。"""
    results = []
    body_json = response_context.get("body_json")
    for extractor in extractors or []:
        jsonpath_expr = extractor.get("jsonpath")
        variable_name = extractor.get("variable_name")
        required = bool(extractor.get("required"))
        is_output = bool(extractor.get("is_output"))
        value = extract_by_jsonpath(body_json, jsonpath_expr) if body_json is not None else None
        success = value is not None or not required
        if success and value is not None and variable_name:
            runtime_vars[variable_name] = value
        results.append(
            {
                "jsonpath": jsonpath_expr,
                "variable_name": variable_name,
                "required": required,
                "is_output": is_output,
                "success": success,
                "value": value,
                "message": "提取成功" if success else "必填提取器未匹配到值",
            }
        )
    return results
