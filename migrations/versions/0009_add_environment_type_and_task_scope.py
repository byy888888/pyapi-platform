# -*- coding: utf-8 -*-
"""
@Author: byy
@Desc: 增加环境类型、任务执行范围和触发来源相关字段。
"""

from alembic import op
import sqlalchemy as sa


revision = "0009_add_environment_type_and_task_scope"
down_revision = "0008_add_suite_step_request_overrides"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """为环境和任务补充类型，并移除任务的具体执行环境。"""
    with op.batch_alter_table("environment") as batch_op:
        batch_op.add_column(
            sa.Column(
                "environment_type",
                sa.String(length=32),
                nullable=False,
                server_default="testing",
            )
        )
        batch_op.create_index("ix_environment_environment_type", ["environment_type"])

    with op.batch_alter_table("scheduled_task") as batch_op:
        batch_op.add_column(sa.Column("environment_type", sa.String(length=32), nullable=True))
        batch_op.create_index("ix_scheduled_task_environment_type", ["environment_type"])

    op.execute(
        """
        UPDATE scheduled_task
        SET environment_type = COALESCE(
            (
                SELECT environment.environment_type
                FROM environment
                WHERE environment.id = scheduled_task.environment_id
            ),
            'testing'
        )
        """
    )

    bind = op.get_bind()
    with op.batch_alter_table("scheduled_task") as batch_op:
        batch_op.alter_column("environment_type", nullable=False)
        batch_op.drop_index("ix_scheduled_task_environment_id")
        if bind.dialect.name == "mysql":
            batch_op.drop_constraint("scheduled_task_ibfk_1", type_="foreignkey")
        batch_op.drop_column("environment_id")


def downgrade() -> None:
    """恢复任务旧的具体执行环境字段。"""
    with op.batch_alter_table("scheduled_task") as batch_op:
        batch_op.add_column(sa.Column("environment_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_scheduled_task_environment_id_environment",
            "environment",
            ["environment_id"],
            ["id"],
        )
        batch_op.create_index("ix_scheduled_task_environment_id", ["environment_id"])
        batch_op.drop_index("ix_scheduled_task_environment_type")
        batch_op.drop_column("environment_type")

    with op.batch_alter_table("environment") as batch_op:
        batch_op.drop_index("ix_environment_environment_type")
        batch_op.drop_column("environment_type")
