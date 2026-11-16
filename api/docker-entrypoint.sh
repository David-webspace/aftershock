#!/bin/sh
set -e

alembic upgrade head

# 第一次啟動：寫入合成採購資料與示範帳號（真實地震與工業區資料已隨 repo 附上，不需要連網）
python - <<'PY'
from sqlalchemy import text
from app.auth import seed_users
from app.db import SessionLocal, engine

with engine.connect() as c:
    empty = c.execute(text("SELECT NOT EXISTS (SELECT 1 FROM suppliers)")).scalar()
if empty:
    from app.seed.generate import main
    main()
with SessionLocal() as db:
    seed_users(db)
PY

exec uvicorn app.main:app --host 0.0.0.0 --port 8000
