# -*- coding: utf-8 -*-
"""
@Author: byy
@Desc: ${message}；负责本版本数据库结构或存量数据迁移。
"""

from alembic import op
import sqlalchemy as sa
${imports if imports else ""}

# Alembic 使用的修订标识。
# 修订编号: ${up_revision}
# 上一修订: ${down_revision | comma,n}
# 创建时间: ${create_date}
revision = ${repr(up_revision)}
down_revision = ${repr(down_revision)}
branch_labels = ${repr(branch_labels)}
depends_on = ${repr(depends_on)}


def upgrade():
    """执行本版本数据库结构和存量数据升级。"""
    ${upgrades if upgrades else "pass"}


def downgrade():
    """回退本版本数据库结构和存量数据变更。"""
    ${downgrades if downgrades else "pass"}
