# -*- coding: utf-8 -*-
"""
@Author: byy
@Desc: 为接口定义增加请求参数模板字段。
"""

from alembic import op
import sqlalchemy as sa


revision = "0004_add_interface_params_template"
down_revision = "0003_decouple_environment_variables"
branch_labels = None
depends_on = None


def upgrade():
    """执行本版本数据库结构和存量数据升级。"""
    op.add_column("interface", sa.Column("params_template", sa.JSON(), nullable=True))


def downgrade():
    """回退本版本数据库结构和存量数据变更。"""
    op.drop_column("interface", "params_template")
