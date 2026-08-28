# -*- coding: utf-8 -*-
"""
@Author: byy
@Desc: 用例执行分发服务，根据协议类型调用 HTTP 或 WebSocket 执行器。
"""

from typing import Any
from typing import Callable
from typing import Dict
from typing import List
from typing import Optional

from ..enums import InterfaceType
from ..extensions import db
from ..models import SuiteCase
from ..models import TestCase
from .assert_engine import assert_response
from .http_runner import run_http_case
from .jsonpath_service import list_jsonpaths
from .extractor_service import run_extractors
from .variable_engine import build_variable_context
from .websocket_runner import run_websocket_case


def run_case(
    case_id: int,
    environment_id: int,
    runtime_vars: Optional[Dict[str, Any]] = None,
    debug: bool = False,
    event_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> Dict[str, Any]:
    """执行已保存的测试用例并返回统一结果。"""
    test_case = db.session.get(TestCase, case_id)
    if test_case is None:
        raise ValueError("测试用例不存在")
    return _run_loaded_case(
        test_case,
        environment_id,
        runtime_vars,
        debug=debug,
        event_callback=event_callback,
    )


def run_suite_case_step(
    suite_case: SuiteCase,
    environment_id: int,
    runtime_vars: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """按集合步骤配置执行用例实例。"""
    test_case = suite_case.case
    if test_case is None:
        raise ValueError("集合步骤未关联有效用例")
    return _run_loaded_case(
        test_case,
        environment_id,
        runtime_vars,
        debug=False,
        suite_case=suite_case,
    )


def _run_loaded_case(
    test_case: TestCase,
    environment_id: int,
    runtime_vars: Optional[Dict[str, Any]] = None,
    debug: bool = False,
    suite_case: Optional[SuiteCase] = None,
    event_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> Dict[str, Any]:
    """执行已加载用例，可叠加集合步骤覆盖配置。"""
    if test_case.interface is None:
        raise ValueError("测试用例未关联接口")

    runtime_vars = dict(runtime_vars or {})
    context = build_variable_context(test_case.project_id, environment_id, runtime_vars)
    interface = test_case.interface
    effective_case = _build_effective_case(test_case, suite_case)

    if interface.interface_type == InterfaceType.WEBSOCKET:
        runner_result = run_websocket_case(
            _build_ws_case(effective_case),
            context,
            event_callback=event_callback,
        )
        runtime_vars.update(context.get("runtime_vars") or {})
    else:
        runner_result = run_http_case(_build_http_case(effective_case), context)

    response_context = runner_result.get("response_context") or {}
    assertion_results = assert_response(effective_case.get("assertions") or [], response_context)
    extractor_results = run_extractors(
        effective_case.get("extractors") or [],
        response_context,
        runtime_vars,
    )

    success = bool(runner_result.get("success")) and all(
        item.get("passed") for item in assertion_results
    ) and all(item.get("success") for item in extractor_results)

    result = {
        "success": success,
        "case_id": test_case.id,
        "case_name": effective_case.get("case_name") or test_case.name,
        "base_case_name": test_case.name,
        "suite_case_id": suite_case.id if suite_case else None,
        "step_name": suite_case.step_name if suite_case else "",
        "interface_id": interface.id,
        "interface_name": interface.name,
        "interface_type": interface.interface_type,
        "runner": runner_result,
        "assertions": assertion_results,
        "extractors": extractor_results,
        "runtime_vars": runtime_vars,
    }

    if debug:
        result["jsonpaths"] = _debug_jsonpaths(response_context)
    return result


def _build_effective_case(
    test_case: TestCase,
    suite_case: Optional[SuiteCase] = None,
) -> Dict[str, Any]:
    """合成接口默认配置、基础用例配置和集合步骤覆盖配置。"""
    interface = test_case.interface
    params = dict(interface.params_template or {})
    params.update(test_case.request_params or {})
    headers = dict(interface.headers_template or {})
    headers.update(test_case.headers_override or {})

    body = test_case.body_override
    if body in (None, {}, [], ""):
        body = interface.body_template or {}

    assertions = test_case.assertions or []
    extractors = test_case.extractors or []
    ws_steps = test_case.ws_steps or []
    ws_config = dict(interface.ws_config or {})
    ws_config_override = dict(test_case.ws_config_override or {})
    interface_url = ws_config_override.pop("url", None) or interface.url
    ws_config.update(ws_config_override)
    timeout_seconds = test_case.timeout_seconds
    case_name = test_case.name

    if suite_case is not None:
        if suite_case.method_override:
            interface_method = suite_case.method_override
        else:
            interface_method = interface.method
        if suite_case.url_override:
            interface_url = suite_case.url_override
        elif interface.interface_type != InterfaceType.WEBSOCKET:
            interface_url = interface.url
        if suite_case.body_type_override:
            interface_body_type = suite_case.body_type_override
        else:
            interface_body_type = interface.body_type
        if suite_case.request_params_override is not None:
            params = suite_case.request_params_override or {}
        if suite_case.headers_override is not None:
            headers = suite_case.headers_override or {}
        if suite_case.body_override is not None:
            body = suite_case.body_override
        if suite_case.assertions_override is not None:
            assertions = suite_case.assertions_override or []
        if suite_case.extractors_override is not None:
            extractors = suite_case.extractors_override or []
        if suite_case.ws_steps_override is not None:
            ws_steps = suite_case.ws_steps_override or []
        if suite_case.timeout_seconds_override:
            timeout_seconds = int(suite_case.timeout_seconds_override)
        if suite_case.step_name:
            case_name = suite_case.step_name
    else:
        interface_method = interface.method
        if interface.interface_type != InterfaceType.WEBSOCKET:
            interface_url = interface.url
        interface_body_type = interface.body_type

    return {
        "method": interface_method,
        "url": interface_url,
        "headers": headers,
        "params": params,
        "body": body,
        "body_type": interface_body_type,
        "timeout_seconds": timeout_seconds,
        "assertions": assertions,
        "extractors": extractors,
        "ws_steps": ws_steps,
        "ws_config": ws_config,
        "case_name": case_name,
    }


def _build_http_case(effective_case: Dict[str, Any]) -> Dict[str, Any]:
    """根据最终合成配置构造 HTTP 执行器入参。"""
    return {
        "method": effective_case.get("method"),
        "url": effective_case.get("url"),
        "headers": effective_case.get("headers") or {},
        "params": effective_case.get("params") or {},
        "body": effective_case.get("body") or {},
        "body_type": effective_case.get("body_type"),
        "timeout_seconds": effective_case.get("timeout_seconds"),
    }


def _build_ws_case(effective_case: Dict[str, Any]) -> Dict[str, Any]:
    """根据最终合成配置构造 WebSocket 执行器入参。"""
    return {
        "url": effective_case.get("url"),
        "headers": effective_case.get("headers") or {},
        "ws_steps": effective_case.get("ws_steps") or [],
        "ws_config": effective_case.get("ws_config") or {},
        "timeout_seconds": effective_case.get("timeout_seconds"),
    }


def _debug_jsonpaths(response_context: Dict[str, Any]) -> List[str]:
    """返回调试模式下可选择的 JSONPath 表达式。"""
    body_json = response_context.get("body_json")
    if body_json is None:
        return []
    return list_jsonpaths(body_json)
