# -*- coding: utf-8 -*-
"""
@Author: byy
@Desc: 数据工厂配置服务，负责校验、保存和组装接口及等待步骤。
"""

from typing import Any
from typing import Dict
from typing import List
from typing import Optional
from typing import Tuple
from urllib.parse import urlsplit

from ..enums import BodyType
from ..enums import DataFactorySourceType
from ..enums import DataFactoryStepType
from ..enums import HttpMethod
from ..enums import InterfaceType
from ..extensions import db
from ..models import DataFactory
from ..models import DataFactoryRun
from ..models import DataFactoryStep
from ..models import Environment
from ..models import Interface
from ..models import Project
from .assert_engine import normalize_assertion_definitions
from .assert_engine import validate_assertion_definitions


MAX_LOOP_COUNT = 10000
MAX_CONCURRENCY = 10
MAX_TIMEOUT_SECONDS = 120
MAX_WAIT_SECONDS = 3600


def build_factory(
    factory: DataFactory,
    data: Dict[str, Any],
) -> Tuple[DataFactory, List[Dict[str, Any]], Optional[str]]:
    """校验提交数据并填充数据工厂基础字段。"""
    name = str(data.get("name") or "").strip()
    project_id = parse_optional_int(data.get("project_id"))
    environment_id = parse_optional_int(data.get("environment_id"))
    loop_count = parse_int(data.get("default_loop_count"), 1)
    concurrency = parse_int(data.get("default_concurrency"), 1)
    steps = data.get("steps") or []

    if not name:
        return factory, steps, "数据工厂名称不能为空"
    if project_id is not None and db.session.get(Project, project_id) is None:
        return factory, steps, "所属项目不存在"
    if environment_id is None:
        return factory, steps, "默认执行环境不能为空"
    if db.session.get(Environment, environment_id) is None:
        return factory, steps, "默认执行环境不存在"
    if loop_count < 1 or loop_count > MAX_LOOP_COUNT:
        return factory, steps, "默认生成次数必须在 1 到 %s 之间" % MAX_LOOP_COUNT
    if concurrency < 1 or concurrency > MAX_CONCURRENCY:
        return factory, steps, "默认并发数必须在 1 到 %s 之间" % MAX_CONCURRENCY
    step_error = validate_factory_steps(project_id, steps)
    if step_error:
        return factory, steps, step_error

    factory.project_id = project_id
    factory.environment_id = environment_id
    factory.name = name
    factory.description = str(data.get("description") or "").strip() or None
    factory.default_loop_count = loop_count
    factory.default_concurrency = concurrency
    return factory, steps, None


def validate_factory_steps(
    project_id: Optional[int],
    steps: List[Dict[str, Any]],
) -> Optional[str]:
    """校验数据工厂图形流程中的全部步骤。"""
    if not isinstance(steps, list) or not steps:
        return "请至少添加一个步骤"
    for index, step_config in enumerate(steps, start=1):
        if not isinstance(step_config, dict):
            return "第 %s 个步骤格式不正确" % index
        error = validate_step_config(project_id, step_config)
        if error:
            return "第 %s 个步骤：%s" % (index, error)
    return None


def validate_step_config(
    project_id: Optional[int],
    step_config: Dict[str, Any],
) -> Optional[str]:
    """按步骤类型校验接口或等待步骤配置。"""
    step_type = step_config.get("step_type") or DataFactoryStepType.REQUEST
    if step_type not in DataFactoryStepType.VALUES:
        return "步骤类型不支持"
    if step_type == DataFactoryStepType.WAIT:
        if not str(step_config.get("name") or "").strip():
            return "步骤名称不能为空"
        wait_seconds = parse_float(step_config.get("wait_seconds"), 0)
        if wait_seconds < 0.1 or wait_seconds > MAX_WAIT_SECONDS:
            return "等待时长必须在 0.1 到 %s 秒之间" % MAX_WAIT_SECONDS
        return None
    return validate_request_config(project_id, step_config)


def validate_request_config(
    project_id: Optional[int],
    request_config: Dict[str, Any],
) -> Optional[str]:
    """校验单个数据工厂接口步骤配置及项目归属。"""
    source_type = request_config.get("source_type") or DataFactorySourceType.CUSTOM
    if source_type not in DataFactorySourceType.VALUES:
        return "接口来源不支持"

    interface = None
    if source_type == DataFactorySourceType.INTERFACE:
        if project_id is None:
            return "未选择所属项目时不能引用接口库"
        interface_id = parse_optional_int(request_config.get("interface_id"))
        if interface_id is None:
            return "请选择接口库中的接口"
        interface = db.session.get(Interface, interface_id)
        if interface is None:
            return "引用的接口不存在"
        if interface.project_id != project_id:
            return "引用的接口不属于当前项目"
        if interface.interface_type != InterfaceType.HTTP:
            return "数据工厂只支持 HTTP 接口"
        if not interface.is_active:
            return "引用的接口已停用"

    effective = build_submitted_request_config(request_config, interface)
    if not effective["name"]:
        return "步骤名称不能为空"
    if effective["method"] not in HttpMethod.VALUES or effective["method"] == HttpMethod.WS:
        return "请求方法不支持"
    if not effective["url"]:
        return "URL 不能为空"
    scheme = urlsplit(effective["url"]).scheme.lower()
    if scheme and scheme not in ("http", "https"):
        return "URL 只允许使用 HTTP 或 HTTPS 协议"
    if effective["body_type"] not in BodyType.VALUES:
        return "请求体类型不支持"
    if not isinstance(effective["params"], dict):
        return "Params 必须是 JSON 对象"
    if not isinstance(effective["headers"], dict):
        return "Headers 必须是 JSON 对象"
    timeout_seconds = effective["timeout_seconds"]
    if timeout_seconds < 1 or timeout_seconds > MAX_TIMEOUT_SECONDS:
        return "超时时间必须在 1 到 %s 秒之间" % MAX_TIMEOUT_SECONDS
    extractor_error = validate_extractors(effective["extractors"])
    if extractor_error:
        return extractor_error
    return validate_assertion_definitions(effective["assertions"])


def validate_extractors(extractors: List[Dict[str, Any]]) -> Optional[str]:
    """校验数据工厂提取器字段。"""
    if not isinstance(extractors, list):
        return "提取器配置必须是数组"
    for index, extractor in enumerate(extractors, start=1):
        if not isinstance(extractor, dict):
            return "第 %s 个提取器格式不正确" % index
        if not str(extractor.get("variable_name") or "").strip():
            return "第 %s 个提取器变量名称不能为空" % index
        if not str(extractor.get("jsonpath") or "").strip():
            return "第 %s 个提取器 JSONPath 不能为空" % index
    return None


def replace_factory_steps(
    factory: DataFactory,
    step_configs: List[Dict[str, Any]],
) -> None:
    """按图形流程顺序替换数据工厂步骤。"""
    DataFactoryStep.query.filter_by(factory_id=factory.id).delete()
    for index, step_config in enumerate(step_configs, start=1):
        db.session.add(build_factory_step(factory, step_config, index))


def build_factory_step(
    factory: DataFactory,
    step_config: Dict[str, Any],
    sort_order: int,
) -> DataFactoryStep:
    """生成接口或等待步骤，并仅保存接口库字段覆盖值。"""
    step_type = step_config.get("step_type") or DataFactoryStepType.REQUEST
    if step_type == DataFactoryStepType.WAIT:
        return DataFactoryStep(
            factory_id=factory.id,
            name=str(step_config.get("name") or "等待").strip(),
            step_type=step_type,
            source_type=DataFactorySourceType.CUSTOM,
            sort_order=sort_order,
            timeout_seconds=30,
            wait_seconds=parse_float(step_config.get("wait_seconds"), 1),
            extractors=[],
            assertions=[],
        )

    source_type = step_config.get("source_type") or DataFactorySourceType.CUSTOM
    interface = None
    if source_type == DataFactorySourceType.INTERFACE:
        interface = db.session.get(Interface, int(step_config.get("interface_id")))
    effective = build_submitted_request_config(step_config, interface)
    if interface is not None:
        base = build_interface_base_config(interface)
        method = diff_value(effective["method"], base["method"])
        url = diff_value(effective["url"], base["url"])
        body_type = diff_value(effective["body_type"], base["body_type"])
        params = diff_value(effective["params"], base["params"])
        headers = diff_value(effective["headers"], base["headers"])
        body = diff_value(effective["body"], base["body"])
    else:
        method = effective["method"]
        url = effective["url"]
        body_type = effective["body_type"]
        params = effective["params"]
        headers = effective["headers"]
        body = effective["body"]

    return DataFactoryStep(
        factory_id=factory.id,
        interface_id=interface.id if interface else None,
        name=effective["name"],
        step_type=step_type,
        source_type=source_type,
        sort_order=sort_order,
        method=method,
        url=url,
        body_type=body_type,
        request_params=params,
        headers=headers,
        body=body,
        timeout_seconds=effective["timeout_seconds"],
        wait_seconds=None,
        extractors=effective["extractors"],
        assertions=effective["assertions"],
    )


def build_submitted_request_config(
    request_config: Dict[str, Any],
    interface: Optional[Interface],
) -> Dict[str, Any]:
    """合成页面提交接口配置和接口库默认配置。"""
    base = build_interface_base_config(interface) if interface else {
        "name": "",
        "method": HttpMethod.GET,
        "url": "",
        "body_type": BodyType.NONE,
        "params": {},
        "headers": {},
        "body": {},
    }
    return {
        "name": str(request_config.get("name", base["name"]) or base["name"]).strip(),
        "method": str(request_config.get("method", base["method"]) or base["method"]).upper(),
        "url": str(request_config.get("url", base["url"]) or base["url"]).strip(),
        "body_type": request_config.get("body_type", base["body_type"]) or base["body_type"],
        "params": request_config.get("params", request_config.get("request_params", base["params"])),
        "headers": request_config.get("headers", base["headers"]),
        "body": request_config.get("body", base["body"]),
        "timeout_seconds": parse_int(request_config.get("timeout_seconds"), 30),
        "extractors": request_config.get("extractors") or [],
        "assertions": normalize_assertion_definitions(request_config.get("assertions") or []),
    }


def build_interface_base_config(interface: Interface) -> Dict[str, Any]:
    """构造接口库接口的基础请求配置。"""
    return {
        "name": interface.name,
        "method": (interface.method or HttpMethod.GET).upper(),
        "url": interface.url or "",
        "body_type": interface.body_type or BodyType.NONE,
        "params": interface.params_template or {},
        "headers": interface.headers_template or {},
        "body": interface.body_template or {},
    }


def build_effective_step_config(item: DataFactoryStep) -> Dict[str, Any]:
    """合成已保存步骤当前实际生效的内容。"""
    if item.step_type == DataFactoryStepType.WAIT:
        return {
            "id": item.id,
            "name": item.name,
            "step_type": item.step_type,
            "sort_order": item.sort_order,
            "wait_seconds": item.wait_seconds,
        }
    base = build_interface_base_config(item.interface) if item.interface else {
        "name": item.name,
        "method": HttpMethod.GET,
        "url": "",
        "body_type": BodyType.NONE,
        "params": {},
        "headers": {},
        "body": {},
    }
    return {
        "id": item.id,
        "interface_id": item.interface_id,
        "interface_name": item.interface.name if item.interface else "",
        "module_name": item.interface.module.name if item.interface and item.interface.module else "",
        "name": item.name or base["name"],
        "step_type": item.step_type,
        "source_type": item.source_type,
        "sort_order": item.sort_order,
        "method": item.method or base["method"],
        "url": item.url or base["url"],
        "body_type": item.body_type or base["body_type"],
        "params": item.request_params if item.request_params is not None else base["params"],
        "headers": item.headers if item.headers is not None else base["headers"],
        "body": item.body if item.body is not None else base["body"],
        "timeout_seconds": item.timeout_seconds,
        "wait_seconds": None,
        "extractors": item.extractors or [],
        "assertions": normalize_assertion_definitions(item.assertions or []),
    }


def build_execution_snapshot(factory: DataFactory) -> Dict[str, Any]:
    """保存一次运行所需的完整流程快照。"""
    steps = [
        build_effective_step_config(item)
        for item in sorted(factory.steps, key=lambda value: value.sort_order)
    ]
    return {
        "factory_id": factory.id,
        "factory_name": factory.name,
        "project_id": factory.project_id,
        "steps": steps,
    }


def serialize_factory(factory: DataFactory, include_steps: bool = True) -> Dict[str, Any]:
    """序列化数据工厂及其最近执行状态。"""
    latest_run = DataFactoryRun.query.filter_by(factory_id=factory.id).order_by(
        DataFactoryRun.id.desc()
    ).first()
    result = {
        "id": factory.id,
        "project_id": factory.project_id,
        "project_name": factory.project.name if factory.project else "",
        "environment_id": factory.environment_id,
        "environment_name": factory.environment.name if factory.environment else "",
        "name": factory.name,
        "description": factory.description or "",
        "default_loop_count": factory.default_loop_count,
        "default_concurrency": factory.default_concurrency,
        "step_count": len(factory.steps),
        "request_step_count": sum(
            1 for item in factory.steps if item.step_type == DataFactoryStepType.REQUEST
        ),
        "latest_run": serialize_run(latest_run) if latest_run else None,
        "created_at": format_datetime(factory.created_at),
        "updated_at": format_datetime(factory.updated_at),
    }
    if include_steps:
        result["steps"] = [
            build_effective_step_config(item)
            for item in sorted(factory.steps, key=lambda value: value.sort_order)
        ]
    return result


def serialize_run(run: DataFactoryRun) -> Dict[str, Any]:
    """序列化数据工厂运行汇总。"""
    if run is None:
        return {}
    progress = 0.0
    if run.loop_count:
        progress = round(run.completed_iteration_count * 100.0 / run.loop_count, 1)
    return {
        "id": run.id,
        "factory_id": run.factory_id,
        "factory_name": run.factory_name,
        "project_id": run.project_id,
        "environment_id": run.environment_id,
        "environment_name": run.environment.name if run.environment else "",
        "status": run.status,
        "loop_count": run.loop_count,
        "concurrency": run.concurrency,
        "total_request_count": run.total_request_count,
        "completed_request_count": run.completed_request_count,
        "completed_iteration_count": run.completed_iteration_count,
        "success_iteration_count": run.success_iteration_count,
        "failed_iteration_count": run.failed_iteration_count,
        "cancel_requested": run.cancel_requested,
        "progress": progress,
        "started_at": format_datetime(run.started_at),
        "ended_at": format_datetime(run.ended_at),
        "created_at": format_datetime(run.created_at),
        "error_message": run.error_message or "",
    }


def diff_value(value: Any, base_value: Any) -> Any:
    """与接口库基础配置一致时不保存覆盖值。"""
    return None if value == base_value else value


def parse_int(value: Any, default: int) -> int:
    """解析整数并在空值时使用默认值。"""
    if value in (None, ""):
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def parse_float(value: Any, default: float) -> float:
    """解析浮点数并在空值或格式错误时使用默认值。"""
    if value in (None, ""):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def parse_optional_int(value: Any) -> Optional[int]:
    """解析允许为空的整数。"""
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def format_datetime(value: Any) -> str:
    """格式化页面展示时间。"""
    from ..utils.datetime_utils import format_datetime as format_local_datetime

    return format_local_datetime(value)
