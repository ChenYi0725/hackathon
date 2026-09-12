# 基準上傳修復驗收（DDD-06）

本次範圍為 `static/` 的基準上傳與確認介面、`e2e/` 回歸及 README 操作說明。相依 PR：無；不代表 DDD-06 的多比較標的功能已完成。

原介面在 OCR 前強制要求起迄日，未標示必填，且錯誤提示位於 modal 對話框外。現在地區與 PDF 為上傳必填，期間可於 OCR 後核對時補齊，建立版本前仍強制驗證期間及人工確認。錯誤顯示於對話框內；OCR／確認請求失敗會恢復原表單，保留檔案、日期及選項供重試。草稿提供原始 PDF 連結。

沒有修改 domain、application、ports、資料庫或矩陣計算方向。

驗收：

- Chrome Playwright 基準上傳流程 3 項通過：既有成功流程、1440 與 390 像素的必填提示、未填日期即可 OCR、OCR 失敗保留檔案重試、確認前期間驗證及保存失敗重試。API 使用合成回應。
- 基準 HTTP／application／表格解析測試 26 項通過。
- Python UTF-8 模式下，一般測試排除 `tests/test_ocr_benchmark.py` 後為 1,188 通過、7 跳過；該檔案依賴 Windows 不提供的 `resource` 模組，原始全量命令會在收集階段失敗。
- `node --check static/app.js` 與 `git diff --check` 通過。

未執行使用者 PDF 的真實 OCR、AWS 呼叫或線上部署。使用方式見 [README](../README.md#評價基準明細表轉-structured-ruleset)。
