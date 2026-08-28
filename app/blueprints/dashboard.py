# -*- coding: utf-8 -*-
"""
@Author: byy
@Desc: 仪表盘页面与统计 API，负责接收项目和统计周期筛选条件。
"""

from typing import Any
from typing import Optional
from typing import Tuple

from flask import Blueprint
from flask import current_app
from flask import jsonify
from flask import render_template
from flask import request

from ..extensions import db
from ..models import Project
from ..services.dashboard_service import ALLOWED_STATISTICS_DAYS
from ..services.dashboard_service import build_dashboard_statistics


dashboard_bp = Blueprint("dashboard", __name__)
dashboard_api_bp = Blueprint(
    "dashboard_api",
    __name__,
    url_prefix="/api/dashboard",
)


@dashboard_bp.route("/")
def index() -> str:
    """渲染仪表盘首页。"""
    return render_template("dashboard.html")


@dashboard_api_bp.route("/statistics", methods=["POST"])
def statistics() -> Any:
    """返回项目资源和定时任务执行统计。"""
    data = request.get_json(silent=True) or {}
    project_id, project_error = parse_optional_int(data.get("project_id"))
    if project_error:
        return jsonify({"success": False, "message": project_error}), 400
    if project_id is not None and db.session.get(Project, project_id) is None:
        return jsonify({"success": False, "message": "统计项目不存在"}), 400

    days, days_error = parse_statistics_days(data.get("days"))
    if days_error:
        return jsonify({"success": False, "message": days_error}), 400

    current_app.logger.info(
        "dashboard statistics queried: project_id=%s days=%s",
        project_id,
        days,
    )
    return jsonify(
        {
            "success": True,
            "data": build_dashboard_statistics(project_id, days),
        }
    )


def parse_optional_int(value: Any) -> Tuple[Optional[int], Optional[str]]:
    """解析可选正整数，为空表示统计全部项目。"""
    if value in (None, ""):
        return None, None
    try:
        parsed_value = int(value)
    except (TypeError, ValueError):
        return None, "统计项目 ID 格式不正确"
    if parsed_value <= 0:
        return None, "统计项目 ID 格式不正确"
    return parsed_value, None


def parse_statistics_days(value: Any) -> Tuple[int, Optional[str]]:
    """解析并校验仪表盘允许的统计周期。"""
    if value in (None, ""):
        return 14, None
    try:
        days = int(value)
    except (TypeError, ValueError):
        return 14, "统计周期格式不正确"
    if days not in ALLOWED_STATISTICS_DAYS:
        return 14, "统计周期仅支持 7、14 或 30 天"
    return days, None
