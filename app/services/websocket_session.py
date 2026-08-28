# -*- coding: utf-8 -*-
"""
@Author: byy
@Desc: WebSocket 会话服务，负责全双工收发、消息缓冲、心跳、断言和提取。
"""

import base64
import json
import queue
import threading
import time
from typing import Any
from typing import Callable
from typing import Dict
from typing import List
from typing import Optional
from urllib.parse import urljoin
from urllib.parse import urlsplit

import websocket

from .assert_engine import assert_response
from .extractor_service import run_extractors
from .variable_engine import replace_variables


class WebSocketSession(object):
    """维护一个后端 WebSocket 连接及其双向消息缓冲区。"""

    def __init__(
        self,
        url: str,
        config: Optional[Dict[str, Any]],
        context: Optional[Dict[str, Any]],
        event_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> None:
        """保存连接配置，实际连接由 connect 方法建立。"""
        self.raw_url = url or ""
        self.config = dict(config or {})
        self.context = context or {}
        self.event_callback = event_callback
        self.connection: Optional[websocket.WebSocket] = None
        self.connected = False
        self.closed = False
        self.close_reason = ""
        self.connected_at = 0.0
        self.connection_time_ms = 0
        self._messages: List[Dict[str, Any]] = []
        self._message_queue: "queue.Queue[Dict[str, Any]]" = queue.Queue()
        self._lock = threading.Lock()
        self._message_condition = threading.Condition(self._lock)
        self._stop_event = threading.Event()
        self._receiver: Optional[threading.Thread] = None
        self._heartbeat: Optional[threading.Thread] = None
        self._sequence = 0

    def connect(self) -> Dict[str, Any]:
        """解析配置并建立连接，同时启动接收器和可选业务心跳。"""
        url = normalize_ws_url(
            str(replace_variables(self.raw_url, self.context)),
            self.context,
        )
        if urlsplit(url).scheme not in ("ws", "wss"):
            raise ValueError("WebSocket 地址必须以 ws:// 或 wss:// 开头")

        headers = replace_variables(self.config.get("headers") or {}, self.context)
        subprotocols = replace_variables(
            self.config.get("subprotocols") or [],
            self.context,
        )
        connect_timeout_ms = _positive_int(
            self.config.get("connect_timeout_ms"),
            5000,
        )
        started_ns = time.perf_counter_ns()
        self.connection = websocket.create_connection(
            url,
            header=format_headers(headers),
            subprotocols=list(subprotocols or []),
            timeout=connect_timeout_ms / 1000.0,
        )
        self.connection.settimeout(0.5)
        self.connection_time_ms = elapsed_ms(started_ns)
        self.connected_at = time.time()
        self.connected = True
        self.closed = False
        self._append_event(
            "system",
            "event",
            "连接成功",
            extra={
                "event": "connected",
                "url": mask_websocket_url(url),
                "connection_time_ms": self.connection_time_ms,
                "subprotocol": getattr(self.connection, "subprotocol", None),
            },
        )
        self._receiver = threading.Thread(
            target=self._receive_loop,
            name="websocket-receiver",
            daemon=True,
        )
        self._receiver.start()
        self._send_connect_message()
        self._start_heartbeat()
        return {
            "url": mask_websocket_url(url),
            "connection_time_ms": self.connection_time_ms,
            "subprotocol": getattr(self.connection, "subprotocol", None),
        }

    def send(
        self,
        content: Any,
        message_type: str = "text",
        is_heartbeat: bool = False,
        is_connect_message: bool = False,
    ) -> Dict[str, Any]:
        """渲染并发送文本、JSON 或二进制消息，返回发送事件。"""
        if self.connection is None or not self.connected or self.closed:
            raise RuntimeError("WebSocket 尚未连接")
        rendered = replace_variables(content, self.context)
        payload, event_data = prepare_outgoing_message(rendered, message_type)
        started_ns = time.perf_counter_ns()
        opcode = websocket.ABNF.OPCODE_BINARY if message_type == "binary" else websocket.ABNF.OPCODE_TEXT
        self.connection.send(payload, opcode=opcode)
        return self._append_event(
            "send",
            message_type,
            event_data,
            extra={
                "sent_ns": started_ns,
                "is_heartbeat": bool(is_heartbeat),
                "is_connect_message": bool(is_connect_message),
            },
        )

    def wait_and_assert(
        self,
        step: Dict[str, Any],
        after_sequence: int,
        timeout_seconds: float,
        runtime_vars: Dict[str, Any],
        started_ns: Optional[int] = None,
    ) -> Dict[str, Any]:
        """在限定时间内查找目标消息，并执行断言和提取。"""
        wait_started_ns = time.perf_counter_ns()
        matched = self._wait_for_message(
            step.get("target") or {},
            after_sequence,
            timeout_seconds,
        )
        if matched is None:
            return {
                "passed": False,
                "message": "等待目标消息超时",
                "wait_time_ms": elapsed_ms(wait_started_ns),
                "assertions": [],
                "extractors": [],
                "matched_message": None,
            }

        response_context = message_response_context(matched)
        assertions = assert_response(step.get("assertions") or [], response_context)
        extractors = run_extractors(
            step.get("extractors") or [],
            response_context,
            runtime_vars,
        )
        passed = all(item.get("passed") for item in assertions) and all(
            item.get("success") for item in extractors
        )
        matched["consumed"] = bool(
            (step.get("target") or {}).get("consume", True)
        )
        response_time_ms = None
        if started_ns:
            response_time_ms = max(
                0,
                int((matched.get("received_ns", started_ns) - started_ns) / 1_000_000),
            )
        return {
            "passed": passed,
            "message": "消息校验通过" if passed else "消息校验失败",
            "wait_time_ms": elapsed_ms(wait_started_ns),
            "response_time_ms": response_time_ms,
            "assertions": assertions,
            "extractors": extractors,
            "matched_message": public_message(matched),
            "response_context": response_context,
        }

    def messages_after(self, sequence: int = 0) -> List[Dict[str, Any]]:
        """返回指定序号后的可序列化消息。"""
        with self._lock:
            return [
                public_message(item)
                for item in self._messages
                if int(item.get("sequence") or 0) > int(sequence or 0)
            ]

    def wait_for_messages_after(
        self,
        sequence: int = 0,
        timeout_seconds: float = 0,
    ) -> List[Dict[str, Any]]:
        """等待新消息到达后立即返回，超时或连接关闭时返回当前增量消息。"""
        deadline = time.monotonic() + max(0, float(timeout_seconds or 0))
        with self._message_condition:
            while True:
                messages = [
                    public_message(item)
                    for item in self._messages
                    if int(item.get("sequence") or 0) > int(sequence or 0)
                ]
                if messages or self.closed:
                    return messages
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return []
                self._message_condition.wait(timeout=remaining)

    def current_sequence(self) -> int:
        """返回当前最新消息序号。"""
        with self._lock:
            return self._sequence

    def latest_send_marker(self) -> tuple:
        """返回最近一次发送事件的序号和单调时钟时间。"""
        with self._lock:
            for item in reversed(self._messages):
                if item.get("direction") == "send":
                    return int(item.get("sequence") or 0), item.get("sent_ns")
        return 0, None

    def close(self, reason: str = "客户端主动断开") -> None:
        """停止心跳和接收器，并安全关闭连接。"""
        if self.closed:
            return
        self._stop_event.set()
        self.close_reason = reason
        connection = self.connection
        self.closed = True
        self.connected = False
        if connection is not None:
            try:
                connection.close()
            except Exception:
                pass
        current = threading.current_thread()
        for worker in (self._receiver, self._heartbeat):
            if worker is not None and worker is not current:
                worker.join(timeout=1)
        self._append_event(
            "system",
            "event",
            reason,
            extra={"event": "closed"},
        )

    def _receive_loop(self) -> None:
        """持续接收服务端消息并写入缓冲区。"""
        while not self._stop_event.is_set() and self.connection is not None:
            try:
                opcode, data = self.connection.recv_data(control_frame=True)
                received_ns = time.perf_counter_ns()
                if opcode == websocket.ABNF.OPCODE_CLOSE:
                    self.close("服务端主动断开连接")
                    break
                if opcode in (
                    websocket.ABNF.OPCODE_PING,
                    websocket.ABNF.OPCODE_PONG,
                ):
                    # websocket-client 会自动回复协议层 Ping；控制帧不混入业务日志。
                    continue
                if opcode == websocket.ABNF.OPCODE_TEXT:
                    if isinstance(data, bytes):
                        data = data.decode("utf-8")
                    message_type = "text"
                    event_data = data
                    parsed_json = parse_message_json(data)
                elif opcode == websocket.ABNF.OPCODE_BINARY:
                    if not isinstance(data, bytes):
                        data = bytes(data)
                    message_type = "binary"
                    event_data = serialize_binary(data)
                    parsed_json = None
                else:
                    continue
                self._append_event(
                    "receive",
                    message_type,
                    event_data,
                    extra={
                        "received_ns": received_ns,
                        "parsed_json": parsed_json,
                    },
                )
            except websocket.WebSocketTimeoutException:
                continue
            except Exception as exc:
                if not self._stop_event.is_set():
                    self._append_event(
                        "system",
                        "error",
                        str(exc),
                        extra={"event": "receive_error"},
                    )
                    self.close("WebSocket 接收连接已关闭")
                break

    def _wait_for_message(
        self,
        target: Dict[str, Any],
        after_sequence: int,
        timeout_seconds: float,
    ) -> Optional[Dict[str, Any]]:
        """从已缓存和新消息中寻找符合目标条件的业务消息。"""
        deadline = time.monotonic() + max(0.01, float(timeout_seconds))
        checked_sequence = int(after_sequence or 0)
        while time.monotonic() < deadline:
            with self._lock:
                candidates = [
                    item
                    for item in self._messages
                    if item.get("direction") == "receive"
                    and int(item.get("sequence") or 0) > checked_sequence
                    and not item.get("consumed")
                ]
            for item in candidates:
                checked_sequence = max(checked_sequence, int(item.get("sequence") or 0))
                if not target.get("include_heartbeat") and item.get("is_heartbeat"):
                    continue
                if message_matches_target(item, target):
                    return item
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            try:
                self._message_queue.get(timeout=min(remaining, 0.2))
            except queue.Empty:
                pass
        return None

    def _append_event(
        self,
        direction: str,
        message_type: str,
        data: Any,
        extra: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """以递增序号追加一条线程安全消息事件。"""
        with self._message_condition:
            self._sequence += 1
            item = {
                "sequence": self._sequence,
                "direction": direction,
                "message_type": message_type,
                "data": data,
                "timestamp": time.time(),
                "consumed": False,
            }
            item.update(extra or {})
            self._messages.append(item)
            self._message_condition.notify_all()
        self._message_queue.put(item)
        if self.event_callback is not None:
            try:
                self.event_callback(public_message(item))
            except Exception:
                # 页面实时日志失败不能影响真正的 WebSocket 收发与自动执行。
                pass
        return item

    def _send_connect_message(self) -> None:
        """根据可选配置在连接完成后发送前置消息。"""
        config = self.config.get("connect_message") or {}
        if not config.get("enabled"):
            return
        content = config.get("content")
        if content in (None, ""):
            raise ValueError("已开启连接后消息，但消息内容为空")
        self.send(
            content,
            config.get("message_type") or "text",
            is_connect_message=True,
        )

    def _start_heartbeat(self) -> None:
        """按可选业务心跳配置启动后台发送线程。"""
        heartbeat = self.config.get("heartbeat") or {}
        if not heartbeat.get("enabled"):
            return
        content = heartbeat.get("content")
        if content in (None, ""):
            raise ValueError("已开启业务心跳，但心跳内容为空")
        interval_ms = _positive_int(heartbeat.get("interval_ms"), 30000)

        def heartbeat_loop() -> None:
            """按固定间隔发送业务层心跳。"""
            while not self._stop_event.wait(interval_ms / 1000.0):
                try:
                    self.send(
                        content,
                        heartbeat.get("message_type") or "text",
                        is_heartbeat=True,
                    )
                except Exception as exc:
                    if not self._stop_event.is_set():
                        self._append_event(
                            "system",
                            "error",
                            "业务心跳发送失败：%s" % exc,
                            extra={"event": "heartbeat_error"},
                        )
                    break

        self._heartbeat = threading.Thread(
            target=heartbeat_loop,
            name="websocket-heartbeat",
            daemon=True,
        )
        self._heartbeat.start()


def message_matches_target(item: Dict[str, Any], target: Dict[str, Any]) -> bool:
    """判断消息是否符合“下一条”或条件匹配规则。"""
    mode = target.get("mode") or "next"
    if mode == "next":
        return True
    conditions = target.get("conditions") or []
    if not conditions:
        return True
    context = message_response_context(item)
    results = assert_response(conditions, context)
    return bool(results) and all(result.get("passed") for result in results)


def message_response_context(item: Dict[str, Any]) -> Dict[str, Any]:
    """把一条 WebSocket 消息转换为通用断言和提取上下文。"""
    data = item.get("data")
    body_length = len(data) if data is not None else 0
    if item.get("message_type") == "binary" and isinstance(data, dict):
        body_length = int(data.get("length") or 0)
    return {
        "body_text": data if isinstance(data, str) else "",
        "body_json": item.get("parsed_json"),
        "body_type": item.get("message_type"),
        "body_length": body_length,
        "ws_message": data,
        "ws_messages": [public_message(item)],
    }


def prepare_outgoing_message(content: Any, message_type: str) -> tuple:
    """按消息类型生成 websocket-client 发送值和日志值。"""
    if message_type == "json":
        if isinstance(content, str):
            try:
                parsed = json.loads(content)
            except (TypeError, ValueError) as exc:
                raise ValueError("JSON 消息格式不正确：%s" % exc)
        else:
            parsed = content
        text = json.dumps(parsed, ensure_ascii=False, separators=(",", ":"))
        return text, text
    if message_type == "binary":
        if isinstance(content, bytes):
            return content, serialize_binary(content)
        try:
            binary = base64.b64decode(str(content), validate=True)
        except (TypeError, ValueError) as exc:
            raise ValueError("二进制消息必须是合法 Base64：%s" % exc)
        return binary, serialize_binary(binary)
    return str(content), str(content)


def parse_message_json(data: Any) -> Any:
    """仅对文本帧尝试解析 JSON，失败时返回空。"""
    if not isinstance(data, str):
        return None
    try:
        return json.loads(data)
    except (TypeError, ValueError):
        return None


def serialize_binary(data: bytes) -> Dict[str, Any]:
    """把二进制帧转换为可存储的 Base64 描述。"""
    return {
        "encoding": "base64",
        "content": base64.b64encode(data).decode("ascii"),
        "length": len(data),
    }


def public_message(item: Dict[str, Any]) -> Dict[str, Any]:
    """移除仅供进程内计时使用的字段。"""
    result = {
        key: value
        for key, value in item.items()
        if key not in ("sent_ns", "received_ns")
    }
    result["data"] = mask_sensitive_data(result.get("data"))
    result.pop("parsed_json", None)
    return result


def mask_sensitive_data(value: Any) -> Any:
    """递归脱敏消息中常见的认证凭证字段。"""
    sensitive = {
        "token",
        "access_token",
        "authorization",
        "api_key",
        "apikey",
        "secret",
        "signature",
        "cookie",
    }
    if isinstance(value, dict):
        return {
            key: mask_secret(item) if str(key).lower() in sensitive else mask_sensitive_data(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [mask_sensitive_data(item) for item in value]
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (TypeError, ValueError):
            return value
        if isinstance(parsed, (dict, list)):
            return json.dumps(mask_sensitive_data(parsed), ensure_ascii=False)
    return value


def format_headers(headers: Dict[str, Any]) -> List[str]:
    """把请求头字典转换为 websocket-client 使用的请求头行。"""
    return ["%s: %s" % (key, value) for key, value in (headers or {}).items()]


def normalize_ws_url(url: str, context: Dict[str, Any]) -> str:
    """使用选中环境将相对地址拼接为 ws/wss 地址。"""
    value = (url or "").strip()
    if urlsplit(value).scheme:
        return value
    environment = context.get("environment") or {}
    global_vars = context.get("global_vars") or {}
    base_url = environment.get("base_url") or global_vars.get("base_url")
    if not base_url:
        return value
    full_url = urljoin(str(base_url).rstrip("/") + "/", value.lstrip("/"))
    if full_url.startswith("https://"):
        return "wss://" + full_url[len("https://"):]
    if full_url.startswith("http://"):
        return "ws://" + full_url[len("http://"):]
    return full_url


def mask_websocket_url(url: str) -> str:
    """对常见敏感 Query 参数做日志脱敏。"""
    from urllib.parse import parse_qsl
    from urllib.parse import urlencode
    from urllib.parse import urlunsplit

    parts = urlsplit(url)
    sensitive = {"token", "access_token", "authorization", "api_key", "apikey", "secret", "signature"}
    query = []
    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        query.append((key, mask_secret(value) if key.lower() in sensitive else value))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def mask_secret(value: Any) -> str:
    """保留敏感值首尾少量字符，避免日志泄露完整凭证。"""
    text = str(value or "")
    if len(text) <= 8:
        return "******"
    return "%s******%s" % (text[:4], text[-3:])


def elapsed_ms(started_ns: int) -> int:
    """根据单调高精度时钟计算毫秒耗时。"""
    return max(0, int((time.perf_counter_ns() - started_ns) / 1_000_000))


def _positive_int(value: Any, default: int) -> int:
    """把配置值转换为正整数，无效时使用默认值。"""
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return number if number > 0 else default
