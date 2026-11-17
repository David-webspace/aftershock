import os

# 測試不啟動自動偵測的背景執行緒（會連 USGS、自動開案）
os.environ["AUTO_DETECT_MINUTES"] = "0"
