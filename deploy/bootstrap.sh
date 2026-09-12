#!/usr/bin/env bash
# Ubuntu 24.04 / x86_64. Invoked by cloud-init with SOURCE_REV and AWS_DEFAULT_REGION.
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
: "${SOURCE_REV:?An immutable source commit is required}"
: "${AWS_DEFAULT_REGION:?AWS region is required}"
apt-get update
apt-get install -y python3-venv git nginx libglib2.0-0 libgl1 libgomp1 fonts-noto-cjk
id landwise >/dev/null 2>&1 || useradd --system --create-home --home-dir /var/lib/landwise --shell /usr/sbin/nologin landwise
install -d -o landwise -g landwise /var/lib/landwise/data /var/lib/landwise/reference
install -d /opt/landwise
git -C /opt/landwise init
git -C /opt/landwise fetch --depth 1 https://github.com/ChenYi0725/hackathon.git "$SOURCE_REV"
git -C /opt/landwise checkout --detach FETCH_HEAD
python3 -m venv /opt/landwise/.venv
/opt/landwise/.venv/bin/pip install --no-cache-dir -r /opt/landwise/requirements-ocr.txt
cat > /etc/landwise.env <<EOF
AWS_DEFAULT_REGION=$AWS_DEFAULT_REGION
BEDROCK_MODEL_ID=qwen.qwen3-32b-v1:0
BEDROCK_ENABLED=true
BEDROCK_MIN_INTERVAL=1.1
APP_DATA_DIR=/var/lib/landwise/data
REFERENCE_DATA_DIR=/var/lib/landwise/reference
FORM_TEMPLATE_DIR=/opt/landwise/out_put_teamplate
SEED_EXAMPLES=false
OCR_TIMEOUT_SECONDS=900
OCR_CPU_THREADS=2
OCR_DPI=180
EOF
chmod 640 /etc/landwise.env
chown root:landwise /etc/landwise.env
cat > /etc/systemd/system/landwise.service <<'EOF'
[Unit]
Description=Landwise valuation review
After=network-online.target
Wants=network-online.target

[Service]
User=landwise
Group=landwise
WorkingDirectory=/opt/landwise
EnvironmentFile=/etc/landwise.env
Environment=HOME=/var/lib/landwise
ExecStart=/opt/landwise/.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1
Restart=on-failure
RestartSec=5
TimeoutStopSec=30
UMask=0077
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/var/lib/landwise

[Install]
WantedBy=multi-user.target
EOF
cat > /etc/nginx/sites-available/landwise <<'EOF'
server {
    listen 80 default_server;
    server_name _;
    server_tokens off;
    client_max_body_size 20m;
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 1000s;
        proxy_send_timeout 1000s;
    }
}
EOF
rm -f /etc/nginx/sites-enabled/default
ln -sf /etc/nginx/sites-available/landwise /etc/nginx/sites-enabled/landwise
nginx -t
systemctl daemon-reload
systemctl enable --now landwise
systemctl restart nginx
# Model downloads use the same home/cache as the service; no real case is uploaded.
runuser -u landwise -- env HOME=/var/lib/landwise /opt/landwise/.venv/bin/python -c \
  'from paddleocr import PaddleOCR; PaddleOCR(device="cpu", text_detection_model_name="PP-OCRv5_mobile_det", text_recognition_model_name="PP-OCRv5_server_rec", use_doc_orientation_classify=False, use_doc_unwarping=False, use_textline_orientation=False, cpu_threads=2, enable_mkldnn=False)'
touch /var/lib/landwise/bootstrap-complete
