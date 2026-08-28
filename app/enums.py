# -*- coding: utf-8 -*-
"""
@Author: byy
@Desc: 平台公共枚举和常量，统一约束接口、用例、执行及断言字段取值。
"""

from typing import Dict
from typing import List


class InterfaceType(object):
    """接口类型取值。"""

    HTTP = "http"
    WEBSOCKET = "websocket"

    VALUES = (HTTP, WEBSOCKET)


class EnvironmentType(object):
    """环境类型取值。"""

    PRODUCTION = "production"
    STAGING = "staging"
    TESTING = "testing"
    DEVELOPMENT = "development"

    VALUES = (PRODUCTION, STAGING, TESTING, DEVELOPMENT)
    LABELS = {
        PRODUCTION: "生产",
        STAGING: "预发",
        TESTING: "测试",
        DEVELOPMENT: "开发",
    }


class HttpMethod(object):
    """支持的 HTTP 请求方法取值。"""

    GET = "GET"
    POST = "POST"
    PUT = "PUT"
    DELETE = "DELETE"
    PATCH = "PATCH"
    HEAD = "HEAD"
    OPTIONS = "OPTIONS"
    WS = "WS"

    VALUES = (GET, POST, PUT, DELETE, PATCH, HEAD, OPTIONS, WS)


class BodyType(object):
    """请求体类型取值。"""

    JSON = "json"
    FORM = "form"
    FORM_DATA = "form-data"
    URLENCODED = "x-www-form-urlencoded"
    RAW = "raw"
    NONE = "none"

    VALUES = (NONE, FORM_DATA, URLENCODED, JSON, FORM, RAW)


class AssertionComparator(object):
    """断言比较器取值及页面展示名称。"""

    EQUALS = "equals"
    NOT_EQUALS = "not_equals"
    GREATER_THAN = "greater_than"
    LESS_THAN = "less_than"
    GREATER_OR_EQUAL = "greater_or_equal"
    LESS_OR_EQUAL = "less_or_equal"
    CONTAINS = "contains"
    NOT_CONTAINS = "not_contains"
    IS_NONE = "is_none"
    IS_NOT_NONE = "is_not_none"
    REGEX_MATCH = "regex_match"
    TIME_LESS_THAN = "time_less_than"
    RECEIVE_CONTAINS_WITHIN = "receive_contains_within"

    VALUES = (
        EQUALS,
        NOT_EQUALS,
        GREATER_THAN,
        LESS_THAN,
        GREATER_OR_EQUAL,
        LESS_OR_EQUAL,
        CONTAINS,
        NOT_CONTAINS,
        IS_NONE,
        IS_NOT_NONE,
        REGEX_MATCH,
        TIME_LESS_THAN,
        RECEIVE_CONTAINS_WITHIN,
    )
    LABELS = {
        EQUALS: "等于",
        NOT_EQUALS: "不等于",
        GREATER_THAN: "大于",
        LESS_THAN: "小于",
        GREATER_OR_EQUAL: "大于等于",
        LESS_OR_EQUAL: "小于等于",
        CONTAINS: "包含",
        NOT_CONTAINS: "不包含",
        IS_NONE: "为空（is_none）",
        IS_NOT_NONE: "非空（is_not_none）",
        REGEX_MATCH: "正则匹配",
        TIME_LESS_THAN: "响应时间小于",
        RECEIVE_CONTAINS_WITHIN: "指定时间内收到包含内容",
    }

    @classmethod
    def options(cls) -> List[Dict[str, str]]:
        """返回前端下拉框使用的比较器选项。"""
        return [
            {"value": value, "label": cls.LABELS[value]}
            for value in cls.VALUES
        ]


class AssertionValueType(object):
    """强类型断言支持的数据类型及页面展示名称。"""

    RAW = ""
    STRING = "string"
    INTEGER = "int"
    FLOAT = "float"
    BOOLEAN = "bool"
    NULL = "null"
    OBJECT = "object"
    ARRAY = "array"

    VALUES = (RAW, STRING, INTEGER, FLOAT, BOOLEAN, NULL, OBJECT, ARRAY)
    LABELS = {
        RAW: "原始值（raw）",
        STRING: "字符串（string）",
        INTEGER: "整数（int）",
        FLOAT: "浮点数（float）",
        BOOLEAN: "布尔值（bool）",
        NULL: "空值（null）",
        OBJECT: "对象（object）",
        ARRAY: "数组（array）",
    }

    @classmethod
    def options(cls) -> List[Dict[str, str]]:
        """返回前端下拉框使用的数据类型选项。"""
        return [
            {"value": value, "label": cls.LABELS[value]}
            for value in cls.VALUES
        ]


class SuiteType(object):
    """测试集合执行类型取值。"""

    SCENE = "scene"
    SINGLE = "single"

    VALUES = (SCENE, SINGLE)


class ScheduleType(object):
    """定时任务计划类型取值。"""

    INTERVAL = "interval"
    DAILY = "daily"
    CRON = "cron"

    VALUES = (INTERVAL, DAILY, CRON)


class NotificationType(object):
    """通知渠道类型取值。"""

    DINGTALK = "dingtalk"
    EMAIL = "email"

    VALUES = (DINGTALK, EMAIL)


class TriggerType(object):
    """执行触发方式取值。"""

    MANUAL = "manual"
    SCHEDULED = "scheduled"

    VALUES = (MANUAL, SCHEDULED)


class HistoryStatus(object):
    """执行历史状态取值。"""

    RUNNING = "running"
    FINISHED = "finished"
    FAILED = "failed"

    VALUES = (RUNNING, FINISHED, FAILED)


class DetailStatus(object):
    """执行明细状态取值。"""

    PASS = "pass"
    FAIL = "fail"
    ERROR = "error"
    SKIPPED = "skipped"

    VALUES = (PASS, FAIL, ERROR, SKIPPED)


class DataFactorySourceType(object):
    """数据工厂接口配置来源。"""

    INTERFACE = "interface"
    CUSTOM = "custom"

    VALUES = (INTERFACE, CUSTOM)


class DataFactoryStepType(object):
    """数据工厂流程步骤类型。"""

    REQUEST = "request"
    WAIT = "wait"

    VALUES = (REQUEST, WAIT)


class DataFactoryRunStatus(object):
    """数据工厂执行状态。"""

    QUEUED = "queued"
    RUNNING = "running"
    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"

    VALUES = (
        QUEUED,
        RUNNING,
        SUCCESS,
        PARTIAL,
        FAILED,
        CANCELLED,
        INTERRUPTED,
    )


class DataFactoryIterationStatus(object):
    """数据工厂单轮执行状态。"""

    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"
    SKIPPED = "skipped"

    VALUES = (RUNNING, SUCCESS, FAILED, CANCELLED, SKIPPED)
