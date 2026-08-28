# -*- coding: utf-8 -*-
"""
@Author: byy
@Desc: 数据工厂页面与 API，负责工厂配置、调试、执行和运行详情查询。
"""

import json
import logging
from typing import Any
from typing import Dict

from flask import Blueprint
from flask import Response
from flask import current_app
from flask import jsonify
from flask import render_template
from flask import request
from sqlalchemy.exc import IntegrityError

from ..enums import AssertionComparator
from ..enums import AssertionValueType
from ..enums import BodyType
from ..enums import DataFactoryRunStatus
from ..enums import DataFactorySourceType
from ..enums import DataFactoryStepType
from ..enums import HttpMethod
from ..enums import InterfaceType
from ..extensions import db
from ..models import DataFactory
from ..models import DataFactoryRun
from ..models import DataFactoryRunDetail
from ..models import DataFactoryRunIteration
from ..models import Environment
from ..models import Interface
from ..models import Project
from ..models import ProjectModule
from ..services.data_factory_executor import submit_factory_run
from ..services.data_factory_runner import create_factory_run
from ..services.data_factory_runner import execute_factory_request
from ..services.data_factory_runner import execute_factory_run
from ..services.data_factory_service import build_factory
from ..services.data_factory_service import build_submitted_request_config
from ..services.data_factory_service import format_datetime
from ..services.data_factory_service import replace_factory_steps
from ..services.data_factory_service import serialize_factory
from ..services.data_factory_service import serialize_run
from ..services.data_factory_service import validate_request_config
from ..services.jsonpath_service import list_jsonpaths
from ..services.pagination_service import paginate_response
from ..services.pagination_service import parse_positive_int


logger = logging.getLogger(__name__)
data_factories_bp = Blueprint("data_factories", __name__, url_prefix="/data-factories")
data_factories_api_bp = Blueprint(
    "data_factories_api",
    __name__,
    url_prefix="/api/data-factory",
)


@data_factories_bp.route("/")
def index() -> str:
    """渲染数据工厂列表页。"""
    return render_template("data_factories.html")


@data_factories_bp.route("/new")
def new_factory() -> str:
    """渲染新增数据工厂页。"""
    return render_template("data_factory_edit.html", factory_id="")


@data_factories_bp.route("/<int:factory_id>/edit")
def edit_factory(factory_id: int) -> str:
    """渲染数据工厂编辑页。"""
    return render_template("data_factory_edit.html", factory_id=factory_id)


@data_factories_bp.route("/runs/<int:run_id>")
def run_detail(run_id: int) -> str:
    """渲染数据工厂运行详情页。"""
    return render_template("data_factory_run_detail.html", run_id=run_id)


@data_factories_api_bp.route("/list", methods=["POST"])
def list_factories() -> Response:
    """分页查询数据工厂。"""
    data = request.get_json(silent=True) or {}
    query = DataFactory.query.order_by(DataFactory.id.desc())
    project_id = data.get("project_id")
    if project_id == "independent":
        query = query.filter(DataFactory.project_id.is_(None))
    elif project_id:
        query = query.filter(DataFactory.project_id == int(project_id))
    keyword = str(data.get("keyword") or "").strip()
    if keyword:
        query = query.filter(DataFactory.name.ilike("%%%s%%" % keyword))
    return paginate_response(query, lambda item: serialize_factory(item, False), data)


@data_factories_api_bp.route("/detail", methods=["POST"])
def get_factory() -> Response:
    """返回单个数据工厂的完整配置。"""
    data = request.get_json(silent=True) or {}
    factory_id = data.get("factory_id")
    if not factory_id:
        return jsonify({"success": False, "message": "数据工厂 ID 不能为空"}), 400
    factory = db.get_or_404(DataFactory, factory_id)
    return jsonify({"success": True, "data": serialize_factory(factory)})


@data_factories_api_bp.route("/create", methods=["POST"])
def create_factory() -> Response:
    """创建数据工厂及动态接口配置。"""
    factory, step_configs, error = build_factory(
        DataFactory(),
        request.get_json(silent=True) or {},
    )
    if error:
        return jsonify({"success": False, "message": error}), 400
    db.session.add(factory)
    db.session.flush()
    replace_factory_steps(factory, step_configs)
    db.session.commit()
    logger.info("created data factory id=%s", factory.id)
    return jsonify({"success": True, "data": serialize_factory(factory)})


@data_factories_api_bp.route("/save", methods=["POST"])
def save_factory() -> Response:
    """更新数据工厂及动态接口配置。"""
    data = request.get_json(silent=True) or {}
    factory_id = data.get("factory_id")
    if not factory_id:
        return jsonify({"success": False, "message": "数据工厂 ID 不能为空"}), 400
    factory = db.get_or_404(DataFactory, factory_id)
    factory, step_configs, error = build_factory(factory, data)
    if error:
        return jsonify({"success": False, "message": error}), 400
    replace_factory_steps(factory, step_configs)
    db.session.commit()
    logger.info("updated data factory id=%s", factory.id)
    return jsonify({"success": True, "data": serialize_factory(factory)})


@data_factories_api_bp.route("/delete", methods=["POST"])
def delete_factory() -> Response:
    """删除没有执行历史的数据工厂。"""
    data = request.get_json(silent=True) or {}
    factory_id = data.get("factory_id")
    if not factory_id:
        return jsonify({"success": False, "message": "数据工厂 ID 不能为空"}), 400
    factory = db.get_or_404(DataFactory, factory_id)
    if DataFactoryRun.query.filter_by(factory_id=factory.id).first():
        return jsonify({"success": False, "message": "数据工厂存在执行历史，不能删除"}), 409
    db.session.delete(factory)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({"success": False, "message": "数据工厂仍被其他数据引用，不能删除"}), 409
    logger.info("deleted data factory id=%s", factory_id)
    return jsonify({"success": True})


@data_factories_api_bp.route("/clone", methods=["POST"])
def clone_factory() -> Response:
    """复制一个数据工厂及其当前有效接口配置。"""
    data = request.get_json(silent=True) or {}
    factory_id = data.get("factory_id")
    if not factory_id:
        return jsonify({"success": False, "message": "数据工厂 ID 不能为空"}), 400
    source = db.get_or_404(DataFactory, factory_id)
    source_data = serialize_factory(source)
    source_data["name"] = "%s-副本" % source.name
    source_data.pop("id", None)
    source_data.pop("latest_run", None)
    clone, step_configs, error = build_factory(DataFactory(), source_data)
    if error:
        return jsonify({"success": False, "message": error}), 400
    db.session.add(clone)
    db.session.flush()
    replace_factory_steps(clone, step_configs)
    db.session.commit()
    logger.info("cloned data factory source=%s target=%s", source.id, clone.id)
    return jsonify({"success": True, "data": serialize_factory(clone)})


@data_factories_api_bp.route("/options", methods=["POST"])
def factory_options() -> Response:
    """返回数据工厂编辑和执行使用的公共选项。"""
    projects = Project.query.filter_by(is_active=True).order_by(Project.name.asc()).all()
    environments = Environment.query.order_by(Environment.name.asc()).all()
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
                "source_types": list(DataFactorySourceType.VALUES),
                "step_types": list(DataFactoryStepType.VALUES),
                "methods": [value for value in HttpMethod.VALUES if value != HttpMethod.WS],
                "body_types": list(BodyType.VALUES),
                "assertion_comparators": AssertionComparator.options(),
                "assertion_value_types": AssertionValueType.options(),
            },
        }
    )


@data_factories_api_bp.route("/interface-options", methods=["POST"])
def interface_options() -> Response:
    """按模块分组返回所选项目可引用的 HTTP 接口。"""
    data = request.get_json(silent=True) or {}
    project_id = data.get("project_id")
    if not project_id:
        return jsonify({"success": True, "data": []})
    modules = ProjectModule.query.filter_by(project_id=project_id).order_by(
        ProjectModule.name.asc()
    ).all()
    groups = []
    for module in modules:
        interfaces = Interface.query.filter_by(
            module_id=module.id,
            interface_type=InterfaceType.HTTP,
            is_active=True,
        ).order_by(Interface.name.asc()).all()
        if not interfaces:
            continue
        groups.append(
            {
                "module_id": module.id,
                "module_name": module.name,
                "interfaces": [
                    {
                        "id": item.id,
                        "name": item.name,
                        "method": item.method,
                        "url": item.url,
                        "body_type": item.body_type,
                        "params": item.params_template or {},
                        "headers": item.headers_template or {},
                        "body": item.body_template or {},
                    }
                    for item in interfaces
                ],
            }
        )
    return jsonify({"success": True, "data": groups})


@data_factories_api_bp.route("/debug-request", methods=["POST"])
def debug_request() -> Response:
    """调试未保存的数据工厂接口配置。"""
    data = request.get_json(silent=True) or {}
    project_id = data.get("project_id") or None
    environment_id = data.get("environment_id")
    request_config = data.get("step_config") or data.get("request_config") or {}
    if not environment_id:
        return jsonify({"success": False, "message": "请选择执行环境"}), 400
    error = validate_request_config(int(project_id) if project_id else None, request_config)
    if error:
        return jsonify({"success": False, "message": error}), 400
    interface = None
    if request_config.get("source_type") == DataFactorySourceType.INTERFACE:
        interface = db.session.get(Interface, int(request_config.get("interface_id")))
    effective = build_submitted_request_config(request_config, interface)
    effective["id"] = request_config.get("id")
    effective["source_type"] = request_config.get("source_type")
    result = execute_factory_request(
        effective,
        int(project_id) if project_id else None,
        int(environment_id),
        {},
    )
    jsonpaths = []
    body_text = (result.get("response_snapshot") or {}).get("body") or ""
    try:
        jsonpaths = list_jsonpaths(json.loads(body_text))
    except (TypeError, ValueError):
        pass
    result["jsonpaths"] = jsonpaths
    return jsonify({"success": True, "data": result})


@data_factories_api_bp.route("/execute", methods=["POST"])
def execute_factory() -> Response:
    """创建执行记录并启动数据工厂后台任务。"""
    data = request.get_json(silent=True) or {}
    factory_id = data.get("factory_id")
    if not factory_id:
        return jsonify({"success": False, "message": "数据工厂 ID 不能为空"}), 400
    factory = db.get_or_404(DataFactory, factory_id)
    try:
        run = create_factory_run(factory, data)
    except ValueError as exc:
        return jsonify({"success": False, "message": str(exc)}), 400
    app = current_app._get_current_object()
    if current_app.config.get("DATA_FACTORY_SYNC_EXECUTION", False):
        execute_factory_run(app, run.id)
    else:
        submit_factory_run(app, run.id)
    logger.info("started data factory run factory=%s run=%s", factory.id, run.id)
    return jsonify({"success": True, "data": {"run_id": run.id}})


@data_factories_api_bp.route("/run/status", methods=["POST"])
def run_status() -> Response:
    """返回数据工厂实时执行进度。"""
    data = request.get_json(silent=True) or {}
    run_id = data.get("run_id")
    if not run_id:
        return jsonify({"success": False, "message": "执行记录 ID 不能为空"}), 400
    run = db.get_or_404(DataFactoryRun, run_id)
    return jsonify({"success": True, "data": serialize_run(run)})


@data_factories_api_bp.route("/run/cancel", methods=["POST"])
def cancel_run() -> Response:
    """请求取消等待中或执行中的数据工厂。"""
    data = request.get_json(silent=True) or {}
    run_id = data.get("run_id")
    if not run_id:
        return jsonify({"success": False, "message": "执行记录 ID 不能为空"}), 400
    run = db.get_or_404(DataFactoryRun, run_id)
    if run.status not in (DataFactoryRunStatus.QUEUED, DataFactoryRunStatus.RUNNING):
        return jsonify({"success": False, "message": "当前执行已经结束"}), 409
    run.cancel_requested = True
    db.session.commit()
    logger.info("cancel requested for data factory run=%s", run.id)
    return jsonify({"success": True})


@data_factories_api_bp.route("/run/list", methods=["POST"])
def run_list() -> Response:
    """分页返回数据工厂执行历史。"""
    data = request.get_json(silent=True) or {}
    query = DataFactoryRun.query.order_by(DataFactoryRun.id.desc())
    if data.get("factory_id"):
        query = query.filter(DataFactoryRun.factory_id == int(data.get("factory_id")))
    return paginate_response(query, serialize_run, data)


@data_factories_api_bp.route("/run/detail", methods=["POST"])
def get_run_detail() -> Response:
    """分页返回运行轮次及其接口执行明细。"""
    data = request.get_json(silent=True) or {}
    run_id = data.get("run_id")
    if not run_id:
        return jsonify({"success": False, "message": "执行记录 ID 不能为空"}), 400
    run = db.get_or_404(DataFactoryRun, run_id)
    page = parse_positive_int(data.get("page"), 1)
    page_size = min(parse_positive_int(data.get("page_size"), 10), 100)
    pagination = DataFactoryRunIteration.query.filter_by(run_id=run.id).order_by(
        DataFactoryRunIteration.iteration_no.asc()
    ).paginate(page=page, per_page=page_size, error_out=False)
    return jsonify(
        {
            "success": True,
            "data": {
                "run": serialize_run(run),
                "iterations": [serialize_iteration(item) for item in pagination.items],
            },
            "pagination": {
                "page": pagination.page,
                "page_size": pagination.per_page,
                "total": pagination.total,
                "pages": pagination.pages,
                "has_prev": pagination.has_prev,
                "has_next": pagination.has_next,
            },
        }
    )


def serialize_iteration(iteration: DataFactoryRunIteration) -> Dict[str, Any]:
    """序列化单轮执行及其接口明细。"""
    details = DataFactoryRunDetail.query.filter_by(iteration_id=iteration.id).order_by(
        DataFactoryRunDetail.sort_order.asc(),
        DataFactoryRunDetail.id.asc(),
    ).all()
    return {
        "id": iteration.id,
        "iteration_no": iteration.iteration_no,
        "status": iteration.status,
        "error_message": iteration.error_message or "",
        "started_at": format_datetime(iteration.started_at),
        "ended_at": format_datetime(iteration.ended_at),
        "details": [serialize_run_detail(item) for item in details],
    }


def serialize_run_detail(detail: DataFactoryRunDetail) -> Dict[str, Any]:
    """序列化单个数据工厂步骤执行明细。"""
    return {
        "id": detail.id,
        "step_config_id": detail.step_config_id,
        "step_name": detail.step_name,
        "step_type": detail.step_type,
        "wait_seconds": detail.wait_seconds,
        "sort_order": detail.sort_order,
        "status": detail.status,
        "method": detail.method or "",
        "url": detail.url or "",
        "error_message": detail.error_message or "",
        "request_snapshot": detail.request_snapshot or {},
        "response_snapshot": detail.response_snapshot or {},
        "assertions_detail": detail.assertions_detail or [],
        "extractors_detail": detail.extractors_detail or [],
        "time_taken_ms": detail.time_taken_ms,
    }
