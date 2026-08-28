# -*- coding: utf-8 -*-
"""
@Author: byy
@Desc: 集中定义开发、生产和测试环境的数据库、邮件、调度器等配置。
"""

import os


BASE_DIR = os.path.abspath(os.path.dirname(__file__))


class Config(object):
    """提供所有运行环境共享的基础应用配置。"""

    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-change-me")
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL",
        "mysql+pymysql://api_user:api_password@127.0.0.1:3306/api_test_platform?charset=utf8mb4",
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    MAIL_SERVER = os.environ.get("MAIL_SERVER", "")
    MAIL_PORT = int(os.environ.get("MAIL_PORT", "465"))
    MAIL_USE_SSL = os.environ.get("MAIL_USE_SSL", "true").lower() == "true"
    MAIL_USE_TLS = os.environ.get("MAIL_USE_TLS", "false").lower() == "true"
    MAIL_USERNAME = os.environ.get("MAIL_USERNAME", "")
    MAIL_PASSWORD = os.environ.get("MAIL_PASSWORD", "")
    MAIL_DEFAULT_SENDER = os.environ.get("MAIL_DEFAULT_SENDER", MAIL_USERNAME)

    BASE_REPORT_URL = os.environ.get("BASE_REPORT_URL", "http://localhost:5000")
    SCHEDULER_TIMEZONE = os.environ.get("SCHEDULER_TIMEZONE", "Asia/Shanghai")
    ENABLE_SCHEDULER = os.environ.get("ENABLE_SCHEDULER", "true").lower() == "true"


class DevelopmentConfig(Config):
    """提供本地开发环境使用的调试配置。"""

    DEBUG = True


class ProductionConfig(Config):
    """提供生产部署使用的稳定运行配置。"""

    DEBUG = False


class TestingConfig(Config):
    """提供自动化测试使用的隔离数据库和执行配置。"""

    TESTING = True
    DEBUG = True
    SQLALCHEMY_DATABASE_URI = os.environ.get("TEST_DATABASE_URL", "sqlite:///:memory:")
    ENABLE_SCHEDULER = False
    DATA_FACTORY_SYNC_EXECUTION = True


config_map = {
    "development": DevelopmentConfig,
    "production": ProductionConfig,
    "testing": TestingConfig,
    "default": DevelopmentConfig,
}
