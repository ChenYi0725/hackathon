# 新北市官方資料 API（DDD-10）

在案件的「依據問答」輸入問題，確認上雲適用性後按「Agent 自動查詢」。例如：

> 請搜尋新北市地政局「實價 樹林」資料集，讀取第一頁一筆資料，列出原始欄位、API 來源與取得時間；無欄位定義時不要猜測。

Agent 現在可先搜尋官方資料集，再取得 JSON 資料。此模式沿用既有 Bedrock 設定；本機查找和一般 AWS 生成說明仍只使用已上傳文件。官方 API 本身不需 API key，首次查詢才連線，啟動與一般測試不會呼叫官方網站。

## 已確認的官方介面

- [開發指引](https://data.ntpc.gov.tw/applications)：JSON 分頁使用 `page`（從 0 開始）與 `size`。
- [OpenAPI 機關目錄](https://data.ntpc.gov.tw/api/v1/openapi/swagger/config)。
- [地政局 OpenAPI](https://data.ntpc.gov.tw/api/v1/openapi/units/1110000)：從 `paths` 的 JSON GET 操作動態取得資料集 ID、名稱與描述，不把搜尋引擎結果當資料。
- 2026-09-12 實測找到「不動產實價登錄資訊-租賃案件-樹林區」，並成功讀取[第一頁一筆](https://data.ntpc.gov.tw/api/datasets/5588f4c3-b929-4fe9-b420-0d7960b20b6f/json?page=0&size=1)。資料回傳 `district`、`rps01` 等欄位；未確認的欄位定義不自行推測。

## 工具與範圍

| 工具 | 用法 |
| --- | --- |
| `search_public_datasets` | `{"keyword":"實價 樹林","unit":"1110000"}`；空格分隔關鍵字全部匹配名稱或描述，每次最多十筆資料集，超出時需縮小查詢 |
| `read_public_dataset` | `{"dataset_id":"搜尋回傳的 ID","page":0,"size":5}`；必須先在本次 Agent 查詢中搜尋到，每頁最多十筆 |

支援機關：地政 `1110000`（預設）、交通 `1130000`、教育 `1050000`、工務 `1060000`、水利 `1070000`、城鄉 `1090000`、環保 `1220000`、衛生 `1240000`、捷運 `1280000`、觀光 `1040000`。每次搜尋僅查一個機關，無命中不代表整個市府沒有資料。

仍使用 `POST /api/cases/{id}/agent-evidence` 與既有 request。回應新增 `public_sources`，包含原始資料列、資料集名稱、精確 API URL、取得時間、分頁與內容雜湊 ID。最終引用允許本次讀到的非空公開資料來源；PDF 的 `hits` 契約不變。目錄與空頁不能用作事實引用。畫面顯示原始資料與官方連結，不修改案件、確認狀態、資料庫 schema 或計算規則。

Application 新增 `OpenDataProvider` port，Infrastructure 的 `NtpcOpenData` 實作它；`bootstrap.py` 注入 Agent，HTTP 仍委派既有用例。新增可選注入參數供整合測試替身使用，既有呼叫方式保持相容。共用 `ports.py`、domain 與 schema 無變更。

## 限制與故障處理

- 這是資料集探索與有限分頁讀取，尚無全資料集資料列搜尋、地址定位、距離計算或自動補入案件欄位。不是所有未知資訊都有官方 API，查不到時保留待確認。
- 現在取得的資料不等於估價基準日的歷史資料。回應中的取得時間不是官方更新日或生效日；需核對資料列本身的期間、地區與單位。缺值、缺欄位、空頁不能補零或推論設施不存在。
- 未修改既有五輪推論／八次工具預算；大片資料不能在單次問題中全部讀完。`next_page` 僅表示滿頁時可嘗試下一頁，不表示官方已確認下一頁有資料。
- 官方目錄快取一小時、資料頁五分鐘，最多 32 個快取項目，重啟即清除；命中快取保留原取得時間。每次 HTTP I/O 逾時十秒、解壓後回應限制 8 MiB，供 Agent 使用的單頁原文限制 8,000 字元。API 錯誤明確回傳工具錯誤，不冒充空結果。
- 僅連線固定官方網域與經驗證的資料路徑，不跟隨轉址，不傳送案件文件給市府 API。工具回傳資料仍會交給 Bedrock，因此沿用現有上雲確認流程。
- 本機 Python 3.13 實測遇到憑證鏈缺少 Subject Key Identifier；adapter 對此 client 採 Python 3.12 預設使用的非 strict X.509 相容模式，保留 CA、有效期及 hostname 驗證，沒有使用 `verify=False`。參考 [Python ssl 說明](https://docs.python.org/3/library/ssl.html)。

## 驗證

```bash
python -X utf8 -m pytest -q
node --check static/app.js
PLAYWRIGHT_CHANNEL=chrome npm run test:e2e -- e2e/open-data.spec.js
python -m scripts.smoke_ntpc
```

Windows PowerShell 先設 `$env:PLAYWRIGHT_CHANNEL='chrome'` 再執行 npm。`-X utf8` 避免 Windows 預設 cp950 無法讀取既有 UTF-8 測資。

一般測試以合成 HTTP 回應驗證目錄探索、分頁、快取、逾時、錯誤格式、轉址拒絕、來源引用、未搜尋資料集拒讀、revision 衝突與案件不被修改；HTTP 整合測試走完整 Agent endpoint。瀏覽器以合成回應驗證桌面與手機引用與 HTML escaping。

2026-09-12 本機驗收：Python **1,149 passed、3 skipped**；Chrome 桌面／手機 **2 passed**；JS 語法與 `git diff --check` 通過。Playwright 在 Windows 結束測試後等待測試伺服器退出，停止本次啟動的伺服器後正常回傳 exit 0。

`scripts.smoke_ntpc` 是選用真實網路驗證，只搜尋官方目錄並讀一筆，輸出來源與欄位名稱，不呼叫 Bedrock、不使用案件資料。真實 Bedrock 模型選工具與回答品質未在本次呼叫驗證。
