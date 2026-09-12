# 地衡 Landwise · PaddleOCR + Amazon Bedrock

本機估價審查工作台。上傳的 PDF 由 **PaddleOCR 在 CPU 辨識**；需要 AI 整理欄位時，使用 **Amazon Bedrock**。計算、級距與矩陣仍由確定性規則引擎執行，AI 回傳草稿須人工確認。

「匯出成果」提供 HTML 列表報告、CSV、JSON，以及表3／表4／表5各自的 Excel 下載。PDF 輸出已移除。表格範例位於 [out_put_teamplate/](out_put_teamplate/README.md)，預設以這些範例作為填值模板；設定見 [分表輸出](docs/form-exports.md)。

> **開發者／coding agent 請先讀：[AGENTS.md](AGENTS.md) → [TODO 與 DDD 分工](docs/TODO.md) → 負責目錄的 `AGENTS.md`。** TODO 包含介面規劃、前置任務與驗收條件；每項工作使用自己的功能分支，經 PR 審查。

共用資料、ports、精度與版本相容規格見 [契約文件](docs/contracts.md)。現行操作中，修改因素會清除該列與總計確認；更換基準、來源或案件適用背景會清除全部確認。請先儲存修改，再勾選確認新版本；匯入 JSON 與採用建議也遵循同一規則。

## 目前專案架構

目前由本機執行網站、OCR、規則計算及資料保存，AWS 提供模型推論。圖中的箭頭表示執行流程；應用層透過 ports 使用基礎設施，由 `bootstrap.py` 注入具體實作。

```mermaid
flowchart TB
    USER["使用者瀏覽器<br/>上傳 PDF、核對草稿、審查與匯出"]

    subgraph LOCAL["本機：DDD 模組化單體"]
        HTTP["介面層 interfaces<br/>FastAPI 路由與 HTTP 回應"]
        APP["應用層 application<br/>案件用例、PDF 匯入、AI 草稿與來源驗證"]
        DOMAIN["領域層 domain<br/>Case、Factor、Evidence<br/>級距、矩陣與審查計算"]

        subgraph INFRA["基礎設施層 infrastructure"]
            OCR["PDF adapter<br/>PDFium 轉圖 → PaddleOCR<br/>CPU 子程序辨識"]
            AI["AI adapter<br/>Bedrock Converse<br/>快取、節流與有限重試"]
            RAG["RAG adapters<br/>文字檢索、引用說明與原生 tool calling"]
            REPO["Repository adapter<br/>SQLite 與本機檔案存取"]
        end

        DB[("SQLite<br/>案件、基準版本、修訂紀錄<br/>OCR 文字與抽取快取")]
        FILES["本機 PDF 檔案<br/>data/uploads/"]
    end

    subgraph CLOUD["AWS：us-west-2"]
        MODEL["Amazon Bedrock<br/>qwen.qwen3-32b-v1:0"]
    end

    USER <--> HTTP
    HTTP --> APP
    APP --> DOMAIN
    APP -->|PdfReader| OCR
    APP -->|FieldExtractor| AI
    APP -->|ReviewRepository| REPO
    APP -->|EvidenceRetriever／EvidenceAnswerer| RAG
    RAG --> REPO
    RAG -->|確認可上雲後：問題與原文片段| MODEL
    REPO --> DB
    REPO --> FILES
    AI -->|確認可上雲後：OCR 文字與因素定義| MODEL
    MODEL -->|欄位草稿與來源行號| AI
```

上傳先走 PaddleOCR，再保存原始 PDF、辨識文字與待確認案件。AI 抽取由使用者另外啟動，預覽不修改案件；套用後仍須人工核對，估價判定由領域規則引擎執行。目前保留單一比較標的，尚未部署 AWS 主機。

## 基準文件 RAG

案件內按「依據問答」，先加入綁定該基準版本及適用期間的 PDF，再查找來源或請 Bedrock 生成附引用說明。本機檢索不需要 AWS；生成前須確認問題與來源可上雲。找不到符合案件版本、地區、用地及日期的依據時不生成答案。

目前使用中文文字檢索基線，不使用向量或 GraphRAG。引用包含文件、頁碼、原文與版本；AI 不修改案件、不執行估價運算。完整操作、API 與限制見 [RAG 文件](docs/rag.md)。

「Agent 自動查詢」使用 Bedrock Converse tool calling，自行選擇搜尋、讀取來源頁、查看規則或呼叫確定性審查。介面顯示工具紀錄與原始引擎結果，詳見 [Agentic RAG](docs/agentic-rag.md)。

## 審查流程與競賽限制

以下為目前已實作的主要操作路徑。DDD 的 application 層編排流程，infrastructure 層處理 OCR、AWS 與儲存，domain 層負責確定性計算；HTTP 與畫面呈現結果。

### PDF 上傳到審查匯出

```mermaid
flowchart TB
    UPLOAD["瀏覽器上傳 PDF"] --> HTTP["interfaces：FastAPI 接收文件<br/>檔案上限 20 MB"]
    HTTP --> OCR["infrastructure：PDFium 轉圖、PaddleOCR CPU 辨識<br/>最多 200 頁，限制像素與執行時間"]
    OCR -->|成功| DRAFT["application：版型解析與待確認草稿<br/>本機保存原始 PDF、OCR 文字、座標及案件"]
    OCR -->|失敗或逾時| ERROR["顯示錯誤<br/>檢查或拆分文件後重新上傳"]
    DRAFT --> OPTIONAL{"需要 AWS AI 整理欄位？"}
    OPTIONAL -->|否| HUMAN["人工核對原文、適用基準與欄位<br/>確認或修正資料"]
    OPTIONAL -->|是| AI["執行下方 AI 抽取子流程<br/>取得草稿或錯誤提示"]
    AI --> HUMAN
    HUMAN --> SAVE["application：檢查 revision<br/>repository：保存案件與修訂快照"]
    SAVE --> RULES["domain：Decimal 計算與規則審查<br/>級距、矩陣、加總及跨表一致性"]
    RULES --> RESULT["通過／疑似錯誤／待確認／資料不足"]
    RESULT -->|繼續修正| HUMAN
    RESULT --> EXPORT["匯出 JSON、CSV、HTML 報告與整理書表<br/>表3／表4／表5另可下載 Excel"]
```

載入案件時也會計算目前審查狀態；未確認資料不會自動通過。儲存時若 revision 已過期，回傳衝突並要求重新載入。尚有疑點的案件仍可匯出，報告會保留待確認狀態。**原書表套印、多比較標的及 GraphRAG 仍列於 [TODO](docs/TODO.md)，未包含在已完成流程中。**

### AWS AI 抽取子流程

```mermaid
flowchart TB
    START["使用者啟動 AWS AI 抽取<br/>需已啟用 Bedrock，並先儲存畫面變更"]
    START --> POLICY{"已確認整份文件符合競賽上雲規範？"}
    POLICY -->|否或尚未確認| LOCAL["不呼叫 AWS<br/>繼續本機 OCR 與人工核對"]
    POLICY -->|是| READ["application：核對案件 revision<br/>載入 OCR 文字與案件指定的基準版本"]
    READ --> CACHE{"相同輸入的 AI 快取存在？"}
    CACHE -->|是，使用已驗證結果| REVISION
    CACHE -->|否| GATE["共用鎖與持久化節流<br/>每次嘗試間隔至少 1.1 秒<br/>適用錯誤最多嘗試 3 次，SDK 自動重試關閉"]

    subgraph AWS["AWS：目前使用 us-west-2"]
        MODEL["Bedrock Converse<br/>qwen.qwen3-32b-v1:0<br/>只整理欄位草稿，不執行估價計算"]
    end

    GATE -->|OCR 文字與因素定義| MODEL
    MODEL -->|欄位與來源行號| VERIFY["本機驗證完整 JSON、因素 ID、原文引用及數值<br/>只保留可接受的候選並寫入快取"]
    MODEL -->|呼叫失敗或重試耗盡| FAIL["顯示錯誤，原案件保持不變<br/>重新載入、稍後重試或人工核對"]
    VERIFY -->|無有效草稿或輸出不完整| FAIL
    VERIFY -->|有有效草稿| REVISION{"抽取前後案件 revision 仍一致？"}
    REVISION -->|否| FAIL
    REVISION -->|是| PREVIEW["回傳未確認草稿，預覽不寫回案件<br/>使用者勾選套用後，回到人工核對與儲存"]
```

引用與數值存在性檢查不代表模型已選對欄位或比較方向。上雲確認是使用者的資料適用性確認，程式目前沒有自動辨識所有受限資料；將 PDF 轉成 OCR 文字不會解除原資料的限制。雲端整合測試只使用合成文件。

### 規範如何反映在流程中

依 `REFERENCE_DATA_DIR` 下的 `黑客松競賽環境規範與限制_20260722.pdf` 第 1–2 頁，對照目前程式如下；若賽期間公告有調整，以主辦最新規範與實際環境為準。

| 競賽規範 | 目前流程／實作 |
| --- | --- |
| 禁止將個資、財務資訊等受限資料引入 AWS | 呼叫前確認整份文件適用性；未確認時保留本機處理路徑，測試使用合成資料 |
| Bedrock 每秒 1 個請求以下 | 同一主機共用鎖、持久化節流及至少 1.1 秒間隔；重試同樣經過節流，命中快取不呼叫模型 |
| 指定主要部署區域為 `us-east-1`、`us-west-2` | 程式只接受這兩區，預設 `us-west-2`；本版使用區域內模型 ID，拒絕跨區 inference profile |
| 僅使用必要模型與資源，不建議大規模訓練 | 本機 CPU 執行 PaddleOCR，需要 AI 時才呼叫設定的模型；目前沒有模型訓練流程 |
| GitHub 不得包含機密憑證 | `.env` 被 Git 忽略，保留不含金鑰的 `.env.example`；AWS SDK 從 profile、環境或 role 讀取憑證 |
| S3 不可公開、EC2 Security Group 不可完全開放、RDS／EMR 不可公開存取 | 目前沒有部署這些雲端資源；未來部署須依規範及支援服務清單另行配置 |

本機節流只涵蓋共用相同資料目錄的應用程序，不會限制同帳號其他工具或其他主機的模型請求；團隊使用 AWS CLI 或新增服務時仍須共同遵守帳號的請求限制。

## 快速開始（macOS / Linux，Python 3.12）

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements-ocr.txt
cp .env.example .env
```

編輯 `.env` 的 `AWS_PROFILE` 與 `REFERENCE_DATA_DIR`，然後：

```bash
./start.sh
```

開啟 http://127.0.0.1:8000 。`start.sh` 會載入本機 `.env`；直接執行 `python run.py` 則使用該 shell 已存在的環境變數。首次 OCR 會下載官方模型至使用者的 PaddleX 快取目錄，需可連線網路；下載內容是模型，PDF 由本機處理。

原生 JavaScript / CSS 由 FastAPI 提供，不需前端建置。`npm` 僅用於 Playwright 測試與簡報工具。

## AWS 身分與模型

AWS 憑證使用 SDK 標準查找鏈，不寫進程式或提交 Git。可使用臨時 session credentials、AWS CLI profile、EC2 instance role，或 SDK 支援的 Bedrock API key。

```bash
aws configure --profile landwise-hackathon
# 臨時憑證另外需要 session token；請使用 AWS CLI 或受保護的 ~/.aws/credentials 設定。
aws sts get-caller-identity --profile landwise-hackathon
```

本地 `.env` 僅需選擇 profile 與非機密設定：

```bash
AWS_PROFILE=landwise-hackathon
AWS_DEFAULT_REGION=us-west-2
BEDROCK_MODEL_ID=qwen.qwen3-32b-v1:0
BEDROCK_ENABLED=true
```

若使用 Bedrock API key，可在啟動 shell 設定 `AWS_BEARER_TOKEN_BEDROCK`；不要將其加入 Git。使用 EC2 role 時移除 `AWS_PROFILE`，讓 SDK 使用 instance role。模型須支援 Converse，並在所選區域具有實際呼叫權限。

預設使用區域內的 `qwen.qwen3-32b-v1:0`。此版本拒絕跨區 inference profile，避免隱含跨區路由。`/api/health` 顯示提供者、模型與區域；設定成功不代表憑證仍有效，實際呼叫錯誤會顯示可處理的訊息。

## 使用流程

1. 建立案件，或上傳 20 MB 以內、最多 200 頁的 PDF。
2. PaddleOCR 將每頁轉為文字、文字框座標與信心值，保存原始 PDF。
3. 已知版型解析器盡可能建立欄位草稿；無法對應時保留待確認。
4. 如需 AI，按「AWS AI 抽取」，確認此文件符合競賽上雲規範後，將辨識文字送至 Bedrock。
5. AI 使用案件選定的基準整理欄位；引用與所述值必須能在 OCR 原文中找到。勾選套用後仍需人工核對。
6. 規則引擎核對等級、修正率、加總與跨表數值；每次修改保存版本及快照。
7. 匯出 CSV、JSON、可列印審查報告與整理書表。

內建案例是 `app/domain/sample.py` 的人工整理資料，並非現場 AI 推論結果。提供範例的文字層只用於內建原文與既有解析器回歸測試；**使用者的 PDF 上傳入口固定走 PaddleOCR，不會靜默改用文字層抽取。**

## DDD 結構

以「估價審查」為一個 bounded context，採模組化單體與 ports/adapters：

```text
app/
  domain/          Case、Factor、Evidence、Totals、規則及審查計算
  application/     案件操作、PDF 匯入、AI 草稿、來源驗證、介面契約
  infrastructure/  PaddleOCR、Bedrock、SQLite、檔案與環境設定
  interfaces/      FastAPI HTTP 路由、CSV / HTML 等輸出
  bootstrap.py     注入具體 PDF / AI / repository adapters
  main.py          ASGI 入口
static/            操作介面
scripts/           合成資料整合測試、教學與簡報工具
tests/             領域、應用流程、介接契約及選用真實 OCR 測試
```

領域與應用層不依賴 FastAPI、Paddle、AWS 或 SQLite。舊的 `app.models` / `engine` / `rules` 等保留相容匯入，實作已搬入上述各層。詳見 [架構與部署邊界](docs/architecture.md)。

## 資料與設定

預設案件、版本、辨識文字與抽取快取存於 `data/review.sqlite3`，上傳檔案存於 `data/uploads/`。`APP_DATA_DIR` 可指定資料目錄；同一台主機的服務程序須共用此目錄，才能共用 Bedrock 節流與快取。

`REFERENCE_DATA_DIR` 預設為相鄰的 `../aws`，支援其中 `範例/`、`其他參考資料/` 的既有目錄配置；找不到時才檢查專案根目錄。原始規範及案例 PDF 不會被複製進 Git。

| 設定 | 預設 | 用途 |
| --- | --- | --- |
| `AWS_DEFAULT_REGION` | `us-west-2` | 也接受優先的 `AWS_REGION`；僅允許競賽指定兩區 |
| `BEDROCK_MODEL_ID` | `qwen.qwen3-32b-v1:0` | 區域內 Converse 模型 |
| `BEDROCK_ENABLED` | `true` | `false` 關閉雲端 AI，仍可使用 OCR 與規則 |
| `BEDROCK_MIN_INTERVAL` | `1.1` 秒 | 所有模型嘗試間隔，包含重試 |
| `OCR_DPI` | `180` | PDF 轉圖片解析度（72–300） |
| `OCR_CPU_THREADS` | `2` | CPU 執行緒數（1–8） |
| `OCR_TIMEOUT_SECONDS` | `300` | 每份 PDF 的辨識逾時，首次下載可暫提高 |
| `OCR_DETECTION_MODEL` | `PP-OCRv5_mobile_det` | 文字偵測模型 |
| `OCR_RECOGNITION_MODEL` | `PP-OCRv5_server_rec` | 文字辨識模型 |
| `SEED_EXAMPLES` | `true` | AWS 環境應設 `false`，只匯入符合規範的資料 |

OCR 在獨立子程序執行；超過時間會終止，不把 AWS 憑證環境變數傳給子程序。每頁限制最大約 1,400 萬像素。長文件或密集表格請拆分；AI 輸入上限為 60,000 字元，模型截斷輸出不會成為草稿。

## 競賽環境

依相鄰 aws 資料夾的 2026-07-22 規範：

- 預設 `us-west-2`；亦可設定 `us-east-1`。
- OCR 使用 CPU，不依賴配額為 0 的 EC2 G / P GPU 系列。
- Bedrock 每次呼叫及重試都通過跨程序鎖與持久化節流；SDK 自動重試已關閉。相同 PDF / OCR 設定及相同 AI 輸入 / 模型 / 基準 / prompt 版本可重用快取。
- 呼叫前須確認資料符合規範。禁止個資、財務資訊等受限資料；附件價格資料的適用界線須由主辦說明，程式中的勾選不是自動合規認證。
- 本次沒有建立 AWS 主機、S3、RDS 或對外服務。未來部署須符合私有 S3、必要 Security Group 權限與非公開資料庫等要求。

目前的協調機制適用於**單台主機、共用 SQLite 與鎖檔**。多台 EC2 各自儲存的資料庫無法共用節流；擴充時需改用集中式請求工作程序。應用程式也無法限制同帳號中其他程式自行呼叫 Bedrock。

## 基準及計算設計

既有金山 ruleset 結構包含 `scope`、`unit`、`bands`、`matrix`、`source_page`，矩陣為
**列＝比準地、欄＝比較標的**。樹林普通住宅的獨立 domain API 則以明確參數名稱保存其表格語意：
**列＝目標區段、欄＝基準區段**；兩者尚未串接，不可在整合時直接混用方向。矩陣儲存百分點，
計算時才除以 100。採用 `Decimal`，不以二進位浮點數累加。

- 數值級距採「下限含、上限不含」，深度包含不連續級距（未滿 10 m 或 100 m 以上均為劣）。
- 文字分類只對照明訂值；`null` / 空白、`0`、`無` 與免比較不混用。
- 匯入欄位未確認、基準適用性不符、基準被封鎖、特殊調整 / 免比較或未定義級距，均不自動通過。
- 原填加總與基準重算分開顯示。上游不完整時不輸出基準總額；原填數值齊全時仍可做純算術一致性檢核。
- 絕對值加總＝日期調整率絕對值＋區域細項絕對值之和＋個別細項絕對值之和，避免正負相消。
- 本 MVP 日期單價公式：正常單價 × (1 + 日期調整率)，顯示取整元；試算價格公式：基準日單價 × (1 + 區域調整率) × (1 + 個別調整率)，四捨五入至元。
- **範本中間精度不可完全由顯示值還原**：184,763 × 1.02 = 188,458.26，範本填 188,459；188,459 × 1.13 = 212,958.67，範本填 212,958。價格差不超過 1 元時標示待確認精度，不直接認定錯誤，也不自動更正。

基準庫驗證矩陣尺寸、有限數值、同級零修正、重複分類及重疊級距。它無法認證使用者輸入的規則是否適合法規或案件。自訂版本需記錄正確來源，並自行確認。

### 原文件的待確認事項

`評價基準明細表範例.pdf` 第 2 頁「站牌」普通級距印為 `200km以上未滿400m`，第 3 頁「觀光遊憩」稍劣級距印為 `1,000km以上未滿1,500m`。內建規則保存為**封鎖的候選級距**（以 m 表示候選數字），並保留原文警告；不能直接執行判定。須確認來源後建立新版本。

區域交流道、廢棄物處理設施與環境污染範例沒有明確的「無」級距，保留資料不足。範本人工整理案例因此不會顯示完全通過。

手冊為民國 104 年 3 月版。本作品是提供文件的案例審查 MVP；正式上線前應確認適用版本及承辦人員的判定流程。

## 測試

一般測試不下載 OCR 模型、不呼叫 AWS：

```bash
.venv/bin/python -m pytest -q
```

外部範例 PDF 未安裝時，兩項範例檔測試會明確跳過。合成掃描 PDF 已隨測試提供。

執行真實 CPU OCR：

```bash
RUN_OCR_TESTS=1 .venv/bin/python -m pytest tests/test_paddle.py -q
```

走完整 HTTP 上傳、PaddleOCR、Bedrock 預覽、來源驗證及快取流程：

```bash
.venv/bin/python -m scripts.smoke_integrations --bedrock --profile landwise-hackathon
```

此命令只使用 `tests/fixtures/synthetic-scanned.pdf`，不含真實案件或價格。測試資料庫放在暫存目錄並自動清除，結果存於被 Git 忽略的 `.analysis/integration-smoke.json`。

瀏覽器測試使用真實 PaddleOCR；Bedrock 介面流程使用合成回應，不呼叫雲端：

```bash
npm ci
npx playwright install chromium
npm run test:e2e
```

已安裝 Google Chrome 時，可改用 `PLAYWRIGHT_CHANNEL=chrome npm run test:e2e`。

### Agent 工具與回答驗收

可用 `.venv/bin/python -m scripts.evaluate_agent --bedrock --profile landwise-hackathon` 跑六題合成驗收；省略 --bedrock 僅檢查測資，不呼叫 AWS。包括規則／計算工具、缺來源、錯版本、缺值與矛盾來源；[執行方式與實測結果](docs/agent-evaluation.md)。

## 目前功能邊界

目前應用流程仍是金山商業用地、單一比較標的範例。樹林普通住宅已具備獨立的純 domain
計算、分級與價格修正率 API，但尚未接入案件模型、ruleset repository 或 HTTP；因此仍不能視為
已完成三筆比較標的流程或官方表格套印。PaddleOCR 能辨識更多 PDF，也不代表已完成不同案件的
端到端流程。保留 OCR 框座標供後續定位，目前介面仍以頁與文字引用對照。AI 引用存在不保證左右欄對應正確。

沒有多人帳號、正式簽章、分散式任務佇列或正式 AWS 部署；預設僅監聽 `127.0.0.1`。

## 實作依據

- [PaddleOCR Python 使用方式與輸出結構](https://www.paddleocr.ai/main/en/quick_start.html)
- [PaddleOCR PP-OCRv5 多語系模型](https://paddlepaddle.github.io/PaddleOCR/latest/version3.x/algorithm/PP-OCRv5/PP-OCRv5_multi_languages.html)
- [AWS Bedrock Converse API](https://docs.aws.amazon.com/boto3/latest/reference/services/bedrock-runtime/client/converse.html)
- [Bedrock API key 使用方式](https://docs.aws.amazon.com/bedrock/latest/userguide/api-keys-use.html)
