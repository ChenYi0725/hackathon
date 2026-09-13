# AWS Knowledge Bases 與 Agent 工具流程

本次為 DDD-07 切片。`RAG_BACKEND=bedrock-kb` 時，一般依據查詢與 Agent 的 `search_evidence` 都使用 Amazon Bedrock Knowledge Bases；由 Titan Text Embeddings v2 建立向量，存於 S3 Vectors。文件與 OCR 原文片段放 S3。案件、修訂、已確認基準與來源指紋繼續保存於 EC2 的 SQLite。

輸入 → 案件版本／基準適用性檢查 → Bedrock 模型選工具 → Knowledge Bases 查規範／政府 API 查候選／domain 函式計算 → 來源驗證與待核對結果。模型使用 Bedrock Converse；工具執行迴圈仍由 EC2 application 管理，**不是 Amazon Bedrock Agents**。先前帳號的 `CreateAgent` 被組織 SCP 拒絕，本次不更動該政策。

## 已接工具

| 工具 | 實際用途 |
| --- | --- |
| `search_evidence` | AWS 語意檢索，限制基準 ID、版本、地區、用地、起迄日期 |
| `read_source_page` | 擴讀已取得引用的同一原文頁面 |
| `get_rule` | 查看已保存的規則設定，不視為法規引用 |
| `inspect_case` | 讀案件欄位、確認狀態、缺漏及此次使用者補充量測 |
| `list_data_sources` | 既有新北市／教育部 45 個來源及需勘查的欄位 |
| `query_public_data` | 依 source key 選一個既有 API；地區固定為案件地區，最多回 10 筆候選及原始連結 |
| `calculate_factor` | 選一個規則 ID，用既有 `review` 引擎取得級距／矩陣修正率或待確認原因 |
| `calculate_measurement` | 選用 domain 的道路平均寬度、建築密度或公尺平面直線距離；只讀使用者量測，不接受模型數值或公式 |
| `review_case` | 既有整案確定性審查，含總修正數、跨表、日期調整與試算 |

每次至多 8 輪、12 次工具，保留最後一輪回答。計算不由 AI 算術，也不從檢索文件產生任意可執行公式。量測計算須提供本次檢索到的規範引用；引用存在不代表已證明語意支持所選公式，結果仍需人工核對。案件版本在模型與工具前後檢查，查詢不寫回案件或確認欄位。

## 網站操作

1. 開案件的「依據問答」，於來源管理加入適用版本的 PDF 與有效日期。
2. 確認資料符合上雲規範後，按「同步這個基準至 AWS 知識庫」，再查同步狀態。OCR 上傳與新基準確認不會偷偷觸發雲端上傳。
3. 同步完成後可按「AWS 查找來源」或「Agent 自動查詢」。例如：「找道路寬度規範，查缺欄位與公園 API，選擇適用計算並審查」。
4. 有原始量測值時展開「補充量測資料」，依比準地／比較標的輸入道路寬度、面積或公尺座標。此資料只供本次預覽，不會儲存為已確認案件值。

API 候選保留來源連結、查詢時間與行政區；不聲稱現時資料適用歷史估價日期。區段歸屬、距離、缺漏欄位仍需核對；查無資料不等於不存在。學校來源需明示學年度；大型工廠／公車清冊仍由既有非同步報表處理。尚未登錄的其他 API 不會由模型任意拼網址，需先加入可驗證 adapter。本次不自動套用候選、不實作通用地址定位或道路路線量測。

## 部署

`deploy/bedrock-kb.json` 建立私有加密 S3、S3 Vectors index、Knowledge Base、S3 data source 與最小 IAM policy。`AppRoleName` 指向既有 EC2 role，無新增長效金鑰；先檢視 CloudFormation change set 再執行。資料資源設 Retain，刪 stack 不等於刪資料，須由管理者另行處理保留資源。

由 stack outputs 設定：

```bash
RAG_BACKEND=bedrock-kb
BEDROCK_KNOWLEDGE_BASE_ID=<KnowledgeBaseId>
BEDROCK_KB_DATA_SOURCE_ID=<DataSourceId>
EVIDENCE_S3_BUCKET=<EvidenceBucket>
EVIDENCE_S3_PREFIX=landwise/
AWS_DEFAULT_REGION=us-west-2
```

EC2 使用 instance role，勿設定開發用 `AWS_PROFILE`。OCR 模型、案件 SQLite 與確定性公式不因切換 KB 而替換。未填完整 KB 設定時啟動失敗；AWS 出錯不會默默改成本機 BM25。

來源同步先核對 PDF SHA-256，使用 800 字元、680 字元步長預切片，metadata 包含文件／範圍／頁碼／字元位移；data source 使用 `NONE` chunking，只索引 `landwise/chunks/`。同步是顯式上傳加 AWS ingestion job，須待 `COMPLETE` 且失敗文件數為零。中断可重試相同物件；上傳狀態不當作索引完成。

回傳片段再次比對保存的 scope、SHA、S3 URI、頁碼、位移與完整原文；只容許 AWS 裁切片段首尾空白，再還原原始引文及位移，內文空格／數字變動仍拒絕。不可驗證片段丟棄。SQLite 保存的原文讓引用連結仍能開到原始 PDF。更換來源 metadata 後須再次同步。

## 驗證

2026-09-13 已部署程式 `d894e39` 至 EC2，健康檢查為 `bedrock-kb`；部署前後案件、基準、文件及 audit 表雜湊一致。EC2 instance role 真實測試完成「AWS 索引／檢索 → 模型選計算 → 政府 API → 審查」，道路寬度 6、8、10 回 8 公尺與一個 API 來源；無案件寫入。本機最終 Python 1,213 passed／7 skipped，EC2 基線 1,212 passed／7 skipped，修正後 RAG 回歸 62 passed；Chrome 12 passed。

既有 3 份合成來源已同步；正式 HTTP 對 4 個既有合成案件查詢皆回傳引用。此步實測發現 AWS 去除片段開頭縮排，已修正為只容許首尾裁切並恢復原始引文。詳細結果見 [機器可讀驗收](evaluations/aws-kb-2026-09-13.json)。**目前雲端內容為合成測試資料；正式規範與適用日期尚需匯入，不能宣稱已建立完整法規知識庫。**

一般測試不使用外部服務：`python -m pytest -q`。瀏覽器驗證 `PLAYWRIGHT_CHANNEL=chrome npm run test:e2e`，AWS 與 API 回應以替身驗證呈現／同意／缺值流程。

真實整合使用獨立暫存 SQLite 與自行產生的合成 PDF，會上傳少量合成 S3 物件並產生索引費用：

```bash
python scripts/smoke_aws_kb.py
python scripts/smoke_aws_kb.py --agent
```

第二個指令另外實際呼叫 Bedrock 模型與政府 API，驗證 Agent 選函式、API 與審查。模型選擇與政府資料可用性可能導致 smoke 失敗，不能用替身測試代替雲端成功證據。

AWS 格式依 [S3 data source](https://docs.aws.amazon.com/bedrock/latest/userguide/s3-data-source-connector.html)、[S3 Vectors KB](https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-vectors-bedrock-kb.html) 與 [CloudFormation S3VectorsConfiguration](https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-properties-bedrock-knowledgebase-s3vectorsconfiguration.html)。
