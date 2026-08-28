# -*- coding: utf-8 -*-
"""
@Author: byy
@Desc: 测试报告页面与 API，负责报告列表、详情和 HTML 内容查询。
"""

from flask import Blueprint
from flask import jsonify
from flask import render_template
from flask import request

from ..models import ExecutionDetail
from ..models import ExecutionHistory
from ..services.report_service import get_report_data
from ..services.report_service import refresh_history_report
from ..services.pagination_service import paginate_response


reports_bp = Blueprint("reports", __name__, url_prefix="/reports")
reports_api_bp = Blueprint("reports_api", __name__, url_prefix="/api/execution-report")


@reports_bp.route("/")
def index():
    """渲染报告历史列表页。"""
    return render_template("report_list.html")


@reports_bp.route("/<int:history_id>")
def detail(history_id):
    """渲染报告详情页。"""
    data = get_report_data(history_id)
    return render_template("report_detail.html", embedded=False, **data)


@reports_api_bp.route("/list", methods=["POST"])
def list_reports():
    """返回报告历史。"""
    data = request.get_json(silent=True) or {}
    query = ExecutionHistory.query.order_by(ExecutionHistory.id.desc())
    return paginate_response(query, serialize_history, data)


@reports_api_bp.route("/detail", methods=["POST"])
def get_report():
    """返回单个报告及其明细。"""
    data = request.get_json(silent=True) or {}
    history_id = data.get("history_id")
    if not history_id:
        return jsonify({"success": False, "message": "执行历史 ID 不能为空"}), 400
    data = get_report_data(history_id)
    return jsonify(
        {
            "success": True,
            "data": {
                "history": serialize_history(data["history"]),
                "details": [serialize_detail(item) for item in data["details"]],
                "assertion_failures": [
                    {
                        "case_name": item["detail"].case_name,
                        "interface_name": item["detail"].interface_name,
                        "name": item["name"],
                        "actual": item["actual"],
                        "expected": item["expected"],
                        "comparator": item["comparator"],
                        "comparator_label": item["comparator_label"],
                        "actual_type": item["actual_type"],
                        "expected_type": item["expected_type"],
                        "value_type": item["value_type"],
                        "message": item["message"],
                    }
                    for item in data["assertion_failures"]
                ],
                "report_url": data["report_url"],
            },
        }
    )


@reports_api_bp.route("/render-html", methods=["POST"])
def render_report():
    """渲染并存储报告 HTML。"""
    data = request.get_json(silent=True) or {}
    history_id = data.get("history_id")
    if not history_id:
        return jsonify({"success": False, "message": "执行历史 ID 不能为空"}), 400
    html = refresh_history_report(history_id)
    return jsonify({"success": True, "data": {"html_length": len(html)}})


def serialize_history(history):
    """序列化执行历史。"""
    return {
        "id": history.id,
        "task_name": history.task_name or "",
        "trigger_type": history.trigger_type,
        "environment_name": history.environment.name if history.environment else "",
        "status": history.status,
        "total_count": history.total_count,
        "success_count": history.success_count,
        "fail_count": history.fail_count,
        "error_count": history.error_count,
        "interrupted": history.interrupted,
        "start_time": format_datetime(history.start_time),
        "end_time": format_datetime(history.end_time),
    }


def serialize_detail(detail):
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
        "time_taken_ms": detail.time_taken_ms,
        "assertions_detail": detail.assertions_detail or [],
        "response_snapshot": detail.response_snapshot or {},
        "ws_messages": detail.ws_messages or [],
        "sort_order": detail.sort_order,
    }


def format_datetime(value):
    """格式化页面展示时间。"""
    from ..utils.datetime_utils import format_datetime as format_local_datetime

    return format_local_datetime(value)
