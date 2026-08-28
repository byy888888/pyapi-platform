# -*- coding: utf-8 -*-
"""
@Author: byy
@Desc: 内置数据生成函数，提供 UUID、时间戳、随机字符串和手机号等测试数据。
"""

import base64
import random
import string
import time
import uuid
from typing import Any
from typing import Dict
from typing import List

import rsa


class HookFunctionError(Exception):
    """钩子函数执行失败时抛出的异常。"""


HOOK_FUNCTIONS = {
    "setrsa": {
        "name": "setrsa",
        "title": "RSA 公钥加密",
        "description": "使用 RSA 公钥加密明文，返回 base64 编码后的密文。",
        "params": [
            {"name": "pwd", "description": "需要加密的明文"},
            {"name": "pubkey", "description": "RSA 公钥内容，可来自变量或提取器"},
        ],
        "usage": "${setrsa('BeiMing_admin','${pubkey}')}",
        "example": {
            "userName": "admin",
            "userPwd": "${setrsa('BeiMing_admin','${pubkey}')}",
            "publicKey": "${pubkey}",
        },
        "supported_locations": [
            "URL",
            "Params",
            "Headers",
            "Body",
            "WebSocket 发送消息",
            "WebSocket 接收断言",
        ],
    },
    "uuid": {
        "name": "uuid",
        "title": "UUID",
        "description": "生成不带连字符的 UUID。",
        "params": [],
        "usage": "${uuid()}",
        "example": "${uuid()}",
        "supported_locations": ["URL", "Params", "Headers", "Body"],
    },
    "timestamp": {
        "name": "timestamp",
        "title": "毫秒时间戳",
        "description": "生成当前毫秒时间戳。",
        "params": [],
        "usage": "${timestamp()}",
        "example": "${timestamp()}",
        "supported_locations": ["URL", "Params", "Headers", "Body"],
    },
    "random_int": {
        "name": "random_int",
        "title": "随机整数",
        "description": "生成指定闭区间内的随机整数。",
        "params": [{"name": "min"}, {"name": "max"}],
        "usage": "${random_int(1000,9999)}",
        "example": "${random_int(1000,9999)}",
        "supported_locations": ["URL", "Params", "Headers", "Body"],
    },
    "random_string": {
        "name": "random_string",
        "title": "随机字符串",
        "description": "生成指定长度的字母数字字符串。",
        "params": [{"name": "length"}],
        "usage": "${random_string(12)}",
        "example": "${random_string(12)}",
        "supported_locations": ["URL", "Params", "Headers", "Body"],
    },
    "random_mobile": {
        "name": "random_mobile",
        "title": "随机手机号",
        "description": "生成用于测试的 11 位手机号格式字符串。",
        "params": [],
        "usage": "${random_mobile()}",
        "example": "${random_mobile()}",
        "supported_locations": ["URL", "Params", "Headers", "Body"],
    },
}


def list_hook_functions() -> List[Dict[str, Any]]:
    """返回平台预置钩子函数说明。"""
    return [HOOK_FUNCTIONS[name] for name in sorted(HOOK_FUNCTIONS.keys())]


def execute_hook_function(name: str, args: List[Any]) -> Any:
    """根据函数名执行预置钩子函数。"""
    if name == "setrsa":
        return setrsa(*args)
    if name == "uuid":
        return uuid.uuid4().hex
    if name == "timestamp":
        return int(time.time() * 1000)
    if name == "random_int":
        return random_int(*args)
    if name == "random_string":
        return random_string(*args)
    if name == "random_mobile":
        return random_mobile()
    raise HookFunctionError("不支持的钩子函数: %s" % name)


def setrsa(pwd: Any, pubkey: Any = None) -> str:
    """使用 RSA 公钥加密明文并返回 base64 字符串。"""
    if pwd is None or pwd == "":
        raise HookFunctionError("setrsa 参数 pwd 不能为空")
    if not pubkey:
        raise HookFunctionError("setrsa 参数 pubkey 不能为空")

    public_key = normalize_public_key(pubkey)
    try:
        pub_key = load_public_key(public_key)
        crypto = rsa.encrypt(str(pwd).encode("utf-8"), pub_key)
    except Exception as exc:
        raise HookFunctionError("setrsa 执行失败: %s" % exc)
    return base64.b64encode(crypto).decode("utf-8")


def random_int(minimum: Any, maximum: Any) -> int:
    """生成指定闭区间内的随机整数。"""
    return random.randint(int(minimum), int(maximum))


def random_string(length: Any) -> str:
    """生成指定长度的字母数字随机字符串。"""
    size = int(length)
    if size < 1 or size > 1024:
        raise HookFunctionError("random_string 长度必须在 1 到 1024 之间")
    alphabet = string.ascii_letters + string.digits
    return "".join(random.choice(alphabet) for _ in range(size))


def random_mobile() -> str:
    """生成用于测试的中国大陆手机号格式字符串。"""
    return "1%s%s" % (random.choice("3456789"), random.randint(100000000, 999999999))


def normalize_public_key(pubkey: Any) -> str:
    """把接口返回的公钥内容规范为 PEM 格式。"""
    text = str(pubkey or "").strip()
    if "BEGIN PUBLIC KEY" in text or "BEGIN RSA PUBLIC KEY" in text:
        return text
    compact = "".join(text.split())
    return "-----BEGIN PUBLIC KEY-----\n%s\n-----END PUBLIC KEY-----" % compact


def load_public_key(public_key: str) -> rsa.PublicKey:
    """加载 OpenSSL 或 PKCS#1 PEM 公钥。"""
    encoded = public_key.encode("utf-8")
    try:
        return rsa.PublicKey.load_pkcs1_openssl_pem(encoded)
    except ValueError:
        return rsa.PublicKey.load_pkcs1(encoded)
