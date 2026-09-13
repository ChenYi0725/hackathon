# AWS CPU OCR 比較（DDD-08，2026-09-13）

已在競賽 EC2 的獨立 checkout 與 Python 環境實測。**未切換正式網站**：全 mobile
模型雖較快，但會使原本可用的評價基準匯入失敗，不符合既定替換條件。

## 環境與方法

- 同一台 us-west-2、t3.large、Ubuntu 24.04 x86_64；CPU 2 執行緒、180 DPI。
- 測試程式固定於已合併的 `6e85f5827d09988f65409b72912eabd77ecb8161`（PR #20）。
- 原網站維持 `7b1ac57c98ffa8d98651be491d2a379e4ef93ccd` 與 PaddleOCR mobile det＋server rec。
- 獨立環境複製既有 venv，再安裝 `requirements-rapidocr.txt`；正式 venv、systemd
  設定及資料庫均未切換。測試使用合成 PDF 與暫存資料庫，不匯入真實案件。
- 一般、密集小字、淡色三份 PDF 各跑三次；暖機結果取後兩輪，共 216 個儲存格、
  108 個數字儲存格。精確比對含儲存格位置、正負號、小數點及百分比，僅忽略空白與字寬。
- 另用未參與上述三張表格評分的 `ruleset.pdf` 檢查完整基準匯入與矩陣；不能用
  一般表格的高分取代此流程驗收。

## 比較結果

| 候選 | 暖機平均秒／頁 | 正確儲存格 | 正確數字儲存格 | 基準匯入／決策 |
| --- | ---: | ---: | ---: | --- |
| PaddleOCR mobile det＋server rec（基線） | 16.694 | 212／216 | 108／108 | 真實 OCR 相關檢查 4 passed |
| RapidOCR 全 mobile | 3.725 | 216／216 | 108／108 | 3 passed、1 failed；不替換 |
| RapidOCR 全 mobile，220 DPI | 未完成速度評估 | — | — | 同一標題漏字，3 passed、1 failed；不替換 |
| PaddleOCR 全 mobile | 未完成速度評估 | — | — | 同一標題漏字，3 passed、1 failed；不替換 |
| RapidOCR mobile det＋server rec | 未完成暖機比較 | — | — | 首輪 clean／dense 分別 79.507／79.088 秒，停止此候選 |
| PaddleOCR＋MKLDNN | 執行失敗 | — | — | Paddle oneDNN `ConvertPirAttribute2RuntimeAttribute` 未實作錯誤 |

RapidOCR 全 mobile 在三張表格的暖機推論約快 4.48 倍，但不能據此宣稱可完整取代
原配置。它與 PaddleOCR 全 mobile 都把標題「住宅用地」辨識成「住宅地」，實際
`PaddleLayoutRulesetExtractor` 因缺少用地類別的完整標題而拒絕匯入。提高至 220 DPI
仍有相同錯誤。基線 server 模型通過同一份測試，這是可重現的功能退步。

本次沒有修改解析器補字、放寬標題驗證、移除失敗測試或降低原先的替換條件。

完整新程序處理單頁 `clean.pdf`，模型已下載，各跑三次並交替順序：基線中位數
**22.795 秒**，RapidOCR 全 mobile **5.886 秒**。暖機推論與此冷程序時間不可混用。

[機器可讀驗收摘要](evaluations/ocr-aws-2026-09-13.json) 包含逐次冷程序時間與真實 AWS smoke。

## 驗證範圍

- EC2 一般 Python：**1,194 passed、7 skipped**。跳過的外部測試不計為通過。
- EC2 真實 OCR：基線通過；mobile 的案件掃描文字檢查通過，但基準匯入失敗，詳見上表。
- EC2 真實 HTTP/TestClient → RapidOCR 全 mobile → Bedrock：通過。合成掃描 OCR 3.26 秒，
  Bedrock 2.32 秒；寬度 5／7、道路寬度 18／6，來源引用與快取驗證成功，AI 未修改案件。
- 本機 Chrome：RapidOCR 全 mobile 設定 **11 passed**；含真實掃描上傳及來源上傳。
  部分 UI 測試使用合成 API 回應，因此不能據此推翻 EC2 的真實基準匯入失敗。

## 重跑與後續

在裝有兩份 OCR requirements 的獨立 AWS checkout 執行：

```bash
python -m scripts.benchmark_ocr paddle_server --output paddle-server.json --repeats 3
python -m scripts.benchmark_ocr rapid_mobile --output rapid-mobile.json --repeats 3
RUN_OCR_TESTS=1 OCR_RECOGNITION_MODEL=PP-OCRv5_mobile_rec \
  python -m pytest tests/test_paddle.py tests/test_ocr_engines.py -q -k rapidocr
```

測試環境保留於 EC2 的 `/opt/landwise-ocr-mobile-20260913`，原始報告在
`/var/lib/landwise/ocr-eval-20260913`。正式網站仍使用原來的服務與 OCR 設定。
下一個可獨立審查的切片是依文件用途分配 OCR：案件草稿評估 mobile，基準文件保留
通過驗收的配置；此分流尚未實作，不能以本次測試宣稱完成。
