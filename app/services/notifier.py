# -*- coding: utf-8 -*-
"""
@Author: byy
@Desc: 通知发送服务，负责组装并发送钉钉和邮件任务结果。
"""

import base64
import hashlib
import hmac
import logging
import smtplib
import time
from email.message import EmailMessage
from urllib.parse import quote_plus

import requests

from ..enums import NotificationType


logger = logging.getLogger(__name__)


def notify_task_result(notifications, task, result):
    """根据任务结果发送全部启用的通知。"""
    results = []
    for notification in notifications:
        if not notification.is_active:
            continue
        try:
            if notification.notification_type == NotificationType.DINGTALK:
                send_dingtalk_notification(notification, task, result)
            elif notification.notification_type == NotificationType.EMAIL:
                send_email_notification(notification, task, result)
            else:
                raise ValueError("不支持的通知类型: %s" % notification.notification_type)
            results.append({"notification_id": notification.id, "success": True, "message": "发送成功"})
        except Exception as exc:
            logger.exception("notification failed: %s", notification.id)
            results.append({"notification_id": notification.id, "success": False, "message": str(exc)})
    return results


def send_dingtalk_notification(notification, task, result):
    """发送钉钉 markdown 通知。"""
    config = notification.config or {}
    webhook = config.get("webhook")
    if not webhook:
        raise ValueError("钉钉 webhook 不能为空")
    webhook = _signed_dingtalk_url(webhook, config.get("secret") or config.get("token"))
    markdown = render_message(notification.message_template, task, result)
    payload = {
        "msgtype": "markdown",
        "markdown": {
            "title": "接口自动化任务执行完成",
            "text": markdown,
        },
    }
    response = requests.post(webhook, json=payload, timeout=10)
    response.raise_for_status()
    body = response.json()
    if body.get("errcode") not in (0, None):
        raise RuntimeError(body.get("errmsg") or "钉钉通知发送失败")


def send_email_notification(notification, task, result):
    """发送邮件 HTML 通知。"""
    config = notification.config or {}
    recipients = config.get("recipients") or []
    if isinstance(recipients, str):
        recipients = [item.strip() for item in recipients.replace(";", ",").split(",") if item.strip()]
    if not recipients:
        raise ValueError("邮件收件人不能为空")

    sender = config.get("sender") or config.get("mail_username")
    if not sender:
        raise ValueError("邮件发件人不能为空")
    subject = "接口自动化任务执行完成 - %s" % task.name
    text = render_message(notification.message_template, task, result)
    html = text.replace("\n", "<br>")
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = sender
    message["To"] = ", ".join(recipients)
    message.set_content(text)
    message.add_alternative(html, subtype="html")

    server = config.get("mail_server")
    port = int(config.get("mail_port") or 465)
    username = config.get("mail_username") or sender
    password = config.get("password") or ""
    use_ssl = bool(config.get("mail_use_ssl"))
    use_tls = bool(config.get("mail_use_tls"))
    if not server:
        raise ValueError("SMTP 服务不能为空")

    smtp_cls = smtplib.SMTP_SSL if use_ssl else smtplib.SMTP
    with smtp_cls(server, port, timeout=15) as smtp:
        if use_tls and not use_ssl:
            smtp.starttls()
        if username and password:
            smtp.login(username, password)
        smtp.send_message(message)


def render_message(template, task, result):
    """使用简单模板渲染通知文本。"""
    context = {
        "task_name": task.name,
        "total_count": result.get("total_count", 0),
        "success_count": result.get("success_count", 0),
        "fail_count": result.get("fail_count", 0),
        "error_count": result.get("error_count", 0),
        "report_links": "\n".join(result.get("report_links") or []),
    }
    if template:
        try:
            return template.format(**context)
        except Exception:
            logger.exception("notification template render failed")
    return (
        "### 接口自动化任务执行完成\n\n"
        "- 任务：{task_name}\n"
        "- 总数：{total_count}\n"
        "- 成功：{success_count}\n"
        "- 失败：{fail_count}\n"
        "- 错误：{error_count}\n"
        "- 报告：\n{report_links}"
    ).format(**context)


def _signed_dingtalk_url(webhook, secret):
    """配置密钥时为钉钉 webhook 追加签名参数。"""
    if not secret:
        return webhook
    timestamp = str(round(time.time() * 1000))
    string_to_sign = "%s\n%s" % (timestamp, secret)
    digest = hmac.new(
        secret.encode("utf-8"),
        string_to_sign.encode("utf-8"),
        digestmod=hashlib.sha256,
    ).digest()
    sign = quote_plus(base64.b64encode(digest))
    separator = "&" if "?" in webhook else "?"
    return "%s%stimestamp=%s&sign=%s" % (webhook, separator, timestamp, sign)
