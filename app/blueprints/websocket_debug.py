# -*- coding: utf-8 -*-
"""
@Author: byy
@Desc: WebSocket 接口调试 API，负责连接、发送、断开和 SSE 实时消息推送。
"""

import json
from typing import Any
from typing import Dict
from typing import Optional

from flask import Blueprint
from flask import current_app
from flask import jsonify
from flask import request
from flask import Response
from flask import stream_with_context

from ..services.variable_engine import build_variable_context
from ..services.websocket_debug_service import debug_registry


websocket_debug_api_bp = Blueprint(
    "websocket_debug_api",
    __name__,
    url_prefix="/api/websocket-debug",
)


@websocket_debug_api_bp.route("/connect", methods=["POST"])
def connect_websocket() -> Any:
    """由平台后端建立页面调试使用的 WebSocket 连接。"""
    data = request.get_json(silent=True) or {}
    error = _validate_connect_payload(data)
    if error:
        return jsonify({"success": False, "message": error}), 400
    try:
        context = build_variable_context(
            int(data["project_id"]),
            int(data["environment_id"]),
            data.get("runtime_vars") or {},
        )
        result = debug_registry.create(
            str(data.get("url") or ""),
            data.get("ws_config") or {},
            context,
        )
    except Exception as exc:
        current_app.logger.warning("websocket debug connect failed: %s", exc)
        return jsonify({"success": False, "message": str(exc)}), 400
    current_app.logger.info("websocket debug connected: session_id=%s", result["session_id"])
    return jsonify({"success": True, "data": result})


@websocket_debug_api_bp.route("/send", methods=["POST"])
def send_websocket_message() -> Any:
    """通过已建立的后端调试连接发送消息。"""
    data = request.get_json(silent=True) or {}
    if not data.get("session_id"):
        return jsonify({"success": False, "message": "调试会话 ID 不能为空"}), 400
    try:
        event = debug_registry.send(
            str(data["session_id"]),
            data.get("content", ""),
            str(data.get("message_type") or "text"),
        )
    except Exception as exc:
        current_app.logger.warning("websocket debug send failed: %s", exc)
        return jsonify({"success": False, "message": str(exc)}), 400
    return jsonify({"success": True, "data": event})


@websocket_debug_api_bp.route("/disconnect", methods=["POST"])
def disconnect_websocket() -> Any:
    """关闭并移除页面调试连接。"""
    data = request.get_json(silent=True) or {}
    session_id = str(data.get("session_id") or "")
    if not session_id:
        return jsonify({"success": False, "message": "调试会话 ID 不能为空"}), 400
    debug_registry.close(session_id)
    current_app.logger.info("websocket debug disconnected: session_id=%s", session_id)
    return jsonify({"success": True})


@websocket_debug_api_bp.route("/events", methods=["GET"])
def stream_websocket_messages() -> Any:
    """通过 SSE 将后端收到的 WebSocket 消息实时推送给调试页面。"""
    session_id = str(request.args.get("session_id") or "")
    if not session_id:
        return jsonify({"success": False, "message": "调试会话 ID 不能为空"}), 400
    try:
        session = debug_registry.get(session_id)
        after_sequence = _event_sequence()
    except (TypeError, ValueError) as exc:
        return jsonify({"success": False, "message": str(exc)}), 404

    @stream_with_context
    def generate():
        """持续等待增量消息，无消息时发送注释心跳保持连接。"""
        sequence = after_sequence
        while True:
            debug_registry.touch(session_id)
            messages = session.wait_for_messages_after(sequence, 15)
            if not messages:
                if session.closed:
                    break
                yield ": heartbeat\n\n"
                continue
            for item in messages:
                sequence = max(sequence, int(item.get("sequence") or 0))
                yield _sse_event("websocket_message", item, sequence)
            if session.closed:
                break

    response = Response(generate(), mimetype="text/event-stream")
    response.headers["Cache-Control"] = "no-cache, no-transform"
    response.headers["X-Accel-Buffering"] = "no"
    response.headers["Connection"] = "keep-alive"
    return response


def _validate_connect_payload(data: Dict[str, Any]) -> Optional[str]:
    """校验调试连接所需的项目、环境和地址。"""
    if not data.get("project_id"):
        return "项目不能为空"
    if not data.get("environment_id"):
        return "请选择调试环境"
    if not str(data.get("url") or "").strip():
        return "WebSocket 连接地址不能为空"
    return None


def _event_sequence() -> int:
    """优先使用 EventSource 自动重连携带的最后事件序号。"""
    value = request.headers.get("Last-Event-ID") or request.args.get("after_sequence") or 0
    return max(0, int(value))


def _sse_event(event_name: str, data: Dict[str, Any], event_id: int) -> str:
    """将字典编码为浏览器 EventSource 可消费的 SSE 事件。"""
    return "id: %s\nevent: %s\ndata: %s\n\n" % (
        event_id,
        event_name,
        json.dumps(data, ensure_ascii=False, separators=(",", ":")),
    )
