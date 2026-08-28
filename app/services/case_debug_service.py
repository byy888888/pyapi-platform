# -*- coding: utf-8 -*-
"""
@Author: byy
@Desc: 用例后台调试服务，负责保存调试进度并通过 SSE 提供实时事件。
"""

import threading
import time
import uuid
from typing import Any
from typing import Dict
from typing import List
from typing import Optional

from ..extensions import db
from .case_runner import run_case


class CaseDebugExecution(object):
    """保存一次 WebSocket 用例调试的实时事件和最终结果。"""

    def __init__(self) -> None:
        """初始化线程安全的事件缓冲区。"""
        self.created_at = time.time()
        self.last_access_at = self.created_at
        self.completed = False
        self._sequence = 0
        self._events: List[Dict[str, Any]] = []
        self._condition = threading.Condition()

    def append(self, event_name: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """追加事件并立即唤醒正在等待的 SSE 连接。"""
        with self._condition:
            self._sequence += 1
            event = {
                "sequence": self._sequence,
                "event": event_name,
                "data": data,
            }
            self._events.append(event)
            self._condition.notify_all()
            return event

    def finish(self) -> None:
        """标记执行结束并唤醒 SSE 连接。"""
        with self._condition:
            self.completed = True
            self._condition.notify_all()

    def wait_after(
        self,
        sequence: int,
        timeout_seconds: float,
    ) -> List[Dict[str, Any]]:
        """等待指定序号后的事件，事件到达后立即返回。"""
        deadline = time.monotonic() + max(0, float(timeout_seconds or 0))
        with self._condition:
            while True:
                self.last_access_at = time.time()
                events = [
                    item
                    for item in self._events
                    if int(item.get("sequence") or 0) > int(sequence or 0)
                ]
                if events or self.completed:
                    return events
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return []
                self._condition.wait(timeout=remaining)


class CaseDebugRegistry(object):
    """管理 WebSocket 用例页面发起的后台调试执行。"""

    def __init__(self, ttl_seconds: int = 900, max_executions: int = 100) -> None:
        """初始化执行有效期与容量限制。"""
        self.ttl_seconds = ttl_seconds
        self.max_executions = max_executions
        self._executions: Dict[str, CaseDebugExecution] = {}
        self._lock = threading.Lock()

    def start(
        self,
        app: Any,
        case_id: int,
        environment_id: int,
        runtime_vars: Optional[Dict[str, Any]] = None,
    ) -> str:
        """创建后台执行并立即返回执行 ID。"""
        self.cleanup()
        execution_id = uuid.uuid4().hex
        execution = CaseDebugExecution()
        with self._lock:
            if len(self._executions) >= self.max_executions:
                raise RuntimeError("WebSocket 用例调试任务过多，请稍后重试")
            self._executions[execution_id] = execution

        worker = threading.Thread(
            target=self._run,
            args=(
                app,
                execution_id,
                int(case_id),
                int(environment_id),
                dict(runtime_vars or {}),
            ),
            name="websocket-case-debug",
            daemon=True,
        )
        worker.start()
        return execution_id

    def get(self, execution_id: str) -> CaseDebugExecution:
        """取得执行对象并刷新访问时间。"""
        with self._lock:
            execution = self._executions.get(execution_id)
            if execution is None:
                raise ValueError("WebSocket 用例调试任务不存在或已过期")
            execution.last_access_at = time.time()
            return execution

    def cleanup(self) -> int:
        """清理已结束且超过有效期的调试执行。"""
        deadline = time.time() - self.ttl_seconds
        removed = []
        with self._lock:
            for execution_id, execution in self._executions.items():
                if execution.completed and execution.last_access_at < deadline:
                    removed.append(execution_id)
            for execution_id in removed:
                self._executions.pop(execution_id, None)
        return len(removed)

    def discard(self, execution_id: str) -> None:
        """移除已经不再需要的调试执行记录。"""
        with self._lock:
            self._executions.pop(execution_id, None)

    def _run(
        self,
        app: Any,
        execution_id: str,
        case_id: int,
        environment_id: int,
        runtime_vars: Dict[str, Any],
    ) -> None:
        """在独立应用上下文中执行用例并持续写入实时事件。"""
        execution = self.get(execution_id)

        def push_message(message: Dict[str, Any]) -> None:
            """将执行器产生的 WebSocket 消息写入 SSE 事件缓冲区。"""
            execution.append("websocket_message", message)

        try:
            with app.app_context():
                result = run_case(
                    case_id,
                    environment_id,
                    runtime_vars=runtime_vars,
                    debug=True,
                    event_callback=push_message,
                )
                execution.append("case_result", result)
        except Exception as exc:
            execution.append("case_error", {"message": str(exc)})
        finally:
            with app.app_context():
                db.session.remove()
            execution.finish()


case_debug_registry = CaseDebugRegistry()
