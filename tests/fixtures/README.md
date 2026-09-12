# Synthetic scanned PDF

`synthetic-scanned.pdf` is a raster-only, one-page Chinese table created for OCR and Bedrock integration testing. It contains no real case, person, address, or transaction price. No text layer is embedded.

| 因素 | 比準地 | 比較標的 |
| --- | --- | --- |
| 寬度 | 5 | 7 |
| 面前道路寬度 | 18 | 6 |

The column headings and both numeric columns share consistent horizontal positions. `scripts/smoke_integrations.py` checks the exact values and direction after actual OCR and model inference, verifies that the preview leaves the case unchanged, and checks reuse of the result cache.

These two rows verify integration behavior, not extraction accuracy across real appraisal documents. Production use still requires source review and manual confirmation.

## core-workflow.xlsx

由 `scripts/demo_core_workflow.py --fixture-only` 產生的合成三工作表：勘查、區域因素、比較法。只含固定測試值、空白／0／無／不適用與一個不執行的公式；不含真實案件。原標題／欄位布局供 parser 辨識測試，並非官方完整模板。
