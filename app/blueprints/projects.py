# -*- coding: utf-8 -*-
"""
@Author: byy
@Desc: 项目与项目模块页面和 API，负责项目层级资源管理。
"""

import uuid
from typing import Any
from typing import Dict
from typing import List
from typing import Optional
from typing import Tuple

from flask import Blueprint
from flask import current_app
from flask import jsonify
from flask import render_template
from flask import request
from sqlalchemy.exc import IntegrityError

from ..extensions import db
from ..models import Project
from ..models import ProjectModule
from ..models import Interface
from ..services.pagination_service import paginate_response


projects_bp = Blueprint("projects", __name__, url_prefix="/projects")
projects_api_bp = Blueprint("projects_api", __name__, url_prefix="/api/project")
project_modules_api_bp = Blueprint(
    "project_modules_api",
    __name__,
    url_prefix="/api/project-module",
)


@projects_bp.route("/")
def index():
    """渲染项目管理页。"""
    return render_template("projects.html")


@projects_api_bp.route("/list", methods=["POST"])
def list_projects():
    """返回全部项目。"""
    data = request.get_json(silent=True) or {}
    query = Project.query.order_by(Project.id.desc())
    return paginate_response(query, serialize_project, data)


@projects_api_bp.route("/create", methods=["POST"])
def create_project() -> Any:
    """创建项目。"""
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"success": False, "message": "项目名称不能为空"}), 400

    module_changes, error = validate_project_modules(data.get("modules"), None, True)
    if error:
        return jsonify({"success": False, "message": error[0]}), error[1]

    project = Project(
        name=name,
        description=(data.get("description") or "").strip(),
        is_active=parse_bool(data.get("is_active"), True),
    )
    db.session.add(project)
    for module_change in module_changes or []:
        project.modules.append(ProjectModule(name=module_change["name"]))
    return commit_project_changes(project)


@projects_api_bp.route("/detail", methods=["POST"])
def get_project():
    """返回项目详情及其模块数据。"""
    data = request.get_json(silent=True) or {}
    project_id = data.get("project_id")
    if not project_id:
        return jsonify({"success": False, "message": "项目 ID 不能为空"}), 400
    project = db.get_or_404(Project, project_id)
    return jsonify({"success": True, "data": serialize_project(project)})


@projects_api_bp.route("/save", methods=["POST"])
def update_project() -> Any:
    """更新项目。"""
    data = request.get_json(silent=True) or {}
    project_id = data.get("project_id")
    if not project_id:
        return jsonify({"success": False, "message": "项目 ID 不能为空"}), 400
    project = Project.query.get_or_404(project_id)
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"success": False, "message": "项目名称不能为空"}), 400

    module_changes, error = validate_project_modules(data.get("modules"), project, False)
    if error:
        return jsonify({"success": False, "message": error[0]}), error[1]

    project.name = name
    project.description = (data.get("description") or "").strip()
    project.is_active = parse_bool(data.get("is_active"), True)
    return commit_project_changes(project, module_changes)


@projects_api_bp.route("/delete", methods=["POST"])
def delete_project():
    """删除项目。"""
    data = request.get_json(silent=True) or {}
    project_id = data.get("project_id")
    if not project_id:
        return jsonify({"success": False, "message": "项目 ID 不能为空"}), 400
    project = Project.query.get_or_404(project_id)
    db.session.delete(project)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({"success": False, "message": "项目已被接口、变量或用例引用，不能删除"}), 409
    return jsonify({"success": True})


@project_modules_api_bp.route("/list", methods=["POST"])
def list_project_modules():
    """返回指定项目的全部模块。"""
    data = request.get_json(silent=True) or {}
    project_id = data.get("project_id")
    if not project_id:
        return jsonify({"success": False, "message": "项目 ID 不能为空"}), 400
    modules = ProjectModule.query.filter_by(project_id=project_id).order_by(
        ProjectModule.name.asc(),
        ProjectModule.id.asc(),
    ).all()
    return jsonify({"success": True, "data": [serialize_module(item) for item in modules]})


@project_modules_api_bp.route("/create", methods=["POST"])
def create_project_module():
    """在指定项目下创建一级模块。"""
    data = request.get_json(silent=True) or {}
    project_id = data.get("project_id")
    name = normalize_module_name(data.get("name"))
    if not project_id:
        return jsonify({"success": False, "message": "项目 ID 不能为空"}), 400
    if not name:
        return jsonify({"success": False, "message": "模块名称不能为空"}), 400
    if db.session.get(Project, project_id) is None:
        return jsonify({"success": False, "message": "项目不存在"}), 400
    if find_project_module(project_id, name):
        return jsonify({"success": False, "message": "当前项目下模块名称已存在"}), 409
    module = ProjectModule(project_id=project_id, name=name)
    db.session.add(module)
    return commit_module(module)


@project_modules_api_bp.route("/save", methods=["POST"])
def update_project_module():
    """修改模块名称，关联接口通过模块 ID 自动同步展示。"""
    data = request.get_json(silent=True) or {}
    module_id = data.get("module_id")
    name = normalize_module_name(data.get("name"))
    if not module_id:
        return jsonify({"success": False, "message": "模块 ID 不能为空"}), 400
    if not name:
        return jsonify({"success": False, "message": "模块名称不能为空"}), 400
    module = db.get_or_404(ProjectModule, module_id)
    duplicate = find_project_module(module.project_id, name)
    if duplicate and duplicate.id != module.id:
        return jsonify({"success": False, "message": "当前项目下模块名称已存在"}), 409
    module.name = name
    return commit_module(module)


@project_modules_api_bp.route("/delete", methods=["POST"])
def delete_project_module():
    """删除没有关联接口的项目模块。"""
    data = request.get_json(silent=True) or {}
    module_id = data.get("module_id")
    if not module_id:
        return jsonify({"success": False, "message": "模块 ID 不能为空"}), 400
    module = db.get_or_404(ProjectModule, module_id)
    interface_count = Interface.query.filter_by(module_id=module.id).count()
    if interface_count:
        return jsonify(
            {
                "success": False,
                "message": "模块“%s”下存在 %s 个接口，不能删除" % (module.name, interface_count),
            }
        ), 409
    db.session.delete(module)
    db.session.commit()
    return jsonify({"success": True})


def serialize_project(project):
    """序列化项目用于 JSON 响应。"""
    modules = sorted(project.modules, key=lambda item: (item.name.lower(), item.id))
    return {
        "id": project.id,
        "name": project.name,
        "description": project.description or "",
        "is_active": project.is_active,
        "modules": [serialize_module(item) for item in modules],
        "created_at": format_datetime(project.created_at),
        "updated_at": format_datetime(project.updated_at),
    }


def serialize_module(module):
    """序列化项目模块及其接口数量。"""
    return {
        "id": module.id,
        "project_id": module.project_id,
        "name": module.name,
        "interface_count": len(module.interfaces),
        "created_at": format_datetime(module.created_at),
        "updated_at": format_datetime(module.updated_at),
    }


def normalize_module_name(value):
    """规范化用户输入的模块名称。"""
    return str(value or "").strip()


def find_project_module(project_id, name):
    """按项目和不区分大小写的名称查找模块。"""
    normalized_name = normalize_module_name(name).lower()
    modules = ProjectModule.query.filter_by(project_id=project_id).all()
    return next(
        (item for item in modules if item.name.strip().lower() == normalized_name),
        None,
    )


def validate_project_modules(
    raw_modules: Any,
    project: Optional[Project],
    is_create: bool,
) -> Tuple[Optional[List[Dict[str, Any]]], Optional[Tuple[str, int]]]:
    """校验项目嵌套提交的模块，返回规范化后的变更列表。"""
    if raw_modules is None:
        return ([] if is_create else None), None
    if not isinstance(raw_modules, list):
        return None, ("项目模块必须是数组", 400)

    existing_modules = {item.id: item for item in (project.modules if project else [])}
    normalized_changes = []
    submitted_ids = set()
    for index, raw_module in enumerate(raw_modules, 1):
        if not isinstance(raw_module, dict):
            return None, ("第 %s 个模块数据格式不正确" % index, 400)
        module_id = raw_module.get("id")
        delete_requested = parse_bool(raw_module.get("_delete"), False)
        name = normalize_module_name(raw_module.get("name"))

        if module_id in (None, ""):
            module_id = None
        else:
            try:
                module_id = int(module_id)
            except (TypeError, ValueError):
                return None, ("第 %s 个模块 ID 格式不正确" % index, 400)
            if module_id <= 0:
                return None, ("第 %s 个模块 ID 格式不正确" % index, 400)

        if is_create and module_id is not None:
            return None, ("新增项目不能关联已有模块", 400)
        if module_id is None and delete_requested:
            return None, ("未保存的新模块不能标记为删除", 400)
        if module_id is not None:
            if module_id in submitted_ids:
                return None, ("模块 ID %s 重复提交" % module_id, 400)
            submitted_ids.add(module_id)
            if module_id not in existing_modules:
                return None, ("模块 ID %s 不属于当前项目" % module_id, 400)
        if not delete_requested:
            if not name:
                return None, ("第 %s 个模块名称不能为空" % index, 400)
            if len(name) > 128:
                return None, ("模块名称不能超过 128 个字符", 400)

        normalized_changes.append(
            {"id": module_id, "name": name, "_delete": delete_requested}
        )

    changes_by_id = {
        item["id"]: item for item in normalized_changes if item["id"] is not None
    }
    final_names = []
    for module_id, module in existing_modules.items():
        change = changes_by_id.get(module_id)
        if change and change["_delete"]:
            interface_count = Interface.query.filter_by(module_id=module_id).count()
            if interface_count:
                return None, (
                    "模块“%s”下存在 %s 个接口，不能删除"
                    % (module.name, interface_count),
                    409,
                )
            continue
        final_names.append(change["name"] if change else module.name)
    final_names.extend(
        item["name"]
        for item in normalized_changes
        if item["id"] is None and not item["_delete"]
    )
    normalized_names = [name.strip().lower() for name in final_names]
    if len(normalized_names) != len(set(normalized_names)):
        return None, ("当前项目下模块名称不能重复", 409)
    return normalized_changes, None


def apply_project_module_changes(
    project: Project,
    module_changes: Optional[List[Dict[str, Any]]],
) -> None:
    """在当前事务中应用模块新增、重命名和删除操作。"""
    if module_changes is None:
        return
    existing_modules = {item.id: item for item in project.modules}
    rename_changes = [
        item
        for item in module_changes
        if item["id"] is not None
        and not item["_delete"]
        and existing_modules[item["id"]].name != item["name"]
    ]
    for change in rename_changes:
        existing_modules[change["id"]].name = "__tmp__%s" % uuid.uuid4().hex
    if rename_changes:
        db.session.flush()
    for change in module_changes:
        if change["id"] is not None and change["_delete"]:
            db.session.delete(existing_modules[change["id"]])
    if any(item["id"] is not None and item["_delete"] for item in module_changes):
        db.session.flush()
    for change in module_changes:
        if change["id"] is None:
            project.modules.append(ProjectModule(name=change["name"]))
        elif not change["_delete"]:
            existing_modules[change["id"]].name = change["name"]


def commit_project_changes(
    project: Project,
    module_changes: Optional[List[Dict[str, Any]]] = None,
) -> Any:
    """原子提交项目基本信息和模块变更，失败时整体回滚。"""
    try:
        apply_project_module_changes(project, module_changes)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        current_app.logger.info("project save conflict: project_id=%s", project.id)
        return jsonify({"success": False, "message": "项目或模块名称已存在"}), 409
    except Exception:
        db.session.rollback()
        current_app.logger.exception("project save failed: project_id=%s", project.id)
        return jsonify({"success": False, "message": "项目保存失败"}), 500
    current_app.logger.info("project saved: project_id=%s", project.id)
    return jsonify({"success": True, "data": serialize_project(project)})


def commit_module(module):
    """提交模块变更并返回统一 JSON。"""
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({"success": False, "message": "当前项目下模块名称已存在"}), 409
    return jsonify({"success": True, "data": serialize_module(module)})


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
