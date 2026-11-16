"""寄出前的檢查（程式判斷，不靠模型自律）。有任何問題就不能核准寄出。"""

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Contact, Supplier

# 金額：寫給供應商的信不該出現價格（尤其是別家的報價），採購想談價格要走正式報價流程
MONEY = re.compile(r"(US\$|USD|NT\$|NTD|RMB|CNY|JPY|THB|\$|¥|￥|円|元)\s?\d|\d[\d,.]*\s?(USD|美元|美金|台幣|日圓|人民幣)", re.I)


def check(db: Session, supplier_id: str, to_addr: str, subject: str, body: str) -> list[str]:
    issues = []
    # 收件人必須是這家供應商登記的聯絡人，且網域在白名單內：避免寄錯對象，也避免示範環境寄到真實信箱
    registered = set(db.scalars(select(Contact.email).where(Contact.supplier_id == supplier_id)))
    if to_addr not in registered:
        issues.append("收件人不是這家供應商登記的聯絡人")
    if not to_addr.endswith(settings.allowed_recipient_suffix):
        issues.append(f"收件網域不在允許範圍（{settings.allowed_recipient_suffix}）")
    text = f"{subject}\n{body}"
    others = [n for n in db.scalars(select(Supplier.name).where(Supplier.id != supplier_id)) if n.lower() in text.lower()]
    if others:
        issues.append(f"信中出現其他供應商名稱：{'、'.join(others)}")
    if MONEY.search(text):
        issues.append("信中出現金額；價格請走正式報價流程，不在應變詢問信中討論")
    return issues
