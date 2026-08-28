# -*- coding: utf-8 -*-
"""
@Author: byy
@Desc: 数据工厂执行器，负责并发轮次、顺序步骤、变量传递和结果落库。
"""

import threading
import time
from concurrent.futures import FIRST_COMPLETED
from concurrent.futures import Future
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import wait
from typing import Any
from typing import Dict
from typing import List
from typing import Optional
from typing import Tuple

from flask import Flask

from ..enums import AssertionComparator
from ..enums import AssertionValueType
from ..enums import DataFactoryIterationStatus
from ..enums import DataFactoryRunStatus
from ..enums import DataFactoryStepType
from ..enums import DetailStatus
from ..extensions import db
from ..models import DataFactory
from ..models import DataFactoryRun
from ..models import DataFactoryRunDetail
from ..models import DataFactoryRunIteration
from ..models import Environment
from ..utils.datetime_utils import now_local
from .assert_engine import assert_response
from .data_factory_service import build_execution_snapshot
from .data_factory_service import MAX_CONCURRENCY
from .data_factory_service import MAX_LOOP_COUNT
from .extractor_service import run_extractors
from .http_runner import run_http_case
from .variable_engine import build_variable_context


SECRET_HEADER_NAMES = {"authorization", "cookie", "set-cookie", "proxy-authorization"}


def create_factory_run(factory: DataFactory, data: Dict[str, Any]) -> DataFactoryRun:
    """校验临时执行参数并创建等待执行的数据工厂记录。"""
    loop_count = _parse_range_int(
        data.get("loop_count"),
        factory.default_loop_count,
        1,
        MAX_LOOP_COUNT,
        "循环次数",
    )
    concurrency = _parse_range_int(
        data.get("concurrency"),
        factory.default_concurrency,
        1,
        MAX_CONCURRENCY,
        "并发数",
    )
    environment_id = _parse_optional_int(data.get("environment_id")) or factory.environment_id
    if db.session.get(Environment, environment_id) is None:
        raise ValueError("执行环境不存在")
    snapshot = build_execution_snapshot(factory)
    if not snapshot["steps"]:
        raise ValueError("数据工厂没有可执行步骤")
    request_step_count = sum(
        1
        for item in snapshot["steps"]
        if item.get("step_type") == DataFactoryStepType.REQUEST
    )

    run = DataFactoryRun(
        factory_id=factory.id,
        factory_name=factory.name,
        project_id=factory.project_id,
        environment_id=environment_id,
        status=DataFactoryRunStatus.QUEUED,
        loop_count=loop_count,
        concurrency=concurrency,
        total_request_count=loop_count * request_step_count,
        execution_config=snapshot,
    )
    db.session.add(run)
    db.session.commit()
    return run


def execute_factory_run(app: Flask, run_id: int) -> Dict[str, Any]:
    """在应用上下文中编排数据工厂全部轮次。"""
    with app.app_context():
        try:
            return _execute_factory_run(run_id, app)
        except Exception as exc:
            db.session.rollback()
            run = db.session.get(DataFactoryRun, run_id)
            if run is not None:
                run.status = DataFactoryRunStatus.INTERRUPTED
                run.error_message = str(exc)
                run.ended_at = now_local()
                db.session.commit()
            return {"run_id": run_id, "status": DataFactoryRunStatus.INTERRUPTED, "error": str(exc)}
        finally:
            db.session.remove()


def _execute_factory_run(run_id: int, app: Flask) -> Dict[str, Any]:
    """使用有限并发执行独立轮次并汇总状态。"""
    run = db.session.get(DataFactoryRun, run_id)
    if run is None:
        raise ValueError("数据工厂执行记录不存在")
    if run.status != DataFactoryRunStatus.QUEUED:
        return {"run_id": run.id, "status": run.status}

    run.status = DataFactoryRunStatus.RUNNING
    run.started_at = now_local()
    db.session.commit()

    stop_event = threading.Event()
    next_iteration = 1
    pending: Dict[Future, int] = {}
    executor = None
    try:
        if run.concurrency == 1:
            while next_iteration <= run.loop_count:
                db.session.expire_all()
                run = db.session.get(DataFactoryRun, run_id)
                if run.cancel_requested or stop_event.is_set():
                    break
                result = _execute_iteration(run_id, next_iteration, stop_event)
                next_iteration += 1
                _merge_iteration_result(run_id, result)
        else:
            executor = ThreadPoolExecutor(max_workers=run.concurrency)
            while pending or next_iteration <= run.loop_count:
                db.session.expire_all()
                run = db.session.get(DataFactoryRun, run_id)
                if run.cancel_requested:
                    stop_event.set()

                while (
                    not stop_event.is_set()
                    and next_iteration <= run.loop_count
                    and len(pending) < run.concurrency
                ):
                    future = executor.submit(
                        _execute_iteration_with_context,
                        app,
                        run_id,
                        next_iteration,
                        stop_event,
                    )
                    pending[future] = next_iteration
                    next_iteration += 1

                if not pending:
                    break
                completed, _ = wait(list(pending.keys()), timeout=0.25, return_when=FIRST_COMPLETED)
                if not completed:
                    continue
                for future in completed:
                    pending.pop(future, None)
                    result = future.result()
                    _merge_iteration_result(run_id, result)
    finally:
        if executor is not None:
            executor.shutdown(wait=True)

    db.session.expire_all()
    run = db.session.get(DataFactoryRun, run_id)
    run.ended_at = now_local()
    if run.cancel_requested:
        run.status = DataFactoryRunStatus.CANCELLED
    elif run.failed_iteration_count == 0 and run.success_iteration_count == run.loop_count:
        run.status = DataFactoryRunStatus.SUCCESS
    elif run.success_iteration_count > 0:
        run.status = DataFactoryRunStatus.PARTIAL
    else:
        run.status = DataFactoryRunStatus.FAILED
    db.session.commit()
    return {"run_id": run.id, "status": run.status}


def _merge_iteration_result(run_id: int, result: Dict[str, Any]) -> None:
    """把单轮执行结果安全汇总到运行记录。"""
    db.session.expire_all()
    run = db.session.get(DataFactoryRun, run_id)
    run.completed_iteration_count += 1
    run.completed_request_count += result.get("request_count", 0)
    if result.get("status") == DataFactoryIterationStatus.SUCCESS:
        run.success_iteration_count += 1
    elif result.get("status") != DataFactoryIterationStatus.CANCELLED:
        run.failed_iteration_count += 1
    db.session.commit()


def _execute_iteration_with_context(
    app: Flask,
    run_id: int,
    iteration_no: int,
    stop_event: threading.Event,
) -> Dict[str, Any]:
    """在线程独立的应用上下文和数据库会话中执行一轮。"""
    with app.app_context():
        try:
            return _execute_iteration(run_id, iteration_no, stop_event)
        finally:
            db.session.remove()


def _execute_iteration(
    run_id: int,
    iteration_no: int,
    stop_event: threading.Event,
) -> Dict[str, Any]:
    """串行执行一轮中的接口，并维护本轮独立运行时变量。"""
    run = db.session.get(DataFactoryRun, run_id)
    if run is None:
        raise ValueError("数据工厂执行记录不存在")
    snapshot = run.execution_config or {}
    runtime_vars = {"factory_run_id": run.id, "iteration_no": iteration_no}
    iteration = DataFactoryRunIteration(
        run_id=run.id,
        iteration_no=iteration_no,
        status=DataFactoryIterationStatus.RUNNING,
        started_at=now_local(),
    )
    db.session.add(iteration)
    db.session.commit()

    request_count = 0
    failed = False
    error_message = ""

    for step_index, step_config in enumerate(snapshot.get("steps") or [], start=1):
        db.session.expire_all()
        current_run = db.session.get(DataFactoryRun, run_id)
        if current_run.cancel_requested or stop_event.is_set():
            error_message = "执行已取消"
            break
        step_type = step_config.get("step_type") or DataFactoryStepType.REQUEST
        if step_type == DataFactoryStepType.WAIT:
            detail_result = execute_wait_step(
                step_config,
                run_id,
                stop_event,
            )
        else:
            request_count += 1
            detail_result = execute_factory_request(
                step_config,
                current_run.project_id,
                current_run.environment_id,
                runtime_vars,
            )
        detail = DataFactoryRunDetail(
            iteration_id=iteration.id,
            step_config_id=step_config.get("id"),
            step_name=step_config.get("name") or "未命名步骤",
            step_type=step_type,
            wait_seconds=step_config.get("wait_seconds"),
            sort_order=step_config.get("sort_order") or step_index,
            status=detail_result["status"],
            method=detail_result.get("method"),
            url=detail_result.get("url"),
            error_message=detail_result.get("error_message") or None,
            request_snapshot=detail_result.get("request_snapshot") or {},
            response_snapshot=detail_result.get("response_snapshot") or {},
            assertions_detail=detail_result.get("assertions") or [],
            extractors_detail=detail_result.get("extractors") or [],
            time_taken_ms=detail_result.get("time_taken_ms"),
        )
        db.session.add(detail)
        db.session.commit()
        if not detail_result["success"]:
            failed = True
            error_message = detail_result.get("error_message") or "接口执行失败"
            break

    db.session.expire(iteration)
    current_run = db.session.get(DataFactoryRun, run_id)
    if current_run.cancel_requested:
        iteration.status = DataFactoryIterationStatus.CANCELLED
    elif failed or (stop_event.is_set() and error_message):
        iteration.status = DataFactoryIterationStatus.FAILED
    else:
        iteration.status = DataFactoryIterationStatus.SUCCESS
    iteration.error_message = error_message or None
    iteration.ended_at = now_local()
    db.session.commit()
    return {
        "iteration_no": iteration_no,
        "status": iteration.status,
        "request_count": request_count,
    }


def execute_wait_step(
    step_config: Dict[str, Any],
    run_id: int,
    stop_event: threading.Event,
) -> Dict[str, Any]:
    """可响应取消请求地执行等待步骤。"""
    wait_seconds = float(step_config.get("wait_seconds") or 0)
    started = time.monotonic()
    deadline = started + wait_seconds
    while time.monotonic() < deadline:
        db.session.expire_all()
        run = db.session.get(DataFactoryRun, run_id)
        if run is None or run.cancel_requested or stop_event.is_set():
            return {
                "success": False,
                "status": DetailStatus.SKIPPED,
                "error_message": "等待步骤已取消",
                "request_snapshot": {},
                "response_snapshot": {},
                "assertions": [],
                "extractors": [],
                "time_taken_ms": int((time.monotonic() - started) * 1000),
            }
        time.sleep(min(0.1, max(deadline - time.monotonic(), 0)))
    return {
        "success": True,
        "status": DetailStatus.PASS,
        "error_message": "",
        "request_snapshot": {},
        "response_snapshot": {},
        "assertions": [],
        "extractors": [],
        "time_taken_ms": int((time.monotonic() - started) * 1000),
    }


def execute_factory_request(
    request_config: Dict[str, Any],
    project_id: Optional[int],
    environment_id: int,
    runtime_vars: Dict[str, Any],
) -> Dict[str, Any]:
    """执行单个数据工厂接口并应用成功条件和提取器。"""
    try:
        context = build_variable_context(project_id, environment_id, runtime_vars)
        runner = run_http_case(
            {
                "method": request_config.get("method"),
                "url": request_config.get("url"),
                "params": request_config.get("params") or {},
                "headers": request_config.get("headers") or {},
                "body": request_config.get("body"),
                "body_type": request_config.get("body_type"),
                "timeout_seconds": request_config.get("timeout_seconds") or 30,
            },
            context,
        )
        response_context = runner.get("response_context") or {}
        status_assertion = _default_status_assertion(response_context)
        assertions = [status_assertion]
        assertions.extend(
            assert_response(request_config.get("assertions") or [], response_context)
        )
        extractors = run_extractors(
            request_config.get("extractors") or [],
            response_context,
            runtime_vars,
        )
        success = bool(runner.get("success")) and all(
            item.get("passed") for item in assertions
        ) and all(item.get("success") for item in extractors)
        request_snapshot = _mask_request_snapshot(runner.get("request") or {})
        response_snapshot = _response_snapshot(
            runner.get("response"),
            response_context,
        )
        return {
            "success": success,
            "status": DetailStatus.PASS if success else DetailStatus.FAIL,
            "method": request_snapshot.get("method") or request_config.get("method"),
            "url": request_snapshot.get("url") or request_config.get("url"),
            "error_message": _failure_reason(runner, assertions, extractors),
            "request_snapshot": request_snapshot,
            "response_snapshot": response_snapshot,
            "assertions": assertions,
            "extractors": extractors,
            "time_taken_ms": response_context.get("elapsed_ms"),
        }
    except Exception as exc:
        return {
            "success": False,
            "status": DetailStatus.ERROR,
            "method": request_config.get("method"),
            "url": request_config.get("url"),
            "error_message": str(exc),
            "request_snapshot": {},
            "response_snapshot": {},
            "assertions": [],
            "extractors": [],
            "time_taken_ms": None,
        }


def _default_status_assertion(response_context: Dict[str, Any]) -> Dict[str, Any]:
    """构造数据工厂默认的 HTTP 2xx 成功条件。"""
    status_code = response_context.get("status_code")
    passed = type(status_code) is int and 200 <= status_code < 300
    return {
        "name": "HTTP 状态码为 2xx",
        "source": "status_code",
        "passed": passed,
        "actual": status_code,
        "expected": "200-299",
        "actual_type": "int" if type(status_code) is int else "null",
        "expected_type": "range",
        "value_type": AssertionValueType.INTEGER,
        "comparator": AssertionComparator.GREATER_OR_EQUAL,
        "comparator_label": "属于 200-299",
        "message": "状态码符合 2xx" if passed else "状态码不是 2xx",
    }


def _failure_reason(
    runner: Dict[str, Any],
    assertions: List[Dict[str, Any]],
    extractors: List[Dict[str, Any]],
) -> str:
    """选择接口执行失败时最有价值的原因。"""
    if not runner.get("success"):
        return runner.get("error") or "HTTP 请求失败"
    for item in assertions:
        if not item.get("passed"):
            return item.get("message") or "成功条件未通过"
    for item in extractors:
        if not item.get("success"):
            return item.get("message") or "提取失败"
    return ""


def _mask_request_snapshot(snapshot: Dict[str, Any]) -> Dict[str, Any]:
    """隐藏请求快照中的常见认证请求头。"""
    result = dict(snapshot or {})
    result["headers"] = _mask_headers(result.get("headers") or {})
    return result


def _mask_headers(headers: Dict[str, Any]) -> Dict[str, Any]:
    """对敏感请求头值进行脱敏。"""
    return {
        key: "******" if str(key).lower() in SECRET_HEADER_NAMES else value
        for key, value in headers.items()
    }


def _response_snapshot(
    response: Optional[Dict[str, Any]],
    response_context: Dict[str, Any],
) -> Dict[str, Any]:
    """构造包含完整响应正文的执行快照。"""
    response = response or {}
    body = str(response.get("body") or "")
    return {
        "status_code": response.get("status_code", response_context.get("status_code")),
        "headers": _mask_headers(response.get("headers") or response_context.get("headers") or {}),
        "body": body,
        "body_type": response_context.get("body_type"),
        "body_length": response_context.get("body_length"),
        "elapsed_ms": response_context.get("elapsed_ms"),
        "error": response_context.get("error"),
    }


def _parse_range_int(
    value: Any,
    default: int,
    minimum: int,
    maximum: int,
    label: str,
) -> int:
    """解析并校验限定范围内的整数。"""
    try:
        parsed = int(default if value in (None, "") else value)
    except (TypeError, ValueError):
        raise ValueError("%s必须是整数" % label)
    if parsed < minimum or parsed > maximum:
        raise ValueError("%s必须在 %s 到 %s 之间" % (label, minimum, maximum))
    return parsed


def _parse_optional_int(value: Any) -> Optional[int]:
    """解析允许为空的整数。"""
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        raise ValueError("执行环境 ID 格式不正确")
