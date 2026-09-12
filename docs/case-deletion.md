# DDD-11：最近案件刪除

「最近案件」每筆提供刪除按鈕。確認視窗顯示案件名稱與案號，使用者可取消；確認後移除案件並更新清單、件數及統計，保留搜尋條件。桌面與窄螢幕均可操作。

刪除無介面復原功能。案件使用且未被其他案件或來源共用的原始 PDF、OCR 文字及文件資料列會一併從本機刪除；案件的歷史快照也會清除。共用文件、共用基準與快取仍保留。僅保留不含案件內容的刪除 tombstone，以避免重啟時重新建立已刪除的內建範例；不提供案件復原。刪除案件後，案件讀取、儲存、匯出及修訂查詢回傳 404。

`DELETE /api/cases/{id}` 接收 `{"revision": 1}`，成功回傳 `{"deleted": "案件 ID"}`。缺少 revision 回傳 422，過期版本回傳 409，不存在的案件回傳 404。介面顯示錯誤並保留案件，使用者重新載入後可再操作。

HTTP 委派 `ReviewService.delete_case`，由 `ReviewRepository.delete_case` 在同一 SQLite transaction 核對 revision、刪除案件及留下刪除紀錄。清單新增 revision 欄位；現有欄位不變。新增 `has_case_history` port，避免全部刪除後重啟重新建立範例。無資料庫 schema 變更；其他 repository adapter 若新增實作，須支援這兩個方法。

負責目錄為 `app/application/`、`app/infrastructure/`、`app/interfaces/`、`static/`，跨層變更用於串接同一刪除用例。此切片依賴既有 v1 案件流程，沒有相依 PR。

驗收測試：

- `tests/test_case_deletion.py`：版本衝突、請求驗證、跨來源拒絕、其他案件與共用文件保留、未共用文件與 OCR 資料刪除、刪除後不可儲存回原案件、重啟不重新建立範例。
- `e2e/case-deletion.spec.js`：桌面與 390px 畫面取消／確認刪除、搜尋、統計、重新整理、衝突提示。

本機驗證：`python -X utf8 -m pytest -q` 為 1151 通過、3 跳過；`npm run test:e2e -- e2e/case-deletion.spec.js` 為 3 通過；`node --check static/app.js` 與 `git diff --check` 通過。Windows 預設 cp950 會使既有 UTF-8 測資讀取失敗，因此 Python 測試明確啟用 UTF-8 模式。
