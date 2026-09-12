# 列表與分表輸出（DDD-05／DDD-06 的 v1 切片）

案件畫面的「匯出成果」保留逐項列表 HTML、CSV、JSON 與整理書表，另提供：

| 下載項目 | kind | 內容 |
| --- | --- | --- |
| 表3 Excel | table3-xlsx | 比準地的地價區段勘查表，以及完整填值／審核明細 |
| 表4 Excel | table4-xlsx | 比較法調查估價表，以及填值／審核明細 |
| 表5 Excel | table5-xlsx | 住宅用地区域因素分析明細表，以及填值／審核明細 |

三個表分開下載，不合併為同一份 Excel。輸出保留模板工作表、合併、欄寬、基本樣式及原有公式，另附填值與審核明細；不修改原始模板。舊版列表與分表 PDF 產製、下載與列印入口已移除；核心流程另提供有效檢核快照的 PDF 審查摘要與 ZIP，見 [核心流程](core-workflow.md)。

## 設定

安裝 requirements.txt。預設使用 [out_put_teamplate/](../out_put_teamplate/README.md) 中的三份 Excel 範例，也可用 FORM_TEMPLATE_DIR 指向其他模板目錄。每種檔案必須唯一：

- 表3*.xlsx，內含「表3區段勘查表」。
- 表4*.xlsx，內含「表4比較法調查估價表」。
- 表5*.xlsx，內含「表5-1區域因素明細表(住)」。

此目錄收錄現有表3／表4／表5範例原檔，未填入目前案件資料。預覽輸出另存於 `.analysis/form-preview/`。

## 資料語意與限制

輸出取自目前已儲存案件的**原填值**；不自動套用修正建議，不呼叫模型或重新決定公式。所有審核狀態與預期值另列在明細；未知欄位標示待補，不補零。數字 0 與「無」、未提供、待確認維持不同語意。數字總計在 Excel 為數值；文字即使以等號開頭仍寫成 literal string。

案件現可保存最多三筆比較標的，表4／表5依各標的填入對應欄；未提供的標的仍明確標示。表3保留原模板，比準地填入原工作表；多標的案件另附已提供比較標的各自的工作表。完整住宅規則與官方套印仍待整合。表3未有獨立欄位的設施名稱、設施類型、勘查範圍與簽章等需承辦補齊；不將通用車站距離硬填為高鐵距離。現有區域因素的原始資料均保留於附錄。

表5模板屬住宅用地。商業案件可取得標示不適用的草稿及原始明細，不將商業等級或修正率冒充住宅審核結果。小計、比準地比較價格未有獨立領域結果者，明示待確認，不在 renderer 新增估價公式。

## 契約與相容

新增 application/export_contracts.py 的 FormRenderer / ExportArtifact 與 ReviewService.export_document，用 bootstrap 注入 TemplateFormRenderer。未變更 Case、資料庫 schema、原有 ports 或既有匯出格式。這是 v1 renderer 切片，並非 docs/contracts.md 尚未實作的 v2 CalculationResult 契約。

GET /api/cases/{id}/export/{kind}?revision={revision}

- 三種 Excel 下載必須指定 revision。未指定為 422、過期為 409、模板未設定為 503。
- 同一份案件快照用於審核與輸出；產製後再次檢查 revision，過期就拒絕回傳。
- Response 包含正確 Content-Type、attachment 檔名、X-Case-Revision 與 no-store。
- 下載不新增 audit、不修改案件；UI 匯出前先保存畫面變更，產製失敗時保留錯誤提示。

## 驗證

tests/test_form_exports.py 使用合成模板檢查分表、值／合併保留、零值、公式注入、原檔不變、已移除的 PDF 端點回傳 404、revision 衝突、產製途中修改，以及缺少模板。

執行 `python -m scripts.preview_form_exports` 可產生合成案例套入預設模板的三份 Excel，預設存於 `.analysis/form-preview/`。這些是合成預覽，並非真實題目完成結果。`e2e/exports.spec.js` 驗證三種下載、舊版分表 PDF 選項已移除、快照 PDF 入口保留及窄螢幕錯誤提示。

本機 Windows 回歸以 PYTHONUTF8=1 執行，避免既有測試用系統 CP950 讀取 UTF-8 fixture。雲端與真實 OCR 不在此切片驗收範圍。
