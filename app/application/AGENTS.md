# Application 開發範圍

先讀根目錄 [AGENTS.md](../../AGENTS.md)及 [TODO](../../docs/TODO.md)。本層主要負責 DDD-00、DDD-04。

- 定義 ports／輸入輸出契約，編排上傳、草稿確認、計算、保存及輸出用例。
- 依賴 domain 與本層契約，不 import infrastructure、interfaces 或外部 SDK；具體注入放在 `app/bootstrap.py`。
- 計算交給 domain；PDF 排版、向量索引、SQL 及 AWS 呼叫交給 adapter。
- 長工作前後核對案件 revision，預覽不修改案件；已保存快照是計算與 PDF 的共同依據。
- 維護 `ports.py` 的共用契約，使用替身測試確認前置條件、例外、版本衝突與無副作用預覽。
