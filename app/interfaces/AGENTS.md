# Interfaces 開發範圍

先讀根目錄 [AGENTS.md](../../AGENTS.md)及 [TODO](../../docs/TODO.md)。本層主要負責 DDD-06 的 HTTP 邊界。

- 處理請求驗證、HTTP 狀態碼、下載檔名及回應格式，業務流程委派給 application。
- 新用例透過 application ports／服務取得結果；不在路由建立 OCR、Bedrock 或 PDF SDK client。
- 匯出數字來自案件／計算快照，不在 HTML、CSV、JSON 或 PDF 回應內另算公式。
- schema 修改與 `static/`、API 測試同步；保留既有 revision 衝突與來源引用，避免洩漏 upstream 錯誤或憑證。
- 現有路由直接存取 repository 的部分可隨相關任務逐步移入 application，不為此擴大不相干任務。
