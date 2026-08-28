# Docker 部署指南

本文说明如何使用 Docker Compose 部署接口自动化测试平台。部署包含一个 Flask/Gunicorn Web 容器和一个 MySQL 5.7 容器。

## 1. 部署结构

```text
浏览器
  ↓ HTTP / SSE
Gunicorn gthread（1 个 worker，多个线程）
  ↓
Flask + APScheduler + WebSocket 调试会话
  ↓
MySQL 5.7 数据卷
```

APScheduler 和 WebSocket 调试会话保存在 Web 进程内，因此必须保持一个 Gunicorn worker。多个线程用于同时处理普通 HTTP 请求和 SSE 实时日志连接。

## 2. 前置要求

- Docker Engine 或 Docker Desktop。
- Docker Compose V2。
- 能够访问 Python 和 MySQL 镜像仓库。

```bash
docker --version
docker compose version
```

如果系统只能使用旧的 `docker-compose` 命令，建议升级 Compose V2。

## 3. 准备环境变量

Linux/macOS：

```bash
cp .env.example .env
```

Windows PowerShell：

```powershell
Copy-Item .env.example .env
```

至少修改：

```text
SECRET_KEY
MYSQL_ROOT_PASSWORD
MYSQL_PASSWORD
BASE_REPORT_URL
```

注意：

- 生产环境必须使用随机 `SECRET_KEY` 和强密码。
- Compose 默认根据 `MYSQL_USER`、`MYSQL_PASSWORD` 和 `MYSQL_DATABASE` 生成数据库连接。
- 显式设置 `DATABASE_URL` 时，该值优先于自动生成的地址。
- 显式连接串中的特殊字符密码必须进行 URL 编码。
- `BASE_REPORT_URL` 必须是浏览器真正能访问的平台地址。
- `.env` 已被 Git 和 Docker 构建上下文忽略，不能提交仓库。

检查变量和最终配置：

```bash
docker compose config --environment
docker compose config
```

以上输出可能包含密码，不要粘贴到公开聊天、日志或 Issue。

## 4. 首次启动

```bash
docker compose up -d --build
```

启动顺序：

1. 创建 MySQL 数据卷并启动 MySQL。
2. 等待 MySQL 健康检查通过。
3. 构建并启动 Web 容器。
4. Web 容器执行 `flask --app run.py db upgrade`。
5. 迁移成功后启动 Gunicorn。

检查状态和日志：

```bash
docker compose ps
docker compose logs -f mysql
docker compose logs -f web
```

默认访问地址：

```text
http://127.0.0.1:5000
```

## 5. 健康检查

MySQL 健康检查确认数据库能够接受连接。Web 健康检查访问平台首页，同时验证 Gunicorn、Flask、数据库和迁移状态。

两个服务均应在 `docker compose ps` 中显示为 `healthy`。如果长时间处于 `starting` 或变成 `unhealthy`：

```bash
docker compose logs --tail=200 mysql
docker compose logs --tail=200 web
```

## 6. 更新部署

```bash
git pull --ff-only
docker compose up -d --build
docker compose ps
```

Web 容器重建时会再次检查数据库迁移，Alembic 只执行尚未应用的迁移。

```bash
docker compose exec web flask --app run.py db heads
docker compose exec web flask --app run.py db upgrade
```

## 7. 重启与停止

```bash
# 仅重启 Web
docker compose restart web

# 重启全部服务
docker compose restart

# 删除容器但保留 MySQL 数据卷
docker compose down

# 删除容器和 MySQL 数据卷
docker compose down -v
```

`down -v` 会永久删除数据库。除非确认数据不再需要或已经备份，否则不要执行。

## 8. 数据持久化

MySQL 数据保存在 Compose 命名卷 `mysql_data`。重建 Web 容器和执行普通 `docker compose down` 都不会删除数据库。

```bash
docker volume ls
```

正式升级、迁移服务器或删除数据卷前，应使用团队认可的 MySQL 备份方案完成备份，并实际验证备份能够恢复。

## 9. 修改端口

如果宿主机的 5000 或 3306 被占用，修改 `.env`：

```text
WEB_PORT=5001
MYSQL_PORT=3307
BASE_REPORT_URL=http://服务器地址:5001
```

容器内部仍使用 Web 5000 和 MySQL 3306，不需要改 Compose 文件。

## 10. Gunicorn 参数

```text
GUNICORN_THREADS=8
GUNICORN_TIMEOUT=120
```

- worker 数固定为 1，保证 APScheduler 和进程内 WebSocket 调试会话只有一份。
- `GUNICORN_THREADS` 控制同一进程可并行处理的请求数量。
- SSE 连接或并发用户较多时，可以结合服务器资源增加线程数。
- `GUNICORN_TIMEOUT` 是 worker 健康超时，不是接口用例自身的请求超时。

修改后执行：

```bash
docker compose up -d --build web
```

## 11. 邮件配置

SSL 示例：

```text
MAIL_PORT=465
MAIL_USE_SSL=true
MAIL_USE_TLS=false
```

STARTTLS 示例：

```text
MAIL_PORT=587
MAIL_USE_SSL=false
MAIL_USE_TLS=true
```

SSL 和 TLS 不要同时开启。部分邮箱必须使用 SMTP 授权码，而不是登录密码。

## 12. 常见故障

### MySQL 一直不健康

- 查看 `docker compose logs mysql`。
- 检查磁盘空间和 `.env` 密码。
- 检查数据库卷是否来自不兼容的 MySQL 版本。

### Web 容器不断重启

- 查看 `docker compose logs web`。
- 检查数据库账号、密码和数据库名。
- 检查迁移或 Python 依赖安装异常。

### 修改代码没有生效

```bash
docker compose up -d --build web
```

需要完全忽略构建缓存时：

```bash
docker compose build --no-cache web
docker compose up -d web
```

### SSE 或 WebSocket 日志异常

- 确认使用项目默认的 `gthread` 启动命令。
- 不要把 Gunicorn worker 数增加到 2 个及以上。
- 反向代理需要关闭 SSE 路由的响应缓冲并延长读取超时。
- 检查浏览器中 `/events` 请求是否持续连接。

## 13. 生产环境建议

- 不对公网暴露 MySQL；生产环境可删除 MySQL 的 `ports` 映射。
- 在 Web 前增加 HTTPS 反向代理。
- 当前版本没有登录和权限控制，应限制平台访问来源。
- 定期备份 MySQL 并验证恢复流程。
- 不提交 `.env`、数据库、Token、Cookie 或生产响应数据。

