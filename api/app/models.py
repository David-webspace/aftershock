"""資料表。sites 是真實工業區；其他採購資料（供應商、料件、採購單、庫存）為合成，日期一律存「相對於事件發生日 T0 的天數」，
重播哪一起真實地震，就以那起地震的日期為 T0 展開。"""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Site(Base):
    """真實工業區或科學園區（OpenStreetMap）。precision＝estate：座標是園區本身；city：只到所在城市。"""

    __tablename__ = "sites"
    key: Mapped[str] = mapped_column(String(24), primary_key=True)
    country: Mapped[str] = mapped_column(String(2))
    name: Mapped[str] = mapped_column(String(64))
    name_en: Mapped[str] = mapped_column(String(160), default="", server_default="")
    lat: Mapped[float] = mapped_column(Float)
    lon: Mapped[float] = mapped_column(Float)
    precision: Mapped[str] = mapped_column(String(8))
    osm: Mapped[str] = mapped_column(String(32))


class Plant(Base):
    __tablename__ = "plants"
    key: Mapped[str] = mapped_column(String(8), primary_key=True)
    site_key: Mapped[str] = mapped_column(ForeignKey("sites.key"))
    name: Mapped[str] = mapped_column(String(32))


class Supplier(Base):
    __tablename__ = "suppliers"
    id: Mapped[str] = mapped_column(String(8), primary_key=True)
    name: Mapped[str] = mapped_column(String(64))
    country: Mapped[str] = mapped_column(String(2))
    commodity: Mapped[str] = mapped_column(String(24), index=True)
    currency: Mapped[str] = mapped_column(String(3))
    language: Mapped[str] = mapped_column(String(8))


class SupplierSite(Base):
    __tablename__ = "supplier_sites"
    id: Mapped[str] = mapped_column(String(12), primary_key=True)
    supplier_id: Mapped[str] = mapped_column(ForeignKey("suppliers.id"), index=True)
    site_key: Mapped[str] = mapped_column(ForeignKey("sites.key"), index=True)


class Contact(Base):
    __tablename__ = "contacts"
    id: Mapped[int] = mapped_column(primary_key=True)
    supplier_id: Mapped[str] = mapped_column(ForeignKey("suppliers.id"), index=True)
    name: Mapped[str] = mapped_column(String(64))
    email: Mapped[str] = mapped_column(String(128))  # 一律是保留網域 .example，不會寄到真實信箱
    title: Mapped[str] = mapped_column(String(32))


class Part(Base):
    __tablename__ = "parts"
    part_no: Mapped[str] = mapped_column(String(24), primary_key=True)
    family: Mapped[str] = mapped_column(String(32))
    category: Mapped[str] = mapped_column(String(32))
    commodity: Mapped[str] = mapped_column(String(24), index=True)
    spec: Mapped[str] = mapped_column(String(96))


class Sourcing(Base):
    """料件的合格來源（某供應商的某個廠區）。qualified＝False 是尚未完成認證的備援來源。"""

    __tablename__ = "sourcing"
    id: Mapped[int] = mapped_column(primary_key=True)
    part_no: Mapped[str] = mapped_column(ForeignKey("parts.part_no"), index=True)
    supplier_site_id: Mapped[str] = mapped_column(ForeignKey("supplier_sites.id"), index=True)
    qualified: Mapped[bool] = mapped_column(Boolean)
    share_pct: Mapped[int] = mapped_column(Integer)  # 正常情況下的訂單分配比例
    lead_days: Mapped[int] = mapped_column(Integer)
    moq: Mapped[int] = mapped_column(Integer)
    price_usd: Mapped[float] = mapped_column(Numeric(12, 5))
    weekly_capacity: Mapped[int] = mapped_column(Integer)  # 可分配給我們的週產能


class Product(Base):
    __tablename__ = "products"
    model: Mapped[str] = mapped_column(String(24), primary_key=True)
    name: Mapped[str] = mapped_column(String(64))


class BomLine(Base):
    __tablename__ = "bom"
    model: Mapped[str] = mapped_column(ForeignKey("products.model"), primary_key=True)
    part_no: Mapped[str] = mapped_column(ForeignKey("parts.part_no"), primary_key=True)
    qty: Mapped[int] = mapped_column(Integer)


class PlantProduct(Base):
    __tablename__ = "plant_products"
    plant: Mapped[str] = mapped_column(ForeignKey("plants.key"), primary_key=True)
    model: Mapped[str] = mapped_column(ForeignKey("products.model"), primary_key=True)
    weekly_demand: Mapped[int] = mapped_column(Integer)


class Inventory(Base):
    __tablename__ = "inventory"
    plant: Mapped[str] = mapped_column(ForeignKey("plants.key"), primary_key=True)
    part_no: Mapped[str] = mapped_column(ForeignKey("parts.part_no"), primary_key=True)
    on_hand: Mapped[int] = mapped_column(Integer)


class PurchaseOrder(Base):
    """未結採購單。order_day／due_day 為相對 T0 的天數；shipped＝已出貨在途。"""

    __tablename__ = "purchase_orders"
    po_no: Mapped[str] = mapped_column(String(16), primary_key=True)
    plant: Mapped[str] = mapped_column(ForeignKey("plants.key"), index=True)
    sourcing_id: Mapped[int] = mapped_column(ForeignKey("sourcing.id"), index=True)
    qty: Mapped[int] = mapped_column(Integer)
    order_day: Mapped[int] = mapped_column(Integer)
    due_day: Mapped[int] = mapped_column(Integer)
    mode: Mapped[str] = mapped_column(String(8))  # truck／sea／air
    transit_days: Mapped[int] = mapped_column(Integer)
    shipped: Mapped[bool] = mapped_column(Boolean)


class CustomerOrder(Base):
    __tablename__ = "customer_orders"
    id: Mapped[int] = mapped_column(primary_key=True)
    plant: Mapped[str] = mapped_column(ForeignKey("plants.key"), index=True)
    model: Mapped[str] = mapped_column(ForeignKey("products.model"))
    customer: Mapped[str] = mapped_column(String(16))
    qty: Mapped[int] = mapped_column(Integer)
    due_day: Mapped[int] = mapped_column(Integer)
    note: Mapped[str | None] = mapped_column(Text)


# ── 應變流程 ───────────────────────────────────────────────


class User(Base):
    """採購（依負責的料件類別分工）、主管（全部）、系統管理員（只看稽核）。"""

    __tablename__ = "users"
    username: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(32))
    role: Mapped[str] = mapped_column(String(16))  # buyer／manager／sysadmin
    commodities: Mapped[list] = mapped_column(JSONB)
    password_hash: Mapped[str | None] = mapped_column(String(255))


class Incident(Base):
    """一起地震的應變案。sim_hours 是示範用的事件時鐘（T0 之後經過幾小時），由畫面推進，供應商回信依此時鐘抵達。"""

    __tablename__ = "incidents"
    id: Mapped[int] = mapped_column(primary_key=True)
    scenario_key: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_by: Mapped[str] = mapped_column(ForeignKey("users.username"))
    sim_hours: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(12), default="open")


class SiteStatus(Base):
    """某供應商在某廠區的現況。state：pending（尚未詢問）→ inquired → replied／needs_review → confirmed；no_reply 為逾時未回。
    resume_day：預計恢復出貨日（相對 T0 天數），確認後覆寫曝險計算的規劃停工天數。"""

    __tablename__ = "site_status"
    id: Mapped[int] = mapped_column(primary_key=True)
    incident_id: Mapped[int] = mapped_column(ForeignKey("incidents.id", ondelete="CASCADE"), index=True)
    supplier_id: Mapped[str] = mapped_column(ForeignKey("suppliers.id"))
    site_key: Mapped[str] = mapped_column(ForeignKey("sites.key"))
    level: Mapped[str] = mapped_column(String(24))
    mmi: Mapped[float | None] = mapped_column(Float)
    state: Mapped[str] = mapped_column(String(16), default="pending")
    operating: Mapped[str] = mapped_column(String(12), default="unknown")  # normal／partial／stopped／unknown
    capacity_pct: Mapped[int | None] = mapped_column(Integer)
    resume_day: Mapped[int | None] = mapped_column(Integer)
    damage: Mapped[str | None] = mapped_column(Text)
    confirmed_by: Mapped[str | None] = mapped_column(String(32))
    source_message_id: Mapped[int | None] = mapped_column(Integer)


class Message(Base):
    """往來信件。寄出的信：draft → approved → sent（或 rejected）；收到的信：received → parsed／needs_review。
    token 寫在主旨（[AS-案號-供應商]），回信靠它與 In-Reply-To 對回原詢問。"""

    __tablename__ = "messages"
    id: Mapped[int] = mapped_column(primary_key=True)
    incident_id: Mapped[int] = mapped_column(ForeignKey("incidents.id", ondelete="CASCADE"), index=True)
    supplier_id: Mapped[str] = mapped_column(ForeignKey("suppliers.id"), index=True)
    direction: Mapped[str] = mapped_column(String(4))  # out／in
    kind: Mapped[str] = mapped_column(String(12))  # inquiry／follow_up／reply
    status: Mapped[str] = mapped_column(String(16))
    from_addr: Mapped[str] = mapped_column(String(128))
    to_addr: Mapped[str] = mapped_column(String(128))
    subject: Mapped[str] = mapped_column(String(256))
    body: Mapped[str] = mapped_column(Text)
    language: Mapped[str] = mapped_column(String(8))
    token: Mapped[str] = mapped_column(String(32), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    sim_hour: Mapped[int] = mapped_column(Integer, default=0)
    created_by: Mapped[str | None] = mapped_column(String(32))
    approved_by: Mapped[str | None] = mapped_column(String(32))
    smtp_message_id: Mapped[str | None] = mapped_column(String(128), index=True)
    in_reply_to: Mapped[str | None] = mapped_column(String(128))
    mailpit_id: Mapped[str | None] = mapped_column(String(64), unique=True)
    guard_issues: Mapped[list | None] = mapped_column(JSONB)
    parsed: Mapped[dict | None] = mapped_column(JSONB)
    parse_note: Mapped[str | None] = mapped_column(Text)


class Truth(Base):
    """模擬用的「實際狀況」：只給回信模擬器與評測使用，API 與模型都讀不到。"""

    __tablename__ = "sim_truth"
    incident_id: Mapped[int] = mapped_column(ForeignKey("incidents.id", ondelete="CASCADE"), primary_key=True)
    supplier_id: Mapped[str] = mapped_column(ForeignKey("suppliers.id"), primary_key=True)
    site_key: Mapped[str] = mapped_column(ForeignKey("sites.key"), primary_key=True)
    operating: Mapped[str] = mapped_column(String(12))
    capacity_pct: Mapped[int] = mapped_column(Integer)
    resume_day: Mapped[int] = mapped_column(Integer)
    damage: Mapped[str] = mapped_column(Text)


class SimReply(Base):
    """排定的模擬回信：某供應商在事件時鐘第幾小時回覆哪一封信；style 決定措辭（完整、部分、含糊、延遲）。"""

    __tablename__ = "sim_replies"
    id: Mapped[int] = mapped_column(primary_key=True)
    incident_id: Mapped[int] = mapped_column(ForeignKey("incidents.id", ondelete="CASCADE"), index=True)
    supplier_id: Mapped[str] = mapped_column(ForeignKey("suppliers.id"))
    reply_to_message_id: Mapped[int] = mapped_column(ForeignKey("messages.id", ondelete="CASCADE"))
    due_hour: Mapped[int] = mapped_column(Integer)
    style: Mapped[str] = mapped_column(String(12))
    delivered: Mapped[bool] = mapped_column(Boolean, default=False)


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    username: Mapped[str | None] = mapped_column(String(32))
    event: Mapped[str] = mapped_column(String(32))
    incident_id: Mapped[int | None] = mapped_column(Integer)
    detail: Mapped[dict | None] = mapped_column(JSONB)
