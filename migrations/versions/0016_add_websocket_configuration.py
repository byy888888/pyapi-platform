# -*- coding: utf-8 -*-
"""
@Author: byy
@Desc: 为接口和用例增加独立 WebSocket 配置及步骤字段。
"""

from alembic import op
import sqlalchemy as sa


revision = "0016_add_websocket_configuration"
down_revision = "0015_remove_data_factory_outputs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """增加 WebSocket 专用 JSON 配置字段。"""
    with op.batch_alter_table("interface") as batch_op:
        batch_op.add_column(sa.Column("ws_config", sa.JSON(), nullable=True))
    op.execute(sa.text("UPDATE interface SET ws_config = '{}' WHERE ws_config IS NULL"))
    with op.batch_alter_table("interface") as batch_op:
        batch_op.alter_column("ws_config", existing_type=sa.JSON(), nullable=False)
    with op.batch_alter_table("test_case") as batch_op:
        batch_op.add_column(sa.Column("ws_config_override", sa.JSON(), nullable=True))
    op.execute(
        sa.text(
            "UPDATE test_case SET ws_config_override = '{}' "
            "WHERE ws_config_override IS NULL"
        )
    )
    with op.batch_alter_table("test_case") as batch_op:
        batch_op.alter_column(
            "ws_config_override",
            existing_type=sa.JSON(),
            nullable=False,
        )


def downgrade() -> None:
    """移除 WebSocket 专用 JSON 配置字段。"""
    with op.batch_alter_table("test_case") as batch_op:
        batch_op.drop_column("ws_config_override")
    with op.batch_alter_table("interface") as batch_op:
        batch_op.drop_column("ws_config")
