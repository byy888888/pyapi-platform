# -*- coding: utf-8 -*-
"""
@Author: byy
@Desc: 为测试集合增加默认执行环境字段。
"""

from alembic import op
import sqlalchemy as sa


revision = "0006_add_suite_environment"
down_revision = "0005_shift_existing_datetimes_to_local"
branch_labels = None
depends_on = None


def upgrade():
    """执行本版本数据库结构和存量数据升级。"""
    with op.batch_alter_table("suite") as batch_op:
        batch_op.add_column(sa.Column("environment_id", sa.Integer(), nullable=True))
        batch_op.create_index("ix_suite_environment_id", ["environment_id"], unique=False)
        batch_op.create_foreign_key(
            "fk_suite_environment_id_environment",
            "environment",
            ["environment_id"],
            ["id"],
        )


def downgrade():
    """回退本版本数据库结构和存量数据变更。"""
    with op.batch_alter_table("suite") as batch_op:
        batch_op.drop_constraint("fk_suite_environment_id_environment", type_="foreignkey")
        batch_op.drop_index("ix_suite_environment_id")
        batch_op.drop_column("environment_id")
