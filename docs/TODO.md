# 開發 TODO 與 DDD 分工

這是後續 coding agent 的任務入口。先閱讀根目錄 [AGENTS.md](../AGENTS.md)，再認領一項工作；本文件列的是規劃，不代表功能已完成。

## 題目與目前差距

命題要求依個案的評價基準核對級距、修正率、加總與跨表填值，並輔助完成書表。`REFERENCE_DATA_DIR` 下的「題目.pdf 的副本.pdf」第 5、6 頁包含樹林普通住宅用地及三個比較標的。

目前已完成：具版本與期間篩選的 v1 文字 RAG（本機查找＋Bedrock 引用說明）、PaddleOCR 上傳、Bedrock 欄位草稿、DDD 分層、SQLite 修訂紀錄及金山商業用地的單一比較標的審查。計算內部使用 `Decimal`，但資料模型仍有 `float`；匯出目前是 JSON、CSV 與可列印 HTML。

尚未完成：住宅規則與多比較標的、完整計算追溯、後端直接生成 PDF、v2 檢索整合及 GraphRAG。現況詳見 [架構文件](architecture.md)。

## 目標介面

保留原規劃五個技術 port 與一個領域計算服務；RAG 另增加獨立的 `EvidenceAnswerer` port，仍部署為同一個後端。

| 名稱 | 所屬與責任 | 現況 |
| --- | --- | --- |
| `PdfReader` | application port；取得 OCR 文字、頁碼、座標與信心值 | 已有，Paddle adapter |
| `FieldExtractor` | application port；整理欄位草稿與引用 | 已有，Bedrock adapter |
| `ReviewRepository` | application port；保存案件、基準、來源、版本與修訂 | 已有，SQLite adapter |
| `EvidenceRetriever` | application port；依案件適用範圍及版本取得來源依據 | v1 文字檢索已接線，v2 待整合 |
| `EvidenceAnswerer` | application port；依檢索片段生成附引用的說明草稿 | v1 Bedrock adapter；不修改案件 |
| `PdfRenderer` | application port；將案件快照及計算結果輸出 PDF | 規劃中 |
| `ValuationCalculator` | domain service；查表、公式、加總、加權及一致性檢查 | 由現有 `engine.py` 擴充，名稱與型別待 DDD-00 定案 |

檢索不得自行取代案件綁定的基準。AI 不執行估價算術，不產生可直接執行的任意公式／Python。PDF 使用同一份案件快照與計算結果，不能在輸出時重新讓 AI 改寫數字。

## 負責區塊

| 區塊 | 主要檔案與目錄 | 工作邊界 |
| --- | --- | --- |
| Domain | `app/domain/`、`tests/test_engine.py`、新增領域測試 | 模型、規則版本、Decimal、計算與追溯 |
| Application | `app/application/`、`app/bootstrap.py`、`tests/test_application.py` | ports、用例順序、確認狀態、版本衝突、adapter 注入 |
| Infrastructure | `app/infrastructure/`、adapter 測試、相應 requirements | 儲存遷移、Paddle、Bedrock、依據檢索、PDF renderer |
| Interfaces／UI | `app/interfaces/`、`static/`、`tests/test_api.py`、`e2e/` | HTTP 契約、比較標的操作、原文核對與 PDF 下載 |
| Integration | `tests/fixtures/`、`scripts/smoke_integrations.py`、跨層測試 | 合成測資、完整流程及錯誤情境驗證 |

每個區塊有自己的 `AGENTS.md`；Integration 遵循根目錄指引。`domain/models.py` 由 Domain 協調、`application/ports.py` 與 `bootstrap.py` 由 Application 協調、資料庫 schema 由 Infrastructure 協調。跨區塊變更在 PR 中列出，避免各自建立同名但不相容的型別。

## TODO 索引

狀態使用「待認領／進行中／待審查／完成／受阻」。認領與協調以 open PR 為準；開發者在自己的分支更新對應列的負責人與 PR，避免只改本地 TODO 就假定其他人已看到。認領狀態見下表。

| ID | 優先序 | 工作 | 負責區塊 | 前置 | 狀態 | 負責人／PR |
| --- | --- | --- | --- | --- | --- | --- |
| DDD-00 | P0 | 共用資料與 port 契約定案 | Application＋Domain | 無 | 待審查 | Codex／[PR #4](https://github.com/ChenYi0725/hackathon/pull/4) |
| DDD-01 | P0 | 住宅規則、多比較標的與精度模型 | Domain | DDD-00 | 待認領 | — |
| DDD-02 | P0 | 可追溯的確定性計算 | Domain | DDD-01 | 待認領 | — |
| DDD-03 | P0 | 舊案件相容與資料遷移 | Infrastructure | DDD-01 | 待認領 | — |
| DDD-04 | P0 | ports 與案件用例整合 | Application | DDD-02、DDD-03 | 待認領 | — |
| DDD-05 | P0 | PDF 報告與原書表產製 | Infrastructure | DDD-04 | 待審查（v1 Excel 分表；依本次需求移除 PDF 輸出） | Codex／[PR #9](https://github.com/ChenYi0725/hackathon/pull/9)；[範圍與驗收](form-exports.md) |
| DDD-06 | P0 | 多標的核對與 PDF 下載介面 | Interfaces／UI | DDD-04、DDD-05 | 待審查（v1 Excel 下載；PDF 入口已移除） | Codex／[PR #9](https://github.com/ChenYi0725/hackathon/pull/9)；多標的輸入尚未整合 |
| DDD-07 | P1 | 具版本篩選及引用的依據檢索 | Infrastructure | DDD-04（v2）；本次先接 v1 | 待審查 | Codex／[PR #6](https://github.com/ChenYi0725/hackathon/pull/6)（基礎 RAG：已合併 PR #5） |
| DDD-08 | P0 | 題目完整流程與回歸驗收 | Integration | DDD-05、DDD-06 | 進行中（Agent／CPU OCR 切片） | Codex／[PR #8](https://github.com/ChenYi0725/hackathon/pull/8)、[PR #20](https://github.com/ChenYi0725/hackathon/pull/20)；[OCR 切換驗收](ocr-engines.md)；[PR #21](https://github.com/ChenYi0725/hackathon/pull/21)（Agent 錯誤修復與總計來源頁碼，已合併）；[9 頁評價基準 AWS 上傳診斷](ocr-ruleset-upload-diagnosis.md)（首次 803.33 秒、快取重傳 2.47 秒；加速尚未實作）／[PR #29](https://github.com/ChenYi0725/hackathon/pull/29) |
| DDD-09 | P2 | GraphRAG 對照評估 | Infrastructure＋Integration | DDD-07、DDD-08 | 待認領 | — |

合併順序：DDD-00 → DDD-01 → DDD-02／DDD-03 → DDD-04 → DDD-05／DDD-07；DDD-05 完成後接 DDD-06、DDD-08。斜線兩側可由不同開發者分別實作。DDD-09 不阻擋主要估價審查流程。

## 任務驗收條件

### DDD-00：共用契約先定案

共用規格已整理於 [contracts.md](contracts.md)，由後續實作共同遵循。文件區分本次 v1 確認失效修正與尚未實作的 v2 契約；這張任務不以未接線的空介面宣稱功能完成。

- 定義案件／比較標的／因素的穩定 ID，來源文件、頁碼、文字框與基準版本的關聯。
- 定義 Decimal 的 JSON／儲存表示、單位、百分比表示與捨入時點，包含現有資料相容策略。
- 定義五個 port 的輸入、輸出、錯誤與確認狀態；新增兩個 port 不得依賴特定 PDF 或檢索 SDK。
- 定義 `CalculationResult`／計算追溯與 PDF 所需快照資料；名稱可調整，但須有唯一共用契約。
- 說明 HTTP schema 如何演進，讓後續分支不各自猜測多比較標的的資料形狀。

### DDD-01：模型與適用規則

- 在 `app/domain/` 支援比準地及多個比較標的，三標的題目可完整表示；不同標的的因素與引用不能覆蓋彼此。
- 根據有來源的住宅基準建立版本，保留金山商業用地回歸案例；各案明確綁定基準，不能混用地區、用地類別或版本。
- 金額／比率以 DDD-00 的精度契約保存；數值 `0`、缺值、「無」、免比較與特殊調整理由維持不同語意。
- 定義舊單一標的的相容表示，保持既有 API／計算可運作，提供合成案例供 DDD-03 遷移測試。

### DDD-02：程式計算與追溯

- 由 `app/domain/engine.py` 或新的領域計算模組完成級距、矩陣方向、各階段調整、加總、跨表一致性、多標的試算與加權。
- 每項計算保留輸入、公式 ID／版本、基準版本、中間值、單位、捨入方式及來源；輸入快照與版本相同時能重算相同結果。
- 精度、日期調整、權重與特殊公式依已確認來源定義，不能直接沿用單一標的 `100%` 假設或由 AI 猜公式。
- 測試級距邊界、正負方向、缺值、權重、捨入及中間精度；資訊不足時回傳待確認，不能補零後宣告通過。

### DDD-03：儲存相容與遷移

- 在 persistence adapter 處理新版資料，保留舊案件 ID、原 PDF、基準版本、revision 與 audit snapshot。
- 提供可重複執行的相容載入／遷移策略、遷移前備份及失敗復原說明，不能清空 SQLite 後重建。
- 案件與計算快照保存維持 transaction／版本衝突檢查；舊資料與新三標的資料均可載入、儲存及核對歷史版本。

### DDD-04：用例與 ports

- 依 DDD-00 在 `app/application/ports.py` 及共用型別落實新增契約，於 `bootstrap.py` 注入 adapter；預設組態未裝可選功能時提供明確行為。
- 編排「OCR → 欄位草稿 → 人工確認 → 確定性計算 → 保存版本 → PDF」，保存與輸出使用同一份案件 revision。
- AI 預覽及依據查詢不修改案件；套用草稿保留人工備註，重設需確認的欄位，長工作結束後再次核對 revision。
- 用測試替身驗證 port 契約與錯誤處理，application 不 import AWS、PDF、OCR 或資料庫 SDK。

### DDD-05：PDF renderer

- 實作 `PdfRenderer`：先完成可下載的審查報告，再完成題目所需原書表填寫。可用 HTML＋WeasyPrint；固定版面套印可評估 ReportLab＋pypdf，選型理由記在 PR。
- 報告包含案件／基準版本、比較標的、輸入值、計算結果、待確認狀態、來源與產出時間；不覆寫原始上傳 PDF。
- 後端直接回傳有效 PDF bytes，不能把 HTML 重新命名成 `.pdf`，也不能只靠瀏覽器列印宣稱完成。
- 原書表先確認模板頁碼、欄位座標與填寫範圍；驗證繁體中文字型、三標的欄位、長文字、分頁與待確認標記。
- PDF 需轉成頁面圖片檢查版面，另核對抽出的文字／數字與固定案件快照一致；不可只檢查檔案存在。

### DDD-06：HTTP 與操作介面

- 在 `app/interfaces/` 與 `static/` 呈現多比較標的，支援逐欄引用、人工確認、計算追溯及 PDF 下載。
- 比較標的使用穩定 ID，切換標的、重新抽取與儲存後不串值；UI 不重寫 domain 公式。
- 保留 revision 衝突回應及既有匯出行為，加入 API 與瀏覽器回歸；PDF 錯誤須顯示可處理訊息。

### DDD-07：來源檢索

依使用者優先順序，先交付可獨立使用的 v1 RAG 切片。新增來源 PDF 上傳、期間綁定、本機中文文字檢索、引用與 Bedrock 說明；另依使用者要求加入四個唯讀工具的 Agentic RAG。v2 多標的契約仍依賴 DDD-04，不以本次完成整體 v2 整合。行為與限制見 [RAG 文件](rag.md)。

- 在 `EvidenceRetriever` 後實作基準 ID／版本精確查找與文件檢索；以地區、用地類別、適用時間及案件指定版本篩選，避免最相似但不適用的規則。
- 回傳文件 ID／版本、頁碼、原文與可用座標，讓說明能追溯；檢索結果不直接修改案件基準或可執行公式。
- 先建立可測試的文字檢索基線；是否加向量檢索由測資結果決定，不預先綁定圖資料庫。
- 新 adapter 共用已定案的 ports／SDK 設定；涉及 schema 或 `ports.py` 變更時列出協調範圍。

### DDD-08：完整題目驗收

先依使用者要求交付單一標的 Agent 六題驗收與 AWS 實測，見 [驗收文件](agent-evaluation.md)。這個切片不代表本任務的三標的、住宅及 PDF 完整流程已完成。

- 建立不含真實案件／價格的三比較標的合成測資，涵蓋跨表錯填、混用基準、錯誤級距、捨入與缺值。
- 驗證上傳 → 草稿 → 人工確認 → 計算 → 儲存／重新載入 → PDF；輸入、公式追溯、畫面及 PDF 數值一致。
- 保留既有金山範例回歸，區分 mock、真實 CPU OCR 與另行執行的 Bedrock 整合；真實題目文件僅在符合規範的範圍使用。
- 整理可重跑的驗收結果與未支援情況。DDD-07 完成後另補檢索正確版本／引用的案例供 DDD-09 比較。

### DDD-09：GraphRAG 評估，非預設導入

- 建立需跨文件連結條文、例外、基準與案件的問題集，以及人工確認的來源答案。
- 在相同文件版本與問題集比較 DDD-07 檢索與 GraphRAG：正確來源／版本、漏證據情況、延遲、token 與建索引成本。
- 只有能說明具體改善時才提出實作 PR；改善不足則記錄暫不導入及重新評估條件。
- GraphRAG 即使導入也不能接管計算、規則核准或 PDF 數字產製。

## PR 交接

PR 使用 [.github/pull_request_template.md](../.github/pull_request_template.md)。完成後留下 TODO ID、實際測試結果、契約變更、下一個相依任務與尚未處理的限制。外部 PDF 未安裝或 AWS 測試未執行時清楚記錄，不把跳過當成通過。
