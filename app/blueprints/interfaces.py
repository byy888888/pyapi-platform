# -*- coding: utf-8 -*-
"""
@Author: byy
@Desc: 接口库页面与 API，负责 HTTP、WebSocket 接口的管理和调试。
"""

import json
from typing import Any
from typing import Dict
from typing import List
from typing import Optional
from typing import Tuple

from flask import Blueprint
from flask import jsonify
from flask import redirect
from flask import render_template
from flask import request
from flask import url_for
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload
from sqlalchemy.orm import selectinload

from ..enums import BodyType
from ..enums import HttpMethod
from ..enums import InterfaceType
from ..extensions import db
from ..models import Interface
from ..models import DataFactoryStep
from ..models import Environment
from ..models import Project
from ..models import ProjectModule
from ..models import Suite
from ..services.http_runner import run_http_case
from ..services.pagination_service import paginate_response
from ..services.variable_engine import build_variable_context


interfaces_bp = Blueprint("interfaces", __name__, url_prefix="/interfaces")
interfaces_api_bp = Blueprint("interfaces_api", __name__, url_prefix="/api/interface-definition")


@interfaces_bp.route("/")
def index():
    """渲染接口管理页。"""
    return render_template("interfaces.html")


@interfaces_bp.route("/new")
def new_interface():
    """兼容旧地址并直接渲染 HTTP 接口新增页。"""
    return render_template("interface_edit.html", interface_id="", interface_type="http")


@interfaces_bp.route("/new/http")
def new_http_interface() -> Any:
    """渲染独立的 HTTP 接口新增页。"""
    return render_template("interface_edit.html", interface_id="", interface_type="http")


@interfaces_bp.route("/new/websocket")
def new_websocket_interface() -> Any:
    """渲染独立的 WebSocket 接口新增页。"""
    return render_template("websocket_interface_edit.html", interface_id="")


@interfaces_bp.route("/<int:interface_id>/edit")
def edit_interface(interface_id):
    """兼容旧编辑地址并根据接口类型直接渲染对应页面。"""
    item = Interface.query.get_or_404(interface_id)
    return render_template(
        "websocket_interface_edit.html"
        if item.interface_type == InterfaceType.WEBSOCKET
        else "interface_edit.html",
        interface_id=interface_id,
        interface_type=item.interface_type,
    )


@interfaces_bp.route("/<int:interface_id>/edit/http")
def edit_http_interface(interface_id: int) -> Any:
    """渲染独立的 HTTP 接口编辑页。"""
    item = Interface.query.get_or_404(interface_id)
    if item.interface_type != InterfaceType.HTTP:
        return redirect(url_for("interfaces.edit_websocket_interface", interface_id=interface_id))
    return render_template("interface_edit.html", interface_id=interface_id, interface_type="http")


@interfaces_bp.route("/<int:interface_id>/edit/websocket")
def edit_websocket_interface(interface_id: int) -> Any:
    """渲染独立的 WebSocket 接口编辑页。"""
    item = Interface.query.get_or_404(interface_id)
    if item.interface_type != InterfaceType.WEBSOCKET:
        return redirect(url_for("interfaces.edit_http_interface", interface_id=interface_id))
    return render_template("websocket_interface_edit.html", interface_id=interface_id)


@interfaces_api_bp.route("/list", methods=["POST"])
def list_interfaces():
    """按项目、模块和 URL 组合查询接口。"""
    data = request.get_json(silent=True) or {}
    query = (
        Interface.query.join(
            ProjectModule,
            Interface.module_id == ProjectModule.id,
        )
        .options(
            joinedload(Interface.module).joinedload(ProjectModule.project),
            selectinload(Interface.test_cases),
        )
        .order_by(Interface.id.desc())
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
    return paginate_response(query, serialize_interface, data)


@interfaces_api_bp.route("/detail", methods=["POST"])
def get_interface():
    """返回单个接口。"""
    data = request.get_json(silent=True) or {}
    interface_id = data.get("interface_id")
    if not interface_id:
        return jsonify({"success": False, "message": "接口 ID 不能为空"}), 400
    item = Interface.query.get_or_404(interface_id)
    return jsonify({"success": True, "data": serialize_interface(item)})


@interfaces_api_bp.route("/create", methods=["POST"])
def create_interface():
    """创建接口。"""
    item, error, status_code = build_interface(
        Interface(),
        request.get_json(silent=True) or {},
    )
    if error:
        db.session.rollback()
        return jsonify({"success": False, "message": error}), status_code
    db.session.add(item)
    return commit_interface(item)


@interfaces_api_bp.route("/save", methods=["POST"])
def update_interface():
    """更新接口。"""
    data = request.get_json(silent=True) or {}
    interface_id = data.get("interface_id")
    if not interface_id:
        return jsonify({"success": False, "message": "接口 ID 不能为空"}), 400
    item = Interface.query.get_or_404(interface_id)
    item, error, status_code = build_interface(item, data)
    if error:
        db.session.rollback()
        return jsonify({"success": False, "message": error}), status_code
    return commit_interface(item)


@interfaces_api_bp.route("/delete", methods=["POST"])
def delete_interface():
    """删除接口。"""
    data = request.get_json(silent=True) or {}
    interface_id = data.get("interface_id")
    if not interface_id:
        return jsonify({"success": False, "message": "接口 ID 不能为空"}), 400
    item = Interface.query.get_or_404(interface_id)
    db.session.delete(item)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({"success": False, "message": "接口已被用例或数据工厂引用，不能删除"}), 409
    return jsonify({"success": True})


@interfaces_api_bp.route("/debug", methods=["POST"])
def debug_interface():
    """调试未保存或已保存的 HTTP 接口草稿。"""
    data = request.get_json(silent=True) or {}
    environment_id = data.get("environment_id")
    project_id = data.get("project_id")
    if not environment_id:
        return jsonify({"success": False, "message": "请选择执行环境"}), 400
    if not project_id:
        return jsonify({"success": False, "message": "项目不能为空"}), 400
    if (data.get("interface_type") or InterfaceType.HTTP) == InterfaceType.WEBSOCKET:
        return jsonify({"success": False, "message": "WebSocket 接口请在用例中配置消息步骤后调试"}), 400

    draft_case, error = build_debug_http_case(data)
    if error:
        return jsonify({"success": False, "message": error}), 400
    context = build_variable_context(project_id, environment_id, data.get("runtime_vars") or {})
    runner_result = run_http_case(draft_case, context)
    return jsonify({"success": True, "data": {"runner": runner_result}})


@interfaces_api_bp.route("/options", methods=["POST"])
def interface_options():
    """返回接口表单选项。"""
    projects = Project.query.order_by(Project.name.asc()).all()
    modules = ProjectModule.query.order_by(ProjectModule.name.asc()).all()
    environments = Environment.query.order_by(Environment.name.asc()).all()
    return jsonify(
        {
            "success": True,
            "data": {
                "projects": [{"id": item.id, "name": item.name} for item in projects],
                "modules": [serialize_module_option(item) for item in modules],
                "environments": [
                    {"id": item.id, "name": item.name, "base_url": item.base_url or ""}
                    for item in environments
                ],
                "interface_types": list(InterfaceType.VALUES),
                "methods": list(HttpMethod.VALUES),
                "body_types": list(BodyType.VALUES),
            },
        }
    )


def build_interface(item, data):
    """根据请求数据填充接口实例。"""
    project_id = data.get("project_id")
    module_id = data.get("module_id")
    module_name = (data.get("module_name") or "").strip()
    name = (data.get("name") or "").strip()
    interface_type = data.get("interface_type") or InterfaceType.HTTP
    method = data.get("method") or HttpMethod.GET
    url = (data.get("url") or "").strip()
    body_type = data.get("body_type") or BodyType.NONE

    if not project_id:
        return item, "项目不能为空", 400
    project = db.session.get(Project, project_id)
    if project is None:
        return item, "项目不存在", 400
    module, module_error = resolve_interface_module(project.id, module_id, module_name)
    if module_error:
        return item, module_error, 400
    if not name:
        return item, "接口名称不能为空", 400
    if interface_type not in InterfaceType.VALUES:
        return item, "接口类型不支持", 400
    if not url:
        return item, "接口 URL 不能为空", 400

    if interface_type == InterfaceType.WEBSOCKET:
        method = HttpMethod.WS
        body_type = BodyType.NONE
        headers_template = {}
        params_template = {}
        body_template = {}
        ws_config, error = normalize_ws_config(data.get("ws_config") or {})
        if error:
            return item, error, 400
    else:
        if method not in HttpMethod.VALUES or method == HttpMethod.WS:
            return item, "HTTP 请求方法不支持", 400
        if body_type not in BodyType.VALUES:
            return item, "请求体类型不支持", 400
        headers_template, error = parse_json_object(data.get("headers_template"), "请求头模板")
        if error:
            return item, error, 400
        params_template, error = parse_json_object(data.get("params_template"), "请求参数模板")
        if error:
            return item, error, 400
        body_template, error = parse_json_value(data.get("body_template"), "请求体模板")
        if error:
            return item, error, 400
        ws_config = {}

    suite_updates = []
    if item.id and item.project_id != module.project_id:
        suite_updates, error = plan_interface_project_move(
            item,
            module.project_id,
        )
        if error:
            return item, error, 409

    item.module = module
    item.name = name
    item.interface_type = interface_type
    item.method = method
    item.url = url
    item.params_template = params_template
    item.headers_template = headers_template
    item.body_template = body_template
    item.body_type = body_type
    item.ws_config = ws_config
    item.description = (data.get("description") or "").strip()
    item.is_active = parse_bool(data.get("is_active"), True)
    for suite in suite_updates:
        suite.project_id = module.project_id
    return item, None, 200


def plan_interface_project_move(
    item: Interface,
    target_project_id: int,
) -> Tuple[List[Suite], Optional[str]]:
    """校验接口跨项目移动，并返回可安全同步项目的集合。"""
    factory_references = DataFactoryStep.query.filter_by(interface_id=item.id).all()
    conflicting_factories = [
        reference.factory.name
        for reference in factory_references
        if reference.factory and reference.factory.project_id != target_project_id
    ]
    if conflicting_factories:
        return [], "接口无法移动：数据工厂%s仍引用该接口" % "、".join(
            "“%s”" % name for name in conflicting_factories
        )

    affected_suites = {}
    for test_case in item.test_cases:
        for suite_case in test_case.suite_cases:
            if suite_case.suite:
                affected_suites[suite_case.suite.id] = suite_case.suite

    updates = []
    conflicts = []
    for suite in affected_suites.values():
        project_ids = set()
        for suite_case in suite.suite_cases:
            test_case = suite_case.case
            if test_case is None or test_case.interface is None:
                continue
            if test_case.interface_id == item.id:
                project_ids.add(int(target_project_id))
            elif test_case.project_id is not None:
                project_ids.add(int(test_case.project_id))
        if len(project_ids) > 1:
            conflicts.append(suite.name)
        elif project_ids:
            updates.append(suite)

    if conflicts:
        return [], "接口无法移动：集合%s将包含多个项目的用例" % "、".join(
            "“%s”" % name for name in conflicts
        )
    return updates, None


def build_debug_http_case(data):
    """根据接口编辑表单构造执行器入参。"""
    method = (data.get("method") or HttpMethod.GET).upper()
    url = (data.get("url") or "").strip()
    body_type = data.get("body_type") or BodyType.NONE
    timeout_seconds = int(data.get("timeout_seconds") or 30)

    if method not in HttpMethod.VALUES:
        return None, "请求方法不支持"
    if not url:
        return None, "接口 URL 不能为空"
    if body_type not in BodyType.VALUES:
        return None, "请求体类型不支持"

    headers, error = parse_json_object(data.get("headers_template"), "请求头")
    if error:
        return None, error
    params, error = parse_json_object(data.get("params_template"), "请求参数")
    if error:
        return None, error
    body, error = parse_json_value(data.get("body_template"), "请求体")
    if error:
        return None, error

    return {
        "method": method,
        "url": url,
        "headers": headers,
        "params": params,
        "body": body,
        "body_type": body_type,
        "timeout_seconds": timeout_seconds,
    }, None


def parse_json_object(value, label):
    """解析 JSON 对象字符串。"""
    parsed, error = parse_json_value(value, label)
    if error:
        return None, error
    if not isinstance(parsed, dict):
        return None, "%s必须是 JSON 对象" % label
    return parsed, None


def parse_json_value(value, label):
    """解析 JSON 字符串，空值返回空对象。"""
    if value in (None, ""):
        return {}, None
    if isinstance(value, (dict, list)):
        return value, None
    try:
        return json.loads(value), None
    except (TypeError, ValueError):
        return None, "%s不是合法 JSON" % label


def normalize_ws_config(
    value: Dict[str, Any],
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """校验并规范化 WebSocket 可选连接、前置消息和心跳配置。"""
    if not isinstance(value, dict):
        return None, "WebSocket 高级配置必须是 JSON 对象"
    headers, error = parse_json_object(value.get("headers"), "握手 Headers")
    if error:
        return None, error
    subprotocols = value.get("subprotocols") or []
    if isinstance(subprotocols, str):
        subprotocols = [item.strip() for item in subprotocols.split(",") if item.strip()]
    if not isinstance(subprotocols, list):
        return None, "子协议必须是数组或逗号分隔文本"
    try:
        connect_timeout_ms = int(value.get("connect_timeout_ms") or 5000)
    except (TypeError, ValueError):
        return None, "连接超时必须是整数"
    if connect_timeout_ms <= 0:
        return None, "连接超时必须大于 0"

    connect_message = _normalize_optional_message(
        value.get("connect_message"),
        "连接后消息",
    )
    if isinstance(connect_message, str):
        return None, connect_message
    heartbeat = _normalize_optional_message(value.get("heartbeat"), "业务心跳")
    if isinstance(heartbeat, str):
        return None, heartbeat
    try:
        heartbeat["interval_ms"] = int(
            (value.get("heartbeat") or {}).get("interval_ms") or 30000
        )
    except (TypeError, ValueError):
        return None, "心跳发送间隔必须是整数"
    if heartbeat["enabled"] and heartbeat["interval_ms"] <= 0:
        return None, "心跳发送间隔必须大于 0"

    default_message = value.get("default_message") or {}
    if not isinstance(default_message, dict):
        return None, "默认消息模板格式不正确"
    default_type = default_message.get("message_type") or "json"
    if default_type not in ("text", "json", "binary"):
        return None, "默认消息类型不支持"
    return {
        "headers": headers,
        "subprotocols": [str(item) for item in subprotocols],
        "connect_timeout_ms": connect_timeout_ms,
        "connect_message": connect_message,
        "heartbeat": heartbeat,
        "default_message": {
            "message_type": default_type,
            "content": default_message.get("content", ""),
        },
    }, None


def _normalize_optional_message(value: Any, label: str) -> Any:
    """规范化可关闭的连接后消息或业务心跳。"""
    config = value or {}
    if not isinstance(config, dict):
        return "%s配置格式不正确" % label
    enabled = parse_bool(config.get("enabled"), False)
    message_type = config.get("message_type") or "text"
    if message_type not in ("text", "json", "binary"):
        return "%s类型不支持" % label
    content = config.get("content", "")
    if enabled and content in (None, ""):
        return "已启用%s，请填写消息内容" % label
    return {
        "enabled": enabled,
        "message_type": message_type,
        "content": content,
    }


def commit_interface(item):
    """提交接口并返回 JSON。"""
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({"success": False, "message": "当前项目下模块名称已存在"}), 409
    return jsonify({"success": True, "data": serialize_interface(item)})


def serialize_interface(item):
    """序列化接口用于 JSON 响应。"""
    return {
        "id": item.id,
        "project_id": item.project_id,
        "project_name": item.project.name if item.project else "",
        "module_id": item.module_id,
        "module_name": item.module.name if item.module else "",
        "name": item.name,
        "interface_type": item.interface_type,
        "method": item.method or "",
        "url": item.url,
        "params_template": item.params_template or {},
        "headers_template": item.headers_template or {},
        "body_template": item.body_template or {},
        "body_type": item.body_type,
        "ws_config": item.ws_config or {},
        "description": item.description or "",
        "is_active": item.is_active,
        "created_at": format_datetime(item.created_at),
        "updated_at": format_datetime(item.updated_at),
        "case_count": len(item.test_cases),
    }


def resolve_interface_module(project_id, module_id, module_name):
    """解析已有模块或按输入名称创建模块。"""
    if module_id:
        module = db.session.get(ProjectModule, module_id)
        if module is None:
            return None, "模块不存在"
        if int(module.project_id) != int(project_id):
            return None, "模块不属于所选项目"
        if module_name and module.name.strip().lower() != module_name.lower():
            return None, "模块名称与所选模块不一致"
        return module, None
    if not module_name:
        module_name = "未分组"
    modules = ProjectModule.query.filter_by(project_id=project_id).all()
    matched = next(
        (item for item in modules if item.name.strip().lower() == module_name.lower()),
        None,
    )
    if matched:
        return matched, None
    module = ProjectModule(project_id=project_id, name=module_name)
    db.session.add(module)
    return module, None


def serialize_module_option(module):
    """序列化接口表单和搜索使用的模块选项。"""
    return {
        "id": module.id,
        "project_id": module.project_id,
        "name": module.name,
    }


def parse_bool(value, default=False):
    """解析 JSON 中类似布尔值的字段。"""
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).lower() in ("1", "true", "yes", "on")


def format_datetime(value):
    """格式化页面展示时间。"""
    from ..utils.datetime_utils import format_datetime as format_local_datetime

    return format_local_datetime(value)
