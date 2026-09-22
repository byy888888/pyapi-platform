# -*- coding: utf-8 -*-
"""
@Author: byy
@Desc: 应用启动入口，负责创建 Flask 实例并启动本地开发服务器。
"""

from dotenv import load_dotenv

# 必须在导入 app 之前加载 .env：config.py 在模块导入阶段就会读取环境变量。
load_dotenv()

from app import create_app


app = create_app()


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=5000,
        debug=app.config.get("DEBUG", False),
        use_reloader=False,
    )
