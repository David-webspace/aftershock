"""身分與分工。採購只處理自己負責的料件類別的供應商；主管看全部；系統管理員只看稽核，碰不到供應商往來。"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import jwt
from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.models import User
from app.security import hash_password, verify_password

COOKIE = "aftershock_session"
LOGIN_FAILED = "帳號或密碼錯誤"
# 帳號不存在時仍做一次雜湊比對，避免用回應時間差判斷帳號是否存在
_DUMMY_HASH = hash_password("timing-equalizer")
ALL_COMMODITIES = ["semiconductor", "passive", "magnetic", "pcb", "mechanical", "electromechanical"]
ROLE_LABEL = {"buyer": "採購", "manager": "供應鏈主管", "sysadmin": "系統管理員"}

DEMO_USERS = [
    ("amy.chou", "Amy Chou", "buyer", ["semiconductor", "electromechanical"]),
    ("ben.lai", "Ben Lai", "buyer", ["passive", "magnetic"]),
    ("cathy.wu", "Cathy Wu", "buyer", ["pcb", "mechanical"]),
    ("scm.manager", "Daniel Ho", "manager", ALL_COMMODITIES),
    ("sysadmin", "System Admin", "sysadmin", []),
]


@dataclass(frozen=True)
class Principal:
    username: str
    name: str
    role: str
    commodities: tuple[str, ...]

    @property
    def role_label(self) -> str:
        return ROLE_LABEL[self.role]

    def handles(self, commodity: str) -> bool:
        return commodity in self.commodities


def load_principal(db: Session, username: str) -> Principal:
    u = db.get(User, username)
    if u is None:
        raise LookupError(username)
    return Principal(u.username, u.name, u.role, tuple(u.commodities))


def authenticate(db: Session, username: str, password: str) -> str | None:
    u = db.get(User, username)
    ok = verify_password(password, u.password_hash if u and u.password_hash else _DUMMY_HASH)
    return u.username if u and u.password_hash and ok else None


def issue_token(username: str) -> str:
    now = datetime.now(UTC)
    return jwt.encode({"sub": username, "iat": now, "exp": now + timedelta(hours=settings.jwt_ttl_hours)},
                      settings.jwt_secret, algorithm="HS256")


def current_principal(request: Request, db: Session = Depends(get_db)) -> Principal:
    token = request.cookies.get(COOKIE)
    if not token:
        raise HTTPException(401, "請先登入")
    try:
        return load_principal(db, jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])["sub"])
    except (jwt.PyJWTError, LookupError):
        raise HTTPException(401, "請重新登入")


def require_role(*roles: str):
    def dep(p: Principal = Depends(current_principal)) -> Principal:
        if p.role not in roles:
            raise HTTPException(403, "沒有這個頁面的權限")
        return p
    return dep


def seed_users(db: Session) -> None:
    if not settings.seed_demo_password:
        return
    for username, name, role, commodities in DEMO_USERS:
        if db.get(User, username) is None:
            db.add(User(username=username, name=name, role=role, commodities=commodities,
                        password_hash=hash_password(settings.seed_demo_password)))
    db.commit()
