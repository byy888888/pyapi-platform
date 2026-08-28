# -*- coding: utf-8 -*-
"""
@Author: byy
@Desc: 为集合步骤增加请求行和请求内容覆盖字段。
"""

from alembic import op
import sqlalchemy as sa


revision = "0008_add_suite_step_request_overrides"
down_revision = "0007_upgrade_suite_case_steps"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """为集合步骤补充 Method、URL、Body Type 覆盖字段。"""
    with op.batch_alter_table("suite_case") as batch_op:
        batch_op.add_column(sa.Column("method_override", sa.String(length=16), nullable=True))
        batch_op.add_column(sa.Column("url_override", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("body_type_override", sa.String(length=16), nullable=True))


def downgrade() -> None:
    """删除集合步骤请求行覆盖字段。"""
    with op.batch_alter_table("suite_case") as batch_op:
        batch_op.drop_column("body_type_override")
        batch_op.drop_column("url_override")
        batch_op.drop_column("method_override")
