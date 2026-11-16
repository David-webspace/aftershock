# aftershock — 供應鏈災害應變助理（開發中）

地震發生後，採購要在幾個小時內回答：哪些供應商廠區受影響、影響到哪些料號與訂單、對方現況如何、怎麼補救。aftershock 用真實地震的實際震度判斷影響，曝險與補救方案由程式計算，模型只負責起草信件、解析回信、解釋方案；所有對外寄信都經過人。

目前進度：
- M1 真實資料擷取（USGS 事件與 ShakeMap 震度網格、OpenStreetMap 工業區座標、匯率）與合成採購資料
- M2 影響判定（震度分級，規則見 [rules.py](api/app/impact/rules.py)）與曝險計算：每座工廠每個料件的可撐天數、預估斷料日（停工後依供應商產能分批補貨）、延誤量、受影響客戶訂單；以獨立實作的標準答案逐筆比對六起真實地震
- M3 詢問流程：每家受影響供應商一封詢問信草稿（依供應商語言的固定範本）→ 負責該料件類別的採購核准才寄出（寄到本機 Mailpit）→ 模擬供應商依實際狀況回信（完整、只說一半、含糊、不回）→ 模型解析成各廠區狀態，程式驗證（依據必須逐字出自原文、停工必須有恢復日）→ 通過的回饋到曝險計算，沒通過的交人確認 → 24 小時沒有可用回覆自動產生追問草稿資料來源與真實度界線見 [DATA_SOURCES.md](DATA_SOURCES.md)。

```bash
cp .env.example .env            # 填 POSTGRES_PASSWORD，並同步到 DATABASE_URL
docker compose up -d db mailpit   # Mailpit 網頁介面 http://localhost:8026
cd api && uv sync
set -a && . ../.env && set +a
uv run alembic upgrade head
uv run python -m app.seed.generate
uv run pytest
uv run python -m app.impact.cli hualien-2024   # 2024 花蓮 M7.4 的受影響廠區與斷料風險
```
