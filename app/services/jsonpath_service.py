# -*- coding: utf-8 -*-
"""
@Author: byy
@Desc: JSONPath 工具服务，负责读取路径并枚举响应 JSON 的候选路径。
"""

import re

from jsonpath_ng import parse


SIMPLE_KEY_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def extract_by_jsonpath(data, jsonpath_expr):
    """通过 JSONPath 从类 JSON 数据中提取值。"""
    if not jsonpath_expr:
        return None
    matches = [match.value for match in parse(jsonpath_expr).find(data)]
    if not matches:
        return None
    if len(matches) == 1:
        return matches[0]
    return matches


def list_jsonpaths(data):
    """列出类 JSON 数据中可选择的 JSONPath 表达式。"""
    paths = []
    _walk(data, "$", paths)
    return paths


def _walk(value, path, paths):
    """递归遍历类 JSON 数据。"""
    paths.append(path)
    if isinstance(value, dict):
        for key in sorted(value.keys()):
            _walk(value[key], _join_key(path, key), paths)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _walk(item, "%s[%s]" % (path, index), paths)


def _join_key(path, key):
    """把字典键拼接到 JSONPath 表达式中。"""
    if SIMPLE_KEY_PATTERN.match(str(key)):
        return "%s.%s" % (path, key)
    escaped = str(key).replace("\\", "\\\\").replace("'", "\\'")
    return "%s['%s']" % (path, escaped)
