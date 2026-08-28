# -*- coding: utf-8 -*-
"""
@Author: byy
@Desc: 集合执行器，负责按集合类型运行用例、共享变量并记录执行历史。
"""

from ..enums import DetailStatus
from ..enums import HistoryStatus
from ..enums import SuiteType
from ..enums import TriggerType
from ..extensions import db
from ..models import ExecutionDetail
from ..models import ExecutionHistory
from ..models import Suite
from ..models import SuiteCase
from .case_runner import run_suite_case_step
from .report_service import refresh_history_report
from ..utils.datetime_utils import now_local


def run_suite(suite_id, environment_id, history_id=None):
    """执行集合，写入历史和明细，并返回汇总数据。"""
    suite = db.session.get(Suite, suite_id)
    if suite is None:
        raise ValueError("测试集合不存在")

    history = _get_or_create_history(history_id, suite, environment_id)
    runtime_vars = {}
    details = []
    interrupted = False
    total_count = 0
    success_count = 0
    fail_count = 0
    error_count = 0

    suite_cases = SuiteCase.query.filter_by(suite_id=suite.id).order_by(SuiteCase.sort_order.asc()).all()

    for index, suite_case in enumerate(suite_cases):
        total_count += 1
        if not suite_case.is_active:
            skipped_detail = _write_skipped_detail(
                history,
                suite,
                suite_case,
                "集合步骤已禁用，跳过执行",
                suite_case.sort_order,
            )
            details.append(_serialize_detail(skipped_detail))
            continue

        case = suite_case.case
        try:
            result = run_suite_case_step(suite_case, environment_id, runtime_vars=runtime_vars)
            runtime_vars.update(result.get("runtime_vars") or {})
            status = DetailStatus.PASS if result.get("success") else DetailStatus.FAIL
            if status == DetailStatus.PASS:
                success_count += 1
            else:
                fail_count += 1
            detail = _write_detail(history, suite, suite_case, result, status, suite_case.sort_order)
            details.append(_serialize_detail(detail))
        except Exception as exc:
            error_count += 1
            status = DetailStatus.ERROR
            detail = _write_error_detail(history, suite, suite_case, str(exc), suite_case.sort_order)
            details.append(_serialize_detail(detail))

        if suite.suite_type == SuiteType.SCENE and status != DetailStatus.PASS:
            interrupted = True
            skipped_cases = suite_cases[index + 1 :]
            for skipped in skipped_cases:
                total_count += 1
                skipped_detail = _write_skipped_detail(
                    history,
                    suite,
                    skipped,
                    "场景集合前置用例失败，后续用例跳过",
                    skipped.sort_order,
                )
                details.append(_serialize_detail(skipped_detail))
            break

    history.end_time = now_local()
    history.status = HistoryStatus.FINISHED
    history.total_count = total_count
    history.success_count = success_count
    history.fail_count = fail_count
    history.error_count = error_count
    history.interrupted = interrupted
    history.summary = {
        "suite_id": suite.id,
        "suite_name": suite.name,
        "suite_type": suite.suite_type,
        "total_count": total_count,
        "success_count": success_count,
        "fail_count": fail_count,
        "error_count": error_count,
        "interrupted": interrupted,
    }
    db.session.commit()
    refresh_history_report(history.id)

    return {
        "history_id": history.id,
        "suite_id": suite.id,
        "suite_name": suite.name,
        "suite_type": suite.suite_type,
        "total_count": total_count,
        "success_count": success_count,
        "fail_count": fail_count,
        "error_count": error_count,
        "interrupted": interrupted,
        "runtime_vars": runtime_vars,
        "details": details,
    }


def _get_or_create_history(history_id, suite, environment_id):
    """加载或创建执行历史。"""
    if history_id:
        history = db.session.get(ExecutionHistory, history_id)
        if history is None:
            raise ValueError("执行历史不存在")
        return history

    history = ExecutionHistory(
        task_id=None,
        task_name=suite.name,
        trigger_type=TriggerType.MANUAL,
        environment_id=environment_id,
        start_time=now_local(),
        status=HistoryStatus.RUNNING,
        summary={},
    )
    db.session.add(history)
    db.session.flush()
    return history


def _write_detail(history, suite, suite_case, result, status, sort_order):
    """写入一条正常执行明细。"""
    case = suite_case.case
    runner = result.get("runner") or {}
    request = runner.get("request")
    response = runner.get("response")
    ws_messages = runner.get("ws_messages") or []
    response_context = runner.get("response_context") or {}
    is_websocket = result.get("interface_type") == "websocket"
    ws_assertions = _flatten_ws_step_results(runner.get("steps") or [], "assertions")
    ws_extractors = _flatten_ws_step_results(runner.get("steps") or [], "extractors")
    detail = ExecutionDetail(
        history_id=history.id,
        suite_id=suite.id,
        suite_name=suite.name,
        case_id=case.id,
        case_name=result.get("case_name") or case.name,
        interface_id=case.interface.id if case.interface else None,
        interface_name=case.interface.name if case.interface else "",
        interface_type=result.get("interface_type"),
        method=(request or {}).get("method", case.interface.method if case.interface else ""),
        url=(request or {}).get("url", case.interface.url if case.interface else ""),
        status=status,
        error_message=_failure_reason(result) if status != DetailStatus.PASS else "",
        request_snapshot=(
            {"steps": runner.get("steps") or []}
            if is_websocket
            else (request or {})
        ),
        response_snapshot=(
            {
                "connected": runner.get("connected"),
                "closed": runner.get("closed"),
                "connection_time_ms": runner.get("connection_time_ms"),
                "error_message": runner.get("error_message") or "",
            }
            if is_websocket
            else _snapshot_response(response, response_context)
        ),
        assertions_detail=(result.get("assertions") or []) + ws_assertions,
        extractors_detail=(result.get("extractors") or []) + ws_extractors,
        ws_messages=ws_messages,
        time_taken_ms=response_context.get("elapsed_ms", response_context.get("time_taken_ms")),
        sort_order=sort_order,
    )
    db.session.add(detail)
    db.session.flush()
    return detail


def _write_error_detail(history, suite, suite_case, error_message, sort_order):
    """写入一条异常执行明细。"""
    case = suite_case.case
    detail = ExecutionDetail(
        history_id=history.id,
        suite_id=suite.id,
        suite_name=suite.name,
        case_id=case.id,
        case_name=suite_case.step_name or case.name,
        interface_id=case.interface.id if case.interface else None,
        interface_name=case.interface.name if case.interface else "",
        interface_type=case.interface.interface_type if case.interface else "",
        method=case.interface.method if case.interface else "",
        url=case.interface.url if case.interface else "",
        status=DetailStatus.ERROR,
        error_message=error_message,
        request_snapshot={},
        response_snapshot={},
        assertions_detail=[],
        extractors_detail=[],
        ws_messages=[],
        sort_order=sort_order,
    )
    db.session.add(detail)
    db.session.flush()
    return detail


def _write_skipped_detail(history, suite, suite_case, message, sort_order):
    """写入一条跳过执行明细。"""
    case = suite_case.case
    detail = ExecutionDetail(
        history_id=history.id,
        suite_id=suite.id,
        suite_name=suite.name,
        case_id=case.id,
        case_name=suite_case.step_name or case.name,
        interface_id=case.interface.id if case.interface else None,
        interface_name=case.interface.name if case.interface else "",
        interface_type=case.interface.interface_type if case.interface else "",
        method=case.interface.method if case.interface else "",
        url=case.interface.url if case.interface else "",
        status=DetailStatus.SKIPPED,
        error_message=message,
        request_snapshot={},
        response_snapshot={},
        assertions_detail=[],
        extractors_detail=[],
        ws_messages=[],
        sort_order=sort_order,
    )
    db.session.add(detail)
    db.session.flush()
    return detail


def _snapshot_response(response, response_context):
    """构造精简的响应快照。"""
    if response:
        return {
            "status_code": response.get("status_code"),
            "headers": response.get("headers") or {},
            "body": response.get("body") or "",
            "elapsed_ms": response.get("elapsed_ms"),
        }
    return {
        "status_code": response_context.get("status_code"),
        "body_type": response_context.get("body_type"),
        "body_length": response_context.get("body_length"),
        "elapsed_ms": response_context.get("elapsed_ms", response_context.get("time_taken_ms")),
        "error": response_context.get("error"),
    }


def _failure_reason(result):
    """选择更易读的失败原因。"""
    for item in result.get("assertions") or []:
        if not item.get("passed"):
            return item.get("message") or "断言失败"
    for item in result.get("extractors") or []:
        if not item.get("success"):
            return item.get("message") or "提取失败"
    runner = result.get("runner") or {}
    for step in runner.get("steps") or []:
        if not step.get("passed"):
            return step.get("message") or "WebSocket 步骤失败"
    return runner.get("error_message") or runner.get("error") or "用例执行失败"


def _flatten_ws_step_results(steps: list, field_name: str) -> list:
    """把 WebSocket 等待步骤中的断言或提取结果展开到报告明细。"""
    results = []
    for step in steps or []:
        for item in step.get(field_name) or []:
            result = dict(item)
            result["step_name"] = step.get("name") or "等待并校验消息"
            results.append(result)
    return results


def _truncate(value, max_length):
    """截断过长文本。"""
    text = str(value)
    if len(text) <= max_length:
        return text
    return text[:max_length] + "...[truncated]"


def _serialize_detail(detail):
    """序列化执行明细用于 API 响应。"""
    return {
        "id": detail.id,
        "case_id": detail.case_id,
        "case_name": detail.case_name,
        "interface_name": detail.interface_name,
        "interface_type": detail.interface_type,
        "method": detail.method,
        "url": detail.url,
        "status": detail.status,
        "error_message": detail.error_message or "",
        "request_snapshot": detail.request_snapshot or {},
        "response_snapshot": detail.response_snapshot or {},
        "assertions_detail": detail.assertions_detail or [],
        "extractors_detail": detail.extractors_detail or [],
        "ws_messages": detail.ws_messages or [],
        "time_taken_ms": detail.time_taken_ms,
        "sort_order": detail.sort_order,
    }
