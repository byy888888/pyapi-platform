# -*- coding: utf-8 -*-
"""
@Author: byy
@Desc: HTTP 请求执行器，负责变量替换、请求发送和标准化请求响应快照。
"""

import json
import time
from urllib.parse import urljoin
from urllib.parse import urlsplit

import requests

from ..enums import BodyType
from .variable_engine import replace_variables


def run_http_case(case, context):
    """执行 HTTP 用例并返回完整的请求和响应信息。"""
    prepared = prepare_http_case(case, context or {})
    started = time.time()
    error = None
    response = None

    try:
        response = requests.request(
            method=prepared["method"],
            url=prepared["url"],
            params=prepared["params"],
            headers=prepared["headers"],
            data=prepared["data"],
            json=prepared["json"],
            files=prepared["files"],
            timeout=prepared["timeout_seconds"],
        )
    except Exception as exc:
        error = str(exc)

    elapsed_ms = int((time.time() - started) * 1000)
    if response is None:
        return {
            "success": False,
            "error": error,
            "request": prepared["request_snapshot"],
            "response": None,
            "response_context": {
                "elapsed_ms": elapsed_ms,
                "error": error,
                "body_type": "empty",
            },
        }

    body_text = response.text
    body_json = _safe_json(response)
    body_type = _detect_body_type(response, body_text, body_json)
    response_context = {
        "status_code": response.status_code,
        "headers": dict(response.headers),
        "body_text": body_text,
        "body_json": body_json,
        "body_type": body_type,
        "body_length": len(response.content or b""),
        "elapsed_ms": elapsed_ms,
    }
    return {
        "success": True,
        "error": None,
        "request": prepared["request_snapshot"],
        "response": {
            "status_code": response.status_code,
            "headers": dict(response.headers),
            "body": body_text,
            "elapsed_ms": elapsed_ms,
        },
        "response_context": response_context,
    }


def prepare_http_case(case, context):
    """根据字典或模型形式的用例准备 HTTP 请求。"""
    method = (_get_case_value(case, "method", "GET") or "GET").upper()
    url = _get_case_value(case, "url", "")
    headers = _get_case_value(case, "headers", None)
    if headers is None:
        headers = _get_case_value(case, "headers_template", {})
    body = _get_case_value(case, "body", None)
    if body is None:
        body = _get_case_value(case, "body_template", {})
    params = _get_case_value(case, "params", None)
    if params is None:
        params = _get_case_value(case, "request_params", {})
    body_type = _get_case_value(case, "body_type", BodyType.NONE) or BodyType.NONE
    timeout_seconds = _get_case_value(case, "timeout_seconds", 30) or 30

    url = replace_variables(url, context)
    url = _normalize_http_url(url, context)
    headers = replace_variables(headers or {}, context)
    params = replace_variables(params or {}, context)
    body = replace_variables(body if body is not None else {}, context)

    data = None
    json_body = None
    files = None
    if body_type == BodyType.JSON:
        json_body = body
    elif body_type in (BodyType.FORM, BodyType.URLENCODED):
        data = body
    elif body_type == BodyType.FORM_DATA:
        files = _form_data_files(body)
    elif body_type == BodyType.RAW:
        data = body if isinstance(body, str) else json.dumps(body, ensure_ascii=False)

    return {
        "method": method,
        "url": url,
        "headers": headers,
        "params": params,
        "data": data,
        "json": json_body,
        "files": files,
        "timeout_seconds": timeout_seconds,
        "request_snapshot": {
            "method": method,
            "url": url,
            "headers": headers,
            "params": params,
            "body": body,
            "body_type": body_type,
            "timeout_seconds": timeout_seconds,
        },
    }


def _get_case_value(case, name, default=None):
    """从字典或模型形式的用例中读取字段。"""
    if isinstance(case, dict):
        return case.get(name, default)
    return getattr(case, name, default)


def _form_data_files(body):
    """构造 multipart form-data 字段，暂不强制支持文件上传。"""
    if not isinstance(body, dict):
        return None
    return [
        (key, (None, "" if value is None else str(value)))
        for key, value in body.items()
    ]


def _normalize_http_url(url, context):
    """接口保存相对路径时，使用 base_url 拼成完整 HTTP 地址。"""
    url = (url or "").strip()
    if urlsplit(url).scheme:
        return url

    base_url = _get_base_url_from_context(context)
    if not base_url:
        return url

    return urljoin(str(base_url).rstrip("/") + "/", url.lstrip("/"))


def _get_base_url_from_context(context):
    """从选中的环境中读取请求域名。"""
    environment = ((context or {}).get("environment") or {})
    return environment.get("base_url") or ((context or {}).get("global_vars") or {}).get("base_url")


def _safe_json(response):
    """尽可能解析响应 JSON。"""
    try:
        return response.json()
    except ValueError:
        return None


def _detect_body_type(response, body_text, body_json):
    """识别简化后的响应体类型。"""
    if not response.content:
        return "empty"
    content_type = response.headers.get("Content-Type", "")
    if body_json is not None or "json" in content_type.lower():
        return "json"
    if _looks_binary(response.content):
        return "binary"
    return "text"


def _looks_binary(content):
    """检查响应内容是否像二进制数据。"""
    if not content:
        return False
    return b"\x00" in content[:1024]
