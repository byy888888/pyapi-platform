# -*- coding: utf-8 -*-
"""
@Author: byy
@Desc: 创建数据库、迁移、邮件和 APScheduler 扩展对象，供应用工厂统一初始化。
"""

from apscheduler.schedulers.background import BackgroundScheduler
from flask_mail import Mail
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy


db = SQLAlchemy()
migrate = Migrate()
mail = Mail()
scheduler = BackgroundScheduler()
