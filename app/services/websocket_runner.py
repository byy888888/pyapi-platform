# -*- coding: utf-8 -*-
"""
@Author: byy
@Desc: WebSocket 用例执行器，负责连接、步骤执行、等待校验和关闭连接。
"""

import time
from typing import Any
from typing import Callable
from typing import Dict
from typing import List
from typing import Optional

from .websocket_session import elapsed_ms
from .websocket_session import WebSocketSession


def run_websocket_case(
    case: Dict[str, Any],
    context: Optional[Dict[str, Any]],
    event_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> Dict[str, Any]:
    """执行完整 WebSocket 会话，并返回统一步骤、消息和响应结果。"""
    started_ns = time.perf_counter_ns()
    runtime_vars = (context or {}).setdefault("runtime_vars", {})
    timeout_seconds = _positive_number(case.get("timeout_seconds"), 60.0)
    deadline = time.monotonic() + timeout_seconds
    session = WebSocketSession(
        str(case.get("url") or ""),
        case.get("ws_config") or {"headers": case.get("headers") or {}},
        context,
        event_callback=event_callback,
    )
    step_results: List[Dict[str, Any]] = []
    last_send_sequence = 0
    last_send_ns: Optional[int] = None
    last_response_context: Dict[str, Any] = {}
    error_message = ""

    try:
        connect_started_ns = time.perf_counter_ns()
        connection_result = session.connect()
        step_results.append(
            {
                "type": "connect",
                "name": "建立连接",
                "passed": True,
                "message": "连接成功",
                "time_taken_ms": elapsed_ms(connect_started_ns),
                "data": connection_result,
            }
        )
        last_send_sequence, last_send_ns = _find_latest_send(session)

        for index, raw_step in enumerate(case.get("ws_steps") or []):
            step = normalize_ws_step(raw_step or {}, index)
            if step.get("type") == "connect":
                continue
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("WebSocket 用例总执行超时")
            step_started_ns = time.perf_counter_ns()
            step_type = step.get("type")

            if step_type == "send":
                event = session.send(
                    step.get("content", ""),
                    step.get("message_type") or "text",
                )
                last_send_sequence = int(event.get("sequence") or 0)
                last_send_ns = event.get("sent_ns")
                result = _base_step_result(step, step_started_ns, True, "发送成功")
                result["data"] = event.get("data")

            elif step_type == "wait_assert":
                wait_timeout = min(
                    _positive_number(step.get("timeout_seconds"), 10.0),
                    remaining,
                )
                after_sequence = last_send_sequence or session.current_sequence()
                verification = session.wait_and_assert(
                    step,
                    after_sequence,
                    wait_timeout,
                    runtime_vars,
                    started_ns=last_send_ns or step_started_ns,
                )
                result = _base_step_result(
                    step,
                    step_started_ns,
                    bool(verification.get("passed")),
                    str(verification.get("message") or "消息校验失败"),
                )
                result.update(verification)
                matched = verification.get("matched_message") or {}
                if matched:
                    last_send_sequence = int(matched.get("sequence") or last_send_sequence)
                    last_response_context = verification.get("response_context") or {}

            elif step_type == "sleep":
                seconds = min(
                    max(0.0, float(step.get("seconds") or 0)),
                    remaining,
                )
                time.sleep(seconds)
                result = _base_step_result(step, step_started_ns, True, "等待完成")
                result["seconds"] = seconds

            elif step_type == "close":
                session.close("用例步骤主动断开")
                result = _base_step_result(step, step_started_ns, True, "连接已关闭")

            else:
                result = _base_step_result(
                    step,
                    step_started_ns,
                    False,
                    "不支持的 WebSocket 步骤：%s" % step_type,
                )

            step_results.append(result)
            if not result.get("passed") and step.get("failure_action", "stop") != "continue":
                break
    except Exception as exc:
        error_message = str(exc)
        step_results.append(
            {
                "type": "error",
                "name": "执行异常",
                "passed": False,
                "message": error_message,
                "time_taken_ms": elapsed_ms(started_ns),
            }
        )
    finally:
        session.close("用例执行结束")

    success = bool(step_results) and all(item.get("passed") for item in step_results)
    messages = session.messages_after(0)
    return {
        "success": success,
        "connected": any(item.get("type") == "connect" and item.get("passed") for item in step_results),
        "closed": session.closed,
        "error_message": error_message,
        "connection_time_ms": session.connection_time_ms,
        "steps": step_results,
        "ws_messages": messages,
        "response_context": dict(
            last_response_context,
            ws_messages=messages,
            time_taken_ms=elapsed_ms(started_ns),
        ),
    }


def normalize_ws_step(step: Dict[str, Any], index: int = 0) -> Dict[str, Any]:
    """将旧版 action 步骤转换为新版简单步骤结构。"""
    normalized = dict(step or {})
    step_type = normalized.get("type") or normalized.get("action")
    aliases = {"receive_assert": "wait_assert", "wait": "sleep"}
    step_type = aliases.get(step_type, step_type)
    normalized["type"] = step_type
    normalized.setdefault("name", _default_step_name(step_type, index))
    if step_type == "send":
        normalized.setdefault("content", normalized.get("message", ""))
    if step_type == "wait_assert" and "target" not in normalized:
        expected = normalized.get("expected", "")
        normalized["target"] = {
            "mode": "condition" if expected not in (None, "") else "next",
            "conditions": (
                [{
                    "name": "消息包含期望内容",
                    "source": "body_text",
                    "comparator": "contains",
                    "value_type": "string",
                    "expected": expected,
                }]
                if expected not in (None, "")
                else []
            ),
            "consume": True,
        }
        normalized.setdefault("assertions", [])
        normalized.setdefault("extractors", [])
    return normalized


def _base_step_result(
    step: Dict[str, Any],
    started_ns: int,
    passed: bool,
    message: str,
) -> Dict[str, Any]:
    """构造统一的 WebSocket 步骤结果。"""
    return {
        "type": step.get("type"),
        "action": step.get("type"),
        "name": step.get("name"),
        "passed": passed,
        "message": message,
        "time_taken_ms": elapsed_ms(started_ns),
    }


def _find_latest_send(session: WebSocketSession) -> tuple:
    """查找连接后自动发送消息，以便随后等待消息统计响应耗时。"""
    return session.latest_send_marker()


def _default_step_name(step_type: str, index: int) -> str:
    """返回步骤的中文默认名称。"""
    labels = {
        "connect": "建立连接",
        "send": "发送消息",
        "wait_assert": "等待并校验消息",
        "sleep": "等待时间",
        "close": "断开连接",
    }
    return "%s %s" % (index + 1, labels.get(step_type, "WebSocket 步骤"))


def _positive_number(value: Any, default: float) -> float:
    """把配置解析为正数，无效时使用默认值。"""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if number > 0 else default
