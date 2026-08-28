# -*- coding: utf-8 -*-
"""
@Author: byy
@Desc: SQLAlchemy 数据模型，定义项目、接口、用例、集合、任务、报告和数据工厂表结构。
"""

from sqlalchemy.dialects import mysql

from .utils.datetime_utils import now_local
from .enums import BodyType
from .enums import DetailStatus
from .enums import DataFactoryIterationStatus
from .enums import DataFactoryRunStatus
from .enums import DataFactorySourceType
from .enums import DataFactoryStepType
from .enums import EnvironmentType
from .enums import HistoryStatus
from .enums import HttpMethod
from .enums import InterfaceType
from .enums import NotificationType
from .enums import ScheduleType
from .enums import SuiteType
from .enums import TriggerType
from .extensions import db


LONG_TEXT = db.Text().with_variant(mysql.LONGTEXT, "mysql")


class TimestampMixin(object):
    """通用时间字段。"""

    created_at = db.Column(db.DateTime, nullable=False, default=now_local)
    updated_at = db.Column(
        db.DateTime,
        nullable=False,
        default=now_local,
        onupdate=now_local,
    )


class Project(TimestampMixin, db.Model):
    """项目表。"""

    __tablename__ = "project"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(128), nullable=False, unique=True, index=True)
    description = db.Column(db.Text)
    is_active = db.Column(db.Boolean, nullable=False, default=True, index=True)

    modules = db.relationship("ProjectModule", back_populates="project")
    suites = db.relationship("Suite", back_populates="project")
    variables = db.relationship("GlobalVariable", back_populates="project")
    data_factories = db.relationship("DataFactory", back_populates="project")

    def __repr__(self):
        """返回便于调试和日志查看的模型文本表示。"""
        return "<Project %r>" % self.name


class ProjectModule(TimestampMixin, db.Model):
    """项目下的一级接口模块。"""

    __tablename__ = "project_module"
    __table_args__ = (
        db.UniqueConstraint("project_id", "name", name="uq_project_module_name"),
    )

    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey("project.id"), nullable=False, index=True)
    name = db.Column(db.String(128), nullable=False, index=True)

    project = db.relationship("Project", back_populates="modules")
    interfaces = db.relationship("Interface", back_populates="module")

    def __repr__(self):
        """返回便于调试和日志查看的模型文本表示。"""
        return "<ProjectModule %r>" % self.name


class Environment(TimestampMixin, db.Model):
    """环境表。"""

    __tablename__ = "environment"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(64), nullable=False, unique=True, index=True)
    environment_type = db.Column(
        db.String(32),
        nullable=False,
        default=EnvironmentType.TESTING,
        index=True,
    )
    base_url = db.Column(db.String(512))
    description = db.Column(db.Text)
    is_default = db.Column(db.Boolean, nullable=False, default=False, index=True)

    test_cases = db.relationship("TestCase", back_populates="environment")
    execution_histories = db.relationship("ExecutionHistory", back_populates="environment")
    data_factories = db.relationship("DataFactory", back_populates="environment")

    def __repr__(self):
        """返回便于调试和日志查看的模型文本表示。"""
        return "<Environment %r>" % self.name


class GlobalVariable(TimestampMixin, db.Model):
    """全局变量和项目变量表，与环境保持独立。"""

    __tablename__ = "global_variable"
    __table_args__ = (
        db.Index("ix_global_variable_lookup", "project_id", "var_key"),
    )

    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey("project.id"), nullable=True)
    environment_id = db.Column(
        db.Integer,
        db.ForeignKey("environment.id"),
        nullable=True,
    )
    var_key = db.Column(db.String(128), nullable=False)
    var_value = db.Column(db.Text, nullable=False)
    description = db.Column(db.Text)
    is_secret = db.Column(db.Boolean, nullable=False, default=False)
    is_active = db.Column(db.Boolean, nullable=False, default=True, index=True)

    project = db.relationship("Project", back_populates="variables")

    def __repr__(self):
        """返回便于调试和日志查看的模型文本表示。"""
        return "<GlobalVariable %r>" % self.var_key


class Interface(TimestampMixin, db.Model):
    """HTTP 或 WebSocket 接口表。"""

    __tablename__ = "interface"

    id = db.Column(db.Integer, primary_key=True)
    module_id = db.Column(
        db.Integer,
        db.ForeignKey("project_module.id"),
        nullable=False,
        index=True,
    )
    name = db.Column(db.String(128), nullable=False, index=True)
    interface_type = db.Column(
        db.String(32),
        nullable=False,
        default=InterfaceType.HTTP,
        index=True,
    )
    method = db.Column(db.String(16), nullable=True, default=HttpMethod.GET)
    url = db.Column(db.Text, nullable=False)
    params_template = db.Column(db.JSON, nullable=True, default=dict)
    headers_template = db.Column(db.JSON, nullable=False, default=dict)
    body_template = db.Column(db.JSON, nullable=False, default=dict)
    body_type = db.Column(db.String(16), nullable=False, default=BodyType.NONE)
    ws_config = db.Column(db.JSON, nullable=False, default=dict)
    description = db.Column(db.Text)
    is_active = db.Column(db.Boolean, nullable=False, default=True, index=True)

    module = db.relationship("ProjectModule", back_populates="interfaces")
    test_cases = db.relationship("TestCase", back_populates="interface")
    data_factory_steps = db.relationship(
        "DataFactoryStep",
        back_populates="interface",
    )

    @property
    def project_id(self):
        """通过所属模块返回接口的项目 ID。"""
        return self.module.project_id if self.module else None

    @property
    def project(self):
        """通过所属模块返回接口的项目。"""
        return self.module.project if self.module else None

    def __repr__(self):
        """返回便于调试和日志查看的模型文本表示。"""
        return "<Interface %r>" % self.name


class TestCase(TimestampMixin, db.Model):
    """测试用例表。"""

    __tablename__ = "test_case"

    id = db.Column(db.Integer, primary_key=True)
    interface_id = db.Column(db.Integer, db.ForeignKey("interface.id"), nullable=False, index=True)
    environment_id = db.Column(db.Integer, db.ForeignKey("environment.id"), nullable=True, index=True)
    name = db.Column(db.String(128), nullable=False, index=True)
    request_params = db.Column(db.JSON, nullable=False, default=dict)
    headers_override = db.Column(db.JSON, nullable=False, default=dict)
    body_override = db.Column(db.JSON, nullable=False, default=dict)
    assertions = db.Column(db.JSON, nullable=False, default=list)
    extractors = db.Column(db.JSON, nullable=False, default=list)
    ws_steps = db.Column(db.JSON, nullable=False, default=list)
    ws_config_override = db.Column(db.JSON, nullable=False, default=dict)
    timeout_seconds = db.Column(db.Integer, nullable=False, default=30)
    description = db.Column(db.Text)
    is_active = db.Column(db.Boolean, nullable=False, default=True, index=True)

    interface = db.relationship("Interface", back_populates="test_cases")
    environment = db.relationship("Environment", back_populates="test_cases")
    suite_cases = db.relationship("SuiteCase", back_populates="case")

    @property
    def project_id(self):
        """通过关联接口返回用例的项目 ID。"""
        return self.interface.project_id if self.interface else None

    @property
    def project(self):
        """通过关联接口返回用例的项目。"""
        return self.interface.project if self.interface else None

    def __repr__(self):
        """返回便于调试和日志查看的模型文本表示。"""
        return "<TestCase %r>" % self.name


class Suite(TimestampMixin, db.Model):
    """测试集合表。"""

    __tablename__ = "suite"

    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey("project.id"), nullable=False, index=True)
    name = db.Column(db.String(128), nullable=False, index=True)
    environment_id = db.Column(db.Integer, db.ForeignKey("environment.id"), nullable=True, index=True)
    suite_type = db.Column(
        db.String(32),
        nullable=False,
        default=SuiteType.SINGLE,
        index=True,
    )
    description = db.Column(db.Text)
    is_active = db.Column(db.Boolean, nullable=False, default=True, index=True)

    project = db.relationship("Project", back_populates="suites")
    environment = db.relationship("Environment")
    suite_cases = db.relationship("SuiteCase", back_populates="suite")
    task_suites = db.relationship("TaskSuite", back_populates="suite")

    def __repr__(self):
        """返回便于调试和日志查看的模型文本表示。"""
        return "<Suite %r>" % self.name


class SuiteCase(TimestampMixin, db.Model):
    """测试集合中的用例执行步骤。"""

    __tablename__ = "suite_case"

    id = db.Column(db.Integer, primary_key=True)
    suite_id = db.Column(db.Integer, db.ForeignKey("suite.id"), nullable=False, index=True)
    case_id = db.Column(db.Integer, db.ForeignKey("test_case.id"), nullable=False, index=True)
    step_name = db.Column(db.String(128))
    is_active = db.Column(db.Boolean, nullable=False, default=True, index=True)
    sort_order = db.Column(db.Integer, nullable=False, default=0)
    method_override = db.Column(db.String(16))
    url_override = db.Column(db.Text)
    body_type_override = db.Column(db.String(16))
    request_params_override = db.Column(db.JSON, nullable=True)
    headers_override = db.Column(db.JSON, nullable=True)
    body_override = db.Column(db.JSON, nullable=True)
    assertions_override = db.Column(db.JSON, nullable=True)
    extractors_override = db.Column(db.JSON, nullable=True)
    ws_steps_override = db.Column(db.JSON, nullable=True)
    timeout_seconds_override = db.Column(db.Integer)

    suite = db.relationship("Suite", back_populates="suite_cases")
    case = db.relationship("TestCase", back_populates="suite_cases")


class ScheduledTask(TimestampMixin, db.Model):
    """定时任务表。"""

    __tablename__ = "scheduled_task"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(128), nullable=False, index=True)
    environment_type = db.Column(db.String(32), nullable=False, index=True)
    schedule_type = db.Column(db.String(32), nullable=False, default=ScheduleType.INTERVAL)
    interval_seconds = db.Column(db.Integer)
    daily_time = db.Column(db.String(5))
    cron_expression = db.Column(db.String(128))
    enabled = db.Column(db.Boolean, nullable=False, default=True, index=True)
    next_run_at = db.Column(db.DateTime)
    last_run_at = db.Column(db.DateTime)

    task_suites = db.relationship("TaskSuite", back_populates="task")
    task_notifications = db.relationship("TaskNotification", back_populates="task")
    execution_histories = db.relationship("ExecutionHistory", back_populates="task")

    def __repr__(self):
        """返回便于调试和日志查看的模型文本表示。"""
        return "<ScheduledTask %r>" % self.name


class TaskSuite(TimestampMixin, db.Model):
    """定时任务和测试集合的关联表。"""

    __tablename__ = "task_suite"

    id = db.Column(db.Integer, primary_key=True)
    task_id = db.Column(db.Integer, db.ForeignKey("scheduled_task.id"), nullable=False, index=True)
    suite_id = db.Column(db.Integer, db.ForeignKey("suite.id"), nullable=False, index=True)
    sort_order = db.Column(db.Integer, nullable=False, default=0)

    task = db.relationship("ScheduledTask", back_populates="task_suites")
    suite = db.relationship("Suite", back_populates="task_suites")


class Notification(TimestampMixin, db.Model):
    """通知配置表。"""

    __tablename__ = "notification"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(128), nullable=False, index=True)
    notification_type = db.Column(
        db.String(32),
        nullable=False,
        default=NotificationType.DINGTALK,
        index=True,
    )
    config = db.Column(db.JSON, nullable=False, default=dict)
    message_template = db.Column(db.Text)
    is_active = db.Column(db.Boolean, nullable=False, default=True, index=True)

    task_notifications = db.relationship("TaskNotification", back_populates="notification")

    def __repr__(self):
        """返回便于调试和日志查看的模型文本表示。"""
        return "<Notification %r>" % self.name


class TaskNotification(TimestampMixin, db.Model):
    """定时任务和通知配置的关联表。"""

    __tablename__ = "task_notification"

    id = db.Column(db.Integer, primary_key=True)
    task_id = db.Column(db.Integer, db.ForeignKey("scheduled_task.id"), nullable=False, index=True)
    notification_id = db.Column(
        db.Integer,
        db.ForeignKey("notification.id"),
        nullable=False,
        index=True,
    )

    task = db.relationship("ScheduledTask", back_populates="task_notifications")
    notification = db.relationship("Notification", back_populates="task_notifications")


class ExecutionHistory(TimestampMixin, db.Model):
    """执行历史汇总表。"""

    __tablename__ = "execution_history"

    id = db.Column(db.Integer, primary_key=True)
    task_id = db.Column(db.Integer, db.ForeignKey("scheduled_task.id"), nullable=True, index=True)
    task_name = db.Column(db.String(128))
    trigger_type = db.Column(db.String(32), nullable=False, default=TriggerType.MANUAL, index=True)
    environment_id = db.Column(
        db.Integer,
        db.ForeignKey("environment.id"),
        nullable=False,
        index=True,
    )
    start_time = db.Column(db.DateTime, nullable=False, default=now_local)
    end_time = db.Column(db.DateTime)
    status = db.Column(db.String(32), nullable=False, default=HistoryStatus.RUNNING, index=True)
    total_count = db.Column(db.Integer, nullable=False, default=0)
    success_count = db.Column(db.Integer, nullable=False, default=0)
    fail_count = db.Column(db.Integer, nullable=False, default=0)
    error_count = db.Column(db.Integer, nullable=False, default=0)
    interrupted = db.Column(db.Boolean, nullable=False, default=False)
    summary = db.Column(db.JSON, nullable=False, default=dict)
    report_path = db.Column(db.String(255))
    report_html = db.Column(LONG_TEXT)

    task = db.relationship("ScheduledTask", back_populates="execution_histories")
    environment = db.relationship("Environment", back_populates="execution_histories")
    details = db.relationship("ExecutionDetail", back_populates="history")

    def __repr__(self):
        """返回便于调试和日志查看的模型文本表示。"""
        return "<ExecutionHistory %r>" % self.id


class ExecutionDetail(TimestampMixin, db.Model):
    """执行明细表。"""

    __tablename__ = "execution_detail"

    id = db.Column(db.Integer, primary_key=True)
    history_id = db.Column(
        db.Integer,
        db.ForeignKey("execution_history.id"),
        nullable=False,
        index=True,
    )
    suite_id = db.Column(db.Integer, db.ForeignKey("suite.id"), nullable=True, index=True)
    suite_name = db.Column(db.String(128))
    case_id = db.Column(db.Integer, db.ForeignKey("test_case.id"), nullable=True, index=True)
    case_name = db.Column(db.String(128))
    interface_id = db.Column(db.Integer, db.ForeignKey("interface.id"), nullable=True, index=True)
    interface_name = db.Column(db.String(128))
    interface_type = db.Column(
        db.String(32),
        nullable=False,
        default=InterfaceType.HTTP,
        index=True,
    )
    method = db.Column(db.String(16))
    url = db.Column(db.Text)
    status = db.Column(db.String(32), nullable=False, default=DetailStatus.PASS, index=True)
    error_message = db.Column(db.Text)
    request_snapshot = db.Column(db.JSON, nullable=False, default=dict)
    response_snapshot = db.Column(db.JSON, nullable=False, default=dict)
    assertions_detail = db.Column(db.JSON, nullable=False, default=list)
    extractors_detail = db.Column(db.JSON, nullable=False, default=list)
    ws_messages = db.Column(db.JSON, nullable=False, default=list)
    time_taken_ms = db.Column(db.Integer)
    sort_order = db.Column(db.Integer, nullable=False, default=0)

    history = db.relationship("ExecutionHistory", back_populates="details")

    def __repr__(self):
        """返回便于调试和日志查看的模型文本表示。"""
        return "<ExecutionDetail %r>" % self.id


class DataFactory(TimestampMixin, db.Model):
    """数据工厂配置表。"""

    __tablename__ = "data_factory"

    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey("project.id"), nullable=True, index=True)
    environment_id = db.Column(
        db.Integer,
        db.ForeignKey("environment.id"),
        nullable=False,
        index=True,
    )
    name = db.Column(db.String(128), nullable=False, index=True)
    description = db.Column(db.Text)
    default_loop_count = db.Column(db.Integer, nullable=False, default=1)
    default_concurrency = db.Column(db.Integer, nullable=False, default=1)

    project = db.relationship("Project", back_populates="data_factories")
    environment = db.relationship("Environment", back_populates="data_factories")
    steps = db.relationship(
        "DataFactoryStep",
        back_populates="factory",
        cascade="all, delete-orphan",
        order_by="DataFactoryStep.sort_order",
    )
    runs = db.relationship("DataFactoryRun", back_populates="factory")


class DataFactoryStep(TimestampMixin, db.Model):
    """数据工厂图形流程中的接口或等待步骤。"""

    __tablename__ = "data_factory_step"

    id = db.Column(db.Integer, primary_key=True)
    factory_id = db.Column(
        db.Integer,
        db.ForeignKey("data_factory.id"),
        nullable=False,
        index=True,
    )
    interface_id = db.Column(
        db.Integer,
        db.ForeignKey("interface.id"),
        nullable=True,
        index=True,
    )
    name = db.Column(db.String(128), nullable=False)
    step_type = db.Column(
        db.String(32),
        nullable=False,
        default=DataFactoryStepType.REQUEST,
        index=True,
    )
    source_type = db.Column(
        db.String(32),
        nullable=False,
        default=DataFactorySourceType.CUSTOM,
        index=True,
    )
    sort_order = db.Column(db.Integer, nullable=False, default=0)
    method = db.Column(db.String(16))
    url = db.Column(db.Text)
    body_type = db.Column(db.String(32), nullable=True)
    request_params = db.Column(db.JSON, nullable=True)
    headers = db.Column(db.JSON, nullable=True)
    body = db.Column(db.JSON, nullable=True)
    timeout_seconds = db.Column(db.Integer, nullable=False, default=30)
    wait_seconds = db.Column(db.Float, nullable=True)
    extractors = db.Column(db.JSON, nullable=False, default=list)
    assertions = db.Column(db.JSON, nullable=False, default=list)

    factory = db.relationship("DataFactory", back_populates="steps")
    interface = db.relationship("Interface", back_populates="data_factory_steps")


class DataFactoryRun(TimestampMixin, db.Model):
    """数据工厂一次完整执行的汇总记录。"""

    __tablename__ = "data_factory_run"

    id = db.Column(db.Integer, primary_key=True)
    factory_id = db.Column(
        db.Integer,
        db.ForeignKey("data_factory.id"),
        nullable=False,
        index=True,
    )
    factory_name = db.Column(db.String(128), nullable=False)
    project_id = db.Column(db.Integer, db.ForeignKey("project.id"), nullable=True, index=True)
    environment_id = db.Column(
        db.Integer,
        db.ForeignKey("environment.id"),
        nullable=False,
        index=True,
    )
    status = db.Column(
        db.String(32),
        nullable=False,
        default=DataFactoryRunStatus.QUEUED,
        index=True,
    )
    loop_count = db.Column(db.Integer, nullable=False, default=1)
    concurrency = db.Column(db.Integer, nullable=False, default=1)
    total_request_count = db.Column(db.Integer, nullable=False, default=0)
    completed_request_count = db.Column(db.Integer, nullable=False, default=0)
    completed_iteration_count = db.Column(db.Integer, nullable=False, default=0)
    success_iteration_count = db.Column(db.Integer, nullable=False, default=0)
    failed_iteration_count = db.Column(db.Integer, nullable=False, default=0)
    cancel_requested = db.Column(db.Boolean, nullable=False, default=False)
    started_at = db.Column(db.DateTime)
    ended_at = db.Column(db.DateTime)
    execution_config = db.Column(db.JSON, nullable=False, default=dict)
    error_message = db.Column(db.Text)

    factory = db.relationship("DataFactory", back_populates="runs")
    project = db.relationship("Project")
    environment = db.relationship("Environment")
    iterations = db.relationship(
        "DataFactoryRunIteration",
        back_populates="run",
        cascade="all, delete-orphan",
    )


class DataFactoryRunIteration(TimestampMixin, db.Model):
    """数据工厂一次执行中的单轮结果。"""

    __tablename__ = "data_factory_run_iteration"
    __table_args__ = (
        db.UniqueConstraint("run_id", "iteration_no", name="uq_factory_run_iteration"),
    )

    id = db.Column(db.Integer, primary_key=True)
    run_id = db.Column(
        db.Integer,
        db.ForeignKey("data_factory_run.id"),
        nullable=False,
        index=True,
    )
    iteration_no = db.Column(db.Integer, nullable=False)
    status = db.Column(
        db.String(32),
        nullable=False,
        default=DataFactoryIterationStatus.RUNNING,
        index=True,
    )
    error_message = db.Column(db.Text)
    started_at = db.Column(db.DateTime)
    ended_at = db.Column(db.DateTime)

    run = db.relationship("DataFactoryRun", back_populates="iterations")
    details = db.relationship(
        "DataFactoryRunDetail",
        back_populates="iteration",
        cascade="all, delete-orphan",
    )


class DataFactoryRunDetail(TimestampMixin, db.Model):
    """数据工厂单轮中每个流程步骤的执行明细。"""

    __tablename__ = "data_factory_run_detail"

    id = db.Column(db.Integer, primary_key=True)
    iteration_id = db.Column(
        db.Integer,
        db.ForeignKey("data_factory_run_iteration.id"),
        nullable=False,
        index=True,
    )
    step_config_id = db.Column(db.Integer, nullable=True, index=True)
    step_name = db.Column(db.String(128), nullable=False)
    step_type = db.Column(
        db.String(32),
        nullable=False,
        default=DataFactoryStepType.REQUEST,
        index=True,
    )
    wait_seconds = db.Column(db.Float, nullable=True)
    sort_order = db.Column(db.Integer, nullable=False, default=0)
    status = db.Column(db.String(32), nullable=False, default=DetailStatus.PASS, index=True)
    method = db.Column(db.String(16))
    url = db.Column(db.Text)
    error_message = db.Column(db.Text)
    request_snapshot = db.Column(db.JSON, nullable=False, default=dict)
    response_snapshot = db.Column(db.JSON, nullable=False, default=dict)
    assertions_detail = db.Column(db.JSON, nullable=False, default=list)
    extractors_detail = db.Column(db.JSON, nullable=False, default=list)
    time_taken_ms = db.Column(db.Integer)

    iteration = db.relationship("DataFactoryRunIteration", back_populates="details")
