# PaddleOCR GPU 接線（DDD-08）

程式支援 `OCR_DEVICE=cpu`（預設）或 `gpu:0`（單張 NVIDIA GPU）。GPU 模式仍使用相同
PaddleOCR、PDFium、文字框及欄位整理流程，只切換模型推論裝置；PDF 渲染與後處理仍在 CPU。
沒有變更 domain、application ports、ruleset 或資料庫 schema。

## 目前部署狀態

2026-09-12 透過 AWS Service Quotas 實際查詢：`us-west-2` 與 `us-east-1` 的
`Running On-Demand G and VT instances`（`L-DB2E81BA`）及
`All G and VT Spot Instance Requests`（`L-3819A6DF`）均為 **0 vCPU**。
目前網站的 `t3.large` 沒有 GPU。因此本切片是已接線、尚未完成 GPU 實機驗收的準備工作；
GPU 測試替身通過不代表真實 CUDA 推論通過，也不代表線上網站已改跑 GPU。

GPU 配額或可用主機確認前，現有網站繼續使用 CPU。本機 macOS 也不能用 NVIDIA CUDA 驗收。
配額調整須循競賽帳號及主辦允許的流程；AWS 提供
[EC2 quota increase](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/ec2-resource-limits.html) 申請，
核准前不能啟動超出配額的 GPU 執行個體。

## GPU 主機安裝

以下針對 Linux x86_64、Python 3.12、NVIDIA GPU；先安裝支援 CUDA 12.6 runtime 的 NVIDIA
驅動程式，確認 `nvidia-smi` 能看到 GPU。依
[Paddle 官方安裝說明](https://www.paddlepaddle.org.cn/documentation/docs/en/install/index_en.html)，
wheel 會處理 CUDA／cuDNN 套件，但主機仍須有相容的 NVIDIA 驅動。
3.3.1 的 Linux Python 3.12 wheel 已列於[官方 cu126 索引](https://www.paddlepaddle.org.cn/packages/stable/cu126/paddlepaddle-gpu/)。

使用獨立環境，不同時安裝 CPU `paddlepaddle` 與 `paddlepaddle-gpu`：

```bash
python3.12 -m venv .venv-gpu
.venv-gpu/bin/python -m pip install -r requirements-ocr-base.txt
.venv-gpu/bin/python -m pip install paddlepaddle-gpu==3.3.1 \
  --index-url https://www.paddlepaddle.org.cn/packages/stable/cu126/
.venv-gpu/bin/python -m pip check
.venv-gpu/bin/python -c 'import paddle; assert paddle.is_compiled_with_cuda(); assert paddle.device.cuda.device_count() > 0; paddle.utils.run_check()'
```

套件版本與 wheel 存在性已查核，GPU 安裝及 CUDA 運行仍須在實際 GPU 主機驗收。
現有 `requirements-ocr.txt` 繼續安裝 CPU 版；不要在 GPU 環境再次安裝它。

## 設定與驗收

服務設定加上 `OCR_DEVICE=gpu:0`，並讓啟動程序使用 GPU 環境的 Python。
例如在 GPU 主機透過 shell 執行：

```bash
OCR_DEVICE=gpu:0 .venv-gpu/bin/python run.py
```

`start.sh` 固定使用 `.venv`；使用額外的 `.venv-gpu` 時，須依上例直接啟動或調整 systemd
`ExecStart`。EC2 部署還要保留原本的 AWS region、資料目錄、模型節流及 `SEED_EXAMPLES=false`。
不能只改目前 CPU 主機的環境變數就當成 GPU 部署。

`/api/health` 的 `ocr_device` 是設定值，不會在 health request 時初始化 CUDA。
每次 OCR 的子程序會確認 CUDA build、GPU 編號及裝置可用性，再用明確的裝置參數初始化
PaddleOCR；無 GPU 時回傳可處理的 503，**不退回 CPU**。
OCR 頁面結果新增 `device`，原有 `method=paddleocr`、座標與引用格式保持相容。

CPU／GPU／GPU 編號均納入 OCR cache key，切換後不會拿另一裝置的舊結果假裝完成推論。
首次切換本版 CPU 設定也會重新建立 OCR 快取，既有案件和已存 OCR 頁面不被改寫。

真實 GPU 驗收使用合成掃描 PDF，未安裝 GPU 或 GPU 不可用時必須失敗：

```bash
RUN_GPU_OCR_TESTS=1 OCR_DEVICE=gpu:0 \
  .venv-gpu/bin/python -m pytest tests/test_ocr_device.py -q
OCR_DEVICE=gpu:0 .venv-gpu/bin/python -m scripts.smoke_integrations --bedrock
```

另外以 `nvidia-smi` 觀察辨識期間的 GPU 程序／記憶體，並檢查實際上傳頁面的 `device=gpu:0`、
文字與框座標；不可只憑 health 設定值或舊快取宣稱 GPU 成功。
既有 CPU 回歸可執行 `RUN_OCR_TESTS=1 ... -m pytest tests/test_paddle.py -q`。

切換 EC2 或 CUDA 環境前，先備份原資料並保留 CPU 環境；在 GPU 完成合成文件及完整 HTTP
流程驗收後才切換網站入口。既有 IP 白名單、instance role 與資料須保留。

## 已完成的本機驗證

- 一般測試：1,178 passed、5 skipped（包含未執行的真實 GPU 驗收）。
- 真實 CPU OCR：4 passed；無 GPU 的真實 runtime 指定 `gpu:0` 時明確拒絕執行。
- Chrome Playwright：11 passed，使用獨立測試 port 18012。
- CPU HTTP smoke 驗證裝置標記、文字及原文框；GPU 效能、VRAM、CUDA 驅動相容性仍未實測。
