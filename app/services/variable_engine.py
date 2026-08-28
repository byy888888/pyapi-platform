# -*- coding: utf-8 -*-
"""
@Author: byy
@Desc: 变量解析引擎，负责替换环境变量、运行时变量和内置函数表达式。
"""

import re

from ..models import Environment
from ..models import GlobalVariable
from .hook_functions import execute_hook_function
from .hook_functions import HookFunctionError


GLOBAL_PATTERN = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}")
FUNCTION_PATTERN = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\(([\s\S]*)\)$")


class VariableReplacementError(Exception):
    """变量引用无法解析时抛出的异常。"""

    def __init__(self, missing_variables):
        """创建变量替换异常并记录便于定位问题的上下文。"""
        self.missing_variables = sorted(set(missing_variables))
        message = "未找到变量: %s" % ", ".join(self.missing_variables)
        super(VariableReplacementError, self).__init__(message)


def build_variable_context(project_id, environment_id, runtime_vars=None):
    """独立于环境加载启用状态的全局变量和项目变量。"""
    query = GlobalVariable.query.filter(
        GlobalVariable.is_active.is_(True),
    ).filter(
        (GlobalVariable.project_id.is_(None)) | (GlobalVariable.project_id == project_id)
    )
    environment = Environment.query.get(environment_id) if environment_id else None

    global_vars = {}
    project_vars = {}
    for item in query.order_by(GlobalVariable.project_id.asc(), GlobalVariable.id.asc()).all():
        if item.project_id is None:
            global_vars[item.var_key] = item.var_value
        else:
            project_vars[item.var_key] = item.var_value

    merged_global_vars = dict(global_vars)
    merged_global_vars.update(project_vars)
    environment_context = {}
    if environment is not None:
        environment_context = {
            "id": environment.id,
            "name": environment.name,
            "base_url": environment.base_url or "",
        }
    if environment_context.get("base_url"):
        merged_global_vars["base_url"] = environment_context["base_url"]
    return {
        "global_vars": merged_global_vars,
        "runtime_vars": dict(runtime_vars or {}),
        "environment": environment_context,
    }


def replace_variables(value, context):
    """递归替换字符串、列表和字典中的变量。"""
    missing = []
    replaced = _replace_value(value, context or {}, missing)
    if missing:
        raise VariableReplacementError(missing)
    return replaced


def _replace_value(value, context, missing):
    """按值类型替换变量。"""
    if isinstance(value, str):
        return _replace_string(value, context, missing)
    if isinstance(value, list):
        return [_replace_value(item, context, missing) for item in value]
    if isinstance(value, tuple):
        return tuple(_replace_value(item, context, missing) for item in value)
    if isinstance(value, dict):
        return {
            key: _replace_value(item, context, missing)
            for key, item in value.items()
        }
    return value


def _replace_string(value, context, missing):
    """先替换全局/项目变量，再替换运行时变量和钩子函数。"""
    global_vars = context.get("global_vars", {})

    def replace_global(match):
        """兼容旧调用方式，替换文本中的全局变量。"""
        name = match.group(1)
        if name not in global_vars:
            missing.append("{{%s}}" % name)
            return match.group(0)
        return str(global_vars[name])

    value = GLOBAL_PATTERN.sub(replace_global, value)
    return _replace_runtime_expressions(value, context, missing)


def _replace_runtime_expressions(value, context, missing):
    """扫描替换 ${变量} 和 ${函数(...)} 表达式。"""
    text = str(value)
    result = []
    index = 0
    while index < len(text):
        start = text.find("${", index)
        if start < 0:
            result.append(text[index:])
            break
        result.append(text[index:start])
        end = _find_expression_end(text, start + 2)
        if end < 0:
            result.append(text[start:])
            break
        expression = text[start + 2:end].strip()
        result.append(str(_resolve_runtime_expression(expression, context, missing)))
        index = end + 1
    return "".join(result)


def _find_expression_end(text, start_index):
    """查找 ${ 表达式对应的右花括号，支持嵌套和引号。"""
    depth = 0
    quote = None
    escaped = False
    index = start_index
    while index < len(text):
        char = text[index]
        if escaped:
            escaped = False
            index += 1
            continue
        if char == "\\" and quote:
            escaped = True
            index += 1
            continue
        if quote:
            if char == quote:
                quote = None
            index += 1
            continue
        if char in ("'", '"'):
            quote = char
            index += 1
            continue
        if text.startswith("${", index):
            depth += 1
            index += 2
            continue
        if char == "}":
            if depth == 0:
                return index
            depth -= 1
        index += 1
    return -1


def _resolve_runtime_expression(expression, context, missing):
    """根据表达式内容解析运行时变量或执行钩子函数。"""
    function_match = FUNCTION_PATTERN.match(expression)
    if function_match:
        name = function_match.group(1)
        missing_count = len(missing)
        args = _parse_function_args(function_match.group(2), context, missing)
        if len(missing) > missing_count:
            return "${%s}" % expression
        try:
            return execute_hook_function(name, args)
        except HookFunctionError:
            raise
        except Exception as exc:
            raise HookFunctionError("%s 执行失败: %s" % (name, exc))

    runtime_vars = context.get("runtime_vars", {})
    if expression not in runtime_vars:
        missing.append("${%s}" % expression)
        return "${%s}" % expression
    return runtime_vars[expression]


def _parse_function_args(args_text, context, missing):
    """解析钩子函数参数，支持引号、逗号和嵌套变量。"""
    args = []
    current = []
    quote = None
    escaped = False
    nested = 0
    for index, char in enumerate(args_text or ""):
        if escaped:
            current.append(char)
            escaped = False
            continue
        if char == "\\" and quote:
            current.append(char)
            escaped = True
            continue
        if quote:
            current.append(char)
            if char == quote:
                quote = None
            continue
        if char in ("'", '"'):
            quote = char
            current.append(char)
            continue
        if args_text.startswith("${", index):
            nested += 1
            current.append(char)
            continue
        if char == "}" and nested:
            nested -= 1
            current.append(char)
            continue
        if char == "," and nested == 0:
            args.append(_normalize_arg("".join(current), context, missing))
            current = []
            continue
        current.append(char)
    if current or (args_text or "").strip():
        args.append(_normalize_arg("".join(current), context, missing))
    return args


def _normalize_arg(value, context, missing):
    """去掉参数外层引号并继续替换参数内变量。"""
    text = (value or "").strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in ("'", '"'):
        text = text[1:-1]
    return _replace_string(text, context, missing)
