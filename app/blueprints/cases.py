# -*- coding: utf-8 -*-
"""
@Author: byy
@Desc: 接口用例页面与 API，负责 HTTP、WebSocket 用例的查询、保存、调试和删除。
"""

import json
from typing import Any

from flask import Blueprint
from flask import current_app
from flask import jsonify
from flask import redirect
from flask import render_template
from flask import request
from flask import Response
from flask import stream_with_context
from flask import url_for
from sqlalchemy import distinct
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload

from ..enums import AssertionComparator
from ..enums import AssertionValueType
from ..enums import BodyType
from ..enums import EnvironmentType
from ..enums import HttpMethod
from ..enums import InterfaceType
from ..extensions import db
from ..models import Environment
from ..models import Interface
from ..models import Project
from ..models import ProjectModule
from ..models import TestCase
from ..services.assert_engine import normalize_assertion_definitions
from ..services.assert_engine import validate_assertion_definitions
from ..services.case_runner import run_case
from ..services.case_debug_service import case_debug_registry
from ..services.pagination_service import paginate_response


cases_bp = Blueprint("cases", __name__, url_prefix="/cases")
cases_api_bp = Blueprint("cases_api", __name__, url_prefix="/api/test-case")


@cases_bp.route("/")
def index():
    """渲染用例列表页。"""
    return render_template("cases.html")


@cases_bp.route("/new")
def new_case():
    """兼容旧新增地址并根据引用接口类型直接渲染页面。"""
    interface_id = request.args.get("interface_id", "")
    template_name = "case_edit.html"
    if interface_id:
        interface = db.session.get(Interface, interface_id)
        if interface and interface.interface_type == InterfaceType.WEBSOCKET:
            template_name = "websocket_case_edit.html"
    return render_template(
        template_name,
        case_id="",
        interface_id=interface_id,
        return_to=normalize_return_to(request.args.get("return_to")),
        case_type="websocket" if template_name.startswith("websocket") else "http",
    )


@cases_bp.route("/new/http")
def new_http_case() -> Any:
    """渲染独立的 HTTP 用例新增页。"""
    return render_template(
        "case_edit.html",
        case_id="",
        interface_id=request.args.get("interface_id", ""),
        return_to=normalize_return_to(request.args.get("return_to")),
        case_type="http",
    )


@cases_bp.route("/new/websocket")
def new_websocket_case() -> Any:
    """渲染独立的 WebSocket 用例新增页。"""
    return render_template(
        "websocket_case_edit.html",
        case_id="",
        interface_id=request.args.get("interface_id", ""),
        return_to=normalize_return_to(request.args.get("return_to")),
    )


@cases_bp.route("/<int:case_id>/edit")
def edit_case(case_id):
    """兼容旧编辑地址并根据接口类型直接渲染页面。"""
    test_case = TestCase.query.get_or_404(case_id)
    is_websocket = bool(
        test_case.interface
        and test_case.interface.interface_type == InterfaceType.WEBSOCKET
    )
    return render_template(
        "websocket_case_edit.html" if is_websocket else "case_edit.html",
        case_id=case_id,
        interface_id="",
        return_to=normalize_return_to(request.args.get("return_to")),
        case_type="websocket" if is_websocket else "http",
    )


@cases_bp.route("/<int:case_id>/edit/http")
def edit_http_case(case_id: int) -> Any:
    """渲染独立的 HTTP 用例编辑页。"""
    test_case = TestCase.query.get_or_404(case_id)
    if test_case.interface and test_case.interface.interface_type == InterfaceType.WEBSOCKET:
        return redirect(url_for("cases.edit_websocket_case", case_id=case_id))
    return render_template(
        "case_edit.html",
        case_id=case_id,
        interface_id="",
        return_to=normalize_return_to(request.args.get("return_to")),
        case_type="http",
    )


@cases_bp.route("/<int:case_id>/edit/websocket")
def edit_websocket_case(case_id: int) -> Any:
    """渲染独立的 WebSocket 用例编辑页。"""
    test_case = TestCase.query.get_or_404(case_id)
    if test_case.interface and test_case.interface.interface_type != InterfaceType.WEBSOCKET:
        return redirect(url_for("cases.edit_http_case", case_id=case_id))
    return render_template(
        "websocket_case_edit.html",
        case_id=case_id,
        interface_id="",
        return_to=normalize_return_to(request.args.get("return_to")),
    )


@cases_api_bp.route("/list", methods=["POST"])
def list_cases():
    """返回全部测试用例。"""
    data = request.get_json(silent=True) or {}
    query = (
        TestCase.query.join(Interface, TestCase.interface_id == Interface.id)
        .join(ProjectModule, Interface.module_id == ProjectModule.id)
        .options(
            joinedload(TestCase.interface).joinedload(Interface.module),
            joinedload(TestCase.environment),
        )
        .order_by(TestCase.id.desc())
    )
    project_id = data.get("project_id")
    if project_id:
        query = query.filter(ProjectModule.project_id == project_id)

    module_id = data.get("module_id")
    if module_id:
        module = db.session.get(ProjectModule, module_id)
        if module is None:
            return jsonify({"success": False, "message": "模块不存在"}), 400
        if project_id and int(module.project_id) != int(project_id):
            return jsonify({"success": False, "message": "模块不属于所选项目"}), 400
        query = query.filter(Interface.module_id == module_id)

    url_keyword = (data.get("url") or "").strip()
    if url_keyword:
        query = query.filter(Interface.url.ilike("%%%s%%" % url_keyword))

    environment_type = (data.get("environment_type") or "").strip()
    if environment_type:
        if environment_type not in EnvironmentType.VALUES:
            return jsonify({"success": False, "message": "环境类型不支持"}), 400
        query = query.join(Environment, TestCase.environment_id == Environment.id)
        query = query.filter(Environment.environment_type == environment_type)

    interface_id = data.get("interface_id")
    if interface_id:
        query = query.filter(TestCase.interface_id == interface_id)
    return paginate_response(query, serialize_case, data)


@cases_api_bp.route("/tree-groups", methods=["POST"])
def list_case_tree_groups():
    """按项目模块分页返回树形视图根节点及匹配数量。"""
    data = request.get_json(silent=True) or {}
    filters, error = parse_case_tree_filters(data)
    if error:
        return jsonify({"success": False, "message": error}), 400

    query = (
        db.session.query(
            ProjectModule.id.label("module_id"),
            ProjectModule.name.label("module_name"),
            Project.id.label("project_id"),
            Project.name.label("project_name"),
            func.count(distinct(Interface.id)).label("interface_count"),
            func.count(TestCase.id).label("case_count"),
        )
        .join(Project, ProjectModule.project_id == Project.id)
        .join(Interface, Interface.module_id == ProjectModule.id)
        .join(TestCase, TestCase.interface_id == Interface.id)
    )
    query = apply_case_tree_filters(query, filters)
    query = query.group_by(
        ProjectModule.id,
        ProjectModule.name,
        Project.id,
        Project.name,
    ).order_by(Project.name.asc(), ProjectModule.name.asc())
    return paginate_response(query, serialize_case_tree_group, data)


@cases_api_bp.route("/tree-interfaces", methods=["POST"])
def list_case_tree_interfaces():
    """分页返回指定模块下包含匹配用例的接口节点。"""
    data = request.get_json(silent=True) or {}
    if not data.get("module_id"):
        return jsonify({"success": False, "message": "模块 ID 不能为空"}), 400
    filters, error = parse_case_tree_filters(data)
    if error:
        return jsonify({"success": False, "message": error}), 400

    query = (
        db.session.query(
            Interface.id.label("interface_id"),
            Interface.name.label("interface_name"),
            Interface.method.label("method"),
            Interface.url.label("url"),
            func.count(TestCase.id).label("case_count"),
        )
        .join(TestCase, TestCase.interface_id == Interface.id)
        .join(ProjectModule, Interface.module_id == ProjectModule.id)
        .filter(Interface.module_id == filters["module_id"])
    )
    query = apply_case_tree_filters(query, filters, include_module=False)
    query = query.group_by(
        Interface.id,
        Interface.name,
        Interface.method,
        Interface.url,
    ).order_by(Interface.name.asc(), Interface.id.asc())
    return paginate_response(query, serialize_case_tree_interface, data)


@cases_api_bp.route("/detail", methods=["POST"])
def get_case():
    """返回单个测试用例。"""
    data = request.get_json(silent=True) or {}
    case_id = data.get("case_id")
    if not case_id:
        return jsonify({"success": False, "message": "用例 ID 不能为空"}), 400
    test_case = TestCase.query.get_or_404(case_id)
    return jsonify({"success": True, "data": serialize_case(test_case)})


@cases_api_bp.route("/create", methods=["POST"])
def create_case():
    """创建测试用例。"""
    test_case, error = build_case(TestCase(), request.get_json(silent=True) or {})
    if error:
        return jsonify({"success": False, "message": error}), 400
    db.session.add(test_case)
    return commit_case(test_case)


@cases_api_bp.route("/save", methods=["POST"])
def update_case():
    """更新测试用例。"""
    data = request.get_json(silent=True) or {}
    case_id = data.get("case_id")
    if not case_id:
        return jsonify({"success": False, "message": "用例 ID 不能为空"}), 400
    test_case = TestCase.query.get_or_404(case_id)
    test_case, error = build_case(test_case, data)
    if error:
        return jsonify({"success": False, "message": error}), 400
    return commit_case(test_case)


@cases_api_bp.route("/delete", methods=["POST"])
def delete_case():
    """删除测试用例。"""
    data = request.get_json(silent=True) or {}
    case_id = data.get("case_id")
    if not case_id:
        return jsonify({"success": False, "message": "用例 ID 不能为空"}), 400
    test_case = TestCase.query.get_or_404(case_id)
    db.session.delete(test_case)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({"success": False, "message": "用例已被集合引用，不能删除"}), 409
    return jsonify({"success": True})


@cases_api_bp.route("/debug", methods=["POST"])
def debug_case():
    """以调试模式执行用例。"""
    data = request.get_json(silent=True) or {}
    case_id = data.get("case_id")
    environment_id = data.get("environment_id")
    if not case_id:
        return jsonify({"success": False, "message": "用例 ID 不能为空"}), 400
    if not environment_id:
        return jsonify({"success": False, "message": "请选择执行环境"}), 400
    try:
        result = run_case(
            case_id,
            environment_id,
            runtime_vars=data.get("runtime_vars") or {},
            debug=True,
        )
    except Exception as exc:
        return jsonify({"success": False, "message": str(exc)}), 400
    return jsonify({"success": True, "data": result})


@cases_api_bp.route("/debug/start", methods=["POST"])
def start_websocket_case_debug() -> Any:
    """启动 WebSocket 用例后台调试，实时日志由 SSE 独立推送。"""
    data = request.get_json(silent=True) or {}
    case_id = data.get("case_id")
    environment_id = data.get("environment_id")
    if not case_id:
        return jsonify({"success": False, "message": "用例 ID 不能为空"}), 400
    if not environment_id:
        return jsonify({"success": False, "message": "请选择执行环境"}), 400
    test_case = db.session.get(TestCase, case_id)
    if test_case is None:
        return jsonify({"success": False, "message": "测试用例不存在"}), 404
    if not test_case.interface or test_case.interface.interface_type != InterfaceType.WEBSOCKET:
        return jsonify({"success": False, "message": "仅 WebSocket 用例支持实时调试"}), 400
    try:
        execution_id = case_debug_registry.start(
            current_app._get_current_object(),
            int(case_id),
            int(environment_id),
            data.get("runtime_vars") or {},
        )
    except Exception as exc:
        return jsonify({"success": False, "message": str(exc)}), 400
    return jsonify({"success": True, "data": {"execution_id": execution_id}})


@cases_api_bp.route("/debug/events", methods=["GET"])
def stream_websocket_case_debug() -> Any:
    """通过 SSE 实时推送 WebSocket 用例消息和最终执行结果。"""
    execution_id = str(request.args.get("execution_id") or "")
    if not execution_id:
        return jsonify({"success": False, "message": "调试执行 ID 不能为空"}), 400
    try:
        execution = case_debug_registry.get(execution_id)
        sequence = _case_event_sequence()
    except (TypeError, ValueError) as exc:
        return jsonify({"success": False, "message": str(exc)}), 404

    @stream_with_context
    def generate():
        """等待后台执行事件，无事件时发送 SSE 心跳。"""
        current_sequence = sequence
        while True:
            events = execution.wait_after(current_sequence, 15)
            if not events:
                if execution.completed:
                    break
                yield ": heartbeat\n\n"
                continue
            for item in events:
                current_sequence = max(
                    current_sequence,
                    int(item.get("sequence") or 0),
                )
                yield _case_sse_event(item)
            if execution.completed:
                break

    response = Response(generate(), mimetype="text/event-stream")
    response.headers["Cache-Control"] = "no-cache, no-transform"
    response.headers["X-Accel-Buffering"] = "no"
    response.headers["Connection"] = "keep-alive"
    return response


@cases_api_bp.route("/options", methods=["POST"])
def case_options():
    """返回用例表单选项。"""
    projects = Project.query.order_by(Project.name.asc()).all()
    environments = Environment.query.order_by(Environment.name.asc()).all()
    interfaces = Interface.query.order_by(Interface.name.asc()).all()
    modules = ProjectModule.query.order_by(ProjectModule.name.asc()).all()
    return jsonify(
        {
            "success": True,
            "data": {
                "projects": [{"id": item.id, "name": item.name} for item in projects],
                "environments": [
                    {
                        "id": item.id,
                        "name": item.name,
                        "base_url": item.base_url or "",
                        "environment_type": item.environment_type,
                    }
                    for item in environments
                ],
                "interfaces": [serialize_interface_option(item) for item in interfaces],
                "modules": [
                    {
                        "id": item.id,
                        "project_id": item.project_id,
                        "name": item.name,
                    }
                    for item in modules
                ],
                "environment_types": [
                    {"value": value, "label": EnvironmentType.LABELS[value]}
                    for value in EnvironmentType.VALUES
                ],
                "assertion_comparators": AssertionComparator.options(),
                "assertion_value_types": AssertionValueType.options(),
            },
        }
    )


def parse_case_tree_filters(data):
    """校验并规范化树形视图的组合筛选条件。"""
    project_id = parse_optional_int(data.get("project_id"))
    module_id = parse_optional_int(data.get("module_id"))
    if data.get("project_id") and project_id is None:
        return None, "项目 ID 格式不正确"
    if data.get("module_id") and module_id is None:
        return None, "模块 ID 格式不正确"

    if module_id:
        module = db.session.get(ProjectModule, module_id)
        if module is None:
            return None, "模块不存在"
        if project_id and module.project_id != project_id:
            return None, "模块不属于所选项目"

    environment_type = (data.get("environment_type") or "").strip()
    if environment_type and environment_type not in EnvironmentType.VALUES:
        return None, "环境类型不支持"
    return {
        "project_id": project_id,
        "module_id": module_id,
        "url": (data.get("url") or "").strip(),
        "environment_type": environment_type,
    }, None


def apply_case_tree_filters(query, filters, include_module=True):
    """把统一筛选条件应用到树形统计查询。"""
    if filters["project_id"]:
        query = query.filter(ProjectModule.project_id == filters["project_id"])
    if include_module and filters["module_id"]:
        query = query.filter(ProjectModule.id == filters["module_id"])
    if filters["url"]:
        query = query.filter(Interface.url.ilike("%%%s%%" % filters["url"]))
    if filters["environment_type"]:
        query = query.join(Environment, TestCase.environment_id == Environment.id)
        query = query.filter(
            Environment.environment_type == filters["environment_type"]
        )
    return query


def serialize_case_tree_group(row):
    """序列化树形视图的项目模块根节点。"""
    return {
        "id": row.module_id,
        "module_id": row.module_id,
        "module_name": row.module_name,
        "project_id": row.project_id,
        "project_name": row.project_name,
        "interface_count": row.interface_count,
        "case_count": row.case_count,
    }


def serialize_case_tree_interface(row):
    """序列化树形视图的接口父节点。"""
    return {
        "id": row.interface_id,
        "interface_id": row.interface_id,
        "interface_name": row.interface_name,
        "method": row.method or "",
        "url": row.url or "",
        "case_count": row.case_count,
    }


def build_case(test_case, data):
    """根据 JSON 数据填充测试用例实例。"""
    project_id = data.get("project_id")
    interface_id = data.get("interface_id")
    environment_id = data.get("environment_id")
    name = (data.get("name") or "").strip()

    if not project_id:
        return test_case, "项目不能为空"
    if not interface_id:
        return test_case, "接口不能为空"
    if not name:
        return test_case, "用例名称不能为空"

    interface = db.session.get(Interface, interface_id)
    if interface is None:
        return test_case, "接口不存在"
    if int(interface.project_id) != int(project_id):
        return test_case, "接口不属于所选项目"
    if environment_id:
        environment = db.session.get(Environment, environment_id)
        if environment is None:
            return test_case, "执行环境不存在"
    url = (data.get("url") or interface.url or "").strip()
    if not url:
        return test_case, "接口 URL 不能为空"

    if interface.interface_type == InterfaceType.WEBSOCKET:
        method = HttpMethod.WS
        body_type = BodyType.NONE
        assertions = []
        ws_steps = data.get("ws_steps") or []
        ws_error = validate_ws_steps(ws_steps)
        if ws_error:
            return test_case, ws_error
        ws_config_override = data.get("ws_config_override") or {}
        if not isinstance(ws_config_override, dict):
            return test_case, "WebSocket 用例覆盖配置必须是对象"
    else:
        method = (data.get("method") or interface.method or HttpMethod.GET).upper()
        body_type = data.get("body_type") or interface.body_type or BodyType.NONE
        if method not in HttpMethod.VALUES or method == HttpMethod.WS:
            return test_case, "HTTP 请求方法不支持"
        if body_type not in BodyType.VALUES:
            return test_case, "请求体类型不支持"
        assertions = data.get("assertions") or []
        assertions_error = validate_assertion_definitions(assertions)
        if assertions_error:
            return test_case, assertions_error
        ws_steps = []
        ws_config_override = {}

    test_case.interface_id = interface_id
    test_case.environment_id = environment_id or None
    if interface.interface_type == InterfaceType.HTTP:
        interface.method = method
        interface.url = url
        interface.body_type = body_type
    else:
        ws_config_override = dict(ws_config_override)
        if url != interface.url:
            ws_config_override["url"] = url
        else:
            ws_config_override.pop("url", None)
    test_case.name = name
    test_case.request_params = data.get("request_params") or {}
    test_case.headers_override = data.get("headers_override") or {}
    test_case.body_override = data.get("body_override") or {}
    test_case.assertions = normalize_assertion_definitions(assertions)
    test_case.extractors = data.get("extractors") or []
    test_case.ws_steps = ws_steps
    test_case.ws_config_override = ws_config_override
    default_timeout = 60 if interface.interface_type == InterfaceType.WEBSOCKET else 30
    test_case.timeout_seconds = int(data.get("timeout_seconds") or default_timeout)
    test_case.description = (data.get("description") or "").strip()
    test_case.is_active = parse_bool(data.get("is_active"), True)
    return test_case, None


def commit_case(test_case):
    """提交测试用例并返回 JSON。"""
    db.session.commit()
    return jsonify({"success": True, "data": serialize_case(test_case)})


def serialize_case(test_case):
    """序列化测试用例用于 JSON 响应。"""
    interface = test_case.interface
    return {
        "id": test_case.id,
        "project_id": test_case.project_id,
        "project_name": test_case.project.name if test_case.project else "",
        "interface_id": test_case.interface_id,
        "interface_name": interface.name if interface else "",
        "module_id": interface.module_id if interface else None,
        "module_name": interface.module.name if interface and interface.module else "",
        "interface_type": interface.interface_type if interface else "",
        "method": interface.method if interface else "",
        "url": (
            (test_case.ws_config_override or {}).get("url") or interface.url
            if interface
            else ""
        ),
        "body_type": interface.body_type if interface else BodyType.NONE,
        "environment_id": test_case.environment_id,
        "environment_name": test_case.environment.name if test_case.environment else "",
        "environment_type": test_case.environment.environment_type if test_case.environment else "",
        "environment_type_name": (
            EnvironmentType.LABELS.get(test_case.environment.environment_type, "")
            if test_case.environment
            else ""
        ),
        "name": test_case.name,
        "request_params": test_case.request_params or {},
        "headers_override": test_case.headers_override or {},
        "body_override": test_case.body_override or {},
        "assertions": test_case.assertions or [],
        "extractors": test_case.extractors or [],
        "ws_steps": test_case.ws_steps or [],
        "ws_config": interface.ws_config or {} if interface else {},
        "ws_config_override": test_case.ws_config_override or {},
        "timeout_seconds": test_case.timeout_seconds,
        "description": test_case.description or "",
        "is_active": test_case.is_active,
        "created_at": format_datetime(test_case.created_at),
        "updated_at": format_datetime(test_case.updated_at),
    }


def serialize_interface_option(interface):
    """序列化表单中的接口选项。"""
    return {
        "id": interface.id,
        "project_id": interface.project_id,
        "name": interface.name,
        "interface_type": interface.interface_type,
        "method": interface.method or "",
        "url": interface.url,
        "body_type": interface.body_type,
        "params_template": interface.params_template or {},
        "headers_template": interface.headers_template or {},
        "body_template": interface.body_template or {},
        "module_id": interface.module_id,
        "module_name": interface.module.name if interface.module else "",
        "is_websocket": interface.interface_type == InterfaceType.WEBSOCKET,
        "ws_config": interface.ws_config or {},
    }


def validate_ws_steps(steps: Any) -> Any:
    """校验 WebSocket 简化步骤及等待断言配置。"""
    if not isinstance(steps, list):
        return "WebSocket 步骤必须是数组"
    supported = {"send", "wait_assert", "sleep", "close", "connect", "receive_assert"}
    for index, step in enumerate(steps, start=1):
        if not isinstance(step, dict):
            return "第 %s 个 WebSocket 步骤格式不正确" % index
        step_type = step.get("type") or step.get("action")
        if step_type not in supported:
            return "第 %s 个 WebSocket 步骤类型不支持" % index
        if step_type == "send" and step.get("content", step.get("message")) in (None, ""):
            return "第 %s 个发送步骤消息内容不能为空" % index
        if step_type in ("wait_assert", "receive_assert"):
            try:
                timeout_seconds = float(step.get("timeout_seconds") or 10)
            except (TypeError, ValueError):
                return "第 %s 个等待步骤超时格式不正确" % index
            if timeout_seconds <= 0:
                return "第 %s 个等待步骤超时必须大于 0" % index
            for label, assertions in (
                ("目标消息条件", (step.get("target") or {}).get("conditions") or []),
                ("内容断言", step.get("assertions") or []),
            ):
                error = validate_assertion_definitions(assertions)
                if error:
                    return "第 %s 个等待步骤%s：%s" % (index, label, error)
    return None


def parse_bool(value, default=False):
    """解析 JSON 中类似布尔值的字段。"""
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).lower() in ("1", "true", "yes", "on")


def parse_optional_int(value):
    """把可选 ID 解析为正整数，无值返回空。"""
    if value in (None, ""):
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _case_event_sequence() -> int:
    """读取 WebSocket 用例 SSE 首次连接或自动重连的事件序号。"""
    value = request.headers.get("Last-Event-ID") or request.args.get("after_sequence") or 0
    return max(0, int(value))


def _case_sse_event(item):
    """将用例调试事件编码为 SSE 文本。"""
    return "id: %s\nevent: %s\ndata: %s\n\n" % (
        int(item.get("sequence") or 0),
        item.get("event") or "message",
        json.dumps(item.get("data") or {}, ensure_ascii=False, separators=(",", ":")),
    )


def normalize_return_to(value):
    """仅允许站内绝对路径作为页面返回地址。"""
    return_to = str(value or "").strip()
    if return_to.startswith("/") and not return_to.startswith("//"):
        return return_to
    return ""


def format_datetime(value):
    """格式化页面展示时间。"""
    from ..utils.datetime_utils import format_datetime as format_local_datetime

    return format_local_datetime(value)
