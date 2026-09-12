# Infrastructure 開發範圍

先讀根目錄 [AGENTS.md](../../AGENTS.md)及 [TODO](../../docs/TODO.md)。本層主要負責 DDD-03、DDD-05、DDD-07，以及 DDD-09 的評估。

- 實作 application ports，處理資料庫、檔案、OCR、Bedrock、檢索及 PDF renderer。
- 不把估價公式或規則適用性判斷搬進 adapter；具體套件不可滲入 domain／application。
- 資料遷移保留舊案件與修訂；失敗不得以清空資料重試。
- 新的模型呼叫沿用共用節流、有限重試、錯誤轉換及憑證查找鏈；整合測試使用合成資料。
- PDF 產製只消費案件與計算快照，需驗證中文、欄位及分頁；檢索必須保留來源與版本。
- 分別修改自己任務的 adapter；schema、settings、requirements 及共用快取有變更時在 PR 明確列出。
