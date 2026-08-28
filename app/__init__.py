# -*- coding: utf-8 -*-
"""
@Author: byy
@Desc: Flask 应用工厂，负责初始化扩展、注册页面蓝图和启动定时调度器。
"""

import os

from flask import Flask

from config import config_map

from .extensions import db, mail, migrate, scheduler


def create_app(config_name=None):
    """创建并配置 Flask 应用。"""
    app = Flask(__name__)
    selected_config = config_name or os.environ.get("APP_ENV") or os.environ.get("FLASK_ENV") or "default"
    app.config.from_object(config_map.get(selected_config, config_map["default"]))
    app.json.ensure_ascii = False

    register_extensions(app)
    register_template_filters(app)
    register_blueprints(app)
    register_scheduler(app)
    return app


def register_extensions(app):
    """初始化 Flask 扩展。"""
    from . import models as _models

    _models.__name__

    db.init_app(app)
    migrate.init_app(app, db)
    mail.init_app(app)

    if not scheduler.running:
        scheduler.configure(timezone=app.config.get("SCHEDULER_TIMEZONE", "Asia/Shanghai"))


def register_template_filters(app):
    """注册公共 Jinja 过滤器。"""
    from .utils.datetime_utils import format_datetime

    app.add_template_filter(format_datetime, "local_datetime")


def register_blueprints(app):
    """注册应用蓝图。"""
    from .blueprints.dashboard import dashboard_api_bp
    from .blueprints.dashboard import dashboard_bp
    from .blueprints.data_factories import data_factories_api_bp
    from .blueprints.data_factories import data_factories_bp
    from .blueprints.cases import cases_api_bp
    from .blueprints.cases import cases_bp
    from .blueprints.interfaces import interfaces_api_bp
    from .blueprints.interfaces import interfaces_bp
    from .blueprints.hooks import hooks_api_bp
    from .blueprints.projects import projects_api_bp
    from .blueprints.projects import project_modules_api_bp
    from .blueprints.projects import projects_bp
    from .blueprints.reports import reports_api_bp
    from .blueprints.reports import reports_bp
    from .blueprints.notifications import notifications_api_bp
    from .blueprints.notifications import notifications_bp
    from .blueprints.suites import suites_api_bp
    from .blueprints.suites import suites_bp
    from .blueprints.tasks import tasks_api_bp
    from .blueprints.tasks import tasks_bp
    from .blueprints.tasks import scheduler_api_bp
    from .blueprints.variables import environments_api_bp
    from .blueprints.variables import variables_api_bp
    from .blueprints.variables import variables_bp
    from .blueprints.websocket_debug import websocket_debug_api_bp

    app.register_blueprint(dashboard_bp)
    app.register_blueprint(dashboard_api_bp)
    app.register_blueprint(data_factories_bp)
    app.register_blueprint(data_factories_api_bp)
    app.register_blueprint(projects_bp)
    app.register_blueprint(projects_api_bp)
    app.register_blueprint(project_modules_api_bp)
    app.register_blueprint(variables_bp)
    app.register_blueprint(environments_api_bp)
    app.register_blueprint(variables_api_bp)
    app.register_blueprint(interfaces_bp)
    app.register_blueprint(interfaces_api_bp)
    app.register_blueprint(hooks_api_bp)
    app.register_blueprint(cases_bp)
    app.register_blueprint(cases_api_bp)
    app.register_blueprint(suites_bp)
    app.register_blueprint(suites_api_bp)
    app.register_blueprint(reports_bp)
    app.register_blueprint(reports_api_bp)
    app.register_blueprint(notifications_bp)
    app.register_blueprint(notifications_api_bp)
    app.register_blueprint(tasks_bp)
    app.register_blueprint(tasks_api_bp)
    app.register_blueprint(scheduler_api_bp)
    app.register_blueprint(websocket_debug_api_bp)


def register_scheduler(app):
    """应用初始化完成后启动任务调度器。"""
    from .services.scheduler_service import init_scheduler

    init_scheduler(app)
