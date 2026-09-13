# 沒有錯的地方架構流程圖

直接以瀏覽器開啟 [互動 HTML](landwise-architecture.html)，可切換深淺色、放大、追蹤關係及使用 Export 匯出。圖中 SRC 可查看已固定版本的程式來源。圖中文字為繁體中文；archify 未提供繁中 locale，固定操作介面與 HTML lang 沿用英文。

[JSON 規格](landwise.architecture.json) 由 archify 2.17 產製。圖以 11 個元件呈現 HTTP → 用例 → 確定性審查 → 匯出，以及 OCR、儲存、RAG 和 Bedrock 分支。三個虛線區塊同屬一台服務主機；它們是責任分組，不是三台主機或三個部署區域。Amazon Bedrock 為外部雲端服務。

箭頭表示呼叫或資料流，並非 Python import 關係。規則結果經 application 傳給匯出 adapter，domain 不呼叫 renderer。為保持總覽可讀性，未逐一展開回傳、repository 的每個使用者及 Agent 四工具的內部接線。原始 PDF 保存在檔案系統，SQLite 保存案件、版本及文件中繼資料。

目前單一比較標的、Excel 輸出等邊界依 README 與 docs/architecture.md；多標的完整整合與 GraphRAG 仍未提供。

## 重產與檢查

設定 `ARCHIFY_SKILL_DIR` 為已安裝 archify 的目錄，在 repository 根目錄執行：

```bash
node "$ARCHIFY_SKILL_DIR/bin/archify.mjs" validate architecture deliverables/archify/landwise.architecture.json --repo-root . --quality showcase --json
node "$ARCHIFY_SKILL_DIR/bin/archify.mjs" deliver architecture deliverables/archify/landwise.architecture.json deliverables/archify/landwise-architecture.html --repo-root . --quality showcase --json
node "$ARCHIFY_SKILL_DIR/bin/archify.mjs" visual-check deliverables/archify/landwise-architecture.html --json
```

來源固定於規格中的 repository revision。程式更新後應重新核對來源，再產製新圖。

[驗收紀錄](verification.json) 包含規格與 HTML 的完整 SHA-256、9/9 showcase 結果、4 種桌面尺寸瀏覽器量測，以及獨立的深淺色視覺檢查紀錄。本次沒有變更或重測應用程式功能，也沒有呼叫 AWS。
