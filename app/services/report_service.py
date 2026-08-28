# -*- coding: utf-8 -*-
"""
@Author: byy
@Desc: 报告服务，负责刷新执行报告、生成报告链接和序列化报告详情。
"""

from flask import current_app
from flask import render_template

from ..enums import AssertionComparator
from ..enums import HistoryStatus
from ..extensions import db
from ..models import ExecutionDetail
from ..models import ExecutionHistory
from ..utils.datetime_utils import now_local


def create_execution_history(task_id=None, task_name="", trigger_type="manual", environment_id=None):
    """创建执行历史记录。"""
    history = ExecutionHistory(
        task_id=task_id,
        task_name=task_name,
        trigger_type=trigger_type,
        environment_id=environment_id,
        start_time=now_local(),
        status=HistoryStatus.RUNNING,
        summary={},
    )
    db.session.add(history)
    db.session.flush()
    return history


def write_execution_detail(history_id, **kwargs):
    """写入一条执行明细记录。"""
    detail = ExecutionDetail(history_id=history_id, **kwargs)
    db.session.add(detail)
    db.session.flush()
    return detail


def summarize_history(history):
    """汇总执行明细并更新执行历史。"""
    details = ExecutionDetail.query.filter_by(history_id=history.id).all()
    history.total_count = len(details)
    history.success_count = len([item for item in details if item.status == "pass"])
    history.fail_count = len([item for item in details if item.status == "fail"])
    history.error_count = len([item for item in details if item.status == "error"])
    history.interrupted = any(item.status == "skipped" for item in details)
    history.summary = {
        "total_count": history.total_count,
        "success_count": history.success_count,
        "fail_count": history.fail_count,
        "error_count": history.error_count,
        "interrupted": history.interrupted,
    }
    if history.status == HistoryStatus.RUNNING:
        history.status = HistoryStatus.FINISHED
    if history.end_time is None:
        history.end_time = now_local()
    return history


def get_report_data(history_id):
    """根据执行历史构造报告数据。"""
    history = db.get_or_404(ExecutionHistory, history_id)
    details = ExecutionDetail.query.filter_by(history_id=history.id).order_by(
        ExecutionDetail.sort_order.asc(),
        ExecutionDetail.id.asc(),
    ).all()
    failed_details = [
        item for item in details if item.status in ("fail", "error")
    ]
    return {
        "history": history,
        "details": details,
        "failed_details": failed_details,
        "assertion_failures": collect_assertion_failures(details),
        "report_url": generate_report_link(history.id),
    }


def collect_assertion_failures(details):
    """收集带明细上下文的失败断言。"""
    failures = []
    for detail in details:
        for assertion in detail.assertions_detail or []:
            if not assertion.get("passed"):
                failures.append(
                    {
                        "detail": detail,
                        "name": assertion.get("name") or assertion.get("source") or "断言",
                        "actual": assertion.get("actual"),
                        "expected": assertion.get("expected"),
                        "comparator": assertion.get("comparator"),
                        "comparator_label": assertion.get("comparator_label")
                        or AssertionComparator.LABELS.get(
                            assertion.get("comparator"),
                            assertion.get("comparator"),
                        ),
                        "actual_type": assertion.get("actual_type"),
                        "expected_type": assertion.get("expected_type"),
                        "value_type": assertion.get("value_type"),
                        "message": assertion.get("message"),
                    }
                )
    return failures


def render_report_html(history_id):
    """渲染独立 HTML 报告并保存到执行历史。"""
    data = get_report_data(history_id)
    html = render_template("report_detail.html", embedded=True, **data)
    history = data["history"]
    history.report_html = html
    history.report_path = generate_report_link(history.id)
    db.session.commit()
    return html


def refresh_history_report(history_id):
    """刷新执行历史汇总和已渲染的报告 HTML。"""
    history = db.get_or_404(ExecutionHistory, history_id)
    summarize_history(history)
    db.session.flush()
    return render_report_html(history.id)


def generate_report_link(history_id):
    """生成绝对地址或配置化的报告链接。"""
    base_url = current_app.config.get("BASE_REPORT_URL")
    path = "/reports/%s" % history_id
    if base_url:
        return base_url.rstrip("/") + path
    return path


def format_datetime(value):
    """格式化报告展示时间。"""
    from ..utils.datetime_utils import format_datetime as format_local_datetime

    return format_local_datetime(value)
