# -*- coding: utf-8 -*-
"""
@Author: byy
@Desc: 初始化平台项目、接口、用例、集合、报告、通知和任务等核心数据表。
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql


revision = "0001_create_initial_tables"
down_revision = None
branch_labels = None
depends_on = None


MYSQL_TABLE_OPTIONS = {
    "mysql_engine": "InnoDB",
    "mysql_charset": "utf8mb4",
    "mysql_collate": "utf8mb4_unicode_ci",
}


def upgrade():
    """执行本版本数据库结构和存量数据升级。"""
    op.create_table(
        "environment",
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_default", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
        **MYSQL_TABLE_OPTIONS
    )
    op.create_index("ix_environment_is_default", "environment", ["is_default"], unique=False)
    op.create_index("ix_environment_name", "environment", ["name"], unique=True)

    op.create_table(
        "notification",
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("notification_type", sa.String(length=32), nullable=False),
        sa.Column("config", sa.JSON(), nullable=False),
        sa.Column("message_template", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        **MYSQL_TABLE_OPTIONS
    )
    op.create_index("ix_notification_is_active", "notification", ["is_active"], unique=False)
    op.create_index("ix_notification_name", "notification", ["name"], unique=False)
    op.create_index(
        "ix_notification_notification_type",
        "notification",
        ["notification_type"],
        unique=False,
    )

    op.create_table(
        "project",
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
        **MYSQL_TABLE_OPTIONS
    )
    op.create_index("ix_project_is_active", "project", ["is_active"], unique=False)
    op.create_index("ix_project_name", "project", ["name"], unique=True)

    op.create_table(
        "global_variable",
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=True),
        sa.Column("environment_id", sa.Integer(), nullable=False),
        sa.Column("var_key", sa.String(length=128), nullable=False),
        sa.Column("var_value", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_secret", sa.Boolean(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(["environment_id"], ["environment.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["project.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "project_id",
            "environment_id",
            "var_key",
            name="uq_global_variable_scope_key",
        ),
        **MYSQL_TABLE_OPTIONS
    )
    op.create_index("ix_global_variable_is_active", "global_variable", ["is_active"], unique=False)
    op.create_index(
        "ix_global_variable_lookup",
        "global_variable",
        ["environment_id", "project_id", "var_key"],
        unique=False,
    )

    op.create_table(
        "interface",
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("interface_type", sa.String(length=32), nullable=False),
        sa.Column("method", sa.String(length=16), nullable=True),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("headers_template", sa.JSON(), nullable=False),
        sa.Column("body_template", sa.JSON(), nullable=False),
        sa.Column("body_type", sa.String(length=16), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["project.id"],
            name="fk_interface_project_id_project",
        ),
        sa.PrimaryKeyConstraint("id"),
        **MYSQL_TABLE_OPTIONS
    )
    op.create_index("ix_interface_interface_type", "interface", ["interface_type"], unique=False)
    op.create_index("ix_interface_is_active", "interface", ["is_active"], unique=False)
    op.create_index("ix_interface_name", "interface", ["name"], unique=False)
    op.create_index("ix_interface_project_id", "interface", ["project_id"], unique=False)

    op.create_table(
        "scheduled_task",
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("environment_id", sa.Integer(), nullable=False),
        sa.Column("schedule_type", sa.String(length=32), nullable=False),
        sa.Column("interval_seconds", sa.Integer(), nullable=True),
        sa.Column("daily_time", sa.String(length=5), nullable=True),
        sa.Column("cron_expression", sa.String(length=128), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("next_run_at", sa.DateTime(), nullable=True),
        sa.Column("last_run_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["environment_id"], ["environment.id"]),
        sa.PrimaryKeyConstraint("id"),
        **MYSQL_TABLE_OPTIONS
    )
    op.create_index("ix_scheduled_task_enabled", "scheduled_task", ["enabled"], unique=False)
    op.create_index(
        "ix_scheduled_task_environment_id",
        "scheduled_task",
        ["environment_id"],
        unique=False,
    )
    op.create_index("ix_scheduled_task_name", "scheduled_task", ["name"], unique=False)

    op.create_table(
        "suite",
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("suite_type", sa.String(length=32), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["project.id"]),
        sa.PrimaryKeyConstraint("id"),
        **MYSQL_TABLE_OPTIONS
    )
    op.create_index("ix_suite_is_active", "suite", ["is_active"], unique=False)
    op.create_index("ix_suite_name", "suite", ["name"], unique=False)
    op.create_index("ix_suite_project_id", "suite", ["project_id"], unique=False)
    op.create_index("ix_suite_suite_type", "suite", ["suite_type"], unique=False)

    op.create_table(
        "task_notification",
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("notification_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["notification_id"], ["notification.id"]),
        sa.ForeignKeyConstraint(["task_id"], ["scheduled_task.id"]),
        sa.PrimaryKeyConstraint("id"),
        **MYSQL_TABLE_OPTIONS
    )
    op.create_index(
        "ix_task_notification_notification_id",
        "task_notification",
        ["notification_id"],
        unique=False,
    )
    op.create_index("ix_task_notification_task_id", "task_notification", ["task_id"], unique=False)

    op.create_table(
        "task_suite",
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("suite_id", sa.Integer(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["suite_id"], ["suite.id"]),
        sa.ForeignKeyConstraint(["task_id"], ["scheduled_task.id"]),
        sa.PrimaryKeyConstraint("id"),
        **MYSQL_TABLE_OPTIONS
    )
    op.create_index("ix_task_suite_suite_id", "task_suite", ["suite_id"], unique=False)
    op.create_index("ix_task_suite_task_id", "task_suite", ["task_id"], unique=False)

    op.create_table(
        "test_case",
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("interface_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("request_params", sa.JSON(), nullable=False),
        sa.Column("headers_override", sa.JSON(), nullable=False),
        sa.Column("body_override", sa.JSON(), nullable=False),
        sa.Column("assertions", sa.JSON(), nullable=False),
        sa.Column("extractors", sa.JSON(), nullable=False),
        sa.Column("ws_steps", sa.JSON(), nullable=False),
        sa.Column("timeout_seconds", sa.Integer(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(["interface_id"], ["interface.id"]),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["project.id"],
            name="fk_test_case_project_id_project",
        ),
        sa.PrimaryKeyConstraint("id"),
        **MYSQL_TABLE_OPTIONS
    )
    op.create_index("ix_test_case_interface_id", "test_case", ["interface_id"], unique=False)
    op.create_index("ix_test_case_is_active", "test_case", ["is_active"], unique=False)
    op.create_index("ix_test_case_name", "test_case", ["name"], unique=False)
    op.create_index("ix_test_case_project_id", "test_case", ["project_id"], unique=False)

    op.create_table(
        "execution_history",
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=True),
        sa.Column("task_name", sa.String(length=128), nullable=True),
        sa.Column("trigger_type", sa.String(length=32), nullable=False),
        sa.Column("environment_id", sa.Integer(), nullable=False),
        sa.Column("start_time", sa.DateTime(), nullable=False),
        sa.Column("end_time", sa.DateTime(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("total_count", sa.Integer(), nullable=False),
        sa.Column("success_count", sa.Integer(), nullable=False),
        sa.Column("fail_count", sa.Integer(), nullable=False),
        sa.Column("error_count", sa.Integer(), nullable=False),
        sa.Column("interrupted", sa.Boolean(), nullable=False),
        sa.Column("summary", sa.JSON(), nullable=False),
        sa.Column("report_path", sa.String(length=255), nullable=True),
        sa.Column("report_html", sa.Text().with_variant(mysql.LONGTEXT(), "mysql"), nullable=True),
        sa.ForeignKeyConstraint(["environment_id"], ["environment.id"]),
        sa.ForeignKeyConstraint(["task_id"], ["scheduled_task.id"]),
        sa.PrimaryKeyConstraint("id"),
        **MYSQL_TABLE_OPTIONS
    )
    op.create_index(
        "ix_execution_history_environment_id",
        "execution_history",
        ["environment_id"],
        unique=False,
    )
    op.create_index("ix_execution_history_status", "execution_history", ["status"], unique=False)
    op.create_index("ix_execution_history_task_id", "execution_history", ["task_id"], unique=False)
    op.create_index(
        "ix_execution_history_trigger_type",
        "execution_history",
        ["trigger_type"],
        unique=False,
    )

    op.create_table(
        "suite_case",
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("suite_id", sa.Integer(), nullable=False),
        sa.Column("case_id", sa.Integer(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["case_id"], ["test_case.id"]),
        sa.ForeignKeyConstraint(["suite_id"], ["suite.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("suite_id", "case_id", name="uq_suite_case_case"),
        **MYSQL_TABLE_OPTIONS
    )
    op.create_index("ix_suite_case_case_id", "suite_case", ["case_id"], unique=False)
    op.create_index("ix_suite_case_suite_id", "suite_case", ["suite_id"], unique=False)

    op.create_table(
        "execution_detail",
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("history_id", sa.Integer(), nullable=False),
        sa.Column("suite_id", sa.Integer(), nullable=True),
        sa.Column("suite_name", sa.String(length=128), nullable=True),
        sa.Column("case_id", sa.Integer(), nullable=True),
        sa.Column("case_name", sa.String(length=128), nullable=True),
        sa.Column("interface_id", sa.Integer(), nullable=True),
        sa.Column("interface_name", sa.String(length=128), nullable=True),
        sa.Column("interface_type", sa.String(length=32), nullable=False),
        sa.Column("method", sa.String(length=16), nullable=True),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("request_snapshot", sa.JSON(), nullable=False),
        sa.Column("response_snapshot", sa.JSON(), nullable=False),
        sa.Column("assertions_detail", sa.JSON(), nullable=False),
        sa.Column("extractors_detail", sa.JSON(), nullable=False),
        sa.Column("ws_messages", sa.JSON(), nullable=False),
        sa.Column("time_taken_ms", sa.Integer(), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["case_id"], ["test_case.id"]),
        sa.ForeignKeyConstraint(["history_id"], ["execution_history.id"]),
        sa.ForeignKeyConstraint(["interface_id"], ["interface.id"]),
        sa.ForeignKeyConstraint(["suite_id"], ["suite.id"]),
        sa.PrimaryKeyConstraint("id"),
        **MYSQL_TABLE_OPTIONS
    )
    op.create_index("ix_execution_detail_case_id", "execution_detail", ["case_id"], unique=False)
    op.create_index("ix_execution_detail_history_id", "execution_detail", ["history_id"], unique=False)
    op.create_index(
        "ix_execution_detail_interface_id",
        "execution_detail",
        ["interface_id"],
        unique=False,
    )
    op.create_index(
        "ix_execution_detail_interface_type",
        "execution_detail",
        ["interface_type"],
        unique=False,
    )
    op.create_index("ix_execution_detail_status", "execution_detail", ["status"], unique=False)
    op.create_index("ix_execution_detail_suite_id", "execution_detail", ["suite_id"], unique=False)


def downgrade():
    """回退本版本数据库结构和存量数据变更。"""
    op.drop_index("ix_execution_detail_suite_id", table_name="execution_detail")
    op.drop_index("ix_execution_detail_status", table_name="execution_detail")
    op.drop_index("ix_execution_detail_interface_type", table_name="execution_detail")
    op.drop_index("ix_execution_detail_interface_id", table_name="execution_detail")
    op.drop_index("ix_execution_detail_history_id", table_name="execution_detail")
    op.drop_index("ix_execution_detail_case_id", table_name="execution_detail")
    op.drop_table("execution_detail")

    op.drop_index("ix_suite_case_suite_id", table_name="suite_case")
    op.drop_index("ix_suite_case_case_id", table_name="suite_case")
    op.drop_table("suite_case")

    op.drop_index("ix_execution_history_trigger_type", table_name="execution_history")
    op.drop_index("ix_execution_history_task_id", table_name="execution_history")
    op.drop_index("ix_execution_history_status", table_name="execution_history")
    op.drop_index("ix_execution_history_environment_id", table_name="execution_history")
    op.drop_table("execution_history")

    op.drop_index("ix_test_case_project_id", table_name="test_case")
    op.drop_index("ix_test_case_name", table_name="test_case")
    op.drop_index("ix_test_case_is_active", table_name="test_case")
    op.drop_index("ix_test_case_interface_id", table_name="test_case")
    op.drop_table("test_case")

    op.drop_index("ix_task_suite_task_id", table_name="task_suite")
    op.drop_index("ix_task_suite_suite_id", table_name="task_suite")
    op.drop_table("task_suite")

    op.drop_index("ix_task_notification_task_id", table_name="task_notification")
    op.drop_index("ix_task_notification_notification_id", table_name="task_notification")
    op.drop_table("task_notification")

    op.drop_index("ix_suite_suite_type", table_name="suite")
    op.drop_index("ix_suite_project_id", table_name="suite")
    op.drop_index("ix_suite_name", table_name="suite")
    op.drop_index("ix_suite_is_active", table_name="suite")
    op.drop_table("suite")

    op.drop_index("ix_scheduled_task_name", table_name="scheduled_task")
    op.drop_index("ix_scheduled_task_environment_id", table_name="scheduled_task")
    op.drop_index("ix_scheduled_task_enabled", table_name="scheduled_task")
    op.drop_table("scheduled_task")

    op.drop_index("ix_interface_project_id", table_name="interface")
    op.drop_index("ix_interface_name", table_name="interface")
    op.drop_index("ix_interface_is_active", table_name="interface")
    op.drop_index("ix_interface_interface_type", table_name="interface")
    op.drop_table("interface")

    op.drop_index("ix_global_variable_lookup", table_name="global_variable")
    op.drop_index("ix_global_variable_is_active", table_name="global_variable")
    op.drop_table("global_variable")

    op.drop_index("ix_project_name", table_name="project")
    op.drop_index("ix_project_is_active", table_name="project")
    op.drop_table("project")

    op.drop_index("ix_notification_notification_type", table_name="notification")
    op.drop_index("ix_notification_name", table_name="notification")
    op.drop_index("ix_notification_is_active", table_name="notification")
    op.drop_table("notification")

    op.drop_index("ix_environment_name", table_name="environment")
    op.drop_index("ix_environment_is_default", table_name="environment")
    op.drop_table("environment")
