# PDF 文字層加速（DDD-08）

評價基準上傳原本將每頁都轉圖再 OCR，9 頁文件首次等待 803.325 秒。本切片在現有受限子程序內，逐頁先檢查可用文字層與座標，只有需要 OCR 的頁面才初始化模型並辨識。

## 行為與相容性

- 預設 `PDF_TEXT_LAYER_ENABLED=true`；設為 `false` 並重啟即可強制 OCR。`/api/health` 回傳 `pdf_text_layer_enabled`，頁面結果保留 `pdf-text` 或實際 OCR 引擎名稱。
- 原始 PDF、頁碼、像素座標與頁面大小繼續保存。PDF 座標轉為與指定 DPI 相同的左上角原點像素座標；文字框的 `confidence=1.0` 表示直接讀取字元，不是 OCR 模型的準確率或規則正確性。
- 沒有更換 Paddle 辨識模型、估價公式、ports 或 schema。原有文件、案件、規則與修訂保持原狀；新上傳仍需人工確認。
- 快取使用 `local-pdf-v3`，包含文字層開關及 OCR 選項。保留舊快取，避免把先前 OCR 結果當成本版文字層結果。
- 翻轉／裁切或頁面旋轉、含圖片、註記、隱藏文字、不支援的 Form 變換、無效 Unicode、文字量不足等頁面走 OCR。支援純平移的巢狀 Form，文字框會套用父層位移。以文字中心排除可視頁面外的物件；邊界上仍無法完整表示的字框回到 OCR。
- 此路徑仍在執行服務的 EC2 上運作，不需使用者本機安裝 OCR，也不呼叫額外的雲端文件服務。掃描文件仍受原 CPU OCR 耗時影響。

## 表格解析修正

文字層會將上標、換行與直排字拆成比 OCR 更細的物件，因此同步修正同一個規則解析 adapter：

1. 依各矩陣列的備註標籤位置界定數字範圍，不將面積 `m²` 的上標誤當矩陣欄位，也保留不同列寬的 7×7 矩陣。
2. 依級距標籤的垂直位置歸屬跨行備註，避免把下一級的第一行接到前一級；排除表頭及說明中的冒號片段。
3. 合併連續直排文字物件，納入較寬的多欄細項，排除頁面標題與鄰欄結構文字。

不會補字、猜數字或修復來源級距。完整矩陣、數值邊界及正式規則版本仍由既有程式驗證。

## 驗證與限制

本機一般 Python：1,208 passed、7 skipped；Chrome 操作流程：11 passed，包含真實掃描上傳。另有真實數位 PDF 測試，涵蓋不啟動 OCR、混合頁分流、關閉開關、隱藏文字／旋轉頁回到 OCR、Form 位移座標及表格解析回歸。一般測試不下載模型或呼叫 AWS。

使用者指定文件共有 9 頁，保留 2 份候選規則集與 48 個因子。人工對照原始 PDF，確認舊 OCR 的 `-0` 實際應為 `-50`；新結果直接讀出原文。來源本身的面積邊界重疊及需人工判斷的因素仍保留阻擋。部分直排名稱仍可能有標點或順序差異，人工確認不可省略；不能以速度提升宣稱所有規則已正確。

## AWS 實際驗收（2026-09-13）

同一台 `t3.large`、180 DPI、2 個 CPU 執行緒，使用者指定的 249,392 bytes／9 頁 PDF：

| 項目 | 耗時與結果 |
| --- | --- |
| 舊版首次完整 HTTP 上傳 | 803.325 秒，HTTP 200 |
| 新版獨立讀取，沒有 repository 快取 | 0.632 秒，9 頁皆為 `pdf-text` |
| 新版完整規則解析 | 0.312 秒，48 個因子 |
| 新版首次公開 HTTP 上傳 | **3.168 秒，HTTP 200**；約快 254 倍 |
| AWS 一般 Python | 1,223 passed、7 skipped |
| AWS 真實掃描 OCR | 1 passed；確認掃描頁仍走 PaddleOCR |

HTTP 首位元組時間 2.499 秒，TCP 連線 0.262 秒。部署使用新快取 namespace；隔離測試沒有讀寫正式快取，因此首次公開請求不是舊 OCR 快取命中。候選規則與本機驗證的級距內容一致，仍有 11 則警告、10 個阻擋因子，未確認為正式規則。

部署保留既有 AWS Knowledge Bases 串接：以 `d894e39` 為底套用此次 PDF／表格修改，工作目錄為 `/opt/landwise-text-20260913`；沒有以 main 覆蓋 AWS 專用功能。`/api/health` 確認 `pdf_text_layer_enabled=true`、`rag_backend=bedrock-kb`，OCR 仍為 mobile det＋server rec。部署與備份紀錄保存在 `/var/lib/landwise/text-fast-path-20260913`。

需要回復時，移除此次新增的 `/etc/systemd/system/landwise.service.d/95-pdf-text.conf`，執行 `systemctl daemon-reload` 與 `systemctl restart landwise`，即可使用保留的原工作目錄；不用清空資料庫。只要關閉文字層則設定 `PDF_TEXT_LAYER_ENABLED=false` 並重啟。

量測摘要見 [JSON 紀錄](evaluations/pdf-text-fast-path-2026-09-13.json)。此次驗證共新增 2 筆待確認文件，documents 共 9 筆；cases、audit、rulesets、evidence_documents 的內容雜湊與切換前備份一致，未新增正式規則、修改案件或同步 Knowledge Base。新版上傳儲存的 9 頁來源標記均為 `pdf-text`。

實作使用既有 pypdfium2 5.13.0 的文字物件與幾何 API，參考 [官方 API 文件](https://pypdfium2.readthedocs.io/en/stable/python_api.html)。
