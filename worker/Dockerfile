FROM python:3.10-slim

WORKDIR /app

# curl 用於 curl 下載模式；ca-certificates 供 https 下載
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# (選用) 安裝 Dragonfly dfget client。
# 正式對接第 2 人 / 真實 Dragonfly 時，把下面註解打開並指定版本。
# 沒有 dfget 時 downloader.py 會自動退回 curl 或模擬模式，不影響流程。
# ARG DFGET_VERSION=2.1.0
# RUN curl -fsSL https://github.com/dragonflyoss/Dragonfly2/releases/download/v${DFGET_VERSION}/dfget-${DFGET_VERSION}-linux-amd64.tar.gz \
#     | tar -xz -C /usr/local/bin dfget

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# API_URL 預設指向 docker-compose 內的服務名稱
ENV API_URL=http://api_server:8000 \
    WORKER_NAME=Worker-Node \
    DOWNLOAD_MODE=auto \
    SELF_ASSIGN=1

CMD ["python", "worker.py"]
