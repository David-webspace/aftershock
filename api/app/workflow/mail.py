"""寄信（SMTP 到 Mailpit）與收信（Mailpit API）。示範環境不連任何真實郵件伺服器。"""

import smtplib
from datetime import datetime
from email.message import EmailMessage
from email.utils import make_msgid

import httpx

from app.config import settings


def send(from_addr: str, to_addr: str, subject: str, body: str, in_reply_to: str | None = None) -> str:
    # 最後一道防線：就算上游檢查被繞過，非白名單網域在這裡也寄不出去
    if not to_addr.endswith(settings.allowed_recipient_suffix):
        raise ValueError(f"拒絕寄到白名單以外的網域：{to_addr}")
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = from_addr, to_addr, subject
    msg_id = make_msgid(domain=from_addr.split("@")[1])
    msg["Message-ID"] = msg_id
    if in_reply_to:
        msg["In-Reply-To"] = msg["References"] = in_reply_to
    msg.set_content(body)
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as s:
        s.send_message(msg)
    return msg_id


def inbox(mailbox: str) -> list[dict]:
    """收件匣：寄給 mailbox 的信（新到舊）。回傳 Mailpit 的 ID、收到時間、寄件人、主旨、Message-ID、In-Reply-To 與純文字內容。"""
    out = []
    with httpx.Client(base_url=settings.mailpit_api, timeout=15) as c:
        listing = c.get("/api/v1/search", params={"query": f"to:{mailbox}", "limit": 500}).raise_for_status().json()
        for m in listing.get("messages", []):
            full = c.get(f"/api/v1/message/{m['ID']}").raise_for_status().json()
            headers = c.get(f"/api/v1/message/{m['ID']}/headers").raise_for_status().json()
            out.append({"mailpit_id": m["ID"], "created": datetime.fromisoformat(m["Created"]),
                        "from": full["From"]["Address"].lower(), "subject": full["Subject"],
                        "message_id": f"<{full['MessageID']}>", "in_reply_to": (headers.get("In-Reply-To") or [None])[0],
                        "body": full.get("Text", "")})
    return out
