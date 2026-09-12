# 共用契約 1.2：確認失效與目標資料模型（DDD-00）

本文件是 Domain、Application、Infrastructure 與 Interfaces 開發者共用的契約。**第一節的 v1 確認失效已在本次實作；第二至七節是 DDD-01 至 DDD-08 的目標 schema v2，尚未提供 v2 API、完整 v2 ports、資料遷移或 PDF renderer。** 不得把目標契約當成已存在的可呼叫功能。第八節為已接線的 v1 RAG 增量。

## 0. 已實作的核心流程相容增量

目前另有 [核心流程契約與驗收](core-workflow.md)：`Case.document_ids`、逐欄 `field_sources`、`change_reason`、最多兩筆 `additional_comparisons`（加上既有第一筆，共三筆）。各比較標的有穩定 ID、自己的 factors／totals／確認狀態；並未將原欄位拆除或宣稱完成以下所有 v2 契約。

`Evidence` 增加可選 document_id、sha256、sheet、cell、formula。文件來源採用透過用例驗證案件關聯與實際儲存格。`review_runs` 保存不可覆寫的案件、規則、證據與結果；`dispositions` 將人工處置與技術判定分開，操作 ID 防止重試重複。

`CaseDocumentReader`、`SnapshotRenderer`、`ExternalEvidence` ports 已在 `application/ports.py` 定義，於 bootstrap 注入。新增 `/review`、`/documents`、`/apply-cell`、`/decisions`、`/external`、`/artifacts/{kind}`；既有 API 保持可讀。`artifacts` 必須帶 revision 及 run_id，前後核對版本。原 HTML forms 對多標的回覆 400，明確引導完整 Excel／ZIP，不取第一筆冒充整案。

## 1. 現行 v1：確認只適用於已保存內容

確認失效規則由 `app/domain/confirmation.py` 定義，application 在一般保存、JSON 建立／匯入及採用建議時執行。HTTP payload 保持原格式，不新增必填欄位。

| 變更 | 必須清除的確認 |
| --- | --- |
| 新增／匯入案件 | 所有 `Factor.confirmed` 與 `totals_confirmed` |
| 因素的條件、原填修正率、等級、免比較、特殊調整備註或 evidence 改變 | 該因素與總計 |
| 新增／刪除因素 | 新因素與總計；其他未改變因素保留 |
| `Totals` 任一值改變 | 總計，保留因素確認 |
| 基準 ID、文件 ID、地區、用地類別、估價日、兩側名稱／區段改變 | 所有因素與總計 |
| 案件名稱、案號、一般案件備註改變，或因素陣列重新排序 | 不因這些變更清除確認 |
| 相同內容上的確認／取消確認 | 接受使用者的新確認值，不當成數值修改 |

- 依因素 ID 比較內容，字串採精確比較，數字使用既有模型驗證後的值；`0` 與 `null` 不相同。
- 即使 PUT 同時帶入新值與 `confirmed=true`，後端仍將受影響確認設為 false。必須先保存新內容，再以回傳 revision 提交確認；用過期 revision 一律回傳 409，不寫入案件或 audit。
- 介面在修改後立即取消並暫停相關確認勾選，保存成功後重新開放。儲存期間暫停編輯，避免回應覆蓋儲存期間的新輸入；失敗保留未存內容，重新嘗試。
- 原填資料與確認失效狀態一起保存成同一筆 audit snapshot。Domain 判定未確認欄位為待確認；不能把因確認失效造成的 pending 改成 pass。
- 內建人工整理範例由專用 seed／sample 用例建立，保留範例本身的確認狀態；外部 POST 案件不能藉由 `demo` 或 `source_kind` 繞過失效。
- 舊案件載入時不批次重置，也不宣稱可追溯補出過去曾修改但未重新確認的紀錄。新規則自本次後的保存操作生效。

## 2. 目標 schema v2：身分、來源與精度

Domain 型別由 Domain 維護；port DTO 由 Application 維護。預計分別位於 `app/domain/models.py` 及 `app/application/contracts.py`，不得各 adapter 自訂相同概念的另一套型別。

| 型別 | 必要資料與約束 |
| --- | --- |
| `CaseSnapshot` | `schema_version=2`、`id`、`revision`、title、case_number、valuation_date、valuation_date_raw、locality、land_use、ruleset_ref、subject、comparisons、documents、notes；讀取後不可就地修改，修改產生新快照 |
| `Subject` | 穩定 `id`、name、section；一案恰有一個比準地 |
| `Comparison` | 穩定 `id`、name、section、factors、entered_totals、totals_confirmation；列表支援 1–3 筆，先涵蓋現有一筆及題目三筆，不能依陣列位置辨識 |
| `FactorObservation` | `rule_id`、subject_value、comparable_value、entered_rate、subject_grade、comparable_grade、exempt、note、subject_evidence、comparable_evidence、rate_evidence、confirmation；同一 Comparison 的 rule_id 唯一 |
| `RulesetRef` | 不可覆寫的 `id`、`version`；案件綁定此版本，不以檢索分數或「最新版本」自動替換 |
| `DocumentRef` | `id`、原始 bytes 的 SHA-256、display_name、media_type；儲存 key 由 repository 管理，不接受用戶傳入任意檔案路徑 |
| `SourceSpan` | `document_id`、document_sha256、原文 quote、locator、method；每側值各自綁定來源，不能只引用另一側恰好出現的相同數字 |
| `Confirmation` | status 為 pending／confirmed；confirmed 時記錄 case_revision、content_hash、confirmed_at、confirmed_by（無身分系統時為 null，不虛構審查人） |

`valuation_date` 使用 ISO 日期或 null，原始字串保存在 `valuation_date_raw`。來源日期無法可靠轉換時保留 raw、將標準日期設 null 並標記待確認，不推定日期。

`locator` 採 tagged union：PDF 使用 `{kind: "pdf", page, bbox, page_width, page_height}`，page 從 1 起算；bbox 為渲染圖片左上原點的 `[x1,y1,x2,y2]` 像素座標，未知時 bbox 與尺寸同為 null。Excel 使用 `{kind: "xlsx", sheet, cell_range}`；此來源表示法不代表本次已支援 Excel 匯入。

- 新身分使用 UUID4 hex；穩定來源身分不因欄位修改或陣列排序而變更。
- Numeric value 表示為 `{kind: "quantity", value: DecimalString, unit}`；文字分類為 `{kind: "text", value: string}`；缺值為 null。「無」保留為文字，不能換成數值零。
- `DecimalString` 為有限十進位字串，無千分位、百分號或科學記號，最多 28 位有效數字；計算使用 Decimal precision 28，不經 float 中轉。
- 初版 quantity 單位為 `m`、`m2`、`TWD/m2`、`percentage_point`、`ratio`；unit 必須與因素／公式契約一致。修正率及權重一律使用百分點字串，例如 `"5"` 表示 5%，乘法時程式才除以 100。
- 未知資料保持 null；負數、上下限與免比較依該領域規則驗證，不由 renderer 或 LLM 補值。
- 捨入由具版本的 ruleset rounding profile 指定，每個公式輸出須有 quantum 與 Decimal rounding mode；中間值不沿用畫面捨入值。缺少來源支持的 rounding profile 時回傳待確認，不替住宅規則猜測整元精度。

## 3. 確認與計算快照的關聯

v2 延續第一節的失效範圍及兩步確認。因素 confirmation 的 `content_hash` 是其規則版本、案件適用背景、兩側身分、值與來源的規範化 JSON SHA-256；總計 confirmation 另包含全部比較資料、權重及原填總計。JSON 使用排序 key、UTF-8、無額外空白，Decimal 先正規化為無多餘小數尾零的字串。

metadata 改名可以建立新 case revision 而保留內容相同的確認；不能僅因 confirmation.case_revision 不是最新整案 revision 就清除它。內容依賴改變時 status 轉 pending，清除其確認 stamp。操作 actor／時間由服務提供，不信任用戶任意填入的審查人或時間。

`CalculationResult` 固定包含：

- `id`、case_id、case_revision、input_hash、ruleset_ref、engine_version、rounding_profile_version、generated_at。
- `comparisons[]`：comparison_id、各項 checks、computed_totals、trial_price、weight；原填值與重算值分開。
- `aggregate`：全案加權結果與檢查；任何必要資料未確認／缺漏時不輸出完整通過的最終值。
- `steps[]`：step_id、comparison_id、formula_id、formula_version、帶單位的 named inputs、input_refs、未捨入與捨入輸出、rounding、evidence_refs、status、reason_code。
- `status`／check status 沿用 pass、error、pending、missing。只有全部必要檢查通過才是 pass；免比較與特殊調整仍需明確處理，不自動視為零。

`input_hash` 使用整份已保存的 CaseSnapshot（不含 derived calculation）之規範化 JSON。相同輸入、規則、引擎與捨入版本應產生相同計算值；ID／產出時間不作數值一致性比較。

## 4. 五個目標 ports 與領域服務

下列為 v2 的行為契約，不改寫現有 v1 method signatures。新增版本由 DDD-04 一次接線；對外 SDK 型別不能進入這些契約。

| 元件 | 目標輸入／輸出 | 必須維持的行為 |
| --- | --- | --- |
| `PdfReader.read(pdf: bytes)` | `DocumentPages`：每頁 text、width、height、帶 bbox／confidence 的 lines、method | CPU OCR；不以辨識失敗後的文字層結果冒充成功；初次回傳的 page locator 在保存文件時綁定 DocumentRef |
| `FieldExtractor.extract(documents, ruleset, subject, comparisons)` | `ExtractionDraft`：帶 comparison_id／rule_id 的候選、三組 evidence、warnings、model_id、prompt_version | 只整理已知身分範圍的草稿，不確認或保存案件；unknown ID、錯誤引用、同因素衝突由 application 驗證並拒收，不讓模型創造標的 |
| `ReviewRepository` | 保存／載入 CaseSnapshot、RulesetSnapshot、DocumentSnapshot、CalculationResult 及 audit | `save_case(snapshot, expected_revision, action)` 原子比較 revision；計算結果 `save_calculation(result, expected_revision)` 必須對應當前快照，過期則拒絕 |
| `EvidenceRetriever.retrieve(query)` | `EvidenceQuery` → `EvidenceHit[]`，每項含 SourceSpan、ruleset_ref、適用範圍、相關性分數 | query 明訂 locality、land_use、valuation_date、ruleset_ref、rule_ids 及文字問題；先篩適用版本再排名。無依據回空列表，不推測規則 |
| `PdfRenderer.render(snapshot, calculation, template_ref, generated_at)` | `PdfArtifact`：PDF bytes、media_type、filename、sha256、case_revision、calculation_id、template_ref | application 先檢查 snapshot／result 的 ID、revision、hash 相符。只使用傳入結果；缺資料可產生明示草稿，不可補算／捏造欄位 |
| `ValuationCalculator.calculate(snapshot, ruleset)` | `CalculationResult` 的內容（ID／時間由 application 包裝） | 純領域服務，不呼叫 ports、檔案、網路或 LLM；公式只能來自程式定義的 formula_id／版本及已核准基準 |

Repository 延續現有 list/get/add rules、documents、audit 與 snapshot 能力，並新增 `get_calculation(id)`；具體 SQL、S3 路徑及鎖不暴露至 application。新計算完成後若案件已更新，拒絕附加為目前結論，不拿舊結果配新 PDF。

`RulesetSnapshot` 為完整規則、來源、適用地區／用地／期間、version、rounding profile、approval_state。新版本預設 draft；只有人工確認的 approved 版本可產生基準通過判定，來源不明或 blocked 的規則回待確認。現有規則的核准狀態由 DDD-01 按來源補齊，不能把所有歷史 custom rules 無條件標成 approved。

PDF 模板 ID 初版固定為 `review-report` 與 `appraisal-forms`，每份有 version。產製前核對文件／結果版本，產製後驗證 PDF 與版面。未支援的 template version 明確拒絕，不偷偷換模板。

## 5. 錯誤與 HTTP 演進

- application/domain 使用現有 `RevisionConflict`、`ExtractionUnavailable`、`ValueError`、`KeyError` 的語意；adapter 不傳出 AWS upstream 訊息或憑證。
- v1 仍使用目前 `/api/...` 路徑與 JSON：修改輸入內容與 true flag 同送時回 200，但回傳清除確認後的實際案件；revision 衝突回 409。
- v2 在 `/api/v2/cases` 與 `/api/v2/cases/{id}` 提供新 schema，GET／POST／PUT 統一回 `{case, calculation}`，尚未計算時 calculation 為 null；AI 預覽、calculate、export 為該案件下的獨立子路徑。
- v2 PUT 帶目前 revision；calculate 及 AI preview 帶 case_revision；export 帶 case_revision、calculation_id、template_ref。回傳來源對應不明的草稿不可套用。
- v2 validation 使用 422，未知 ID 使用 404，過期 revision／計算快照不符使用 409，OCR／模型／renderer 不可用使用 503；錯誤 JSON 為 `{code, detail}`，detail 為可公開顯示文字。
- 升級後 v1 對單一標的仍提供平面格式；對多標的案件的讀取、修改及匯出回 409 `case_schema_unsupported`，提示使用 v2，不取第一筆冒充整案。v1 list 保留摘要並增加 `requires_v2`，不得將不支援案件默默遺漏。

## 6. 遷移與相容性

- DDD-03 在複本上驗證遷移並備份原庫。v1 audit snapshot 保留原 bytes／結構，不能把舊歷史改寫成新答案；新寫入才使用 v2。
- 舊 Case 的 id／revision 不變；Subject ID 使用 UUID5（NAMESPACE_URL，`landwise:{case_id}:subject`），單一 Comparison 使用 UUID5（同 namespace，`landwise:{case_id}:comparison:1`）。重跑遷移結果一致。
- 舊 factors 放入這筆 Comparison；old subject／comparable／entered_rate 分別映射 v2 欄位。已有 document_id 的引用綁定該 DocumentRef；原文未知時保留缺引用，不捏造 bbox。
- 舊數字從原始 JSON number 的十進位字面值轉成 DecimalString；已丟失的精度不能復原。原始字串／快照保留，無法轉換的值標示待人工處理。
- 舊確認 bool 可在 v1 相容檢視保留；首次轉為 v2 時統一 pending，因為舊資料沒有 content_hash、確認時間或審查人。這是 v2 遷移行為，不是本次 v1 載入行為。
- 案件適用性或規則不明時保留案件但停止自動通過；禁止以刪庫、換預設金山規則或截掉比較標的完成遷移。

## 7. 交付與驗收

| 工作 | 驗收重點 |
| --- | --- |
| 本次確認修正 | 直接 API 帶過期 true、換基準、變更引用／備註、因素增刪、總計修改、重新確認、stale revision、採用建議及 JSON 匯入 |
| DDD-01／02 | 三標的身分隔離、Decimal round-trip、不同規則版本、可重算 steps 與缺值拒算 |
| DDD-03／04 | v1 相容、遷移可重跑、audit 不變、CAS 與計算完成時版本衝突；ports 使用替身通過用例測試 |
| DDD-05／06 | PDF 引用精確快照、中文／長文字／分頁視覺驗證、三標的不串欄、過期 PDF 請求被拒絕 |
| DDD-07／08 | 檢索不跨基準版本、錯側引用拒收、合成測資完整流程；GraphRAG 不改變上述契約 |

GraphRAG 的選型、住宅公式來源核對及正式 PDF 模板實作仍依 [TODO](TODO.md) 分工，不在 DDD-00 實作。契約變更需更新本文版本與相依任務，不另開互不相容的 DTO。


## 8. v1 RAG 增量（DDD-07 提前切片）

`app/application/rag_contracts.py` 定義已實作的 EvidenceQuery、SourceSpan、EvidenceHit、AnswerDraft。沿用第四節 EvidenceRetriever 的 retrieve(query)，補入 EvidenceAnswerer.answer(question, hits) 作為生成說明的獨立 port，不混入抄錄欄位的 FieldExtractor。

- Query 的 ruleset_id／version、locality、land_use、valuation_date 由已保存案件及基準取得；HTTP 不接受另指定適用版本。rule_ids 可限制來源頁，未知 ID 拒絕。估價日接受 ISO 或既有民國 YYYMMDD；其他格式不猜測。
- SourceSpan 的 page／start／end 是 PDF OCR 文字的頁碼與 Python 字元區間，quote 為原切片；bbox 與尺寸只有能明確對應整頁片段時提供，其他情況為 null。v2 可包入 tagged PDF locator，保留字元區間作為額外定位。
- EvidenceHit 保存文件 ID、原 bytes SHA-256、基準 ID／version、地區、用地、人工指定的含首尾適用期間及排名分數。分數不是信心值。
- ReviewRepository 增加 save_evidence_document、list_evidence_documents、evidence_sources。來源 PDF 與綁定在同一 SQLite transaction 保存；只加 evidence_documents 表與索引，不遷移現有案件／audit。
- AnswerDraft 為 statements 陣列，每段有 text 與 citation_ids；ID 必須全部存在於本次 hits。無依據或模型回報不足時不展示回答。引用存在性檢查不保證語意支持。
- 本次 /api/cases/{id}/evidence 為唯讀 POST，帶 revision／question／generate／cloud_data_approved／rule_ids；回傳 case_revision、基準版本、hits、statements、status、message。狀態為 sources、no_evidence、insufficient_evidence、draft。
- v1 缺 ID 使用 404、revision 衝突 409、模型不可用 503；輸入結構及來源上傳錯誤 422，用例適用性或缺少上雲確認 400，沿用 v1 既有錯誤格式。
- generate=false 完全本機；true 須明確上雲確認，且有 hits 才呼叫模型。RAG 共享欄位抽取的 Bedrock 鎖、gate、有限重試與憑證鏈；快取隔離 prompt／model／region／問題與完整 hits。
- 資料來源綁定及 OCR 內容不等於規則核准；本次無 approved rules 自動提升、無估價運算、無基準自動切換、無 v2 API。v2 的主體／多標的及核准模型仍留給 DDD-01／04。


## 9. Agentic RAG 增量

Application 擁有 AgentModel.next_turn(context, history, tools) → AgentTurn；ToolCall、ToolResult 與四個工具的參數 schema 在 agent_contracts.py。AgentTurn.continuation 是 adapter 擁有的不透明往返信息，不由 application 解讀 AWS 欄位；SDK 型別不進入 domain。

agentic_rag.py 執行工具白名單與有界迴圈，使用既有 EvidenceRetriever、ReviewRepository 與 domain.review。新增唯讀 /api/cases/{id}/agent-evidence；不改 v1 Case、保存、確認或資料庫 schema。API 與預算見 [Agentic RAG 文件](agentic-rag.md)。原本純本機檢索與單次生成 API 保持相容。


### core-2 來源及快照相容補充

- `field_sources` 的逐欄引用優先；單一 `Factor.evidence` 為 Excel cell 時，不可作為同列其他欄位的推定來源。PDF 列來源與逐欄來源保留相容，但追加文件前會固定舊文件 ID。
- OCR／AI 草稿來源明確綁定文件；採用 AI 草稿同步替換 subject、comparable、entered_rate 的來源，不變更其他未採用欄位。
- `input_sources` 額外包含 subject_grade、comparable_grade。既有三個鍵保留，不修改數值 JSON 型別或資料庫 schema。
- `review_runs.engine_version` 使用 `core-2`；舊引擎快照仍可保存歷史，不能作為目前版本匯出或新增人工處置的依據。重新檢核保留案件 revision，但產生不同 run ID。
