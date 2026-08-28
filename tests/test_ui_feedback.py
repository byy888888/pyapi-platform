# -*- coding: utf-8 -*-
"""
@Author: byy
@Desc: 全局确认弹窗和提示组件测试，防止重新使用浏览器原生弹窗。
"""

import re
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = PROJECT_ROOT / "app"


class UiFeedbackTestCase(unittest.TestCase):
    """验证统一弹窗与顶部居中提示的静态接入。"""

    def test_base_template_loads_global_feedback_components(self) -> None:
        """公共布局应加载全局弹窗、Toast 容器及实现脚本。"""
        base_template = (APP_ROOT / "templates" / "base.html").read_text(
            encoding="utf-8"
        )

        self.assertIn('id="appToastContainer"', base_template)
        self.assertIn('id="appDialogModal"', base_template)
        self.assertIn("modal-dialog-centered app-dialog-position", base_template)
        self.assertIn("top: -64px;", base_template)
        self.assertIn("js/app_ui.js", base_template)
        self.assertIn("left: 50%;", base_template)
        self.assertIn("transform: translateX(-50%);", base_template)

    def test_global_feedback_script_exposes_expected_api(self) -> None:
        """全局脚本应提供确认框、信息框和四类提示方法。"""
        script = (APP_ROOT / "static" / "js" / "app_ui.js").read_text(
            encoding="utf-8"
        )

        self.assertIn("window.AppDialog", script)
        self.assertIn("window.AppToast", script)
        self.assertIn("confirm: function", script)
        self.assertIn("alert: function", script)
        for feedback_type in ("success", "error", "warning", "info"):
            self.assertIn(f"{feedback_type}: function", script)

    def test_project_has_no_native_browser_dialog_calls(self) -> None:
        """业务脚本和模板不应重新使用浏览器原生弹窗。"""
        native_dialog_pattern = re.compile(
            r"(?<![\w.])(?:window\.)?(?:alert|confirm|prompt)\s*\("
        )
        occurrences = []
        for path in APP_ROOT.rglob("*"):
            if path.suffix not in {".html", ".js"}:
                continue
            content = path.read_text(encoding="utf-8")
            for match in native_dialog_pattern.finditer(content):
                line_number = content.count("\n", 0, match.start()) + 1
                occurrences.append(f"{path.relative_to(PROJECT_ROOT)}:{line_number}")

        self.assertEqual([], occurrences, "发现原生浏览器弹窗：" + ", ".join(occurrences))


if __name__ == "__main__":
    unittest.main()
