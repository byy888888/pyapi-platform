# -*- coding: utf-8 -*-
"""
@Author: byy
@Desc: 新增项目模块表并迁移接口模块归属。
"""

from alembic import op
import sqlalchemy as sa


revision = "0010_add_project_modules"
down_revision = "0009_add_environment_type_and_task_scope"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """创建模块表，并将历史接口归入各项目的未分组模块。"""
    op.create_table(
        "project_module",
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["project.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "name", name="uq_project_module_name"),
    )
    op.create_index("ix_project_module_project_id", "project_module", ["project_id"])
    op.create_index("ix_project_module_name", "project_module", ["name"])

    with op.batch_alter_table("interface") as batch_op:
        batch_op.add_column(sa.Column("module_id", sa.Integer(), nullable=True))
        batch_op.create_index("ix_interface_module_id", ["module_id"])
        batch_op.create_foreign_key(
            "fk_interface_module_id_project_module",
            "project_module",
            ["module_id"],
            ["id"],
        )

    connection = op.get_bind()
    project_rows = connection.execute(
        sa.text("SELECT DISTINCT project_id FROM interface ORDER BY project_id")
    ).fetchall()
    for row in project_rows:
        project_id = row[0]
        connection.execute(
            sa.text(
                "INSERT INTO project_module "
                "(project_id, name, created_at, updated_at) "
                "VALUES (:project_id, :name, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            ),
            {"project_id": project_id, "name": "未分组"},
        )
        module_id = connection.execute(
            sa.text(
                "SELECT id FROM project_module "
                "WHERE project_id = :project_id AND name = :name"
            ),
            {"project_id": project_id, "name": "未分组"},
        ).scalar()
        connection.execute(
            sa.text(
                "UPDATE interface SET module_id = :module_id "
                "WHERE project_id = :project_id"
            ),
            {"module_id": module_id, "project_id": project_id},
        )

    with op.batch_alter_table("interface") as batch_op:
        batch_op.alter_column("module_id", nullable=False)


def downgrade() -> None:
    """删除接口模块关联及项目模块表。"""
    with op.batch_alter_table("interface") as batch_op:
        batch_op.drop_constraint("fk_interface_module_id_project_module", type_="foreignkey")
        batch_op.drop_index("ix_interface_module_id")
        batch_op.drop_column("module_id")
    op.drop_index("ix_project_module_name", table_name="project_module")
    op.drop_index("ix_project_module_project_id", table_name="project_module")
    op.drop_table("project_module")
