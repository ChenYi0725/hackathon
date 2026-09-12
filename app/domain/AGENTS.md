# Domain 開發範圍

先讀根目錄 [AGENTS.md](../../AGENTS.md)及 [TODO](../../docs/TODO.md)。本層主要負責 DDD-01、DDD-02，並參與 DDD-00。

- 模型、適用基準、分類、修正率、公式及捨入規則屬於本層。
- 不 import application、infrastructure、interfaces、FastAPI、SQLite、Paddle 或 AWS；計算不依賴網路、檔案或 AI 回覆。
- 依共用契約使用 Decimal、穩定標的 ID 與規則版本，保留原填數值與重算結果的差別。
- 改 `models.py` 時同時交代舊資料／JSON 相容性，通知相依任務的 application／persistence 開發者。
- 以邊界值、方向、捨入、多標的及已知來源案例驗證，不能只寫與實作完全相同的計算作為測試答案。
