"""寄出前的檢查（程式判斷，不靠模型自律）。有任何問題就不能核准寄出。"""

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Contact, Supplier

# 金額：寫給供應商的信不該出現價格（尤其是別家的報價），採購想談價格要走正式報價流程
MONEY = re.compile(r"(US\$|USD|NT\$|NTD|RMB|CNY|JPY|THB|\$|¥|￥|円|元)\s?\d|\d[\d,.]*\s?(USD|美元|美金|台幣|日圓|人民幣)", re.I)


NUMBER = re.compile(r"(?<![A-Za-z0-9-])\d[\d,]*(?![\d-])")


def internal_mailboxes() -> set[str]:
    return {f"{p.lower()}.materials@arcwell.example" for p in ("TW1", "CN1", "TH1", "VN1")} | {"engineering@arcwell.example"}


def check(db: Session, supplier_id: str | None, to_addr: str, subject: str, body: str,
          allowed_numbers: list[int] | None = None) -> list[str]:
    issues = []
    # 收件人必須是這家供應商登記的聯絡人（內部通知則必須是內部信箱），且網域在白名單內：避免寄錯對象，也避免寄到真實信箱
    registered = set(db.scalars(select(Contact.email).where(Contact.supplier_id == supplier_id))) if supplier_id else internal_mailboxes()
    if to_addr not in registered:
        issues.append("收件人不是登記的聯絡人或內部信箱")
    if not to_addr.endswith(settings.allowed_recipient_suffix):
        issues.append(f"收件網域不在允許範圍（{settings.allowed_recipient_suffix}）")
    text = f"{subject}\n{body}"
    others = [n for n in db.scalars(select(Supplier.name).where(Supplier.id != supplier_id)) if n.lower() in text.lower()]
    if others:
        issues.append(f"信中出現其他供應商名稱：{'、'.join(others)}")
    if supplier_id and MONEY.search(text):
        issues.append("信中出現金額；價格請走正式報價流程，不在應變信件中討論")
    if allowed_numbers is not None:
        # 方案信件裡的數量就是對外承諾：只能出現主管核准方案中的數字（料號、日期另外排除）
        ok = {int(n) for n in allowed_numbers}
        extra = sorted({n for n in NUMBER.findall(body) if int(n.replace(",", "")) not in ok and int(n.replace(",", "")) > 31})
        if extra:
            issues.append(f"信中出現核准方案以外的數量：{'、'.join(extra)}")
    return issues
