"""補救方案的成本與時間假設。全部是擬真假設（不是實測），集中在這裡，方案說明會照實標註。

調整任何一項，三種方案都會重算；評測也只驗證「在這組假設下，求解器的解是可行且最佳的」。
"""

# 成品出貨單價（美元）：缺料時的損失依此估算
PRODUCT_VALUE_USD = {"ARC-PSU1K2-TP": 180, "ARC-PSU2K4-TP": 320, "ARC-PSU3K0-54": 520, "ARC-ADP100-GAN": 28, "ARC-ADP240-GAN": 55}
MARGIN = 0.3  # 少做一台成品損失的毛利比例

# 向未受影響的合格來源追加訂單：從其剩餘週產能出貨，下單後約 7 天可出貨
EXTRA_ORDER_PREP_DAYS = 7
EXTRA_HANDLING_RATE = 0.02  # 追加訂單的處理與多餘庫存成本：單價的 2%，避免「同價就隨便多買」
AIR_TRANSIT_DAYS = 3
AIR_PREMIUM_RATE = 0.25  # 改空運：每個料件多付單價的 25%（電子料件體積小，實務上常見的量級）
AIR_PREMIUM_MIN_USD = 0.01

# 工廠間調撥庫存：空運或陸運，約 4 天到；成本為單價的 5%（運費、報關、處理）
TRANSFER_DAYS = 4
TRANSFER_RATE = 0.05
TRANSFER_KEEP_DAYS = 7  # 調出的工廠至少保留 7 天用量，不為了救別廠把自己掏空

# 啟用尚未認證的備援來源：工程認證約 21 天，一次性成本 15,000 美元，之後依其交期與產能供貨
QUALIFICATION_DAYS = 21
QUALIFICATION_COST_USD = 15000

# 「最少缺料」方案的缺料懲罰倍數：願意花更多錢換取不缺料
MIN_SHORTAGE_PENALTY_MULTIPLIER = 50
