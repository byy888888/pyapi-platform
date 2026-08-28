# -*- coding: utf-8 -*-
"""
@Author: byy
@Desc: 重构数据工厂图形流程步骤、等待步骤和断言配置。
"""

from alembic import op
import sqlalchemy as sa


revision = "0014_redesign_data_factory_steps"
down_revision = "0013_remove_factory_initial_variables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """用统一步骤表替换旧接口配置，并移除废弃运行选项。"""
    op.drop_table("data_factory_request")
    op.create_table(
        "data_factory_step",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("factory_id", sa.Integer(), nullable=False),
        sa.Column("interface_id", sa.Integer(), nullable=True),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("step_type", sa.String(length=32), nullable=False),
        sa.Column("source_type", sa.String(length=32), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("method", sa.String(length=16), nullable=True),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column("body_type", sa.String(length=32), nullable=True),
        sa.Column("request_params", sa.JSON(), nullable=True),
        sa.Column("headers", sa.JSON(), nullable=True),
        sa.Column("body", sa.JSON(), nullable=True),
        sa.Column("timeout_seconds", sa.Integer(), nullable=False),
        sa.Column("wait_seconds", sa.Float(), nullable=True),
        sa.Column("extractors", sa.JSON(), nullable=False),
        sa.Column("assertions", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["factory_id"], ["data_factory.id"]),
        sa.ForeignKeyConstraint(["interface_id"], ["interface.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_data_factory_step_factory_id", "data_factory_step", ["factory_id"])
    op.create_index("ix_data_factory_step_interface_id", "data_factory_step", ["interface_id"])
    op.create_index("ix_data_factory_step_source_type", "data_factory_step", ["source_type"])
    op.create_index("ix_data_factory_step_step_type", "data_factory_step", ["step_type"])

    with op.batch_alter_table("data_factory") as batch_op:
        batch_op.drop_index("ix_data_factory_is_active")
        batch_op.drop_column("interval_ms")
        batch_op.drop_column("failure_policy")
        batch_op.drop_column("is_active")

    with op.batch_alter_table("data_factory_run") as batch_op:
        batch_op.drop_column("interval_ms")

    with op.batch_alter_table("data_factory_run_detail") as batch_op:
        batch_op.drop_index("ix_data_factory_run_detail_request_config_id")
        batch_op.alter_column("request_config_id", new_column_name="step_config_id")
        batch_op.alter_column("request_name", new_column_name="step_name")
        batch_op.add_column(
            sa.Column("step_type", sa.String(length=32), nullable=False, server_default="request")
        )
        batch_op.add_column(sa.Column("wait_seconds", sa.Float(), nullable=True))

    with op.batch_alter_table("data_factory_run_detail") as batch_op:
        batch_op.create_index(
            "ix_data_factory_run_detail_step_config_id",
            ["step_config_id"],
        )
        batch_op.create_index("ix_data_factory_run_detail_step_type", ["step_type"])
        batch_op.alter_column("step_type", server_default=None)


def downgrade() -> None:
    """回滚为只支持接口配置的旧数据工厂结构。"""
    with op.batch_alter_table("data_factory_run_detail") as batch_op:
        batch_op.drop_index("ix_data_factory_run_detail_step_config_id")
        batch_op.drop_index("ix_data_factory_run_detail_step_type")
        batch_op.drop_column("wait_seconds")
        batch_op.drop_column("step_type")
        batch_op.alter_column("step_name", new_column_name="request_name")
        batch_op.alter_column("step_config_id", new_column_name="request_config_id")

    with op.batch_alter_table("data_factory_run_detail") as batch_op:
        batch_op.create_index(
            "ix_data_factory_run_detail_request_config_id",
            ["request_config_id"],
        )

    with op.batch_alter_table("data_factory_run") as batch_op:
        batch_op.add_column(
            sa.Column("interval_ms", sa.Integer(), nullable=False, server_default="0")
        )
        batch_op.alter_column("interval_ms", server_default=None)

    with op.batch_alter_table("data_factory") as batch_op:
        batch_op.add_column(
            sa.Column("interval_ms", sa.Integer(), nullable=False, server_default="0")
        )
        batch_op.add_column(
            sa.Column(
                "failure_policy",
                sa.String(length=32),
                nullable=False,
                server_default="stop_iteration",
            )
        )
        batch_op.add_column(
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true())
        )
        batch_op.create_index("ix_data_factory_is_active", ["is_active"])
        batch_op.alter_column("interval_ms", server_default=None)
        batch_op.alter_column("failure_policy", server_default=None)
        batch_op.alter_column("is_active", server_default=None)

    op.drop_table("data_factory_step")
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
