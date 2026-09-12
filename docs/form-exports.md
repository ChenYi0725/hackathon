# 列表與分表輸出（DDD-05／DDD-06 的 v1 切片）

案件畫面的「匯出成果」保留逐項列表 HTML、CSV、JSON 與整理書表，另提供：

| 下載項目 | kind | 內容 |
| --- | --- | --- |
| 列表審查報告 PDF | report-pdf | 逐項狀態、原填值、預期值、說明、來源頁及基準版本 |
| 表3 Excel／PDF | table3-xlsx / table3-pdf | 比準地、比較標的1各一張地價區段勘查表，以及完整填值／審核明細 |
| 表4 Excel／PDF | table4-xlsx / table4-pdf | 比較法調查估價表，以及填值／審核明細 |
| 表5 Excel／PDF | table5-xlsx / table5-pdf | 住宅用地区域因素分析明細表，以及填值／審核明細 |

三個表分開下載，不合併為同一份 Excel。Excel 保留指定工作表的儲存格、合併、欄寬與基本樣式，移除其他隱藏範例工作表、外部連結及範例公式。原始模板不變更。PDF 由後端 ReportLab 直接生成，表3／表5採 A3 直式、表4採 A3 橫式，再附可分頁的完整明細；不是瀏覽器列印或 Excel 自動化。極長儲存格內容在表內指向附錄全文。

## 設定

安裝 requirements.txt。將三份原始 xlsx 放入 problem_files，或以 FORM_TEMPLATE_DIR 指向模板目錄。每種檔案必須唯一：

- 表3*.xlsx，內含「表3區段勘查表」。
- 表4*.xlsx，內含「表4比較法調查估價表」。
- 表5*.xlsx，內含「表5-1區域因素明細表(住)」。

模板不提交 Git；部署時需另提供。PDF_FONT_PATH 可指定有合法使用權的繁體中文 TrueType 字型（.ttf 或 TrueType 輪廓的 .ttc）。Windows 自動尋找微軟正黑體；Linux 另嘗試 AR PL UMing。找不到字型時 PDF 回 503 並提示設定，Excel 不依賴 PDF 字型。字型嵌入 PDF，不複製系統字型至 Git。

## 資料語意與限制

輸出取自目前已儲存案件的**原填值**；不自動套用修正建議，不呼叫模型或重新決定公式。所有審核狀態與預期值另列在明細；未知欄位標示待補，不補零。數字 0 與「無」、未提供、待確認維持不同語意。數字總計在 Excel 為數值；文字即使以等號開頭仍寫成 literal string。

目前 v1 Case 仍只保存一筆比較標的，表4／表5的第2、3標的欄標示未提供。題目中三標的全案填完仍依賴多標的案件整合，不以此切片宣稱完成。表3未有獨立欄位的設施名稱、設施類型、勘查範圍與簽章等需承辦補齊；不將通用車站距離硬填為高鐵距離。現有區域因素的原始資料均保留於附錄。

表5模板屬住宅用地。商業案件可取得標示不適用的草稿及原始明細，不將商業等級或修正率冒充住宅審核結果。小計、比準地比較價格未有獨立領域結果者，明示待確認，不在 renderer 新增估價公式。

## 契約與相容

新增 application/export_contracts.py 的 FormRenderer / ExportArtifact 與 ReviewService.export_document，用 bootstrap 注入 TemplateFormRenderer。未變更 Case、資料庫 schema、原有 ports 或既有匯出格式。這是 v1 renderer 切片，並非 docs/contracts.md 尚未實作的 v2 CalculationResult 契約。

GET /api/cases/{id}/export/{kind}?revision={revision}

- 新增七種下載必須指定 revision。未指定為 422、過期為 409、模板／字型未設定為 503。
- 同一份案件快照用於審核與輸出；產製後再次檢查 revision，過期就拒絕回傳。
- Response 包含正確 Content-Type、attachment 檔名、X-Case-Revision 與 no-store。
- 下載不新增 audit、不修改案件；UI 匯出前先保存畫面變更，產製失敗時保留錯誤提示。

## 驗證

tests/test_form_exports.py 使用合成模板檢查分表、值／合併保留、零值、公式注入、原檔不變、PDF 中文及長文字、revision 衝突、產製途中修改，以及缺少模板。

執行 scripts.preview_form_exports --template-dir problem_files 可產生合成案例套入原模板的 Excel、PDF 與首頁圖片；圖片驗證另需 pypdfium2。這些是合成預覽，並非真實題目完成結果。e2e/exports.spec.js 在設定 FORM_TEMPLATE_DIR 後驗證七種真實下載及窄螢幕錯誤提示。

本機 Windows 回歸以 PYTHONUTF8=1 執行，避免既有測試用系統 CP950 讀取 UTF-8 fixture。雲端與真實 OCR 不在此切片驗收範圍。
