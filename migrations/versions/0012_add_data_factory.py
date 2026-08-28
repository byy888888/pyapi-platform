# -*- coding: utf-8 -*-
"""
@Author: byy
@Desc: 新增数据工厂、步骤、运行轮次和执行详情数据表。
"""

from alembic import op
import sqlalchemy as sa


revision = "0012_add_data_factory"
down_revision = "0011_normalize_ownership"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """创建数据工厂配置、轮次和接口执行明细表。"""
    op.create_table(
        "data_factory",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=True),
        sa.Column("environment_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("default_loop_count", sa.Integer(), nullable=False),
        sa.Column("default_concurrency", sa.Integer(), nullable=False),
        sa.Column("interval_ms", sa.Integer(), nullable=False),
        sa.Column("failure_policy", sa.String(length=32), nullable=False),
        sa.Column("initial_variables", sa.JSON(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["environment_id"], ["environment.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["project.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_data_factory_project_id", "data_factory", ["project_id"])
    op.create_index("ix_data_factory_environment_id", "data_factory", ["environment_id"])
    op.create_index("ix_data_factory_name", "data_factory", ["name"])
    op.create_index("ix_data_factory_is_active", "data_factory", ["is_active"])

    op.create_table(
        "data_factory_request",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("factory_id", sa.Integer(), nullable=False),
        sa.Column("interface_id", sa.Integer(), nullable=True),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("source_type", sa.String(length=32), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("method", sa.String(length=16), nullable=True),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column("body_type", sa.String(length=32), nullable=True),
        sa.Column("request_params", sa.JSON(), nullable=True),
        sa.Column("headers", sa.JSON(), nullable=True),
        sa.Column("body", sa.JSON(), nullable=True),
        sa.Column("timeout_seconds", sa.Integer(), nullable=False),
        sa.Column("extractors", sa.JSON(), nullable=False),
        sa.Column("assertions", sa.JSON(), nullable=False),
        sa.Column("failure_policy", sa.String(length=32), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["factory_id"], ["data_factory.id"]),
        sa.ForeignKeyConstraint(["interface_id"], ["interface.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_data_factory_request_factory_id", "data_factory_request", ["factory_id"])
    op.create_index("ix_data_factory_request_interface_id", "data_factory_request", ["interface_id"])
    op.create_index("ix_data_factory_request_source_type", "data_factory_request", ["source_type"])
    op.create_index("ix_data_factory_request_is_active", "data_factory_request", ["is_active"])

    op.create_table(
        "data_factory_run",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("factory_id", sa.Integer(), nullable=False),
        sa.Column("factory_name", sa.String(length=128), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=True),
        sa.Column("environment_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("loop_count", sa.Integer(), nullable=False),
        sa.Column("concurrency", sa.Integer(), nullable=False),
        sa.Column("interval_ms", sa.Integer(), nullable=False),
        sa.Column("total_request_count", sa.Integer(), nullable=False),
        sa.Column("completed_request_count", sa.Integer(), nullable=False),
        sa.Column("completed_iteration_count", sa.Integer(), nullable=False),
        sa.Column("success_iteration_count", sa.Integer(), nullable=False),
        sa.Column("failed_iteration_count", sa.Integer(), nullable=False),
        sa.Column("cancel_requested", sa.Boolean(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("ended_at", sa.DateTime(), nullable=True),
        sa.Column("execution_config", sa.JSON(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["environment_id"], ["environment.id"]),
        sa.ForeignKeyConstraint(["factory_id"], ["data_factory.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["project.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_data_factory_run_factory_id", "data_factory_run", ["factory_id"])
    op.create_index("ix_data_factory_run_project_id", "data_factory_run", ["project_id"])
    op.create_index("ix_data_factory_run_environment_id", "data_factory_run", ["environment_id"])
    op.create_index("ix_data_factory_run_status", "data_factory_run", ["status"])

    op.create_table(
        "data_factory_run_iteration",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=False),
        sa.Column("iteration_no", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("output_variables", sa.JSON(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("ended_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["data_factory_run.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "iteration_no", name="uq_factory_run_iteration"),
    )
    op.create_index("ix_data_factory_run_iteration_run_id", "data_factory_run_iteration", ["run_id"])
    op.create_index("ix_data_factory_run_iteration_status", "data_factory_run_iteration", ["status"])

    op.create_table(
        "data_factory_run_detail",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("iteration_id", sa.Integer(), nullable=False),
        sa.Column("request_config_id", sa.Integer(), nullable=True),
        sa.Column("request_name", sa.String(length=128), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("method", sa.String(length=16), nullable=True),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("request_snapshot", sa.JSON(), nullable=False),
        sa.Column("response_snapshot", sa.JSON(), nullable=False),
        sa.Column("assertions_detail", sa.JSON(), nullable=False),
        sa.Column("extractors_detail", sa.JSON(), nullable=False),
        sa.Column("output_variables", sa.JSON(), nullable=False),
        sa.Column("time_taken_ms", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["iteration_id"], ["data_factory_run_iteration.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_data_factory_run_detail_iteration_id", "data_factory_run_detail", ["iteration_id"])
    op.create_index("ix_data_factory_run_detail_request_config_id", "data_factory_run_detail", ["request_config_id"])
    op.create_index("ix_data_factory_run_detail_status", "data_factory_run_detail", ["status"])


def downgrade() -> None:
    """删除数据工厂相关表。"""
    op.drop_table("data_factory_run_detail")
    op.drop_table("data_factory_run_iteration")
    op.drop_table("data_factory_run")
    op.drop_table("data_factory_request")
    op.drop_table("data_factory")
