# -*- coding: utf-8 -*-
"""
@Author: byy
@Desc: 移除数据工厂已废弃的轮次最终输出字段。
"""

from alembic import op
import sqlalchemy as sa


revision = "0015_remove_data_factory_outputs"
down_revision = "0014_redesign_data_factory_steps"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """删除不再用于导出结果的数据工厂输出字段。"""
    with op.batch_alter_table("data_factory_run_iteration") as batch_op:
        batch_op.drop_column("output_variables")
    with op.batch_alter_table("data_factory_run_detail") as batch_op:
        batch_op.drop_column("output_variables")


def downgrade() -> None:
    """回滚时恢复允许为空的输出字段。"""
    with op.batch_alter_table("data_factory_run_iteration") as batch_op:
        batch_op.add_column(sa.Column("output_variables", sa.JSON(), nullable=True))
    with op.batch_alter_table("data_factory_run_detail") as batch_op:
        batch_op.add_column(sa.Column("output_variables", sa.JSON(), nullable=True))
