# -*- coding: utf-8 -*-
"""
@Author: byy
@Desc: 将存量日期时间调整为平台约定的本地时间。
"""

from alembic import op
import sqlalchemy as sa


revision = "0005_shift_existing_datetimes_to_local"
down_revision = "0004_add_interface_params_template"
branch_labels = None
depends_on = None


TABLE_COLUMNS = {
    "project": ("created_at", "updated_at"),
    "environment": ("created_at", "updated_at"),
    "global_variable": ("created_at", "updated_at"),
    "interface": ("created_at", "updated_at"),
    "test_case": ("created_at", "updated_at"),
    "suite": ("created_at", "updated_at"),
    "suite_case": ("created_at", "updated_at"),
    "scheduled_task": ("created_at", "updated_at", "next_run_at", "last_run_at"),
    "task_suite": ("created_at", "updated_at"),
    "notification": ("created_at", "updated_at"),
    "task_notification": ("created_at", "updated_at"),
    "execution_history": ("created_at", "updated_at", "start_time", "end_time"),
    "execution_detail": ("created_at", "updated_at"),
}


def upgrade():
    """执行本版本数据库结构和存量数据升级。"""
    _shift_hours(8)


def downgrade():
    """回退本版本数据库结构和存量数据变更。"""
    _shift_hours(-8)


def _shift_hours(hours):
    """将指定数据表中的时间字段按小时批量平移。"""
    bind = op.get_bind()
    dialect = bind.dialect.name
    for table_name, columns in TABLE_COLUMNS.items():
        for column_name in columns:
            bind.execute(sa.text(_shift_sql(dialect, table_name, column_name, hours)))


def _shift_sql(dialect, table_name, column_name, hours):
    """生成适配当前数据库类型的时间平移 SQL。"""
    table = _quote(dialect, table_name)
    column = _quote(dialect, column_name)
    if dialect == "mysql":
        func = "DATE_ADD" if hours >= 0 else "DATE_SUB"
        return (
            "UPDATE {table} SET {column} = {func}({column}, INTERVAL {hours} HOUR) "
            "WHERE {column} IS NOT NULL"
        ).format(table=table, column=column, func=func, hours=abs(hours))

    sign = "+" if hours >= 0 else "-"
    return (
        "UPDATE {table} SET {column} = datetime({column}, '{sign}{hours} hours') "
        "WHERE {column} IS NOT NULL"
    ).format(table=table, column=column, sign=sign, hours=abs(hours))


def _quote(dialect, name):
    """按当前数据库方言安全引用表名或字段名。"""
    if dialect == "mysql":
        return "`%s`" % name
    return '"%s"' % name
