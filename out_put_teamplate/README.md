# 輸出表格範例

此目錄收錄從 `problem_files/` 複製的三份 Excel 範例原檔，供核對輸出版型，也是應用程式預設的填值模板：

- 表3：地價區段勘查表。
- 表4：比較法調查估價表。
- 表5：影響地價區域因素分析明細表（住宅用地）。

範例保留原始內容，不是目前案件的審查成果。應用程式產生下載副本，不覆寫這些檔案。更換模板時須保留指定工作表名稱與填值位置，詳見[分表輸出說明](../docs/form-exports.md)。

產生填入合成資料的 Excel 範例：

```bash
python -m scripts.preview_form_exports
```

結果存於 `.analysis/form-preview/`，可用 `--out` 指定其他目錄。PDF 輸出已移除。
