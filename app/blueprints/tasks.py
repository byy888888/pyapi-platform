# -*- coding: utf-8 -*-
"""
@Author: byy
@Desc: 定时任务页面与 API，负责任务配置、调度状态和手动触发。
"""

from flask import Blueprint
from flask import jsonify
from flask import render_template
from flask import request
from ..enums import EnvironmentType
from ..enums import ScheduleType
from ..enums import TriggerType
from ..extensions import db
from ..models import Notification
from ..models import ScheduledTask
from ..models import Suite
from ..models import TaskNotification
from ..models import TaskSuite
from ..services.scheduler_service import scheduler_status
from ..services.scheduler_service import execute_task
from ..services.scheduler_service import remove_task
from ..services.scheduler_service import sync_task
from ..services.pagination_service import paginate_response


tasks_bp = Blueprint("tasks", __name__, url_prefix="/tasks")
tasks_api_bp = Blueprint("tasks_api", __name__, url_prefix="/api/scheduled-task")
scheduler_api_bp = Blueprint("scheduler_api", __name__, url_prefix="/api/scheduler")


@tasks_bp.route("/")
def index():
    """渲染定时任务管理页。"""
    return render_template("tasks.html")


@tasks_api_bp.route("/list", methods=["POST"])
def list_tasks():
    """按任务名称和环境类型查询定时任务。"""
    data = request.get_json(silent=True) or {}
    query = ScheduledTask.query.order_by(ScheduledTask.id.desc())
    keyword = (data.get("keyword") or "").strip()
    environment_type = data.get("environment_type") or ""
    if keyword:
        query = query.filter(ScheduledTask.name.ilike("%%%s%%" % keyword))
    if environment_type:
        if environment_type not in EnvironmentType.VALUES:
            return jsonify({"success": False, "message": "环境类型不支持"}), 400
        query = query.filter(ScheduledTask.environment_type == environment_type)
    return paginate_response(query, serialize_task, data)


@tasks_api_bp.route("/detail", methods=["POST"])
def get_task():
    """返回单个定时任务。"""
    data = request.get_json(silent=True) or {}
    task_id = data.get("task_id")
    if not task_id:
        return jsonify({"success": False, "message": "任务 ID 不能为空"}), 400
    task = db.get_or_404(ScheduledTask, task_id)
    return jsonify({"success": True, "data": serialize_task(task)})


@tasks_api_bp.route("/create", methods=["POST"])
def create_task():
    """创建定时任务。"""
    task, suite_ids, notification_ids, error = build_task(
        ScheduledTask(),
        request.get_json(silent=True) or {},
    )
    if error:
        return jsonify({"success": False, "message": error}), 400
    db.session.add(task)
    db.session.flush()
    replace_task_relations(task, suite_ids, notification_ids)
    db.session.commit()
    sync_task(task)
    return jsonify({"success": True, "data": serialize_task(task)})


@tasks_api_bp.route("/save", methods=["POST"])
def update_task():
    """更新定时任务。"""
    data = request.get_json(silent=True) or {}
    task_id = data.get("task_id")
    if not task_id:
        return jsonify({"success": False, "message": "任务 ID 不能为空"}), 400
    task = db.get_or_404(ScheduledTask, task_id)
    task, suite_ids, notification_ids, error = build_task(task, data)
    if error:
        return jsonify({"success": False, "message": error}), 400
    replace_task_relations(task, suite_ids, notification_ids)
    db.session.commit()
    sync_task(task)
    return jsonify({"success": True, "data": serialize_task(task)})


@tasks_api_bp.route("/delete", methods=["POST"])
def delete_task():
    """删除定时任务。"""
    data = request.get_json(silent=True) or {}
    task_id = data.get("task_id")
    if not task_id:
        return jsonify({"success": False, "message": "任务 ID 不能为空"}), 400
    task = db.get_or_404(ScheduledTask, task_id)
    remove_task(task.id)
    TaskSuite.query.filter_by(task_id=task.id).delete()
    TaskNotification.query.filter_by(task_id=task.id).delete()
    db.session.delete(task)
    db.session.commit()
    return jsonify({"success": True})


@tasks_api_bp.route("/execute", methods=["POST"])
def run_task():
    """手动执行定时任务。"""
    data = request.get_json(silent=True) or {}
    task_id = data.get("task_id")
    if not task_id:
        return jsonify({"success": False, "message": "任务 ID 不能为空"}), 400
    try:
        result = execute_task(task_id, TriggerType.MANUAL)
    except Exception as exc:
        db.session.rollback()
        return jsonify({"success": False, "message": str(exc)}), 400
    return jsonify({"success": True, "data": result})


@tasks_api_bp.route("/options", methods=["POST"])
def task_options():
    """返回定时任务表单选项。"""
    suites = Suite.query.filter(Suite.environment_id.isnot(None)).order_by(Suite.name.asc()).all()
    notifications = Notification.query.order_by(Notification.name.asc()).all()
    return jsonify(
        {
            "success": True,
            "data": {
                "environment_types": serialize_environment_types(),
                "suites": [serialize_suite_option(item) for item in suites],
                "notifications": [{"id": item.id, "name": item.name, "notification_type": item.notification_type} for item in notifications],
                "schedule_types": list(ScheduleType.VALUES),
            },
        }
    )


@scheduler_api_bp.route("/status", methods=["POST"])
def get_scheduler_status():
    """返回任务页展示的 APScheduler 当前状态。"""
    return jsonify({"success": True, "data": scheduler_status()})


def build_task(task, data):
    """根据 JSON 数据填充定时任务字段。"""
    name = (data.get("name") or "").strip()
    environment_type = data.get("environment_type")
    schedule_type = data.get("schedule_type") or ScheduleType.INTERVAL
    suite_ids = [int(item) for item in data.get("suite_ids") or []]
    notification_ids = [int(item) for item in data.get("notification_ids") or []]

    if not name:
        return task, suite_ids, notification_ids, "任务名称不能为空"
    if environment_type not in EnvironmentType.VALUES:
        return task, suite_ids, notification_ids, "所属环境类型不能为空或不支持"
    if schedule_type not in ScheduleType.VALUES:
        return task, suite_ids, notification_ids, "执行计划不支持"
    if schedule_type == ScheduleType.INTERVAL and not data.get("interval_seconds"):
        return task, suite_ids, notification_ids, "interval 模式需要间隔秒数"
    if schedule_type == ScheduleType.DAILY and not data.get("daily_time"):
        return task, suite_ids, notification_ids, "daily 模式需要固定时间"
    if schedule_type == ScheduleType.CRON and not data.get("cron_expression"):
        return task, suite_ids, notification_ids, "cron 模式需要表达式"
    if not suite_ids:
        return task, suite_ids, notification_ids, "请至少绑定一个集合"
    suites = Suite.query.filter(Suite.id.in_(suite_ids)).all()
    if len(suites) != len(set(suite_ids)):
        return task, suite_ids, notification_ids, "关联集合不存在"
    for suite in suites:
        if suite.environment is None:
            return task, suite_ids, notification_ids, "关联集合未配置执行环境"
        if suite.environment.environment_type != environment_type:
            return task, suite_ids, notification_ids, "关联集合的环境类型必须与任务所属环境一致"

    task.name = name
    task.environment_type = environment_type
    task.schedule_type = schedule_type
    task.interval_seconds = int(data.get("interval_seconds") or 0) or None
    task.daily_time = data.get("daily_time") or None
    task.cron_expression = data.get("cron_expression") or None
    task.enabled = parse_bool(data.get("enabled"), True)
    return task, suite_ids, notification_ids, None


def replace_task_relations(task, suite_ids, notification_ids):
    """替换集合和通知配置的关联关系。"""
    TaskSuite.query.filter_by(task_id=task.id).delete()
    TaskNotification.query.filter_by(task_id=task.id).delete()
    for index, suite_id in enumerate(suite_ids, start=1):
        db.session.add(TaskSuite(task_id=task.id, suite_id=suite_id, sort_order=index))
    for notification_id in notification_ids:
        db.session.add(TaskNotification(task_id=task.id, notification_id=notification_id))


def serialize_task(task):
    """序列化定时任务。"""
    suites = sorted(task.task_suites, key=lambda item: item.sort_order)
    return {
        "id": task.id,
        "name": task.name,
        "environment_type": task.environment_type,
        "environment_type_name": EnvironmentType.LABELS.get(
            task.environment_type,
            task.environment_type,
        ),
        "schedule_type": task.schedule_type,
        "interval_seconds": task.interval_seconds,
        "daily_time": task.daily_time or "",
        "cron_expression": task.cron_expression or "",
        "enabled": task.enabled,
        "next_run_at": format_datetime(task.next_run_at),
        "last_run_at": format_datetime(task.last_run_at),
        "suite_ids": [item.suite_id for item in suites],
        "suites": [serialize_suite_option(item.suite) for item in suites if item.suite],
        "notification_ids": [item.notification_id for item in task.task_notifications],
        "notifications": [
            {"id": item.notification_id, "name": item.notification.name if item.notification else ""}
            for item in task.task_notifications
        ],
        "created_at": format_datetime(task.created_at),
        "updated_at": format_datetime(task.updated_at),
    }


def serialize_environment_types():
    """序列化任务表单与筛选条件使用的环境类型。"""
    return [
        {"value": item, "name": EnvironmentType.LABELS[item]}
        for item in EnvironmentType.VALUES
    ]


def serialize_suite_option(suite):
    """序列化任务可关联集合，并附带其默认执行环境信息。"""
    environment = suite.environment
    return {
        "id": suite.id,
        "name": suite.name,
        "project_name": suite.project.name if suite.project else "",
        "environment_id": suite.environment_id,
        "environment_name": environment.name if environment else "",
        "environment_type": environment.environment_type if environment else "",
        "environment_type_name": (
            EnvironmentType.LABELS.get(environment.environment_type, "")
            if environment
            else ""
        ),
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
