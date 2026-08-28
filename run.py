# -*- coding: utf-8 -*-
"""
@Author: byy
@Desc: 应用启动入口，负责创建 Flask 实例并启动本地开发服务器。
"""

from app import create_app


app = create_app()


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=5000,
        debug=app.config.get("DEBUG", False),
        use_reloader=False,
    )
