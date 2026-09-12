# Coding agent 開發入口

開始修改前，依序閱讀：

1. [開發 TODO 與分工](docs/TODO.md)：確認本次任務 ID、前置工作、負責範圍與驗收條件。
2. [目前架構](docs/architecture.md)及 [README](README.md)：分清楚已實作能力與規劃中的能力。
3. 本次修改目錄的 `AGENTS.md`：`app/domain/`、`app/application/`、`app/infrastructure/`、`app/interfaces/`、`static/`。

這份 TODO 是後續工作清單，不是一次執行全部功能的授權。依使用者指定任務開發；缺少實際規則來源時記錄待確認，不自行杜撰估價公式。

## DDD 邊界

- 本專案是「估價審查」單一 bounded context 的模組化單體。
- `domain` 保存模型、規則、計算與不變條件，不 import application、HTTP、SQLite、OCR 或 AWS。
- `application` 編排用例、定義 ports／輸入輸出契約，只依賴 domain 與自身契約，不 import infrastructure 或 interfaces。
- `infrastructure` 實作 ports，處理 PaddleOCR、Bedrock、檢索、PDF 產製與持久化，不決定估價規則。
- `interfaces` 和 `static` 處理輸入、輸出與操作介面，不複製計算公式。
- `app/bootstrap.py` 是 adapter 注入入口。既有 `app/models.py` 等相容入口不放新業務邏輯。

## 多人與多 agent 協作

- 開始前查看 Git 狀態及 open PR，依 TODO ID 確認是否已有人開發；在 PR 描述標示任務 ID、負責目錄及相依 PR。
- 每位開發者使用自己的 branch／worktree／checkout。保留其他人的變更，不任意重置、清除或覆蓋共用工作區。
- `domain/models.py`、`application/ports.py`、`bootstrap.py` 及資料庫 schema 是共用契約；變更時列出受影響模組與相容方案。相依工作可先拆出契約 PR。
- 目錄分工代表責任範圍；必要的跨層修改要在 PR 說明，不能為了避開分工而繞過 ports。
- TODO 狀態及 PR 連結只更新本次任務的列。完成須有驗收證據，不能以空介面或 stub 宣稱功能完成。

## GitHub Flow

1. 從最新 `main` 建短期功能分支；命名可用 `feat/ddd-01-case-model` 或工具提供的前綴。
2. 以一項 TODO 或可獨立審查的切片為單位，實作、檢查並提交。
3. 推送到有寫入權限的 remote；沒有 upstream 權限時使用 fork，PR 目標為 `ChenYi0725/hackathon:main`。
4. 按 [PR 範本](.github/pull_request_template.md)填寫行為變更、DDD 範圍、測試與限制。開發中可用 Draft，完成後改為 ready for review。
5. 不直接 push `main`；未被要求時不自行合併 PR。相依 PR 尚未合併時明確標註，不混入其他人的功能。

## 驗證與資料

- 一般 Python 檢查：`.venv/bin/python -m pytest -q`；JS 修改另跑 `node --check static/app.js`。
- 涉及操作流程時跑 `PLAYWRIGHT_CHANNEL=chrome npm run test:e2e`，或使用本機已安裝的 Playwright 瀏覽器。
- 真實 OCR：`RUN_OCR_TESTS=1 .venv/bin/python -m pytest tests/test_paddle.py -q`。
- 雲端整合依 README 的 smoke 指令使用合成測資；一般測試不依賴有效 AWS 憑證或外部模型。文件修改只需檢查內容、連結與 diff，不新增無意義的程式測試。
- `.env` 與憑證不進 Git，非機密設定範例放 `.env.example`。不要把開發者的絕對路徑或 AWS 金鑰寫進共用文件。
- AI 產生草稿及說明；估價運算由確定性程式執行。上雲仍依競賽規範確認資料適用性；整合測試使用合成資料。

這份檔案是共用指引。`CLAUDE.md` 與 `.github/copilot-instructions.md` 只導向此處，避免各工具的規則分歧。
