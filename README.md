# 接口自动化测试平台

基于 Flask 的接口自动化测试平台，面向测试、开发和质量保障人员，支持 HTTP、WebSocket、场景集合、定时任务、测试报告、通知和批量造数。页面使用 Jinja2、Bootstrap 5 和 jQuery，不需要单独安装前端工程。

第一次运行建议使用 Docker；需要修改代码时再选择本地源码运行。

## 1. 当前功能

- 仪表盘：展示项目资源，以及仅由定时任务产生的用例执行趋势和结果分布。
- 项目管理：维护项目和项目下的一级模块。
- 环境与变量：维护环境基础地址、平台全局变量和项目变量。
- 接口库：HTTP 与 WebSocket 使用独立的新增、编辑和调试页面。
- 接口用例：支持强类型断言、响应提取、JSONPath 点选和 WebSocket 全双工步骤。
- 场景集合：支持场景集合、单接口集合、步骤级请求覆盖和变量传递。
- 数据工厂：通过接口步骤和等待步骤批量、并发构造测试数据。
- 测试报告：记录完整请求响应、断言、提取和执行结果。
- 通知与任务：支持钉钉、邮件以及 interval、daily、cron 定时执行。
- 通用交互：统一确认弹窗、顶部居中 Toast 和可搜索组合框。

## 2. 技术栈

- Python 3.12（Docker 镜像、本地开发环境和依赖基线统一为 3.12）。
- Flask 3.1、Jinja2 3.1、Bootstrap 5、jQuery。
- Flask-SQLAlchemy、SQLAlchemy 1.4、Flask-Migrate、Alembic。
- MySQL 5.7，字符集 `utf8mb4`。
- APScheduler、requests、websocket-client、jsonpath-ng。
- Docker Compose、Gunicorn gthread。

> 项目已从 Python 3.8 迁移到 Python 3.12，并同步完成依赖安全升级（Flask 3.1、Werkzeug 3.1、Jinja2 3.1、requests 2.33、urllib3 2.7、gunicorn 23）。不再兼容 Python 3.8，本地虚拟环境需要按 3.12 重建。

## 3. 项目结构

```text
api_test_platform/
├── app/
│   ├── blueprints/       页面路由和业务 API
│   ├── services/         HTTP、WebSocket、断言、集合和调度服务
│   ├── static/js/        页面交互脚本
│   ├── templates/        Jinja2 页面模板
│   ├── utils/            公共工具
│   └── models.py         SQLAlchemy 数据模型
├── docs/                 功能与部署说明
├── migrations/           Alembic 数据库迁移
├── tests/                自动化测试
├── config.py             环境配置
├── run.py                应用入口
├── requirements.txt      Python 依赖
├── Dockerfile            Web 镜像
└── docker-compose.yml    Web + MySQL 编排
```

## 4. Docker 快速启动（推荐）

### 4.1 前置条件

安装 Git、Docker Desktop 或 Docker Engine，并确认 Compose V2 可用：

```bash
docker --version
docker compose version
```

### 4.2 准备配置

进入项目目录后复制配置示例。

Windows PowerShell：

```powershell
Copy-Item .env.example .env
notepad .env
```

Linux 或 macOS：

```bash
cp .env.example .env
```

至少修改以下变量，不能把示例密码用于正式环境：

```text
SECRET_KEY
MYSQL_ROOT_PASSWORD
MYSQL_PASSWORD
BASE_REPORT_URL
```

生成随机 `SECRET_KEY`：

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

如果浏览器通过 `http://192.168.1.20:5000` 访问平台，应设置：

```text
BASE_REPORT_URL=http://192.168.1.20:5000
```

否则通知中的报告链接可能仍指向 `localhost`。

### 4.3 检查并启动

```bash
docker compose config
docker compose up -d --build
docker compose ps
```

Web 容器会在启动 Gunicorn 前自动执行数据库迁移。查看日志：

```bash
docker compose logs -f web
docker compose logs -f mysql
```

启动成功后访问：

```text
http://127.0.0.1:5000
```

详细部署、更新、数据持久化和故障排查见 [Docker 部署指南](docs/Docker部署指南.md)。

## 5. Windows 本地源码运行

### 5.1 准备软件

- Python 3.12。
- MySQL 5.7。
- Git。

进入自己的项目目录，例如：

```powershell
Set-Location E:\JG_API\api_test_platform
```

### 5.2 创建虚拟环境并安装依赖

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

没有 `py` 命令时，请用 Python 3.12 的完整安装路径执行 `-m venv .venv`。

### 5.3 创建 MySQL 数据库

使用 MySQL 管理员账号执行：

```sql
CREATE DATABASE api_test_platform
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

CREATE USER 'api_user'@'localhost' IDENTIFIED BY '请替换为安全密码';
GRANT ALL PRIVILEGES ON api_test_platform.* TO 'api_user'@'localhost';
FLUSH PRIVILEGES;
```

用户已存在时，只需确认密码和授权正确，不要重复执行 `CREATE USER`。

### 5.4 设置当前终端环境变量

```powershell
$env:APP_ENV="development"
$env:SECRET_KEY="仅用于本地开发的随机字符串"
$env:DATABASE_URL="mysql+pymysql://api_user:你的密码@127.0.0.1:3306/api_test_platform?charset=utf8mb4"
$env:BASE_REPORT_URL="http://127.0.0.1:5000"
$env:ENABLE_SCHEDULER="true"
$env:SCHEDULER_TIMEZONE="Asia/Shanghai"
```

密码包含 `@`、`:`、`/`、`#`、`%` 等 URL 特殊字符时，需要先进行 URL 编码。

### 5.5 迁移并启动

```powershell
.\.venv\Scripts\python.exe -m flask --app run.py db upgrade
.\.venv\Scripts\python.exe -m flask --app run.py db heads
.\.venv\Scripts\python.exe run.py
```

当前最新迁移应为：

```text
0016_add_websocket_configuration
```

访问 `http://127.0.0.1:5000`，停止时在终端按 `Ctrl + C`。

## 6. Linux/macOS 本地源码运行

先按上一节创建 MySQL 数据库，然后执行：

```bash
python3.12 -m venv .venv
./.venv/bin/python -m pip install --upgrade pip
./.venv/bin/python -m pip install -r requirements.txt

export APP_ENV=development
export SECRET_KEY=local-development-secret
export DATABASE_URL='mysql+pymysql://api_user:password@127.0.0.1:3306/api_test_platform?charset=utf8mb4'
export BASE_REPORT_URL='http://127.0.0.1:5000'
export ENABLE_SCHEDULER=true
export SCHEDULER_TIMEZONE=Asia/Shanghai

./.venv/bin/python -m flask --app run.py db upgrade
./.venv/bin/python run.py
```

Gunicorn 不支持原生 Windows。Windows 本地开发使用 `python run.py`，Docker Linux 容器使用 Gunicorn。

## 7. 第一次使用平台

平台当前没有登录模块，打开首页后可以直接使用。推荐顺序：

1. 在“项目管理”创建项目和模块。
2. 在“环境与变量管理”创建执行环境，填写 HTTP 或 WebSocket 基础地址。
3. 按需创建平台全局变量或项目变量。
4. 在“接口库”创建 HTTP 或 WebSocket 接口并完成调试。
5. 在“接口用例”配置请求、断言和响应提取。
6. 在“场景集合”编排并执行用例，到“测试报告”查看结果。
7. 需要自动执行时，配置通知渠道并创建定时任务。
8. 需要批量构造数据时，进入“数据工厂”配置生成流程。

变量语法：

```text
环境或平台变量：{{variable_name}}
前置步骤提取变量：${variable_name}
内置生成函数：${uuid()}、${timestamp()}、${random_int(1,100)}
```

## 8. HTTP、WebSocket 与数据工厂

- HTTP 接口和用例使用 Params、Body、Headers、断言和提取器。
- 断言由后端执行强类型比较，整数 `200` 与字符串 `"200"` 不相等。
- WebSocket 支持 URL Query、握手 Header、子协议、连接后认证消息和业务心跳。
- WebSocket 用例通过发送、等待校验、等待时间和主动断开步骤描述全双工交互。
- WebSocket 页面日志通过 SSE 实时推送。
- 数据工厂支持引用接口库或自定义 URL、步骤依赖、等待步骤、生成次数和并发数。

数据工厂详细规则见 [数据工厂功能说明](docs/数据工厂功能说明.md)。

## 9. 环境变量

| 变量 | 默认值 | 说明 |
|---|---|---|
| `APP_ENV` | `development` | `development`、`production` 或 `testing` |
| `SECRET_KEY` | `dev-change-me` | Flask 签名密钥，生产必须修改 |
| `DATABASE_URL` | 本地 MySQL 地址 | SQLAlchemy 数据库连接串 |
| `BASE_REPORT_URL` | `http://localhost:5000` | 通知报告链接前缀 |
| `ENABLE_SCHEDULER` | `true` | 是否启动 APScheduler |
| `SCHEDULER_TIMEZONE` | `Asia/Shanghai` | 定时任务时区 |
| `MAIL_SERVER` | 空 | SMTP 地址 |
| `MAIL_PORT` | `465` | SMTP 端口 |
| `MAIL_USE_SSL` | `true` | 是否使用 SSL |
| `MAIL_USE_TLS` | `false` | 是否使用 STARTTLS，不能和 SSL 同时开启 |
| `MAIL_USERNAME` | 空 | SMTP 用户名 |
| `MAIL_PASSWORD` | 空 | SMTP 密码或授权码 |
| `MAIL_DEFAULT_SENDER` | 用户名 | 默认发件人 |
| `WEB_PORT` | `5000` | Docker 宿主机 Web 端口 |
| `MYSQL_PORT` | `3306` | Docker 宿主机 MySQL 端口 |
| `GUNICORN_THREADS` | `8` | Docker Web 服务线程数 |
| `GUNICORN_TIMEOUT` | `120` | Gunicorn worker 健康超时秒数 |

## 10. 测试与开发命令

Windows：

```powershell
.\.venv\Scripts\python.exe -B -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m flask --app run.py routes
.\.venv\Scripts\python.exe -m flask --app run.py db heads
```

当前完整测试基线为 81 项及以上，结果应为 `OK`。

## 11. Docker 常用命令

```bash
# 启动或更新
docker compose up -d --build

# 状态和日志
docker compose ps
docker compose logs -f web

# 手动迁移
docker compose exec web flask --app run.py db upgrade

# 停止容器但保留数据库卷
docker compose down

# 删除容器和数据库卷
docker compose down -v
```

`docker compose down -v` 会永久删除数据库，仅应在确认数据不再需要或已备份时使用。

## 12. 常见问题

### 端口被占用

修改 `.env`：

```text
WEB_PORT=5001
MYSQL_PORT=3307
BASE_REPORT_URL=http://localhost:5001
```

### 数据库连接失败

检查 MySQL 是否启动、账号密码是否一致、特殊字符是否 URL 编码。Docker 中数据库主机名是 `mysql`，本地源码运行是 `127.0.0.1`。

```bash
docker compose logs mysql
docker compose logs web
```

### 定时任务不自动执行

- 检查 `ENABLE_SCHEDULER=true`。
- 查看任务管理页顶部的 APScheduler 状态。
- Docker 必须保持一个 Gunicorn worker，不能随意增加 worker 进程数。

### WebSocket 日志中断

- 检查浏览器中 SSE `/events` 请求是否持续连接。
- 检查反向代理是否缓冲了 SSE 响应。
- Docker 应使用项目默认的 gthread 启动参数。

### 修改代码后没有变化

Docker 运行时重新构建：

```bash
docker compose up -d --build web
```

本地运行时完整停止并重新启动 Flask，项目未启用自动 reloader。

## 13. 文档

- [Docker 部署指南](docs/Docker部署指南.md)
- [数据工厂功能说明](docs/数据工厂功能说明.md)
- [环境与变量解耦存量数据清理](docs/环境变量解耦存量数据清理.md)
- [0-1 历史设计与开发基线](docs/接口自动化平台0-1开发.md)
- [技术债与升级计划](docs/技术债与升级计划.md)
- [平台对接 CI 方案](docs/平台对接CI方案.md)

## 14. 安全注意事项

- 不要提交真实 `.env`、数据库、邮件授权码、Token、Cookie 或生产数据。
- 生产环境必须修改 `SECRET_KEY` 和 MySQL 密码。
- `.env.example` 只是字段示例，不是生产配置。
- 对外提供服务时，建议配置 HTTPS、访问控制和数据库网络隔离。

