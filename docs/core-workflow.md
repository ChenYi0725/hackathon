# 核心流程實作與驗收

本次是既有 FastAPI／原生 JS／SQLite 模組化單體的增量整合，沒有新增服務或多 Agent 框架。適用已人工發布、矩陣方向正確且資料可核對的規則；並不代表整份樹林住宅題目的所有公式或原始 PDF 套印已完成。

## 實際流程對照

| 目標步驟 | 實際程式位置 | 修正前／修正後與界線 |
| --- | --- | --- |
| 建立案件、標的與版本 | `domain/models.py`、`application/services.py` | 原為一筆比較標的；增量保存最多三筆，追加標的使用穩定 ID，保留原單筆欄位相容性 |
| 同案上傳多文件 | `application/workflow.py:upload`、`infrastructure/documents.py` | 原上傳只建立新 PDF 案件；現在可附加 PDF／XLSX，每次保存原 bytes、新文件 ID、版本與 audit |
| 文件解析與定位 | `infrastructure/documents.py`、`application/workflow.py:apply_cell` | PaddleOCR 保留；Excel 依標題＋內容欄位辨識三種表，不依檔名。保存 sheet、cell、formula、原值／百分點、空值與 hash |
| 欄位確認 | `domain/confirmation.py`、`static/app.js` | 延用先保存再確認；改來源、基準或適用背景清除確認，新增標的獨立確認。空白、0、無、不適用不互換 |
| Agent 規劃 | `application/agentic_rag.py`、`agent_contracts.py` | 案件欄位進入 context；既有四工具之外，接通 `plan_checks`、`lookup_facility`。只允許固定 schema，不執行任意程式 |
| RAG | `application/rag.py`、`infrastructure/retrieval.py` | 沿用由案件導出的基準 ID／版本、地區、用地、日期篩選；回傳原文定位。無適用文件時資料不足 |
| 外部資料 | `infrastructure/external.py` | 新北官方公園清冊 adapter；區分 timeout／unauthorized／unavailable／no_match／incomplete／candidates。只有候選清冊不等於現地事實已驗證 |
| GIS | `infrastructure/external.py:measure` | WGS84 橢球測地線、TWD97 121 分帶公尺平面距離；記錄 CRS、單位、方法、起訖角色。拒絕 POI 中心點與步行方法替代。沒有入口或邊界證據仍待核對 |
| 確定性驗證 | `domain/engine.py`、`domain/workflow.py` | 沿用 Decimal 級距／矩陣／加總／跨表。加入發布狀態、期間、區段、外部缺漏、多標的身分及同一比準地條件一致性；AI 不決定結果 |
| 結果與人工處置 | `application/workflow.py:disposition`、`static/workflow.js` | 問題、原填／預期值、規則、來源及公式保存於 snapshot；接受／拒絕獨立保存原因與時間，精確重試不重複新增。修改仍走案件 revision 與 audit |
| 匯出 | `infrastructure/reports.py`、`interfaces/http.py` | 新增真正的 PDF、Excel 整理書表及 ZIP 快照包。匯出前後驗證案件／規則／證據與人工處置；舊連結 409、其他案件 run ID 404 |
| 基準管理 | `services.py:publish_ruleset`、`persistence.py:add_rules` | 匯入固定 draft；核對原文、矩陣、期間與原因後產生新 ID。發布不覆寫原版，不自動切換案件；相同發布重試回傳同一版本 |

## 第二輪實作修正（core-2）

本地工作仍在 `codex/core-workflow`；尚未合併至 `main`。這輪在既有切片上追加以下修正，沒有重寫服務：

| 已重現問題 | 程式修正與驗收 |
| --- | --- |
| 追加 PDF 後舊列引用可能跟著切換文件 | 追加前固定既有文件 ID；新 OCR／AI 草稿也明確綁定文件 |
| 採用一個 Excel 儲存格卻成為其他欄位的來源 | 逐欄保存引用；未指定來源保持人工輸入，不推定同列共用儲存格 |
| 區域條件、等級與修正率來自不同 PDF 頁卻共用引用 | parser 分別保存實際頁碼及原文；介面與 PDF 分別列出來源 |
| AI 草稿替換值後保留舊 Excel 引用 | 套用選取欄位時同步替換該欄引用，仍待人工確認 |
| Excel 原生日期變成含時間字串 | 保留來源原值，採用估價日時轉為日期；沒有範圍資訊的 XLSX 明確拒絕並提示重存 |
| 引擎更新後舊快照仍可下載 | 明確 `ENGINE_VERSION=core-2`，舊引擎快照拒絕匯出／處置；歷史資料保留，重新檢核產生新快照 |
| 處置理由含首尾空白導致同一操作重試衝突 | 比對與保存使用相同正規化理由，相同操作只保留一筆 |
| 追加標的的總計映射／外部查證缺少操作入口 | 前端補上各標的總計欄位、外部查證標的選擇，瀏覽器驗證不串到第一筆 |

最初 5 個新增重現測試皆失敗，修正後通過；另補 PDF 跨頁與摘要多來源測試。沒有改寫既有審查數學公式或規則版本。

## 版本與非同步保護

- `review_runs` 保存完整案件、規則、外部證據、結果與雜湊。ID 由輸入／規則／證據／引擎版本決定；同輸入重跑不重複附加結果。
- `save_run` 在 SQLite transaction 中核對案件 revision 與外部證據 hash。背景工作晚完成時無法寫入過期結果。此版沒有新工作佇列；OCR 是既有有界子程序，查證與匯出是有界請求。
- `dispositions` 使用操作 ID 防重複，保存技術狀態及人工處置；不同 run 的處置在匯出標示歷史，不假裝適用新版。
- 外部結果另存 `external_evidence`；同一案件 revision／標的／因素／查詢類型重試取最新結果，歷史列保留。修改案件後舊佐證不自動套入新版。
- 外部查證預覽由 Agent 取得時不寫入案件；畫面明示「尚未保存」。持久化佐證由案件的外部查證操作執行。Agent 的結構化預覽會包含本次查證失敗；不以模型說明替換技術結論。
- 前端改值立即顯示舊結果過期；儲存與工作期間鎖住案件編輯。沒有虛構百分比進度，解析失敗顯示失敗而非完成。

## 規則及資料界線

現有內建金山範例沒有已核對的適用期間，仍可顯示條件式計算，但規範判定是預檢／待確認。不能因來源叫「範例」就補造發布日期。

多標的 `weighted-trial-v1` 僅於規則含 `aggregation_formula`、`aggregation_source` 且人工發布後啟用：各已驗證試算價格乘百分點權重後加總，以 Decimal `ROUND_HALF_UP` 至元。沒有適用來源時不啟用；沒有把此合成驗收公式自動指定給樹林案件。

本版仍沿用 v1 的數值表示，計算使用 Decimal，API 數字仍有 float；沒有宣稱完成 contracts.md 所有 v2 精度遷移。`additional_comparisons` 為原 Case 的相容增量；不刪除、重寫既有 audit。舊 HTML forms 對多標的明確拒絕，請改用包含全部標的的 Excel／ZIP。

Excel 公式保存原式及 cached value，但不執行 Excel 巨集、外部連結或任意公式。cached value 不可直接採用；人工需核對後填入。未知版型仍可查看儲存格並人工映射，不冒充自動欄位解析。原始文件不被匯出覆蓋。保留並整合表 3／4／5 Excel 模板填寫與 PDF 轉出，支援最多三筆標的；模板書表保留原填值及核對明細，另有僅輸出已確認值的整理工作簿。審查摘要共用既有 PDF renderer，包含來源、快照與人工處置。尚未套印原始 PDF。

## 本地 Demo

在功能分支根目錄，使用 Python 3.12 及繁體中文 TrueType 字型：

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements-ocr.txt
# macOS 使用既有 Arial Unicode；Linux 請指定有嵌入授權的繁中字型：
# export PDF_FONT_PATH=/path/to/traditional-chinese.ttf
.venv/bin/python -m scripts.demo_core_workflow --data-dir .analysis/core-demo
APP_DATA_DIR=.analysis/core-demo SEED_EXAMPLES=false BEDROCK_ENABLED=false PORT=8037 .venv/bin/python run.py
```

開啟 `http://127.0.0.1:8037`。Demo 資料庫已存在時命令拒絕覆寫；重跑請換一個資料目錄。

1. 開啟「合成 Demo · 正常」；已透過 Excel 儲存格映射、人工確認與固定合成規則完成檢核。
2. 點「同案文件／Excel 核對」，查看三種工作表的儲存格、公式與來源，或追加 `tests/fixtures/core-workflow.xlsx`。
3. 點「資料核對」改寬度／修正率；立即看到舊結果過期。先保存，再勾選確認並重新保存。
4. 開啟錯誤案：原填 9%，程式預期 2%。人工拒絕後仍維持技術錯誤；採用建議後仍須確認。
5. 開啟缺資料案：比準地寬度空白；區域因素仍能檢核。補 12、儲存、確認後重查。
6. 開啟外部失敗案：明示 mock timeout，其他 11 項表內檢核仍保留。
7. 「比較標的管理」新增第二、三筆；分別填值、保存與確認。沒有發布加權公式來源時保持全案待確認。
8. 「匯出成果」下載 PDF、Excel 或完整 ZIP；ZIP 保存 run、規則、輸入、來源及所有人工處置。
9. 使用「核對並發布基準」產生新版本，案件不自動切換；在「案件與計算」明確選新版，重做確認。

## 驗證與已知外部依賴

合成固定答案：寬度 12 對 8 → 2%；100 × 1.02 → 102。三標的固定測試為 102×40%＋100×30%＋100×30% → 101 元。測試答案為固定人工 oracle，沒有向模型詢問預期值。

```bash
.venv/bin/python -m pytest -q
PLAYWRIGHT_CHANNEL=chrome TEST_PORT=8037 npm run test:e2e
RUN_OCR_TESTS=1 .venv/bin/python -m pytest tests/test_paddle.py -q
```

`tests/test_core_workflow.py` 包含正常、錯誤、缺資料、API 失敗、真實執行緒競爭、證據競爭、版本切換、三標的不串值、跨案匯出拒絕、長文字 PDF 及 Agent 新工具。`e2e/z-core-workflow.spec.js` 實際操作新前端；既有 E2E 保留真實 CPU OCR 及合成模型回覆。

第二輪本地驗收（2026-09-12）：指定本地附件並啟用真實 CPU OCR，Python **1036 passed、0 skipped**（2 個既有依賴棄用警告）。Chrome 完整回歸先取得 12 通過、1 失敗；失敗是新增測試未等待儲存完成就讀取案件，補上實際保存完成的等待後，更新後核心 E2E **3/3 通過**，其餘既有 10 項已有通過證據。沒有把測試替身當作 Bedrock live 驗收。

重跑完整 Python 驗證須設定 `REFERENCE_DATA_DIR` 指向本地競賽附件，並設定 `RUN_OCR_TESTS=1`。瀏覽器可用 `TEST_PORT` 指定未使用埠；這輪使用 8037，未停止原有服務。

| 合成 Demo | 實際結果 |
| --- | --- |
| 正常 | 11 通過，完整 |
| 植入 9% 修正率錯誤 | 8 通過、3 錯誤，不完整 |
| 寬度空白 | 9 通過、1 待確認、1 缺資料，不完整 |
| 外部 API mock timeout | 11 通過、1 待確認，不完整 |

原有 Agent 評估腳本已改用同一個新版確定性驗證器，固定數學 oracle 保留；新增 `fixture_version=core-1` 區分舊成績。47 因素工具輸出有界且明示截斷，前端最終結果保留全部檢核，不因來源追溯資訊變多而使工具超限。

PDF 驗收包含 pypdf 中文／儲存格文字比對及 PDFium 轉圖檢視；Excel 重新開啟核對已確認值、原始型別、標的 ID 與版本。CLI 在指定隔離資料夾產生四個 Demo ZIP。

2026-09-12 官方公園 API 小量實測成功取得候選資料；達到 3 頁／100 筆展示上限，結果記錄 `truncated=true`、`data_date=null`、`check_status=pending`。這不是完整名錄或歷史 GIS 驗證。這次未使用 AWS 呼叫驗證新核心流程，未建立或部署付費資源。

| 缺少什麼 | 阻擋功能 | 已完成替代驗證／接通後驗收 |
| --- | --- | --- |
| 樹林題目完整、經人工確認的角色映射、公式及版本 | 完整住宅題目定論 | 沿用現有獨立住宅 domain；三標的整合以合成規則驗證。取得核准規則後以原文標註值回歸，不套金山規則 |
| 歷史設施清冊、入口／邊界幾何、定位及有效日期 | 真實距離事實與區段套疊 | 固定 3-4-5 公尺與 WGS84 計算測試；缺幾何／POI 中心點拒絕。接通後核對來源、日期及人工黃金量測 |
| 授權地圖／TGOS／TDX 憑證與特定 API 契約 | 更多官方設施與定位服務 | 官方公園 adapter、錯誤分類、明確 mock 已接通；不猜其他端點、不保存 Google 資料 |
| 原始 PDF 套印及完整住宅欄位映射 | 所有題目原格式完整輸出 | 表 3／4／5 Excel 模板與 PDF、整理工作簿及 ZIP 已整合並支援三標的；原始 PDF 套印與未支援住宅欄位仍待補齊 |
| 新核心 Agent 六工具的 Bedrock live 驗收 | 新工具在指定模型的真實選用行為 | 模型替身＋真實工具編排測試已做；有授權後用合成案件重跑，不把先前四工具成績延伸成六工具成績 |

## 競賽與部署

已讀本地 2026-07-22 競賽規範與命題文件，並核對 [AWS S3 Block Public Access](https://docs.aws.amazon.com/AmazonS3/latest/userguide/access-control-block-public-access.html)、[Bedrock Converse](https://docs.aws.amazon.com/bedrock/latest/userguide/conversation-inference-call.html) 及 [新北公園資料集](https://data.ntpc.gov.tw/datasets/5fe3a136-29cc-4695-a17e-6636a32c3342)。

- S3 尚未使用／建立，不能宣稱已驗證 bucket 設定；如新增儲存，須啟用四項 Block Public Access 並另作部署驗證。
- 所有 Bedrock 呼叫仍共用既有 transport 的跨程序鎖、至少 1.1 秒間隔、有限重試；新增 Agent 工具不另建模型 client。須共用 APP_DATA_DIR；沒有多機或跨專案帳號限流保證。
- 本機無 token 時只接受 loopback client 與可信 Host；知道 ID 不提供遠端存取權。`APP_ACCESS_TOKEN` 可保護私有 API，須由受控的驗證代理提供 Authorization；尚無多人帳號／每案角色管理或公開部署。
- `.env` 不進 Git；AWS 憑證仍由 SDK 查找，不送前端或 OCR 子程序。新測試使用合成案件；第三方只查官方開放清冊，不使用 Google Places／Routes 快取。
- 模型、外部 API 與 OCR 失敗都不會產生全案通過；已有來源與人工處置仍可在草稿匯出中查看。
