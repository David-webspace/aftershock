"""資料表。sites 是真實工業區；其他採購資料（供應商、料件、採購單、庫存）為合成，日期一律存「相對於事件發生日 T0 的天數」，
重播哪一起真實地震，就以那起地震的日期為 T0 展開。"""

from sqlalchemy import Boolean, Float, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Site(Base):
    """真實工業區或科學園區（OpenStreetMap）。precision＝estate：座標是園區本身；city：只到所在城市。"""

    __tablename__ = "sites"
    key: Mapped[str] = mapped_column(String(24), primary_key=True)
    country: Mapped[str] = mapped_column(String(2))
    name: Mapped[str] = mapped_column(String(64))
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
