# -*- coding: utf-8 -*-
"""
@Author: byy
@Desc: 仪表盘统计服务，汇总项目资源和定时任务产生的用例执行数据。
"""

from datetime import datetime
from datetime import time
from datetime import timedelta
from typing import Any
from typing import Dict
from typing import List
from typing import Optional

from sqlalchemy import distinct
from sqlalchemy import func
from sqlalchemy import or_
from sqlalchemy.orm import Query

from ..enums import DetailStatus
from ..enums import TriggerType
from ..extensions import db
from ..models import ExecutionDetail
from ..models import ExecutionHistory
from ..models import Interface
from ..models import Project
from ..models import ProjectModule
from ..models import Suite
from ..models import TestCase
from ..utils.datetime_utils import now_local


ALLOWED_STATISTICS_DAYS = (7, 14, 30)
RESULT_STATUSES = (
    DetailStatus.PASS,
    DetailStatus.FAIL,
    DetailStatus.ERROR,
    DetailStatus.SKIPPED,
)


def build_dashboard_statistics(
    project_id: Optional[int],
    days: int,
) -> Dict[str, Any]:
    """构造仪表盘资源总数和定时任务执行统计。"""
    projects = Project.query.order_by(Project.name.asc()).all()
    start_date = now_local().date() - timedelta(days=days - 1)
    start_time = datetime.combine(start_date, time.min)
    trend = build_execution_trend(project_id, start_time, days)
    distribution = {
        status: sum(item[status] for item in trend)
        for status in RESULT_STATUSES
    }
    total_count = sum(distribution.values())
    pass_count = distribution[DetailStatus.PASS]
    return {
        "projects": [
            {"id": project.id, "name": project.name}
            for project in projects
        ],
        "scope": {
            "project_id": project_id,
            "days": days,
            "trigger_type": TriggerType.SCHEDULED,
        },
        "metrics": build_resource_metrics(project_id),
        "trend": trend,
        "distribution": {
            **distribution,
            "total": total_count,
            "pass_rate": round(pass_count * 100.0 / total_count, 1)
            if total_count
            else 0.0,
        },
    }


def build_resource_metrics(project_id: Optional[int]) -> Dict[str, int]:
    """按项目范围统计项目、接口、用例、集合和定时任务报告数。"""
    interface_query = Interface.query.join(
        ProjectModule,
        Interface.module_id == ProjectModule.id,
    )
    case_query = (
        TestCase.query.join(Interface, TestCase.interface_id == Interface.id)
        .join(ProjectModule, Interface.module_id == ProjectModule.id)
    )
    suite_query = Suite.query

    if project_id is not None:
        interface_query = interface_query.filter(
            ProjectModule.project_id == project_id
        )
        case_query = case_query.filter(ProjectModule.project_id == project_id)
        suite_query = suite_query.filter(Suite.project_id == project_id)

    return {
        "project_count": 1 if project_id is not None else Project.query.count(),
        "interface_count": interface_query.count(),
        "case_count": case_query.count(),
        "suite_count": suite_query.count(),
        "report_count": count_scheduled_reports(project_id),
    }


def count_scheduled_reports(project_id: Optional[int]) -> int:
    """统计全部或指定项目由定时任务生成的执行报告。"""
    if project_id is None:
        return ExecutionHistory.query.filter_by(
            trigger_type=TriggerType.SCHEDULED
        ).count()

    query = (
        db.session.query(func.count(distinct(ExecutionHistory.id)))
        .select_from(ExecutionHistory)
        .join(
            ExecutionDetail,
            ExecutionDetail.history_id == ExecutionHistory.id,
        )
        .filter(ExecutionHistory.trigger_type == TriggerType.SCHEDULED)
    )
    query = apply_detail_project_scope(query, project_id)
    return int(query.scalar() or 0)


def build_execution_trend(
    project_id: Optional[int],
    start_time: datetime,
    days: int,
) -> List[Dict[str, Any]]:
    """按平台本地日期聚合定时任务产生的用例执行明细。"""
    execution_date = func.date(ExecutionHistory.start_time)
    query = (
        db.session.query(
            execution_date.label("execution_date"),
            ExecutionDetail.status,
            func.count(ExecutionDetail.id).label("result_count"),
        )
        .select_from(ExecutionDetail)
        .join(
            ExecutionHistory,
            ExecutionDetail.history_id == ExecutionHistory.id,
        )
        .filter(
            ExecutionHistory.trigger_type == TriggerType.SCHEDULED,
            ExecutionHistory.start_time >= start_time,
            ExecutionDetail.status.in_(RESULT_STATUSES),
        )
    )
    query = apply_detail_project_scope(query, project_id)
    rows = query.group_by(execution_date, ExecutionDetail.status).all()

    result_map: Dict[str, Dict[str, int]] = {}
    for execution_day, status, result_count in rows:
        date_key = format_query_date(execution_day)
        result_map.setdefault(date_key, {})[status] = int(result_count)

    trend: List[Dict[str, Any]] = []
    start_date = start_time.date()
    for offset in range(days):
        execution_day = start_date + timedelta(days=offset)
        date_key = execution_day.isoformat()
        counts = result_map.get(date_key, {})
        trend.append(
            {
                "date": date_key,
                DetailStatus.PASS: counts.get(DetailStatus.PASS, 0),
                DetailStatus.FAIL: counts.get(DetailStatus.FAIL, 0),
                DetailStatus.ERROR: counts.get(DetailStatus.ERROR, 0),
                DetailStatus.SKIPPED: counts.get(DetailStatus.SKIPPED, 0),
            }
        )
    return trend


def apply_detail_project_scope(
    query: Query,
    project_id: Optional[int],
) -> Query:
    """通过集合或接口归属把执行明细限制到指定项目。"""
    if project_id is None:
        return query
    return (
        query.outerjoin(Suite, ExecutionDetail.suite_id == Suite.id)
        .outerjoin(Interface, ExecutionDetail.interface_id == Interface.id)
        .outerjoin(ProjectModule, Interface.module_id == ProjectModule.id)
        .filter(
            or_(
                Suite.project_id == project_id,
                ProjectModule.project_id == project_id,
            )
        )
    )


def format_query_date(value: Any) -> str:
    """兼容 SQLite 与 MySQL 的 date 聚合结果并返回 ISO 日期。"""
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)
