# -*- coding: utf-8 -*-
"""
@Author: byy
@Desc: 统一接口与用例的项目、模块归属关系。
"""

from alembic import op
import sqlalchemy as sa


revision = "0011_normalize_ownership"
down_revision = "0010_add_project_modules"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """删除接口和用例中可由关联关系推导的项目字段。"""
    _drop_project_column("test_case", "ix_test_case_project_id")
    _drop_project_column("interface", "ix_interface_project_id")


def downgrade() -> None:
    """恢复项目字段，并根据当前关联关系回填项目 ID。"""
    with op.batch_alter_table("interface") as batch_op:
        batch_op.add_column(sa.Column("project_id", sa.Integer(), nullable=True))
    op.execute(
        sa.text(
            "UPDATE interface SET project_id = ("
            "SELECT project_module.project_id FROM project_module "
            "WHERE project_module.id = interface.module_id)"
        )
    )
    with op.batch_alter_table("interface") as batch_op:
        batch_op.alter_column("project_id", nullable=False)
        batch_op.create_index("ix_interface_project_id", ["project_id"])
        batch_op.create_foreign_key(
            "fk_interface_project_id_project",
            "project",
            ["project_id"],
            ["id"],
        )

    with op.batch_alter_table("test_case") as batch_op:
        batch_op.add_column(sa.Column("project_id", sa.Integer(), nullable=True))
    op.execute(
        sa.text(
            "UPDATE test_case SET project_id = ("
            "SELECT interface.project_id FROM interface "
            "WHERE interface.id = test_case.interface_id)"
        )
    )
    with op.batch_alter_table("test_case") as batch_op:
        batch_op.alter_column("project_id", nullable=False)
        batch_op.create_index("ix_test_case_project_id", ["project_id"])
        batch_op.create_foreign_key(
            "fk_test_case_project_id_project",
            "project",
            ["project_id"],
            ["id"],
        )


def _drop_project_column(table_name: str, index_name: str) -> None:
    """按数据库能力安全移除项目字段及其外键和索引。"""
    dialect_name = op.get_context().dialect.name
    if dialect_name == "sqlite":
        with op.batch_alter_table(table_name, recreate="always") as batch_op:
            batch_op.drop_index(index_name)
            batch_op.drop_column("project_id")
        return

    with op.batch_alter_table(table_name) as batch_op:
        batch_op.drop_constraint(
            "fk_%s_project_id_project" % table_name,
            type_="foreignkey",
        )
        batch_op.drop_index(index_name)
        batch_op.drop_column("project_id")
