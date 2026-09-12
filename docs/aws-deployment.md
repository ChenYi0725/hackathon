# AWS 單機部署（DDD-08）

本次將現有 FastAPI、PaddleOCR、SQLite、Excel 匯出及 Bedrock 功能部署到同一台 EC2。
不變更 domain、application ports 或資料庫 schema；本機案件不會自動搬上雲端。

## 部署內容

- `us-west-2`、Ubuntu 24.04 x86_64、`t3.large`（2 vCPU／8 GiB）。
- 40 GiB 加密 gp3 根磁碟；終止 EC2 時保留磁碟，避免連帶刪除案件。
- Nginx HTTP 80 → `127.0.0.1:8000`；單一 Uvicorn worker，systemd 自動啟動／故障重啟。
- Security Group 只接受四個指定 IPv4 與操作者目前出口 IPv4 `/32`；沒有開放 SSH、8000 或全網路 ingress。
- IAM instance role 僅包含 SSM 管理權限及區域內 Qwen3 模型的 `bedrock:InvokeModel`。
  使用 IMDSv2；不複製開發者的 access key、session token 或 `.env`。
- `SEED_EXAMPLES=false`；資料及 OCR 模型快取在 `/var/lib/landwise`，程式在 `/opt/landwise`。
- OCR 及 HTTP proxy timeout 支援長文件處理，模型首次下載在 bootstrap 預熱。

目前入口為 HTTP，沒有 TLS 或應用程式帳號；允許 IP 的使用者共用同一工作台及案件。
這是限制來源網路的競賽測試部署。需要加密連線可用下方 SSM tunnel；正式分享入口須另設 HTTPS。
單機 SQLite 沒有跨機備援、自動快照或背景工作佇列；停止主機時進行中的 OCR／AI 工作會中斷。

## 建立另一個環境

先選擇同區域的既有 public subnet、VPC，以及 Canonical 的 Ubuntu 24.04 amd64 AMI。
從專案根目錄產生模板（此步不呼叫 AWS）：

```bash
mkdir -p .analysis
python3 deploy/render_stack.py > .analysis/aws-stack.json
aws cloudformation validate-template --profile landwise-hackathon --region us-west-2 \
  --template-body file://.analysis/aws-stack.json
```

將非機密參數寫入本機 `.analysis/aws-parameters.json`，使用 AWS CLI parameters 格式：
`[{"ParameterKey":"VpcId","ParameterValue":"vpc-..."}, ...]`。
必填參數為 `VpcId`、`SubnetId`、`ImageId`、`SourceRevision`（upstream repo 可取得的 40 位 commit），
以及 `ClientCidr1` 至 `ClientCidr5`（各一個 IPv4 `/32`）。再建立 stack：

```bash
aws cloudformation create-stack --profile landwise-hackathon --region us-west-2 \
  --stack-name landwise-web --template-body file://.analysis/aws-stack.json \
  --parameters file://.analysis/aws-parameters.json --capabilities CAPABILITY_IAM
aws cloudformation describe-stacks --profile landwise-hackathon --region us-west-2 \
  --stack-name landwise-web --query 'Stacks[0].{Status:StackStatus,Outputs:Outputs}'
```

CloudFormation `CREATE_COMPLETE` 僅表示資源已建立，套件／OCR 安裝仍可能進行中。
須檢查 `/var/lib/landwise/bootstrap-complete`、`systemctl status landwise`、`nginx -t`、
`/api/health` 與真實 smoke。安裝失敗見 `/var/log/cloud-init-output.log`。

## 管理與加密 tunnel

由 stack Outputs 取得 InstanceId；以下 `INSTANCE_ID` 由操作者填入。
管理透過 [AWS Systems Manager Session Manager](https://docs.aws.amazon.com/systems-manager/latest/userguide/session-manager-working-with-sessions-start.html)，
AWS CLI 使用者需具有 SSM session 權限，且本機已安裝 Session Manager plugin。

```bash
aws ssm start-session --profile landwise-hackathon --region us-west-2 --target "$INSTANCE_ID"
```

在主機內查看 `sudo journalctl -u landwise -n 100`，或執行 `sudo systemctl restart landwise`。
需要加密通道時，另開本機 terminal，保持下列程序運行：

```bash
aws ssm start-session --profile landwise-hackathon --region us-west-2 --target "$INSTANCE_ID" \
  --document-name AWS-StartPortForwardingSession \
  --parameters '{"portNumber":["80"],"localPortNumber":["8001"]}'
```

瀏覽器開 `http://127.0.0.1:8001`，本機到 AWS 的流量透過 SSM 加密通道。
直接 HTTP 網址仍受五個 Security Group IP 限制；換網路時應更新對應 `/32`，不要開放 `0.0.0.0/0`。

## 更新、備份與停止

模板是初次安裝；修改 `SourceRevision` 不會自動重新執行 cloud-init，不能當成程式發布。
修改既有 stack 前，先產生並檢查 CloudFormation change set；Security Group 的描述、網卡、
AMI 等變更可能連帶替換 EC2。若出現 replacement，先備份並規劃資料掛載，不能直接套用。
保留的舊根磁碟不會自動掛到新主機。
更新程式前，先在 SSM 停止 `landwise`，將整個 `/var/lib/landwise/data` 備份到受保護磁碟，
記錄 `git -C /opt/landwise rev-parse HEAD`，再抓取並 checkout 已審查的新 commit、安裝相應 requirements、
重新啟動並 smoke。失敗時回到記錄的 commit；若版本包含資料遷移，須同時依該版本的復原方案恢復資料。
不可對運行中的 SQLite 直接複製單一 `.sqlite3` 檔當作完整備份。

```bash
aws ec2 stop-instances --profile landwise-hackathon --region us-west-2 --instance-ids "$INSTANCE_ID"
aws ec2 start-instances --profile landwise-hackathon --region us-west-2 --instance-ids "$INSTANCE_ID"
```

停止後運算計費停止，EBS 仍計費；再次啟動的 public IP 可能改變，應重新查詢 EC2。
刪除 stack 前先備份；根磁碟刻意保留，刪除 stack 後仍需由操作者確認資料用途及磁碟清理。
本部署沒有另建 S3、RDS、ALB、Elastic IP 或 GPU。費用依
[EC2 On-Demand](https://aws.amazon.com/ec2/pricing/on-demand/)、EBS、public IPv4 及 Bedrock 實際用量計算。

## 驗收

2026-09-12 使用 `tests/fixtures/` 合成文件完成驗收：

- 本機 Python：1,164 passed、4 skipped；Chrome Playwright：11 passed。
- EC2 主機使用 `iam-role` 憑證來源，完成 OCR → Bedrock 抽取及 Agent 六題。
- 由操作者網路連至 Nginx，PDF 上傳、真實 OCR、AI 原文引用與快取、RAG 引用說明、
  Agent 規則／計算工具皆通過；AI 與問答沒有更動案件或 audit。
- 完整審查 Excel、表3／4／5 Excel 均可下載並由 openpyxl 開啟；JSON、CSV、HTML 均回傳成功。
- 首次外部 AI 抽取曾回 503，未保留該次錯誤正文；隨後重試成功，不能據此認定確切原因。
  仍須保留服務錯誤提示及人工重試行為，不把模型服務視為保證每次成功。

[合成 HTTP 驗收結果](evaluations/aws-2026-09-12.json) 保留引用與工具結果；網站保留一個
「AWS純合成驗收」案件供操作者試用。未匯入本機原案件。
這個部署切片不宣稱完成 DDD-08 的住宅三標的審查。
