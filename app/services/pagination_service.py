# -*- coding: utf-8 -*-
"""
@Author: byy
@Desc: 公共分页参数服务，负责解析和校验列表页分页条件。
"""

from flask import jsonify


DEFAULT_PAGE = 1
DEFAULT_PAGE_SIZE = 10
MAX_PAGE_SIZE = 100


def paginate_response(query, serializer, data=None):
    """按统一结构返回分页列表数据。"""
    data = data or {}
    page = parse_positive_int(data.get("page"), DEFAULT_PAGE)
    page_size = parse_positive_int(data.get("page_size"), DEFAULT_PAGE_SIZE)
    page_size = min(page_size, MAX_PAGE_SIZE)
    pagination = query.paginate(page=page, per_page=page_size, error_out=False)
    return jsonify(
        {
            "success": True,
            "data": [serializer(item) for item in pagination.items],
            "pagination": {
                "page": pagination.page,
                "page_size": pagination.per_page,
                "total": pagination.total,
                "pages": pagination.pages,
                "has_prev": pagination.has_prev,
                "has_next": pagination.has_next,
            },
        }
    )


def parse_positive_int(value, default):
    """把页面提交的分页参数解析为正整数。"""
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    if number < 1:
        return default
    return number
