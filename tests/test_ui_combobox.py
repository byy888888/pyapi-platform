# -*- coding: utf-8 -*-
"""
@Author: byy
@Desc: 可搜索组合框测试，验证页面不再使用原生 datalist。
"""

import os
import unittest

from app import create_app


class UiComboboxTestCase(unittest.TestCase):
    """验证项目不再使用浏览器原生 datalist，并接入统一下拉组件。"""

    def setUp(self):
        """创建页面测试客户端。"""
        self.app = create_app("testing")
        self.client = self.app.test_client()

    def test_interface_pages_remove_native_datalist(self):
        """HTTP 和 WebSocket 接口页的模块输入不应使用原生 datalist。"""
        for path in ("/interfaces/new/http", "/interfaces/new/websocket"):
            response = self.client.get(path)
            html = response.get_data(as_text=True)
            self.assertEqual(response.status_code, 200)
            self.assertNotIn("<datalist", html)
            self.assertNotIn('list="moduleOptions"', html)
            self.assertIn('id="moduleInput"', html)
            self.assertIn('id="interfaceName"', html)
            self.assertIn('autocomplete="off"', html)

    def test_scripts_use_common_combobox_for_modules_and_headers(self):
        """模块与 Header Key 都应使用公共 AppCombobox。"""
        js_folder = os.path.join(self.app.static_folder, "js")
        with open(os.path.join(js_folder, "app_ui.js"), "r", encoding="utf-8") as file:
            app_ui = file.read()
        with open(os.path.join(js_folder, "interface_edit.js"), "r", encoding="utf-8") as file:
            interface_script = file.read()
        with open(os.path.join(js_folder, "websocket_interface_edit.js"), "r", encoding="utf-8") as file:
            websocket_script = file.read()
        with open(os.path.join(js_folder, "case_edit.js"), "r", encoding="utf-8") as file:
            case_script = file.read()

        self.assertIn("window.AppCombobox", app_ui)
        self.assertIn("disableBrowserInputHistory(document)", app_ui)
        self.assertIn("moduleCombobox = AppCombobox.attach", interface_script)
        self.assertIn("moduleCombobox = AppCombobox.attach", websocket_script)
        self.assertIn("options: AppCombobox.headerOptions", interface_script)
        self.assertIn("options: AppCombobox.headerOptions", case_script)
        self.assertNotIn("<datalist", interface_script + websocket_script + case_script)
        self.assertNotIn("headerPresets", interface_script + case_script)


if __name__ == "__main__":
    unittest.main()
