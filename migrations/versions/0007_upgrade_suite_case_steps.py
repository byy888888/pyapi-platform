# -*- coding: utf-8 -*-
"""
@Author: byy
@Desc: 升级集合用例步骤结构并保存步骤级配置。
"""

from alembic import op
import sqlalchemy as sa


revision = "0007_upgrade_suite_case_steps"
down_revision = "0006_add_suite_environment"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """新增集合步骤覆盖字段，并移除同集合同用例唯一约束。"""
    with op.batch_alter_table("suite_case", recreate="always") as batch_op:
        batch_op.drop_constraint("uq_suite_case_case", type_="unique")
        batch_op.add_column(sa.Column("step_name", sa.String(length=128), nullable=True))
        batch_op.add_column(
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true())
        )
        batch_op.add_column(sa.Column("request_params_override", sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column("headers_override", sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column("body_override", sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column("assertions_override", sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column("extractors_override", sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column("ws_steps_override", sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column("timeout_seconds_override", sa.Integer(), nullable=True))
        batch_op.create_index("ix_suite_case_is_active", ["is_active"], unique=False)

    with op.batch_alter_table("suite_case") as batch_op:
        batch_op.alter_column("is_active", server_default=None)


def downgrade() -> None:
    """回退到旧的集合用例引用结构。"""
    with op.batch_alter_table("suite_case", recreate="always") as batch_op:
        batch_op.drop_index("ix_suite_case_is_active")
        batch_op.drop_column("timeout_seconds_override")
        batch_op.drop_column("ws_steps_override")
        batch_op.drop_column("extractors_override")
        batch_op.drop_column("assertions_override")
        batch_op.drop_column("body_override")
        batch_op.drop_column("headers_override")
        batch_op.drop_column("request_params_override")
        batch_op.drop_column("is_active")
        batch_op.drop_column("step_name")
        batch_op.create_unique_constraint("uq_suite_case_case", ["suite_id", "case_id"])
