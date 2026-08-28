# -*- coding: utf-8 -*-
"""
@Author: byy
@Desc: Alembic 迁移运行环境，负责加载 Flask 数据库连接并执行在线或离线迁移。
"""

import logging
from logging.config import fileConfig

from flask import current_app

from alembic import context

# Alembic 配置对象，可访问当前使用的 .ini 配置值。
config = context.config

# 根据配置文件初始化 Python 日志。
fileConfig(config.config_file_name)
logger = logging.getLogger('alembic.env')


def get_engine():
    """获取 Flask-Migrate 当前使用的数据库引擎。"""
    try:
        # 兼容 Flask-SQLAlchemy 3 之前版本和 Alchemical。
        return current_app.extensions['migrate'].db.get_engine()
    except (TypeError, AttributeError):
        # 兼容 Flask-SQLAlchemy 3 及之后版本。
        return current_app.extensions['migrate'].db.engine


def get_engine_url():
    """获取并规范化迁移使用的数据库连接地址。"""
    try:
        return get_engine().url.render_as_string(hide_password=False).replace(
            '%', '%%')
    except AttributeError:
        return str(get_engine().url).replace('%', '%%')


# 在这里提供模型元数据，用于支持自动生成迁移。
config.set_main_option('sqlalchemy.url', get_engine_url())
target_db = current_app.extensions['migrate'].db

# 如有需要，可从配置中读取 env.py 使用的其他值。


def get_metadata():
    """获取迁移自动检测所需的 SQLAlchemy 元数据。"""
    if hasattr(target_db, 'metadatas'):
        return target_db.metadatas[None]
    return target_db.metadata


def run_migrations_offline():
    """以离线模式运行迁移。

    离线模式只使用数据库地址配置迁移上下文，不需要创建数据库引擎，
    因此即使没有可用的 DBAPI 也可以生成迁移脚本输出。
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url, target_metadata=get_metadata(), literal_binds=True
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    """以在线模式运行迁移。

    在线模式需要创建数据库引擎，并把连接绑定到迁移上下文。
    """

    # 没有表结构变更时，阻止生成空的自动迁移脚本。
    def process_revision_directives(context, revision, directives):
        """在数据库结构没有变化时阻止生成空迁移文件。"""
        if getattr(config.cmd_opts, 'autogenerate', False):
            migration_script = directives[0]
            if migration_script.upgrade_ops.is_empty():
                directives[:] = []
                logger.info('未检测到表结构变更。')

    conf_args = current_app.extensions['migrate'].configure_args
    if conf_args.get("process_revision_directives") is None:
        conf_args["process_revision_directives"] = process_revision_directives

    connectable = get_engine()

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=get_metadata(),
            **conf_args
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
