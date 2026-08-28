# -*- coding: utf-8 -*-
"""
@Author: byy
@Desc: 场景集合页面与 API，负责集合配置、步骤保存和手动执行。
"""

from typing import Any
from typing import Dict
from typing import List
from typing import Optional

from flask import Blueprint
from flask import jsonify
from flask import render_template
from flask import request
from sqlalchemy.exc import IntegrityError

from ..enums import AssertionComparator
from ..enums import AssertionValueType
from ..enums import BodyType
from ..enums import EnvironmentType
from ..enums import HttpMethod
from ..enums import SuiteType
from ..extensions import db
from ..models import Environment
from ..models import ExecutionDetail
from ..models import ExecutionHistory
from ..models import Project
from ..models import Suite
from ..models import SuiteCase
from ..models import TestCase
from ..services.assert_engine import normalize_assertion_definitions
from ..services.assert_engine import validate_assertion_definitions
from ..services.pagination_service import paginate_response
from ..services.suite_runner import run_suite


suites_bp = Blueprint("suites", __name__, url_prefix="/suites")
suites_api_bp = Blueprint("suites_api", __name__, url_prefix="/api/test-suite")


@suites_bp.route("/")
def index():
    """渲染集合列表页。"""
    return render_template("suites.html")


@suites_bp.route("/new")
def new_suite():
    """渲染新增集合页。"""
    return render_template("suite_edit.html", suite_id="")


@suites_bp.route("/<int:suite_id>/edit")
def edit_suite(suite_id):
    """渲染集合编辑页。"""
    return render_template("suite_edit.html", suite_id=suite_id)


@suites_api_bp.route("/list", methods=["POST"])
def list_suites():
    """返回全部集合。"""
    data = request.get_json(silent=True) or {}
    query = Suite.query.order_by(Suite.id.desc())
    return paginate_response(query, serialize_suite, data)


@suites_api_bp.route("/detail", methods=["POST"])
def get_suite():
    """返回单个集合。"""
    data = request.get_json(silent=True) or {}
    suite_id = data.get("suite_id")
    if not suite_id:
        return jsonify({"success": False, "message": "集合 ID 不能为空"}), 400
    suite = db.get_or_404(Suite, suite_id)
    return jsonify({"success": True, "data": serialize_suite(suite)})


@suites_api_bp.route("/create", methods=["POST"])
def create_suite():
    """创建集合。"""
    suite, steps, error = build_suite(Suite(), request.get_json(silent=True) or {})
    if error:
        return jsonify({"success": False, "message": error}), 400
    db.session.add(suite)
    db.session.flush()
    replace_suite_steps(suite, steps)
    db.session.commit()
    return jsonify({"success": True, "data": serialize_suite(suite)})


@suites_api_bp.route("/save", methods=["POST"])
def update_suite():
    """更新集合。"""
    data = request.get_json(silent=True) or {}
    suite_id = data.get("suite_id")
    if not suite_id:
        return jsonify({"success": False, "message": "集合 ID 不能为空"}), 400
    suite = db.get_or_404(Suite, suite_id)
    suite, steps, error = build_suite(suite, data)
    if error:
        return jsonify({"success": False, "message": error}), 400
    replace_suite_steps(suite, steps)
    db.session.commit()
    return jsonify({"success": True, "data": serialize_suite(suite)})


@suites_api_bp.route("/save-steps", methods=["POST"])
def save_suite_steps():
    """仅保存集合步骤配置，不修改集合基础属性。"""
    data = request.get_json(silent=True) or {}
    suite_id = data.get("suite_id")
    steps = data.get("steps") or []
    if not suite_id:
        return jsonify({"success": False, "message": "集合 ID 不能为空"}), 400

    suite = db.get_or_404(Suite, suite_id)
    error = validate_suite_steps(suite.project_id, steps)
    if error:
        return jsonify({"success": False, "message": error}), 400

    replace_suite_steps(suite, steps)
    db.session.commit()
    return jsonify({"success": True, "data": serialize_suite(suite)})


@suites_api_bp.route("/delete", methods=["POST"])
def delete_suite():
    """删除集合。"""
    data = request.get_json(silent=True) or {}
    suite_id = data.get("suite_id")
    if not suite_id:
        return jsonify({"success": False, "message": "集合 ID 不能为空"}), 400
    suite = db.get_or_404(Suite, suite_id)
    SuiteCase.query.filter_by(suite_id=suite.id).delete()
    db.session.delete(suite)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({"success": False, "message": "集合已被任务或执行历史引用，不能删除"}), 409
    return jsonify({"success": True})


@suites_api_bp.route("/execute", methods=["POST"])
def run_suite_api():
    """手动执行集合。"""
    data = request.get_json(silent=True) or {}
    suite_id = data.get("suite_id")
    environment_id = data.get("environment_id")
    if not suite_id:
        return jsonify({"success": False, "message": "集合 ID 不能为空"}), 400
    suite = db.get_or_404(Suite, suite_id)
    environment_id = environment_id or suite.environment_id
    if not environment_id:
        return jsonify({"success": False, "message": "集合未配置默认执行环境，请先保存集合"}), 400
    try:
        result = run_suite(suite_id, environment_id)
    except Exception as exc:
        db.session.rollback()
        return jsonify({"success": False, "message": str(exc)}), 400
    return jsonify({"success": True, "data": result})


@suites_api_bp.route("/options", methods=["POST"])
def suite_options():
    """返回集合表单选项。"""
    projects = Project.query.order_by(Project.name.asc()).all()
    environments = Environment.query.order_by(Environment.name.asc()).all()
    cases = TestCase.query.order_by(TestCase.name.asc()).all()
    return jsonify(
        {
            "success": True,
            "data": {
                "projects": [{"id": item.id, "name": item.name} for item in projects],
                "environments": [serialize_environment_option(item) for item in environments],
                "cases": [serialize_case_option(item) for item in cases],
                "suite_types": list(SuiteType.VALUES),
                "methods": list(HttpMethod.VALUES),
                "body_types": list(BodyType.VALUES),
                "assertion_comparators": AssertionComparator.options(),
                "assertion_value_types": AssertionValueType.options(),
            },
        }
    )


@suites_api_bp.route("/execution-history-detail", methods=["POST"])
def get_history():
    """返回执行历史和执行明细。"""
    data = request.get_json(silent=True) or {}
    history_id = data.get("history_id")
    if not history_id:
        return jsonify({"success": False, "message": "执行历史 ID 不能为空"}), 400
    history = db.get_or_404(ExecutionHistory, history_id)
    details = ExecutionDetail.query.filter_by(history_id=history.id).order_by(
        ExecutionDetail.sort_order.asc(),
        ExecutionDetail.id.asc(),
    ).all()
    return jsonify(
        {
            "success": True,
            "data": {
                "history": serialize_history(history),
                "details": [serialize_history_detail(item) for item in details],
            },
        }
    )


def build_suite(suite, data):
    """根据 JSON 数据填充集合字段。"""
    project_id = data.get("project_id")
    environment_id = data.get("environment_id") or None
    name = (data.get("name") or "").strip()
    suite_type = data.get("suite_type") or SuiteType.SINGLE
    steps = data.get("steps") or []

    if not project_id:
        return suite, steps, "项目不能为空"
    if not environment_id:
        return suite, steps, "集合执行环境不能为空"
    if not name:
        return suite, steps, "集合名称不能为空"
    if suite_type not in SuiteType.VALUES:
        return suite, steps, "集合类型不支持"
    if db.session.get(Environment, environment_id) is None:
        return suite, steps, "执行环境不存在"
    steps_error = validate_suite_steps(project_id, steps)
    if steps_error:
        return suite, steps, steps_error

    suite.project_id = project_id
    suite.environment_id = environment_id
    suite.name = name
    suite.suite_type = suite_type
    suite.description = (data.get("description") or "").strip()
    suite.is_active = parse_bool(data.get("is_active"), True)
    return suite, steps, None


def validate_suite_steps(project_id: int, steps: List[Dict[str, Any]]) -> Optional[str]:
    """校验集合的全部步骤及其项目归属。"""
    if not steps:
        return "请至少添加一个集合步骤"
    try:
        case_ids = [int(item.get("case_id") or 0) for item in steps]
    except (AttributeError, TypeError, ValueError):
        return "集合步骤数据格式不正确"

    cases = TestCase.query.filter(TestCase.id.in_(case_ids)).all()
    if len(cases) != len(set(case_ids)):
        return "选择的用例不存在"
    for case in cases:
        if int(case.project_id) != int(project_id):
            return "集合中的用例必须属于所选项目"

    case_map = {item.id: item for item in cases}
    for step in steps:
        error = validate_step_config(step, case_map[int(step.get("case_id"))])
        if error:
            return error
    return None


def validate_step_config(step: Dict[str, Any], case: TestCase) -> Optional[str]:
    """校验集合步骤提交的完整配置。"""
    base_config = build_base_case_config(case)
    method = (step.get("method", base_config["method"]) or "").upper()
    url = (step.get("url", base_config["url"]) or "").strip()
    body_type = step.get("body_type", base_config["body_type"]) or BodyType.NONE
    if method not in HttpMethod.VALUES:
        return "集合步骤请求方法不支持"
    if not url:
        return "集合步骤 URL 不能为空"
    if body_type not in BodyType.VALUES:
        return "集合步骤请求体类型不支持"
    if parse_optional_int(step.get("timeout_seconds", base_config["timeout_seconds"])) is None:
        return "集合步骤超时时间不能为空"
    assertions = step.get("assertions", base_config["assertions"]) or []
    assertions_error = validate_assertion_definitions(assertions)
    if assertions_error:
        return "集合步骤%s" % assertions_error
    return None


def replace_suite_steps(suite: Suite, steps: List[Dict[str, Any]]) -> None:
    """按提交顺序替换集合中的用例步骤实例。"""
    case_ids = [int(step.get("case_id")) for step in steps]
    cases = {
        item.id: item
        for item in TestCase.query.filter(TestCase.id.in_(case_ids)).all()
    }
    SuiteCase.query.filter_by(suite_id=suite.id).delete()
    for index, step in enumerate(steps, start=1):
        case_id = int(step.get("case_id"))
        db.session.add(build_suite_case_step(suite, cases[case_id], step, index))


def build_suite_case_step(
    suite: Suite,
    case: TestCase,
    step: Dict[str, Any],
    sort_order: int,
) -> SuiteCase:
    """根据步骤完整配置生成只保存差异的集合步骤。"""
    base_config = build_base_case_config(case)
    method = (step.get("method", base_config["method"]) or "").upper()
    url = (step.get("url", base_config["url"]) or "").strip()
    body_type = step.get("body_type", base_config["body_type"]) or BodyType.NONE
    return SuiteCase(
        suite_id=suite.id,
        case_id=case.id,
        step_name=(step.get("step_name") or "").strip() or None,
        is_active=parse_bool(step.get("is_active"), True),
        sort_order=sort_order,
        method_override=diff_value(method, base_config["method"]),
        url_override=diff_value(url, base_config["url"]),
        body_type_override=diff_value(body_type, base_config["body_type"]),
        request_params_override=diff_value(
            step.get("request_params", base_config["request_params"]),
            base_config["request_params"],
        ),
        headers_override=diff_value(step.get("headers", base_config["headers"]), base_config["headers"]),
        body_override=diff_value(step.get("body", base_config["body"]), base_config["body"]),
        assertions_override=diff_value(
            step.get("assertions", base_config["assertions"]),
            base_config["assertions"],
        ),
        extractors_override=diff_value(
            step.get("extractors", base_config["extractors"]),
            base_config["extractors"],
        ),
        ws_steps_override=diff_value(
            step.get("ws_steps", base_config["ws_steps"]),
            base_config["ws_steps"],
        ),
        timeout_seconds_override=diff_value(
            parse_optional_int(step.get("timeout_seconds", base_config["timeout_seconds"])),
            base_config["timeout_seconds"],
        ),
    )


def serialize_suite(suite):
    """序列化集合用于 JSON 响应。"""
    ordered_cases = sorted(suite.suite_cases, key=lambda item: item.sort_order)
    return {
        "id": suite.id,
        "project_id": suite.project_id,
        "project_name": suite.project.name if suite.project else "",
        "environment_id": suite.environment_id,
        "environment_name": suite.environment.name if suite.environment else "",
        "environment_type": suite.environment.environment_type if suite.environment else "",
        "environment_type_name": (
            EnvironmentType.LABELS.get(suite.environment.environment_type, "")
            if suite.environment
            else ""
        ),
        "name": suite.name,
        "suite_type": suite.suite_type,
        "description": suite.description or "",
        "is_active": suite.is_active,
        "steps": [serialize_suite_case(item) for item in ordered_cases],
        "created_at": format_datetime(suite.created_at),
        "updated_at": format_datetime(suite.updated_at),
    }


def serialize_environment_option(environment: Environment) -> Dict[str, Any]:
    """序列化集合编辑页的环境选项。"""
    return {
        "id": environment.id,
        "name": environment.name,
        "environment_type": environment.environment_type,
        "environment_type_name": EnvironmentType.LABELS.get(
            environment.environment_type,
            environment.environment_type,
        ),
    }


def serialize_suite_case(suite_case):
    """序列化集合用例关联关系。"""
    case = suite_case.case
    effective_config = build_effective_step_config(suite_case)
    return {
        "suite_case_id": suite_case.id,
        "case_id": suite_case.case_id,
        "case_name": case.name if case else "",
        "step_name": suite_case.step_name or "",
        "interface_name": case.interface.name if case and case.interface else "",
        "interface_type": case.interface.interface_type if case and case.interface else "",
        "sort_order": suite_case.sort_order,
        "is_active": suite_case.is_active,
        "method": effective_config.get("method"),
        "url": effective_config.get("url"),
        "body_type": effective_config.get("body_type"),
        "request_params": effective_config.get("request_params"),
        "headers": effective_config.get("headers"),
        "body": effective_config.get("body"),
        "assertions": effective_config.get("assertions"),
        "extractors": effective_config.get("extractors"),
        "ws_steps": effective_config.get("ws_steps"),
        "timeout_seconds": effective_config.get("timeout_seconds"),
        "method_override": suite_case.method_override,
        "url_override": suite_case.url_override,
        "body_type_override": suite_case.body_type_override,
        "request_params_override": suite_case.request_params_override,
        "headers_override": suite_case.headers_override,
        "body_override": suite_case.body_override,
        "assertions_override": suite_case.assertions_override,
        "extractors_override": suite_case.extractors_override,
        "ws_steps_override": suite_case.ws_steps_override,
        "timeout_seconds_override": suite_case.timeout_seconds_override,
        "has_override": suite_case_has_override(suite_case),
    }


def serialize_case_option(case):
    """序列化用例选项。"""
    interface = case.interface
    base_config = build_base_case_config(case)
    return {
        "id": case.id,
        "project_id": case.project_id,
        "name": case.name,
        "interface_name": interface.name if interface else "",
        "interface_type": interface.interface_type if interface else "",
        "method": interface.method if interface else "",
        "url": interface.url if interface else "",
        "body_type": interface.body_type if interface else "",
        "base_config": base_config,
        "base_request_params": base_config["request_params"],
        "base_headers": base_config["headers"],
        "base_body": base_config["body"],
        "base_assertions": base_config["assertions"],
        "base_extractors": base_config["extractors"],
        "base_ws_steps": base_config["ws_steps"],
        "base_timeout_seconds": base_config["timeout_seconds"],
    }


def build_base_params(case: TestCase) -> Dict[str, Any]:
    """合成基础用例的请求参数。"""
    interface = case.interface
    params = dict(interface.params_template or {}) if interface else {}
    params.update(case.request_params or {})
    return params


def build_base_case_config(case: TestCase) -> Dict[str, Any]:
    """合成基础用例的完整可执行配置。"""
    interface = case.interface
    return {
        "method": interface.method if interface else "",
        "url": interface.url if interface else "",
        "body_type": interface.body_type if interface else BodyType.NONE,
        "request_params": build_base_params(case),
        "headers": build_base_headers(case),
        "body": build_base_body(case),
        "assertions": normalize_assertion_definitions(case.assertions or []),
        "extractors": case.extractors or [],
        "ws_steps": case.ws_steps or [],
        "timeout_seconds": case.timeout_seconds,
    }


def build_effective_step_config(suite_case: SuiteCase) -> Dict[str, Any]:
    """合成集合步骤当前生效的完整配置。"""
    base_config = build_base_case_config(suite_case.case)
    return {
        "method": suite_case.method_override or base_config["method"],
        "url": suite_case.url_override or base_config["url"],
        "body_type": suite_case.body_type_override or base_config["body_type"],
        "request_params": (
            suite_case.request_params_override
            if suite_case.request_params_override is not None
            else base_config["request_params"]
        ),
        "headers": (
            suite_case.headers_override
            if suite_case.headers_override is not None
            else base_config["headers"]
        ),
        "body": suite_case.body_override if suite_case.body_override is not None else base_config["body"],
        "assertions": (
            suite_case.assertions_override
            if suite_case.assertions_override is not None
            else base_config["assertions"]
        ),
        "extractors": (
            suite_case.extractors_override
            if suite_case.extractors_override is not None
            else base_config["extractors"]
        ),
        "ws_steps": (
            suite_case.ws_steps_override
            if suite_case.ws_steps_override is not None
            else base_config["ws_steps"]
        ),
        "timeout_seconds": (
            suite_case.timeout_seconds_override
            if suite_case.timeout_seconds_override is not None
            else base_config["timeout_seconds"]
        ),
    }


def build_base_headers(case: TestCase) -> Dict[str, Any]:
    """合成基础用例的请求头。"""
    interface = case.interface
    headers = dict(interface.headers_template or {}) if interface else {}
    headers.update(case.headers_override or {})
    return headers


def build_base_body(case: TestCase) -> Any:
    """合成基础用例的请求体。"""
    interface = case.interface
    body = case.body_override
    if body in (None, {}, [], ""):
        return interface.body_template or {} if interface else {}
    return body


def suite_case_has_override(suite_case: SuiteCase) -> bool:
    """判断集合步骤是否存在任意覆盖配置。"""
    return any(
        value is not None
        for value in (
            suite_case.method_override,
            suite_case.url_override,
            suite_case.body_type_override,
            suite_case.request_params_override,
            suite_case.headers_override,
            suite_case.body_override,
            suite_case.assertions_override,
            suite_case.extractors_override,
            suite_case.ws_steps_override,
            suite_case.timeout_seconds_override,
        )
    )


def diff_value(value: Any, base_value: Any) -> Any:
    """与基础配置一致时不保存覆盖值。"""
    if normalize_compare_value(value) == normalize_compare_value(base_value):
        return None
    return value


def normalize_compare_value(value: Any) -> Any:
    """规范化配置值，避免空字符串和空值比较误判。"""
    if value == "":
        return None
    return value


def serialize_history(history):
    """序列化执行历史。"""
    return {
        "id": history.id,
        "task_name": history.task_name or "",
        "trigger_type": history.trigger_type,
        "environment_id": history.environment_id,
        "status": history.status,
        "total_count": history.total_count,
        "success_count": history.success_count,
        "fail_count": history.fail_count,
        "error_count": history.error_count,
        "interrupted": history.interrupted,
        "summary": history.summary or {},
        "start_time": format_datetime(history.start_time),
        "end_time": format_datetime(history.end_time),
    }


def serialize_history_detail(detail):
    """序列化执行明细。"""
    return {
        "id": detail.id,
        "suite_name": detail.suite_name,
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


def parse_bool(value, default=False):
    """解析 JSON 中类似布尔值的字段。"""
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).lower() in ("1", "true", "yes", "on")


def parse_optional_int(value: Any) -> Optional[int]:
    """解析可选整数字段，空值表示继承基础用例。"""
    if value in (None, ""):
        return None
    return int(value)


def format_datetime(value):
    """格式化页面展示时间。"""
    from ..utils.datetime_utils import format_datetime as format_local_datetime

    return format_local_datetime(value)
