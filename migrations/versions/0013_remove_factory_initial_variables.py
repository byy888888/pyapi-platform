# -*- coding: utf-8 -*-
"""
@Author: byy
@Desc: 移除数据工厂不再使用的初始运行变量字段。
"""

from alembic import op
import sqlalchemy as sa


revision = "0013_remove_factory_initial_variables"
down_revision = "0012_add_data_factory"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """从数据工厂配置中删除不再使用的初始变量字段。"""
    with op.batch_alter_table("data_factory") as batch_op:
        batch_op.drop_column("initial_variables")


def downgrade() -> None:
    """回滚时恢复允许为空的初始变量字段。"""
    with op.batch_alter_table("data_factory") as batch_op:
        batch_op.add_column(sa.Column("initial_variables", sa.JSON(), nullable=True))
