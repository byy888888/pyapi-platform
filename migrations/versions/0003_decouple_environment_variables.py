# -*- coding: utf-8 -*-
"""
@Author: byy
@Desc: 将环境基础地址与变量解耦，并迁移已有环境变量数据。
"""

from alembic import op
import sqlalchemy as sa


revision = "0003_decouple_environment_variables"
down_revision = "0002_add_case_environment"
branch_labels = None
depends_on = None


URL_KEYS = ("base_url", "backend_test", "host", "domain", "api_host", "api_base_url")


def upgrade():
    """执行本版本数据库结构和存量数据升级。"""
    op.add_column("environment", sa.Column("base_url", sa.String(length=512), nullable=True))

    bind = op.get_bind()
    environments = bind.execute(sa.text("select id from environment")).fetchall()
    for environment in environments:
        environment_id = environment[0]
        row = bind.execute(
            sa.text(
                """
                select var_value
                from global_variable
                where environment_id = :environment_id
                  and is_active = 1
                  and lower(var_key) in :url_keys
                  and (
                    var_value like 'http://%'
                    or var_value like 'https://%'
                    or var_value like 'ws://%'
                    or var_value like 'wss://%'
                  )
                order by
                  case lower(var_key)
                    when 'base_url' then 0
                    when 'api_base_url' then 1
                    when 'backend_test' then 2
                    when 'api_host' then 3
                    when 'host' then 4
                    when 'domain' then 5
                    else 9
                  end,
                  id asc
                """
            ).bindparams(sa.bindparam("url_keys", expanding=True)),
            {"environment_id": environment_id, "url_keys": URL_KEYS},
        ).fetchone()
        if row and row[0]:
            bind.execute(
                sa.text("update environment set base_url = :base_url where id = :environment_id"),
                {"base_url": str(row[0]).rstrip("/"), "environment_id": environment_id},
            )

    op.drop_index("ix_global_variable_lookup", table_name="global_variable")
    with op.batch_alter_table("global_variable") as batch_op:
        batch_op.drop_constraint("uq_global_variable_scope_key", type_="unique")
        batch_op.alter_column("environment_id", existing_type=sa.Integer(), nullable=True)

    bind.execute(sa.text("update global_variable set environment_id = null"))
    op.create_index("ix_global_variable_lookup", "global_variable", ["project_id", "var_key"], unique=False)


def downgrade():
    """回退本版本数据库结构和存量数据变更。"""
    op.drop_index("ix_global_variable_lookup", table_name="global_variable")
    with op.batch_alter_table("global_variable") as batch_op:
        batch_op.alter_column("environment_id", existing_type=sa.Integer(), nullable=True)
        batch_op.create_unique_constraint(
            "uq_global_variable_scope_key",
            ["project_id", "environment_id", "var_key"],
        )
    op.create_index(
        "ix_global_variable_lookup",
        "global_variable",
        ["environment_id", "project_id", "var_key"],
        unique=False,
    )
    op.drop_column("environment", "base_url")
