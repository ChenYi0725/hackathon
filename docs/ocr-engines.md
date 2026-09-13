# CPU OCR 引擎切換（DDD-08 切片）

本次接上可設定的 PaddleOCR／RapidOCR，預設仍為 PaddleOCR。案件上傳、評價基準
匯入與 RAG 來源上傳共用同一個 `PdfReader`。這是 PR #20 的功能切片；AWS CPU
效能比較及線上替換尚未在本次續作驗收，不據此宣稱 RapidOCR 較快或更準。

後續 DDD-08 切片新增 [文字層加速](pdf-text-fast-path.md)：數位頁優先以 PDFium
讀取文字與座標，掃描頁保留本文件所述 OCR 設定。下方為原引擎切換切片的驗收紀錄。

## 設定與回復

依 [README](../README.md#切換本機-ocr-引擎) 安裝對應 requirements，再在 `.env`
設定 `OCR_ENGINE=paddleocr` 或 `OCR_ENGINE=rapidocr` 並重啟服務。
`/api/health` 提供引擎及偵測／辨識模型；不代表模型已下載或 OCR 已成功執行。

RapidOCR 固定使用 PP-OCRv5 ONNX CPU，預設 mobile det + server rec；模型在首次
執行下載至使用者快取目錄。兩個模型設定可分別選 v5 mobile／server，其他名稱在
啟動時拒絕。本次真實驗收使用預設模型組合、180 DPI、2 個 CPU 執行緒。

回復為 `OCR_ENGINE=paddleocr` 並重啟即可，需保留 Paddle 套件。不需清空、遷移或
重建 SQLite；本次沒有更新正式環境的設定。

## 相容性

- `LocalPdfReader` 注入現有用例；`PaddlePdfReader` 保留相容匯入名稱，亦遵循設定。
- `PdfReader` port、domain 模型與資料庫 schema 不變；不新增估價公式。
- 頁碼、像素座標、頁面尺寸、原文及信心值保留。RapidOCR polygon 轉為包圍矩形，
  再交給既有行列重建器；不將 polygon 當成 PDF point 座標。
- 每頁 `method` 保存 `paddleocr` 或 `rapidocr`，已解析因素來源衍生對應的 `-layout`。
  未定位頁面的因素維持通用 `ocr-layout`，不推定不存在的來源。
- 舊文件／案件／修訂紀錄直接載入已存結果，不因切換設定重新辨識；新上傳會另存文件。
- OCR 快取包含 PDF 內容、引擎、模型、DPI、執行緒與 adapter 版本。舊版快取保留，
  新版使用獨立 namespace；切回相同設定可重用新版已存的結果。
- 錯誤不寫入成功快取，不靜默換引擎。人工確認與 revision 控制維持原流程。

跨層修改包含 infrastructure 的設定、worker／backend、requirements，bootstrap 注入，
application 的來源標記，health HTTP 欄位及 UI 通用文字。沒有變動共用 ports 或 schema。

## 驗收（2026-09-12，本機 CPU、合成資料）

| 檢查 | 結果 |
| --- | --- |
| 一般 Python 全套 | 1,180 passed、7 skipped；外部整合另行執行 |
| 真實掃描 PDF，PaddleOCR＋RapidOCR | `tests/test_paddle.py` 5 passed |
| 合成評價基準 PDF → 草稿，各引擎分別執行 | 各 1 passed；保留待人工確認 |
| 引擎契約及合成基準矩陣數字、方向、級距邊界 | `tests/test_ocr_engines.py` 真實模式 12 passed |
| RapidOCR Chromium／Chrome 桌面與窄螢幕 E2E | 11 passed；含真實題目、來源上傳、確認及匯出 |
| JavaScript syntax、Git diff 空白檢查 | 通過 |

一般測試涵蓋設定驗證、同檔跨引擎／模型／DPI 快取隔離、切回後快取命中、失敗不快取、
polygon 正負數與座標轉換、引擎切換後舊文件／案件／audit 不變，以及新案件未確認狀態。
外部 Bedrock／AWS 部署未於本次重跑。

可重跑指令（先安裝兩份 OCR requirements）：

```bash
.venv/bin/python -m pytest -q
RUN_OCR_TESTS=1 .venv/bin/python -m pytest tests/test_paddle.py tests/test_ocr_engines.py -q
OCR_ENGINE=rapidocr RUN_RULESET_OCR_TESTS=1 \
RULESET_PDF_PATH=tests/fixtures/ocr_benchmark/ruleset.pdf RULESET_LOCALITY=測試市甲區 \
.venv/bin/python -m pytest tests/test_ruleset_ocr_integration.py -q
OCR_ENGINE=rapidocr PLAYWRIGHT_CHANNEL=chrome TEST_PORT=8021 npm run test:e2e
node --check static/app.js
node --check static/rag.js
```

`TEST_PORT` 可避開其他工作目錄正在使用的 8011；預設仍為 8011。

## 限制與後續

[合成 CPU 比較集](../tests/fixtures/ocr_benchmark/README.md) 與 benchmark scripts 保留，
但此文件未包含可稽核的 AWS 五候選時間／準確率報告。本次不切換部署預設。
後續須在同一 AWS CPU、相同文件與設定比較數字及儲存格位置，再依事先固定的閘門
決定是否替換。小型合成文件的成功不能推論所有真實掃描品質；人工確認始終必要。
