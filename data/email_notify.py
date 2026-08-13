# data/email_notify.py
"""邮件通知 — QQ 邮箱 SMTP 发送（最佳努力，失败静默记录日志）。

凭据通过 config.SMTP_* 从 .env 读取，绝不硬编码；未配置时直接跳过发送。
邮件是「加分通知渠道」，永远不是硬依赖 —— 任何失败只记录日志、返回 False，
不影响主流程。
"""
import logging
import smtplib
from email.header import Header
from email.mime.text import MIMEText

from config import SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS, SMTP_TO

_log = logging.getLogger(__name__)


def is_configured() -> bool:
    """SMTP 是否可用（同时具备账号与授权码）。"""
    return bool(SMTP_USER and SMTP_PASS)


def send_email(subject: str, body: str, to: str = "") -> bool:
    """通过 QQ SMTP 发送一封纯文本邮件。成功返回 True。

    Args:
        subject: 邮件主题
        body: 纯文本正文
        to: 收件人；留空则用 config.SMTP_TO，再留空则发给自己（SMTP_USER）
    """
    if not is_configured():
        _log.debug("SMTP not configured, skipping email notification")
        return False
    recipient = to or SMTP_TO or SMTP_USER
    try:
        msg = MIMEText(body, "plain", "utf-8")
        msg["Subject"] = Header(subject, "utf-8")
        msg["From"] = SMTP_USER
        msg["To"] = recipient
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=10) as server:
            server.login(SMTP_USER, SMTP_PASS)
            server.sendmail(SMTP_USER, [recipient], msg.as_string())
        _log.info("Email sent to %s (subject=%r)", recipient, subject)
        return True
    except Exception:
        _log.warning("Email send failed (subject=%r)", subject, exc_info=True)
        return False
