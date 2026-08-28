# -*- coding: utf-8 -*-
"""
@Author: byy
@Desc: 定时任务调度服务，负责 APScheduler 启停、任务同步和自动执行。
"""

import logging
from typing import Any
from typing import Dict

from flask import Flask
from flask import current_app

from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy.exc import SQLAlchemyError

from ..enums import ScheduleType
from ..enums import TriggerType
from ..extensions import db
from ..extensions import scheduler
from ..models import ScheduledTask
from ..models import TaskNotification
from ..models import TaskSuite
from ..utils.datetime_utils import now_local
from ..utils.datetime_utils import to_local_naive
from .notifier import notify_task_result
from .report_service import generate_report_link
from .report_service import refresh_history_report
from .suite_runner import run_suite


logger = logging.getLogger(__name__)


def init_scheduler(app):
    """在配置允许时启动 APScheduler 并加载启用的任务。"""
    if not app.config.get("ENABLE_SCHEDULER", True):
        return
    if not scheduler.running:
        scheduler.configure(timezone=app.config.get("SCHEDULER_TIMEZONE", "Asia/Shanghai"))
        scheduler.start()
    with app.app_context():
        try:
            load_enabled_tasks()
        except SQLAlchemyError:
            logger.info("skip scheduler task loading before database is ready")


def scheduler_status():
    """返回调度器运行状态用于诊断。"""
    enabled_config = bool(current_app.config.get("ENABLE_SCHEDULER", True))
    return {
        "enabled_config": enabled_config,
        "running": scheduler.running,
        "job_count": len(scheduler.get_jobs()) if scheduler.running else 0,
        "timezone": str(current_app.config.get("SCHEDULER_TIMEZONE", "Asia/Shanghai")),
    }


def load_enabled_tasks():
    """把全部启用的定时任务加载到 APScheduler。"""
    tasks = ScheduledTask.query.filter_by(enabled=True).all()
    for task in tasks:
        sync_task(task)


def execute_scheduled_task(app: Flask, task_id: int) -> Dict[str, Any]:
    """在 Flask 应用上下文中执行调度器自动触发的任务。"""
    with app.app_context():
        try:
            return execute_task(task_id, TriggerType.SCHEDULED)
        finally:
            db.session.remove()


def sync_task(task):
    """在 APScheduler 中新增、更新或移除任务。"""
    job_id = _job_id(task.id)
    if not scheduler.running:
        task.next_run_at = None
        db.session.commit()
        return None
    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)
    if not task.enabled:
        task.next_run_at = None
        db.session.commit()
        return None
    trigger = build_trigger(task)
    job = scheduler.add_job(
        execute_scheduled_task,
        trigger=trigger,
        args=[current_app._get_current_object(), task.id],
        id=job_id,
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    task.next_run_at = to_local_naive(job.next_run_time)
    db.session.commit()
    return job


def remove_task(task_id):
    """存在定时任务时将其移除。"""
    job_id = _job_id(task_id)
    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)


def build_trigger(task):
    """根据任务计划字段构造 APScheduler 触发器。"""
    if task.schedule_type == ScheduleType.INTERVAL:
        seconds = int(task.interval_seconds or 60)
        return IntervalTrigger(seconds=seconds)
    if task.schedule_type == ScheduleType.DAILY:
        hour, minute = _parse_daily_time(task.daily_time)
        return CronTrigger(hour=hour, minute=minute)
    if task.schedule_type == ScheduleType.CRON:
        if not task.cron_expression:
            raise ValueError("cron 表达式不能为空")
        return CronTrigger.from_crontab(task.cron_expression)
    raise ValueError("不支持的执行计划: %s" % task.schedule_type)


def execute_task(task_id: int, trigger_type: str) -> Dict[str, Any]:
    """按指定触发来源执行任务并发送通知。"""
    if trigger_type not in TriggerType.VALUES:
        raise ValueError("任务执行触发方式不支持")
    task = db.session.get(ScheduledTask, task_id)
    if task is None:
        raise ValueError("定时任务不存在")

    task.last_run_at = now_local()
    task_suites = TaskSuite.query.filter_by(task_id=task.id).order_by(TaskSuite.sort_order.asc()).all()
    notifications = [
        item.notification for item in TaskNotification.query.filter_by(task_id=task.id).all()
        if item.notification is not None
    ]
    results = []
    report_links = []
    total_count = 0
    success_count = 0
    fail_count = 0
    error_count = 0

    for task_suite in task_suites:
        suite = task_suite.suite
        if suite is None or suite.environment_id is None:
            raise ValueError("任务关联集合未配置执行环境")
        result = run_suite(suite.id, suite.environment_id)
        history = result.get("history_id")
        if history:
            from ..models import ExecutionHistory

            history_obj = db.session.get(ExecutionHistory, history)
            if history_obj:
                history_obj.task_id = task.id
                history_obj.task_name = task.name
                history_obj.trigger_type = trigger_type
                db.session.commit()
                refresh_history_report(history_obj.id)
            report_links.append(generate_report_link(history))
        results.append(result)
        total_count += result.get("total_count", 0)
        success_count += result.get("success_count", 0)
        fail_count += result.get("fail_count", 0)
        error_count += result.get("error_count", 0)

    summary = {
        "task_id": task.id,
        "task_name": task.name,
        "total_count": total_count,
        "success_count": success_count,
        "fail_count": fail_count,
        "error_count": error_count,
        "report_links": report_links,
        "suites": results,
    }
    summary["notifications"] = notify_task_result(notifications, task, summary)
    db.session.commit()
    return summary


def _parse_daily_time(value):
    """解析 HH:MM 格式的每日执行时间。"""
    if not value or ":" not in value:
        raise ValueError("daily 时间格式必须为 HH:MM")
    hour, minute = value.split(":", 1)
    return int(hour), int(minute)


def _job_id(task_id):
    """构造调度任务编号。"""
    return "scheduled_task_%s" % task_id
