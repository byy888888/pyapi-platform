# -*- coding: utf-8 -*-
"""
@Author: byy
@Desc: WebSocket 页面调试会话注册表，负责创建、查找、发送和回收临时连接。
"""

import threading
import time
import uuid
from typing import Any
from typing import Dict
from typing import Optional

from .websocket_session import public_message
from .websocket_session import WebSocketSession


class WebSocketDebugRegistry(object):
    """管理页面调试使用的临时 WebSocket 会话。"""

    def __init__(self, ttl_seconds: int = 900, max_sessions: int = 100) -> None:
        """初始化会话有效期和最大数量。"""
        self.ttl_seconds = ttl_seconds
        self.max_sessions = max_sessions
        self._sessions: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()

    def create(
        self,
        url: str,
        config: Dict[str, Any],
        context: Dict[str, Any],
    ) -> Dict[str, Any]:
        """创建并连接一个新的页面调试会话。"""
        self.cleanup()
        with self._lock:
            if len(self._sessions) >= self.max_sessions:
                raise RuntimeError("WebSocket 调试会话数量已达上限，请先断开不用的连接")
        session = WebSocketSession(url, config, context)
        try:
            connection = session.connect()
        except Exception:
            session.close("调试连接建立失败")
            raise
        session_id = uuid.uuid4().hex
        now = time.time()
        with self._lock:
            self._sessions[session_id] = {
                "session": session,
                "created_at": now,
                "last_access_at": now,
            }
        return {
            "session_id": session_id,
            "connection": connection,
            "messages": session.messages_after(0),
        }

    def send(
        self,
        session_id: str,
        content: Any,
        message_type: str,
    ) -> Dict[str, Any]:
        """向指定调试连接发送消息。"""
        session = self.get(session_id)
        return public_message(session.send(content, message_type))

    def close(self, session_id: str) -> bool:
        """关闭并移除指定调试会话。"""
        with self._lock:
            entry = self._sessions.pop(session_id, None)
        if entry is None:
            return False
        entry["session"].close("页面调试主动断开")
        return True

    def get(self, session_id: str) -> WebSocketSession:
        """读取会话并刷新最后访问时间。"""
        with self._lock:
            entry = self._sessions.get(session_id)
            if entry is None:
                raise ValueError("WebSocket 调试会话不存在或已过期")
            entry["last_access_at"] = time.time()
            return entry["session"]

    def touch(self, session_id: str) -> None:
        """刷新 SSE 正在监听的调试会话访问时间。"""
        with self._lock:
            entry = self._sessions.get(session_id)
            if entry is not None:
                entry["last_access_at"] = time.time()

    def cleanup(self) -> int:
        """回收超过有效期的调试连接。"""
        deadline = time.time() - self.ttl_seconds
        expired = []
        with self._lock:
            for session_id, entry in self._sessions.items():
                if entry["last_access_at"] < deadline:
                    expired.append((session_id, entry))
            for session_id, _entry in expired:
                self._sessions.pop(session_id, None)
        for _session_id, entry in expired:
            entry["session"].close("调试会话超时回收")
        return len(expired)


debug_registry = WebSocketDebugRegistry()
