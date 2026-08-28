# -*- coding: utf-8 -*-
"""
@Author: byy
@Desc: 内置数据生成函数查询 API，为页面提供可用钩子函数列表。
"""

from flask import Blueprint
from flask import jsonify

from ..services.hook_functions import list_hook_functions


hooks_api_bp = Blueprint("hooks_api", __name__, url_prefix="/api/hook-function")


@hooks_api_bp.route("/list", methods=["POST"])
def list_hooks():
    """返回平台预置钩子函数清单。"""
    return jsonify({"success": True, "data": list_hook_functions()})
