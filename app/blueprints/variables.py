# -*- coding: utf-8 -*-
"""
@Author: byy
@Desc: 环境与变量页面和 API，负责执行环境及全局、项目变量管理。
"""

from flask import Blueprint
from flask import jsonify
from flask import render_template
from flask import request
from sqlalchemy.exc import IntegrityError

from ..extensions import db
from ..enums import EnvironmentType
from ..models import Environment
from ..models import GlobalVariable
from ..models import Project
from ..services.pagination_service import paginate_response


variables_bp = Blueprint("variables", __name__, url_prefix="/variables")
environments_api_bp = Blueprint("environments_api", __name__, url_prefix="/api/execution-environment")
variables_api_bp = Blueprint("variables_api", __name__, url_prefix="/api/global-variable")


@variables_bp.route("/")
def index():
    """渲染环境和变量管理页。"""
    return render_template("variables.html")


@environments_api_bp.route("/list", methods=["POST"])
def list_environments():
    """返回全部环境。"""
    data = request.get_json(silent=True) or {}
    query = Environment.query.order_by(Environment.is_default.desc(), Environment.id.desc())
    return paginate_response(query, serialize_environment, data)


@environments_api_bp.route("/create", methods=["POST"])
def create_environment():
    """创建环境。"""
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"success": False, "message": "环境名称不能为空"}), 400
    environment_type = data.get("environment_type") or EnvironmentType.TESTING
    if environment_type not in EnvironmentType.VALUES:
        return jsonify({"success": False, "message": "环境类型不支持"}), 400

    environment = Environment(
        name=name,
        environment_type=environment_type,
        base_url=normalize_base_url(data.get("base_url")),
        description=(data.get("description") or "").strip(),
        is_default=parse_bool(data.get("is_default"), False),
    )
    db.session.add(environment)
    set_default_environment(environment)
    return commit_environment(environment)


@environments_api_bp.route("/save", methods=["POST"])
def update_environment():
    """更新环境。"""
    data = request.get_json(silent=True) or {}
    environment_id = data.get("environment_id")
    if not environment_id:
        return jsonify({"success": False, "message": "环境 ID 不能为空"}), 400
    environment = Environment.query.get_or_404(environment_id)
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"success": False, "message": "环境名称不能为空"}), 400

    environment.name = name
    environment_type = data.get("environment_type")
    if environment_type not in EnvironmentType.VALUES:
        return jsonify({"success": False, "message": "环境类型不支持"}), 400
    environment.environment_type = environment_type
    environment.base_url = normalize_base_url(data.get("base_url"))
    environment.description = (data.get("description") or "").strip()
    environment.is_default = parse_bool(data.get("is_default"), False)
    set_default_environment(environment)
    return commit_environment(environment)


@environments_api_bp.route("/delete", methods=["POST"])
def delete_environment():
    """删除环境。"""
    data = request.get_json(silent=True) or {}
    environment_id = data.get("environment_id")
    if not environment_id:
        return jsonify({"success": False, "message": "环境 ID 不能为空"}), 400
    environment = Environment.query.get_or_404(environment_id)
    db.session.delete(environment)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({"success": False, "message": "环境已被用例、任务或历史记录引用，不能删除"}), 409
    return jsonify({"success": True})


@variables_api_bp.route("/list", methods=["POST"])
def list_variables():
    """返回全部变量。"""
    data = request.get_json(silent=True) or {}
    query = GlobalVariable.query.order_by(GlobalVariable.id.desc())
    return paginate_response(query, serialize_variable, data)


@variables_api_bp.route("/create", methods=["POST"])
def create_variable():
    """创建变量。"""
    data = request.get_json(silent=True) or {}
    variable, error = build_variable(GlobalVariable(), data)
    if error:
        return jsonify({"success": False, "message": error}), 400

    db.session.add(variable)
    return commit_variable(variable)


@variables_api_bp.route("/save", methods=["POST"])
def update_variable():
    """更新变量。"""
    data = request.get_json(silent=True) or {}
    variable_id = data.get("variable_id")
    if not variable_id:
        return jsonify({"success": False, "message": "变量 ID 不能为空"}), 400
    variable = GlobalVariable.query.get_or_404(variable_id)
    variable, error = build_variable(variable, data)
    if error:
        return jsonify({"success": False, "message": error}), 400

    return commit_variable(variable)


@variables_api_bp.route("/delete", methods=["POST"])
def delete_variable():
    """删除变量。"""
    data = request.get_json(silent=True) or {}
    variable_id = data.get("variable_id")
    if not variable_id:
        return jsonify({"success": False, "message": "变量 ID 不能为空"}), 400
    variable = GlobalVariable.query.get_or_404(variable_id)
    db.session.delete(variable)
    db.session.commit()
    return jsonify({"success": True})


@variables_api_bp.route("/options", methods=["POST"])
def variable_options():
    """返回项目选项。"""
    projects = Project.query.order_by(Project.name.asc()).all()
    return jsonify(
        {
            "success": True,
            "data": {
                "projects": [{"id": item.id, "name": item.name} for item in projects],
                "environment_types": serialize_environment_types(),
            },
        }
    )


def build_variable(variable, data):
    """根据请求数据填充变量实例。"""
    var_key = (data.get("var_key") or "").strip()
    var_value = data.get("var_value")
    project_id = data.get("project_id") or None

    if not var_key:
        return variable, "变量名不能为空"
    if var_value is None:
        return variable, "变量值不能为空"
    if variable_exists(variable.id, project_id, var_key):
        return variable, "同一作用域内变量名已存在"

    variable.project_id = project_id
    variable.environment_id = None
    variable.var_key = var_key
    variable.var_value = str(var_value)
    variable.description = (data.get("description") or "").strip()
    variable.is_secret = parse_bool(data.get("is_secret"), False)
    variable.is_active = parse_bool(data.get("is_active"), True)
    return variable, None


def variable_exists(variable_id, project_id, var_key):
    """检查同一作用域内是否存在重复变量名。"""
    query = GlobalVariable.query.filter(
        GlobalVariable.var_key == var_key,
    )
    if project_id:
        query = query.filter(GlobalVariable.project_id == project_id)
    else:
        query = query.filter(GlobalVariable.project_id.is_(None))
    if variable_id:
        query = query.filter(GlobalVariable.id != variable_id)
    return db.session.query(query.exists()).scalar()


def set_default_environment(environment):
    """保证默认环境只有一个。"""
    if environment.is_default and environment.id is not None:
        Environment.query.filter(Environment.id != environment.id).update(
            {"is_default": False},
            synchronize_session=False,
        )


def commit_environment(environment):
    """提交环境并返回 JSON。"""
    try:
        db.session.flush()
        set_default_environment(environment)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({"success": False, "message": "环境名称已存在"}), 409
    return jsonify({"success": True, "data": serialize_environment(environment)})


def commit_variable(variable):
    """提交变量并返回 JSON。"""
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({"success": False, "message": "同一作用域内变量名已存在"}), 409
    return jsonify({"success": True, "data": serialize_variable(variable)})


def serialize_environment(environment):
    """序列化环境用于 JSON 响应。"""
    return {
        "id": environment.id,
        "name": environment.name,
        "environment_type": environment.environment_type,
        "environment_type_name": EnvironmentType.LABELS.get(
            environment.environment_type,
            environment.environment_type,
        ),
        "base_url": environment.base_url or "",
        "description": environment.description or "",
        "is_default": environment.is_default,
        "created_at": format_datetime(environment.created_at),
        "updated_at": format_datetime(environment.updated_at),
    }


def serialize_environment_types():
    """序列化环境类型选项。"""
    return [
        {"value": item, "name": EnvironmentType.LABELS[item]}
        for item in EnvironmentType.VALUES
    ]


def serialize_variable(variable):
    """序列化变量用于 JSON 响应。"""
    masked_value = "******" if variable.is_secret else variable.var_value
    return {
        "id": variable.id,
        "project_id": variable.project_id,
        "project_name": variable.project.name if variable.project else "全局",
        "environment_id": None,
        "environment_name": "",
        "var_key": variable.var_key,
        "var_value": variable.var_value,
        "display_value": masked_value,
        "description": variable.description or "",
        "is_secret": variable.is_secret,
        "is_active": variable.is_active,
        "created_at": format_datetime(variable.created_at),
        "updated_at": format_datetime(variable.updated_at),
    }


def parse_bool(value, default=False):
    """解析 JSON 中类似布尔值的字段。"""
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).lower() in ("1", "true", "yes", "on")


def normalize_base_url(value):
    """规范化可选的环境请求域名。"""
    value = (value or "").strip()
    return value.rstrip("/") if value else ""


def format_datetime(value):
    """格式化页面展示时间。"""
    from ..utils.datetime_utils import format_datetime as format_local_datetime

    return format_local_datetime(value)
