# 評價基準明細表上傳耗時實測

DDD-08 診斷切片，2026-09-13。使用者要求實際上傳其文件，已對部署中的 AWS 網站送出與前端相同的 HTTP 請求。第一次成功回傳花 **803.33 秒（13 分 23 秒）**；等待主要發生在 CPU 逐頁 OCR。

## 文件與執行環境

- 文件：`評價基準明細表.pdf 的副本.pdf`，9 頁、249,392 bytes；SHA-256 與量測值見 [JSON 紀錄](evaluations/ocr-ruleset-upload-2026-09-13.json)。原始 PDF 與完整辨識結果未加入 Git。
- AWS EC2 `t3.large`，2 vCPU、約 8 GiB RAM，Ubuntu 24.04；部署版本 `d894e39`。本報告提交基底 `bbc7e03` 已包含 PR #26 的 Windows 編碼與等待提示修改，但此次未部署該版本。
- PaddleOCR 3.7.0、PaddlePaddle 3.3.1、pypdfium2 5.13.0；CPU 2 threads、180 DPI、MKLDNN 關閉。
- 偵測模型 `PP-OCRv5_mobile_det`；**辨識模型仍為 `PP-OCRv5_server_rec`**。目前不是全 mobile 組合。

## 實測結果

| 量測 | 結果 | 範圍 |
| --- | ---: | --- |
| 第一次完整上傳 | 803.325 秒，HTTP 200 | 9 頁、沒有該文件的 OCR 快取 |
| 同一文件再次上傳 | 2.466 秒，HTTP 200 | 命中 OCR 快取，候選規則與首次完全相同 |
| 讀取完整 OCR 快取 | 0.007 秒 | 後端獨立計時 |
| 完整 9 頁規則解析 | 0.087 秒 | 已有 OCR 頁面 → extractor → build_review_candidates |
| 單頁模型初始化 | 2.991 秒 | 第一頁獨立診斷程序，模型已在磁碟 |
| 第一頁 OCR | 70.455 秒 | 1489 × 2105 像素，205 個文字框；含偵測與辨識 |
| 單頁診斷 OCR 總計 | 73.798 秒 | 包含初始化、PDF 處理與版面整理 |

單頁診斷在首次完整 OCR 結束後才執行，避免兩份 OCR 爭用 CPU。沒有重跑第二次完整的無快取 OCR；不能把單頁時間當成其餘每頁的實測時間。

全文件共 2,308 個文字框，每頁分別為 205、306、286、304、303、253、318、253、80。首次請求等待第一個回應位元組 802.718 秒；TCP 連線只需 0.152 秒。

## 為何畫面長時間停在 OCR

1. [上傳用例](../app/application/ruleset_imports.py) 先等待 PDF reader 完整返回，再解析與儲存草稿。此路徑沒有呼叫 Bedrock 或 Knowledge Base。
2. [PDF adapter](../app/infrastructure/paddle_pdf.py) 未命中快取時會等待 OCR subprocess；[worker](../app/infrastructure/ocr_worker.py) 將每頁轉成圖片，依序跑偵測與辨識，完成整份 PDF 後才返回。快取包含 PDF 內容與 OCR 選項，因此新文件仍需首次運算。
3. [OCR backend](../app/infrastructure/ocr_backends.py) 使用 CPU 與 server 辨識模型。量測確認大部分延遲在這段逐頁運算；本次未分別量出偵測與辨識模型各自的耗時。

完整 OCR 執行中，worker 約使用 109–111% CPU（Linux process 指標，一個核心滿載約 100%），RSS 約 805–829 MiB；可用記憶體約 6.4 GiB，沒有 swap，CPU credit balance 為 419.0691。健康檢查仍於 0.322 秒返回 HTTP 200，沒有觀察到記憶體耗盡或整個服務停止回應。

部署版本的前端等待整個 POST 完成，沒有逐頁進度；所以使用者會一直看到轉換中的畫面。提高 timeout 可以避免提早中斷，但不會減少 OCR 運算時間。

## 辨識結果與資料變更

成功產生 2 份候選規則集、48 個因子，仍有 12 則警告與 11 個因子需要人工核對或受到阻擋；不能把 HTTP 成功視為全部規則可直接計算。此次沒有推測適用期間、確認匯入或同步至 Knowledge Base。

兩次實際上傳共新增 2 筆文件草稿。完成後資料表計數為 documents=7、cases=4、audit=14、rulesets=3、evidence_documents=3；未新增正式規則集或案件。

## 後續加速方向與限制

這份 PDF 有原生文字層，現有文字 reader 在本機約 0.207 秒抽出 9 頁文字，但同時回報旋轉文字可能遺漏，且沒有提供規則解析需要的文字框座標。這不是與完整 OCR 等價的成功結果，不能直接替換上線。

優先評估「原生文字與座標抽取，缺少可用文字層時才 OCR」，並用本文件的表格、旋轉文字、標題與級距做正確性比對。全 mobile 辨識、調整推論 runtime 或硬體也可另行比較，但都需要保留規則品質驗收。本切片只診斷，沒有變更正式 OCR 模型、部署設定或等待流程。

## 重現方式

HTTP 上傳會建立待確認文件；只對已授權文件與目標執行，勿呼叫確認匯入端點：

```sh
curl --max-time 960 --silent --show-error \
  -H 'Content-Type: application/pdf' \
  --data-binary @input.pdf \
  --output upload-response.json \
  --write-out 'HTTP %{http_code}; connect %{time_connect}; first-byte %{time_starttransfer}; total %{time_total}\n' \
  "${APP_BASE_URL}/api/ruleset-imports?expected_locality=%E6%96%B0%E5%8C%97%E5%B8%82%E6%A8%B9%E6%9E%97%E5%8D%80&name=valuation-rules-upload-diagnostic.pdf"
```

[診斷工具](../scripts/profile_ruleset_upload.py) 在指定主機上使用現有 Settings 與實際 OCR backend，記錄初始化、每頁運算及完整文件的規則解析；不會自行上傳、儲存案件或確認規則。須在與部署相同的環境變數、執行身分和模型快取下執行。輸出可能包含來源檔名及解析警告，應留在本機或受控診斷目錄。

```sh
.venv/bin/python scripts/profile_ruleset_upload.py input.pdf \
  --locality 新北市樹林區 --page 1 --output .analysis/ruleset-page-one
```

省略 `--page` 會重新 OCR 整份文件，並計時規則解析；本工具不使用應用程式 OCR 快取。單頁模式不解析不完整的規則表。`timings.json` 的每頁秒數是 wall time；`first-page.prof` 與文字 profile 僅追蹤呼叫執行緒，無法涵蓋 Paddle 所有背景執行緒，不可將其 cumulative time 當成整體 OCR 耗時。

驗證：真實 AWS 完整上傳及快取重傳均 HTTP 200；AWS 單頁診斷程序成功；工具 `--help`、Python 語法檢查及文件 diff 檢查通過。未使用 GUI 自動化，本次以網站相同 HTTP 端點重現。
