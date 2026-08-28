# -*- coding: utf-8 -*-
"""
@Author: byy
@Desc: 通用断言引擎，负责提取实际值并按声明类型和比较器执行强类型校验。
"""

import json
import re
from typing import Any
from typing import Dict
from typing import List
from typing import Optional
from typing import Tuple

from ..enums import AssertionComparator
from ..enums import AssertionValueType
from .jsonpath_service import extract_by_jsonpath


NULL_COMPARATORS = (
    AssertionComparator.IS_NONE,
    AssertionComparator.IS_NOT_NONE,
)


def assert_response(
    assertions: List[Dict[str, Any]],
    response_context: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """执行断言并返回包含类型信息的断言结果列表。"""
    results = []
    for index, assertion in enumerate(assertions or []):
        result = _assert_one(assertion or {}, response_context or {}, index)
        results.append(result)
    return results


def validate_assertion_definitions(assertions: List[Dict[str, Any]]) -> Optional[str]:
    """校验断言配置中与来源、比较器和数据类型相关的必填字段。"""
    if not isinstance(assertions, list):
        return "断言配置必须是数组"
    for index, assertion in enumerate(assertions, start=1):
        if not isinstance(assertion, dict):
            return "第 %s 条断言配置格式不正确" % index
        error = _validate_assertion_definition(assertion)
        if error:
            return "第 %s 条断言：%s" % (index, error)
    return None


def normalize_assertion_definitions(
    assertions: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """移除与当前断言来源或比较器无关的冗余字段。"""
    normalized_assertions = []
    for assertion in assertions or []:
        normalized = dict(assertion or {})
        source = normalized.get("source")
        comparator = normalized.get("comparator") or AssertionComparator.EQUALS
        if source != "body_json":
            normalized.pop("jsonpath", None)
        if source != "headers":
            normalized.pop("header", None)
        if comparator in NULL_COMPARATORS:
            normalized.pop("expected", None)
            normalized["value_type"] = AssertionValueType.RAW
        elif normalized.get("value_type") == "raw":
            normalized["value_type"] = AssertionValueType.RAW
        normalized_assertions.append(normalized)
    return normalized_assertions


def _validate_assertion_definition(assertion: Dict[str, Any]) -> Optional[str]:
    """校验单条断言的静态配置。"""
    source = assertion.get("source")
    comparator = assertion.get("comparator") or AssertionComparator.EQUALS
    value_type = assertion.get("value_type") or AssertionValueType.RAW
    if not source:
        return "来源不能为空"
    if source == "headers" and not str(assertion.get("header") or "").strip():
        return "响应头名称不能为空"
    if source == "body_json" and not str(assertion.get("jsonpath") or "").strip():
        return "JSONPath 不能为空"
    if comparator not in AssertionComparator.VALUES:
        return "比较器不支持: %s" % comparator
    if value_type == "raw":
        value_type = AssertionValueType.RAW
    if value_type not in AssertionValueType.VALUES:
        return "数据类型不支持: %s" % value_type
    return None


def _assert_one(
    assertion: Dict[str, Any],
    response_context: Dict[str, Any],
    index: int,
) -> Dict[str, Any]:
    """执行单条断言，实际响应值不做类型转换。"""
    source = assertion.get("source")
    comparator = assertion.get("comparator") or AssertionComparator.EQUALS
    comparator_label = AssertionComparator.LABELS.get(comparator, comparator)
    expected = assertion.get("expected")
    value_type = assertion.get("value_type") or AssertionValueType.RAW
    if value_type == "raw":
        value_type = AssertionValueType.RAW
    name = assertion.get("name") or source or "assertion_%s" % (index + 1)

    config_error = _validate_assertion_definition(assertion)
    if config_error:
        return _build_result(
            name,
            source,
            False,
            None,
            expected,
            comparator,
            comparator_label,
            value_type,
            config_error,
        )

    actual = _read_actual(assertion, response_context)
    expected_value = expected
    expected_type = None
    if comparator not in NULL_COMPARATORS:
        try:
            expected_value = _convert_expected_value(expected, value_type)
        except (TypeError, ValueError) as exc:
            message = "期望值 %r 无法转换为 %s: %s" % (
                expected,
                _declared_type_name(value_type),
                exc,
            )
            return _build_result(
                name,
                source,
                False,
                actual,
                expected,
                comparator,
                comparator_label,
                value_type,
                message,
            )
        expected_type = _value_type_name(expected_value)

        if value_type and not _matches_declared_type(actual, value_type):
            message = (
                "实际值类型为 %s，断言要求类型为 %s；"
                "实际值=%r，期望值=%r，比较器=%s"
            ) % (
                _value_type_name(actual),
                _declared_type_name(value_type),
                actual,
                expected_value,
                comparator_label,
            )
            return _build_result(
                name,
                source,
                False,
                actual,
                expected,
                comparator,
                comparator_label,
                value_type,
                message,
                expected_type=expected_type,
            )

    passed, message = _compare(
        actual,
        expected_value,
        comparator,
        assertion,
        comparator_label,
    )
    return _build_result(
        name,
        source,
        passed,
        actual,
        expected,
        comparator,
        comparator_label,
        value_type,
        message,
        expected_type=expected_type,
    )


def _build_result(
    name: str,
    source: Optional[str],
    passed: bool,
    actual: Any,
    expected: Any,
    comparator: str,
    comparator_label: str,
    value_type: str,
    message: str,
    expected_type: Optional[str] = None,
) -> Dict[str, Any]:
    """构造统一的断言结果。"""
    return {
        "name": name,
        "source": source,
        "passed": passed,
        "actual": actual,
        "expected": expected,
        "actual_type": _value_type_name(actual),
        "expected_type": expected_type,
        "value_type": value_type or "raw",
        "comparator": comparator,
        "comparator_label": comparator_label,
        "message": message,
    }


def _read_actual(assertion: Dict[str, Any], response_context: Dict[str, Any]) -> Any:
    """从响应上下文中读取实际值。"""
    source = assertion.get("source")
    if source == "status_code":
        return response_context.get("status_code")
    if source == "headers":
        header_name = str(assertion.get("header") or "").strip()
        headers = response_context.get("headers") or {}
        for key, value in headers.items():
            if key.lower() == header_name.lower():
                return value
        return None
    if source == "body_json":
        return extract_by_jsonpath(response_context.get("body_json"), assertion.get("jsonpath"))
    if source == "body_text":
        return response_context.get("body_text")
    if source == "body_type":
        return response_context.get("body_type")
    if source == "body_length":
        return response_context.get("body_length")
    if source in ("elapsed_ms", "time_taken_ms"):
        return response_context.get("elapsed_ms", response_context.get("time_taken_ms"))
    if source == "ws_message":
        return _ws_message_text(response_context.get("ws_messages") or [])
    return response_context.get(source)


def _ws_message_text(messages: List[Dict[str, Any]]) -> str:
    """拼接 WebSocket 文本消息用于断言匹配。"""
    return "\n".join([str(item.get("data", "")) for item in messages])


def _convert_expected_value(value: Any, value_type: str) -> Any:
    """只转换用户输入的期望值，实际响应值保持原始类型。"""
    if value_type in (None, "", "raw"):
        return value
    if value_type == AssertionValueType.STRING:
        if value is None:
            return None
        return str(value)
    if value_type == AssertionValueType.INTEGER:
        if value is None or value == "":
            return None
        return int(value)
    if value_type == AssertionValueType.FLOAT:
        if value is None or value == "":
            return None
        return float(value)
    if value_type == AssertionValueType.BOOLEAN:
        if isinstance(value, bool):
            return value
        normalized = str(value).strip().lower()
        if normalized in ("1", "true", "yes", "on"):
            return True
        if normalized in ("0", "false", "no", "off"):
            return False
        raise ValueError("布尔值仅支持 true/false、1/0、yes/no、on/off")
    if value_type == AssertionValueType.NULL:
        if value in (None, "", "null", "None"):
            return None
        raise ValueError("空值仅支持 null 或留空")
    if value_type in (AssertionValueType.OBJECT, AssertionValueType.ARRAY):
        parsed = value
        if isinstance(value, str):
            parsed = json.loads(value)
        expected_type = dict if value_type == AssertionValueType.OBJECT else list
        if type(parsed) is not expected_type:
            raise ValueError("期望值不是%s" % value_type)
        return parsed
    raise ValueError("不支持的数据类型: %s" % value_type)


def _matches_declared_type(actual: Any, value_type: str) -> bool:
    """严格判断实际响应值是否符合声明类型。"""
    expected_python_types = {
        AssertionValueType.STRING: str,
        AssertionValueType.INTEGER: int,
        AssertionValueType.FLOAT: float,
        AssertionValueType.BOOLEAN: bool,
        AssertionValueType.NULL: type(None),
        AssertionValueType.OBJECT: dict,
        AssertionValueType.ARRAY: list,
    }
    expected_type = expected_python_types.get(value_type)
    if expected_type is None:
        return True
    return type(actual) is expected_type


def _declared_type_name(value_type: str) -> str:
    """返回声明类型的稳定英文名称。"""
    return value_type or "raw"


def _value_type_name(value: Any) -> str:
    """把 Python 原生类型转换为调试结果使用的名称。"""
    if value is None:
        return "null"
    if type(value) is bool:
        return "bool"
    if type(value) is int:
        return "int"
    if type(value) is float:
        return "float"
    if type(value) is str:
        return "string"
    if type(value) is list:
        return "array"
    if type(value) is dict:
        return "object"
    return type(value).__name__


def _compare(
    actual: Any,
    expected: Any,
    comparator: str,
    assertion: Dict[str, Any],
    comparator_label: str,
) -> Tuple[bool, str]:
    """使用指定比较器比较实际值和期望值。"""
    try:
        if comparator == AssertionComparator.EQUALS:
            passed = actual == expected
        elif comparator == AssertionComparator.NOT_EQUALS:
            passed = actual != expected
        elif comparator == AssertionComparator.GREATER_THAN:
            passed = actual > expected
        elif comparator == AssertionComparator.LESS_THAN:
            passed = actual < expected
        elif comparator == AssertionComparator.GREATER_OR_EQUAL:
            passed = actual >= expected
        elif comparator == AssertionComparator.LESS_OR_EQUAL:
            passed = actual <= expected
        elif comparator == AssertionComparator.CONTAINS:
            passed = str(expected) in str(actual)
        elif comparator == AssertionComparator.NOT_CONTAINS:
            passed = str(expected) not in str(actual)
        elif comparator == AssertionComparator.IS_NONE:
            passed = actual is None or actual == ""
        elif comparator == AssertionComparator.IS_NOT_NONE:
            passed = actual is not None and actual != ""
        elif comparator == AssertionComparator.REGEX_MATCH:
            passed = re.search(str(expected), str(actual or "")) is not None
        elif comparator == AssertionComparator.TIME_LESS_THAN:
            passed = float(actual) < float(expected)
        elif comparator == AssertionComparator.RECEIVE_CONTAINS_WITHIN:
            passed = str(expected) in str(actual or "")
        else:
            return False, "不支持的比较器: %s" % comparator
    except Exception as exc:
        return False, "比较失败: %s" % exc

    if passed:
        return True, "断言通过"
    return False, _failure_message(
        actual,
        expected,
        comparator_label,
        assertion,
    )


def _failure_message(
    actual: Any,
    expected: Any,
    comparator_label: str,
    assertion: Dict[str, Any],
) -> str:
    """构造包含中文比较器的断言失败信息。"""
    label = assertion.get("name") or assertion.get("source") or "断言"
    return "%s失败，实际值=%r，期望值=%r，比较器=%s" % (
        label,
        actual,
        expected,
        comparator_label,
    )
