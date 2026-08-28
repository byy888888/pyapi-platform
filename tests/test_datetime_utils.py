# -*- coding: utf-8 -*-
"""
@Author: byy
@Desc: 日期时间工具测试，验证时区转换和页面格式化。
"""

import unittest
from datetime import datetime

import pytz

from app.utils.datetime_utils import format_datetime
from app.utils.datetime_utils import to_local_naive


class DatetimeUtilsTestCase(unittest.TestCase):
    """集中验证日期时间转换与格式化工具。"""
    def test_format_local_datetime_without_timezone_shift(self):
        """验证本地日期时间格式化时不会发生重复时区偏移。"""
        value = datetime(2026, 8, 3, 14, 0, 0)

        self.assertEqual(format_datetime(value), "2026-08-03 14:00:00")

    def test_to_local_naive_converts_aware_utc_time(self):
        """验证带时区的 UTC 时间可以转换为本地无时区时间。"""
        value = pytz.utc.localize(datetime(2026, 8, 3, 6, 0, 0))

        self.assertEqual(to_local_naive(value), datetime(2026, 8, 3, 14, 0, 0))


if __name__ == "__main__":
    unittest.main()
