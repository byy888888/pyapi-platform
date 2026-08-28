# -*- coding: utf-8 -*-
"""
@Author: byy
@Desc: 日期时间工具，统一处理平台本地时间、时区转换和页面格式化。
"""

from datetime import datetime
import os

import pytz


DEFAULT_TIMEZONE = "Asia/Shanghai"


def local_timezone():
    """返回平台配置的时区。"""
    timezone_name = os.environ.get("SCHEDULER_TIMEZONE") or DEFAULT_TIMEZONE
    try:
        return pytz.timezone(timezone_name)
    except pytz.UnknownTimeZoneError:
        return pytz.timezone(DEFAULT_TIMEZONE)


def now_local():
    """返回用于数据库落库的平台本地时间，结果不带时区信息。"""
    return datetime.now(local_timezone()).replace(tzinfo=None)


def to_local_naive(value):
    """把 datetime 转换为不带时区信息的平台本地时间。"""
    if not value:
        return None
    if value.tzinfo is None:
        return value
    return value.astimezone(local_timezone()).replace(tzinfo=None)


def format_datetime(value, fmt="%Y-%m-%d %H:%M:%S"):
    """格式化已按平台本地时间存储的时间字段。"""
    if not value:
        return ""
    return value.strftime(fmt)
