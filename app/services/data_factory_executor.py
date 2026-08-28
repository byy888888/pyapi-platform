# -*- coding: utf-8 -*-
"""
@Author: byy
@Desc: 数据工厂后台执行管理器，负责启动、取消和维护运行线程。
"""

from concurrent.futures import Future
from concurrent.futures import ThreadPoolExecutor
from threading import Lock
from typing import Dict

from flask import Flask

from .data_factory_runner import execute_factory_run


_executor = ThreadPoolExecutor(max_workers=4)
_futures: Dict[int, Future] = {}
_lock = Lock()


def submit_factory_run(app: Flask, run_id: int) -> Future:
    """把数据工厂执行提交到独立的有限后台线程池。"""
    future = _executor.submit(execute_factory_run, app, run_id)
    with _lock:
        _futures[run_id] = future
    future.add_done_callback(lambda _: _forget_future(run_id))
    return future


def _forget_future(run_id: int) -> None:
    """后台执行完成后释放 Future 引用。"""
    with _lock:
        _futures.pop(run_id, None)
