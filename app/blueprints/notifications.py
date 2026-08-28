# -*- coding: utf-8 -*-
"""
@Author: byy
@Desc: 通知管理页面与 API，负责钉钉和邮件渠道配置。
"""

from flask import Blueprint
from flask import current_app
from flask import jsonify
from flask import render_template
from flask import request

from ..enums import NotificationType
from ..extensions import db
from ..models import Notification
from ..models import TaskNotification
from ..services.pagination_service import paginate_response


notifications_bp = Blueprint("notifications", __name__, url_prefix="/notifications")
notifications_api_bp = Blueprint("notifications_api", __name__, url_prefix="/api/notification-channel")


@notifications_bp.route("/")
def index():
    """渲染通知管理页。"""
    return render_template("notifications.html")


@notifications_api_bp.route("/list", methods=["POST"])
def list_notifications():
    """返回全部通知配置。"""
    data = request.get_json(silent=True) or {}
    query = Notification.query.order_by(Notification.id.desc())
    return paginate_response(query, serialize_notification, data)


@notifications_api_bp.route("/detail", methods=["POST"])
def get_notification():
    """返回单个通知配置。"""
    data = request.get_json(silent=True) or {}
    notification_id = data.get("notification_id")
    if not notification_id:
        return jsonify({"success": False, "message": "通知 ID 不能为空"}), 400
    notification = db.get_or_404(Notification, notification_id)
    return jsonify({"success": True, "data": serialize_notification(notification)})


@notifications_api_bp.route("/create", methods=["POST"])
def create_notification():
    """创建通知配置。"""
    try:
        notification, error = build_notification(Notification(), request.get_json(silent=True) or {})
        if error:
            return jsonify({"success": False, "message": error}), 400
        db.session.add(notification)
        db.session.commit()
        return jsonify({"success": True, "data": serialize_notification(notification)})
    except Exception as exc:
        db.session.rollback()
        current_app.logger.exception("create notification failed")
        return jsonify({"success": False, "message": "通知保存失败: %s" % exc}), 500


@notifications_api_bp.route("/save", methods=["POST"])
def update_notification():
    """更新通知配置。"""
    try:
        data = request.get_json(silent=True) or {}
        notification_id = data.get("notification_id")
        if not notification_id:
            return jsonify({"success": False, "message": "通知 ID 不能为空"}), 400
        notification = db.get_or_404(Notification, notification_id)
        notification, error = build_notification(notification, data)
        if error:
            return jsonify({"success": False, "message": error}), 400
        db.session.commit()
        return jsonify({"success": True, "data": serialize_notification(notification)})
    except Exception as exc:
        db.session.rollback()
        current_app.logger.exception("update notification failed")
        return jsonify({"success": False, "message": "通知保存失败: %s" % exc}), 500


@notifications_api_bp.route("/delete", methods=["POST"])
def delete_notification():
    """删除通知配置。"""
    data = request.get_json(silent=True) or {}
    notification_id = data.get("notification_id")
    if not notification_id:
        return jsonify({"success": False, "message": "通知 ID 不能为空"}), 400
    notification = db.get_or_404(Notification, notification_id)
    TaskNotification.query.filter_by(notification_id=notification.id).delete()
    db.session.delete(notification)
    db.session.commit()
    return jsonify({"success": True})


def build_notification(notification, data):
    """根据 JSON 数据填充通知配置字段。"""
    name = (data.get("name") or "").strip()
    notification_type = data.get("notification_type") or NotificationType.DINGTALK
    if not name:
        return notification, "通知名称不能为空"
    if notification_type not in NotificationType.VALUES:
        return notification, "通知类型不支持"
    config, config_error = normalize_config(notification_type, data.get("config") or {})
    if config_error:
        return notification, config_error
    if notification_type == NotificationType.DINGTALK and not config.get("webhook"):
        return notification, "钉钉 webhook 不能为空"
    if notification_type == NotificationType.DINGTALK and not config.get("webhook").startswith(("http://", "https://")):
        return notification, "钉钉 webhook 必须以 http:// 或 https:// 开头"
    if notification_type == NotificationType.EMAIL and not config.get("recipients"):
        return notification, "邮件收件人不能为空"
    config = preserve_masked_secret(notification, config)

    notification.name = name
    notification.notification_type = notification_type
    notification.config = config
    notification.message_template = data.get("message_template") or ""
    notification.is_active = parse_bool(data.get("is_active"), True)
    return notification, None


def normalize_config(notification_type, config):
    """规范化页面或 API 直接提交的通知配置。"""
    config = dict(config or {})
    if notification_type == NotificationType.DINGTALK:
        return {
            "webhook": (config.get("webhook") or "").strip(),
            "secret": (config.get("secret") or config.get("token") or "").strip(),
        }, None

    recipients = config.get("recipients") or []
    if isinstance(recipients, str):
        recipients = recipients.replace("，", ",").split(",")
    recipients = [item.strip() for item in recipients if str(item).strip()]
    try:
        mail_port = int(config.get("mail_port") or 465)
    except (TypeError, ValueError):
        return {}, "邮件端口必须是数字"
    return {
        "mail_server": (config.get("mail_server") or "").strip(),
        "mail_port": mail_port,
        "mail_use_ssl": parse_bool(config.get("mail_use_ssl"), True),
        "mail_use_tls": parse_bool(config.get("mail_use_tls"), False),
        "sender": (config.get("sender") or "").strip(),
        "mail_username": (config.get("mail_username") or "").strip(),
        "password": config.get("password") or "",
        "recipients": recipients,
    }, None


def serialize_notification(notification):
    """序列化通知配置。"""
    config = dict(notification.config or {})
    if config.get("password"):
        config["password"] = "******"
    if config.get("secret"):
        config["secret"] = "******"
    safe_raw_config = dict(config)
    return {
        "id": notification.id,
        "name": notification.name,
        "notification_type": notification.notification_type,
        "config": config,
        "raw_config": safe_raw_config,
        "message_template": notification.message_template or "",
        "is_active": notification.is_active,
        "created_at": format_datetime(notification.created_at),
        "updated_at": format_datetime(notification.updated_at),
    }


def preserve_masked_secret(notification, config):
    """提交脱敏占位符时保留原有敏感值。"""
    old_config = notification.config or {}
    config = dict(config or {})
    for key in ("password", "secret"):
        if config.get(key) == "******" and old_config.get(key):
            config[key] = old_config.get(key)
    return config


def parse_bool(value, default=False):
    """解析 JSON 中类似布尔值的字段。"""
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).lower() in ("1", "true", "yes", "on")


def format_datetime(value):
    """格式化页面展示时间。"""
    from ..utils.datetime_utils import format_datetime as format_local_datetime

    return format_local_datetime(value)
